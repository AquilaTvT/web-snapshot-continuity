"""Exercise actual HTTP framework validators under a declared rollback schedule.

This tests interface semantics, not a defect in Express, Apache, or Python.
All servers bind loopback only. State transitions are controlled; there is no
claim of naturally occurring production failures or measured Web prevalence.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,os,platform,selectors,signal,socket,subprocess,sys,time,tempfile
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
ROOT=Path(__file__).resolve().parents[1]
STATES=[{'a':'Admission: eligible.\n','b':'Fee: 100 dollars.\n'},
        {'a':'Admission: ineligible.\n','b':'Fee: 10 dollars.\n'},
        {'a':'Admission: eligible.\n','b':'Fee: 100 dollars.\n'}]

def request(port,path,headers=None,method='GET',timeout=5):
    req=Request(f'http://127.0.0.1:{port}/{path}',headers=headers or {},method=method)
    try: response=urlopen(req,timeout=timeout)
    except HTTPError as error: response=error
    with response:
        raw=response.read()
        return {'request_method':req.get_method(),'request_headers':dict(req.header_items()),
                'status':response.status,'body':raw.decode(),
                'etag':response.headers.get('ETag'),
                'last_modified':response.headers.get('Last-Modified'),
                'content_type':response.headers.get('Content-Type'),
                'body_sha256':hashlib.sha256(raw).hexdigest()}

def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def read_startup_metadata(proc, timeout=8.0):
    """Read one bounded JSON line, including when a child writes no newline."""
    deadline=time.monotonic()+timeout
    received=bytearray()
    with selectors.DefaultSelector() as ready:
        ready.register(proc.stdout, selectors.EVENT_READ)
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0 or not ready.select(remaining):
                raise TimeoutError('Express startup metadata timed out')
            chunk=os.read(proc.stdout.fileno(),4096)
            if not chunk:
                raise RuntimeError('Express exited before its startup JSON line')
            received.extend(chunk)
            if len(received)>65536:
                raise RuntimeError('Express startup metadata exceeded 64 KiB')
            if b'\n' in received:
                meta=json.loads(received.split(b'\n',1)[0].decode('utf-8'))
                if not isinstance(meta,dict) or type(meta.get('port')) is not int or not 0<meta['port']<65536:
                    raise ValueError('Express startup JSON needs a valid integer port')
                return meta


def wait_ready(proc,port,timeout=8.0):
    """Bound both readiness polling and individual HTTP attempts."""
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if proc.poll() is not None:
            raise RuntimeError(f'Server exited during startup (status {proc.returncode})')
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        try:
            if request(port,'a',timeout=min(.25,remaining))['status']==200:return
        except (URLError,OSError):
            pass
        time.sleep(min(.05,max(0,deadline-time.monotonic())))
    raise TimeoutError('Server readiness timed out')


def _group_has_live_members(group):
    """Inspect the exact group; zombies cannot execute or retain open pipes.

    Used only to disambiguate a failed group signal. A failed or malformed
    process listing is an error, never evidence that cleanup succeeded.
    """
    result=subprocess.run(['/bin/ps','-axo','pid=,pgid=,stat='],
                          capture_output=True,text=True,check=True,timeout=2)
    if not result.stdout.strip():
        raise RuntimeError('Process-group inspection returned no process table')
    live=False
    for row in result.stdout.splitlines():
        fields=row.split()
        if len(fields)!=3 or not fields[0].isdigit() or not fields[1].isdigit():
            raise RuntimeError('Cannot interpret process-group inspection')
        if int(fields[1])==group and not fields[2].startswith('Z'):
            live=True
    return live


def stop_owned_session(proc,timeout=3.0):
    """Stop only the new session created for this Popen, including workers."""
    group=proc.pid
    if group<=1 or group==os.getpgrp():
        raise RuntimeError('Refusing to signal the parent process group')
    try:
        if os.getpgid(proc.pid)!=group:
            raise RuntimeError('Child is not the leader of its owned process group')
    except ProcessLookupError:
        pass  # The leader can exit while its Apache workers remain alive.

    def signal_group(sig):
        try:os.killpg(group,sig)
        except ProcessLookupError:return False
        except PermissionError:
            # On Darwin a group containing only a newly exited zombie can
            # produce EPERM: XNU killpg1 skips SZOMB and then has nfound=0.
            # https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_sig.c
            # Reap our leader, then establish whether the group is gone. Do
            # not interpret EPERM itself as evidence that workers have exited.
            proc.poll()
            try:os.killpg(group,0)
            except ProcessLookupError:return False
            except PermissionError:
                if not _group_has_live_members(group):return False
                raise
            if sig==0:return True  # The new probe confirms a remaining group.
            raise  # A real signal failed while the group still exists.
        return True

    signal_group(signal.SIGTERM)
    deadline=time.monotonic()+timeout
    while True:
        proc.poll()  # Reap the leader before inspecting the remaining group.
        if not signal_group(0):break
        if time.monotonic()>=deadline:
            signal_group(signal.SIGKILL)
            break
        time.sleep(.025)
    try:proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        signal_group(signal.SIGKILL)
        proc.wait(timeout=timeout)

def static_files(directory,phase,preserve):
    # Withdraw the second target before restoring the first. Updating a,b in
    # both directions would briefly create exactly the bundle being excluded.
    order=('b','a') if phase==2 else ('a','b')
    trace=[]
    for name in order:
        body=STATES[phase][name]
        path=directory/name;staging=directory/(name+'.pending')
        staging.write_text(body)
        stamp=1600000000+(0 if preserve and phase==2 else phase)*10
        os.utime(staging,(stamp,stamp));os.replace(staging,path)
        observed={key:(directory/key).read_text() if (directory/key).exists() else None for key in ('a','b')}
        trace.append({'phase':phase,'replaced':name,'state':observed})
        assert not (observed['a']==STATES[0]['a'] and observed['b']==STATES[1]['b'])
    return trace

def run_one(name,kind,preserve=False,apache='/usr/sbin/httpd',modules='/usr/libexec/apache2'):
    if kind not in {'express','python','apache'}:
        raise ValueError(f'Unknown server kind: {kind}')
    work=(Path(tempfile.mkdtemp(prefix='acm-http-'+name+'-')) if kind=='apache'
          else ROOT/'tmp/http-stacks'/name)
    work.mkdir(parents=True,exist_ok=True)
    files=work/'public';files.mkdir(exist_ok=True)
    for key in ('a','b'):(files/key).unlink(missing_ok=True)
    mutation_trace=[] if kind=='express' else static_files(files,0,preserve)
    observations=[]
    proc=None
    with (work/'server.log').open('w') as output:
        try:
            if kind=='express':
                proc=subprocess.Popen(['node','express_server.cjs',name.split('-')[-1]],
                    cwd=ROOT/'experiments/http_stacks',stdout=subprocess.PIPE,
                    stderr=output,start_new_session=True)
                meta=read_startup_metadata(proc)
                port=meta.pop('port')
            else:
                port=free_port()
                if kind=='python':
                    cmd=[sys.executable,'-m','http.server',str(port),'--bind','127.0.0.1','--directory',str(files)]
                    meta={'python':platform.python_version(),'validator':'Last-Modified','preserve_mtime':preserve}
                else:
                    module_root=Path(modules)
                    if not module_root.exists():
                        raise RuntimeError('Apache module directory not found; pass --apache-modules')
                    compiled=subprocess.check_output([apache,'-l'],text=True,timeout=5)
                    loads=[]
                    for module in ('mpm_prefork','authz_core','unixd'):
                        shared=module_root/f'mod_{module}.so'
                        if shared.exists():
                            loads.append(f'LoadModule {module}_module {shared}')
                        elif f'mod_{module}.c' not in compiled:
                            raise RuntimeError(f'Apache module {module} is neither shared nor compiled in')
                    config=work/'httpd.conf'
                    lines=[f'ServerRoot "{work}"',f'PidFile "{work}/httpd.pid"',f'ErrorLog "{work}/error.log"',
                           f'Listen 127.0.0.1:{port}','ServerName localhost',*loads,
                           f'DocumentRoot "{files}"',f'<Directory "{files}">','Require all granted','</Directory>',
                           'FileETag MTime Size','EnableSendfile Off','EnableMMAP Off']
                    config.write_text('\n'.join(lines)+'\n')
                    cmd=[apache,'-f',str(config),'-DFOREGROUND']
                    meta={'server':subprocess.check_output([apache,'-v'],text=True,timeout=5).splitlines()[0],
                          'binary_sha256':hashlib.sha256(Path(apache).read_bytes()).hexdigest(),
                          'validator':'FileETag MTime Size','preserve_mtime':preserve}
                proc=subprocess.Popen(cmd,stdout=output,stderr=output,start_new_session=True)
            wait_ready(proc,port)

            def record_express_phase(phase,replaced):
                readback={key:request(port,key) for key in ('a','b')}
                assert all(response['status']==200 for response in readback.values())
                actual={key:response['body'] for key,response in readback.items()}
                assert actual==STATES[phase]
                mutation_trace.append({'phase':phase,'replaced':replaced,
                                       'state':actual,'readback':readback})

            if kind=='express':
                record_express_phase(0,'initial Express state')

            def capture(path,tick,headers=None):
                result=request(port,path,headers);result.update(resource=path,tick=tick)
                observations.append(result);return result

            def transition(phase):
                if kind=='express':
                    assert request(port,f'phase/{phase}',method='POST')['status']==204
                    record_express_phase(phase,'phase (single event-loop assignment)')
                else:mutation_trace.extend(static_files(files,phase,preserve))

            a0=capture('a',0);transition(1);b1=capture('b',1);b2=capture('b',2)
            transition(2);a3=capture('a',3)
            if a0['etag']:conditional={'If-None-Match':a0['etag']}
            else:conditional={'If-Modified-Since':a0['last_modified']}
            a_cond=capture('a',3,conditional)
        finally:
            try:
                if proc is not None:stop_owned_session(proc)
            finally:
                if proc is not None and proc.stdout is not None:proc.stdout.close()
    assert all(x['status']==200 for x in observations[:4])
    assert a0['body']==a3['body']==STATES[0]['a'] and b1['body']==b2['body']==STATES[1]['b']
    validator='etag' if a0['etag'] else 'last_modified'
    target={'a':STATES[0]['a'],'b':STATES[1]['b']}
    ever_present=any(step['state']==target for step in mutation_trace)
    assert not ever_present
    return {'case':name,'scope':'controlled framework execution, not natural deployment incidence',
       'software':meta,'states':STATES,'observations':observations,
       'validator':validator,'endpoint_validator_equal':a0[validator]==a3[validator],
       'conditional_status':a_cond['status'],'target_bundle_ever_present':ever_present,
       'mutation_trace':mutation_trace,
       'transition_semantics':'atomic single-file replacement; withdraw b before restoring a; Express changes its shared phase in one event-loop assignment',
       'history_evidence':'mutation_trace records the ordered serving states after each controlled mutation; logical phases are not measured wall-clock validity intervals',
       'target':target,
       'illustrative_phase_intervals':{'a':[[0,1],[3,4]],'b':[[1,3]]},
       'consumer_endpoint_rule_would_accept':a0[validator]==a3[validator] and b1[validator]==b2[validator]}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apache',default='/usr/sbin/httpd')
    parser.add_argument('--apache-modules',default='/usr/libexec/apache2')
    parser.add_argument('--output',type=Path,default=ROOT/'data/raw/http-stacks')
    parser.add_argument('--derived',type=Path,default=ROOT/'data/derived/http_stacks.csv')
    parser.add_argument('--overwrite',action='store_true',help='replace existing traces in --output')
    args=parser.parse_args()
    cases=[('express-weak','express',False),('express-strong','express',False),
           ('python-fresh','python',False),('python-restored','python',True),
           ('apache-fresh','apache',False),('apache-restored','apache',True)]
    output=args.output;output.mkdir(parents=True,exist_ok=True)
    if not args.overwrite and any((output/(name+'.json')).exists() for name,_,_ in cases):
        raise SystemExit('Traces already exist in '+str(output)+'; frozen evidence is not overwritten (use --overwrite or a new --output)')
    results=[]
    for name,kind,preserve in cases:
        result=run_one(name,kind,preserve,args.apache,args.apache_modules)
        result['platform']={'system':platform.system(),'machine':platform.machine(),'python':platform.python_version()}
        (output/(name+'.json')).write_text(json.dumps(result,indent=2)+'\n');results.append(result)
        print(name,result['endpoint_validator_equal'],result['conditional_status'],flush=True)
    rows=[{k:r[k] for k in ['case','validator','endpoint_validator_equal','conditional_status','target_bundle_ever_present','consumer_endpoint_rule_would_accept']} for r in results]
    with args.derived.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
if __name__=='__main__':main()

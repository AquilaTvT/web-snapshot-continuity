"""Controlled HTTP witness. Logical transitions, real loopback HTTP requests.

This is an executable construction, not a natural-Web measurement. Both the
hash ETag and a non-reused change epoch are observed under identical requests.
"""
import hashlib, json, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.temporal import intervals_from_revisions,common_times

def main():
    state={'/a':b'A','/b':b'b'}; epoch={'/a':0,'/b':0}
    revisions={'/a':[(0,'A')],'/b':[(0,'b')]}
    lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            with lock: body=state.get(self.path); revision=epoch.get(self.path)
            if body is None: self.send_error(404);return
            self.send_response(200)
            self.send_header('Content-Type','text/plain')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('ETag','"'+hashlib.sha256(body).hexdigest()+'"')
            self.send_header('X-Change-Epoch',str(revision))
            self.end_headers();self.wfile.write(body)
        def log_message(self,*args): pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    observations=[]
    def read(path,tick):
        with urlopen(f'http://127.0.0.1:{server.server_port}{path}',timeout=5) as response:
            observations.append(dict(resource=path,tick=tick,status=response.status,
                body=response.read().decode(),etag=response.headers['ETag'],epoch=int(response.headers['X-Change-Epoch'])))
    def change(tick,values):
        with lock:
            for path,body in values.items():
                if state[path]!=body:
                    state[path]=body;epoch[path]+=1;revisions[path].append((tick,body.decode()))
    try:
        read('/a',0);change(1,{'/a':b'a','/b':b'B'})
        read('/b',1);read('/b',2)
        change(3,{'/a':b'A','/b':b'b'});read('/a',3)
    finally: server.shutdown();server.server_close();thread.join()
    family=[intervals_from_revisions(revisions[p],target,(0,4)) for p,target in [('/a','A'),('/b','B')]]
    result=dict(scope='controlled loopback HTTP construction on logical ticks',observations=observations,
                complete_revisions=revisions,validity=family,coexistence=common_times(family,(0,4)),
                equal_endpoint_hashes=[observations[0]['etag']==observations[3]['etag'],observations[1]['etag']==observations[2]['etag']],
                a_epoch_changes=observations[0]['epoch']!=observations[3]['epoch'])
    assert result['equal_endpoint_hashes']==[True,True] and result['coexistence']==() and result['a_epoch_changes']
    path=ROOT/'data/derived/http_demo.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__': main()

"""Refresh local inputs, derive exact plot values, render, and hash each figure.

The canonical derive.py and plot.py live beside their inputs and output in
figure-artifacts/. Copy any numbered directory to rebuild it independently.
"""
from __future__ import annotations
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'figure-artifacts'

def copy(relative,directory,name=None):
    source=ROOT/relative;shutil.copy2(source,directory/(name or source.name))

def manifest(directory,recursive):
    files=sorted(p for p in (directory.rglob('*') if recursive else directory.iterdir())
                 if p.is_file() and p.name!='MANIFEST.sha256' and '__pycache__' not in p.parts)
    (directory/'MANIFEST.sha256').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '
        +p.relative_to(directory).as_posix()+'\n' for p in files))


def refresh_sources(directory):
    """Re-hash the inputs that figure.json lists, keeping every other field."""
    path=directory/'figure.json'
    meta=json.loads(path.read_text())
    meta['data_sources']={name:hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in meta['data_sources']}
    path.write_text(json.dumps(meta,indent=2,ensure_ascii=False)+'\n')


def main():
    specs=[
      ('01-observation-ambiguity',[3.35,3.1],
       'Identical captures do not identify historical coexistence. White markers are the same four observations in both constructed histories. Intervals are left-closed and right-open. Blue segments contain the target representation. A change epoch distinguishes these histories only under a non-reuse and atomic-read contract.',
       'Mathematical construction. No observed incidence, sampling, or aggregation.'),
      ('02-http-validators',[7,2.1],
       'Six controlled framework executions. Four configurations return 304 after the endpoint bytes and validator return. Fresh modification times distinguish the other two. Each full-body endpoint GET precedes the conditional GET; every intermediate single-file state is recorded. These are valid representation comparisons, not continuity guarantees or measured failure rates.',
       'One row per configuration; raw request/response records and atomic mutation traces determine every plotted value.')]
    for name,size,caption,method in specs:
        directory=DEST/name;directory.mkdir(parents=True,exist_ok=True)
        if name.startswith('01'):
            design={'worlds':{'unchanged':{'a':[[0,4,1]],'b':[[0,4,1]]},
                             'returned':{'a':[[0,1,1],[1,3,0],[3,4,1]],'b':[[0,1,0],[1,3,1],[3,4,0]]}},
                    'observations':[dict(resource=r,time=t,target=1) for r,t in [('a',0),('b',1),('b',2),('a',3)]]}
            (directory/'construction.json').write_text(json.dumps(design,indent=2)+'\n')
            inputs=['construction.json']
        elif name.startswith('02'):
            inputs=[]
            for source in sorted((ROOT/'data/raw/http-stacks').glob('*.json')):
                copy(source.relative_to(ROOT),directory);inputs.append(source.name)
            copy('data/derived/http_stacks.csv',directory,'source-results.csv');inputs.append('source-results.csv')
        (directory/'requirements.txt').write_text('matplotlib==3.10.7\n')
        (directory/'caption.txt').write_text(caption+'\n')
        (directory/'README.md').write_text('# '+name+'\n\n'+caption+'\n\nCopy this directory anywhere. Run:\n\n```sh\npython3 -m pip install -r requirements.txt\npython3 derive.py\npython3 plot.py\n```\n\n`derive.py` rebuilds the exact `plot-data.csv` from the source files here, with explicit consistency assertions. `plot.py` reads that CSV and creates vector PDF/SVG and a PNG preview. No parent-directory import or network access is used.\n\n'+method+'\n\n`MANIFEST.sha256` covers every packaged file. `figure.json` records source hashes, provenance and final physical size. Font size is specified at that size; scale neither panel arbitrarily for submission.\n')
        meta={'name':name,'size_inches':size,'caption':caption,'method':method,
              'data_sources':{p:hashlib.sha256((directory/p).read_bytes()).hexdigest() for p in inputs}}
        if name.startswith('01'):
            meta.update(layout='two vertically stacked history panels',minimum_font_size_points=8.0)
        (directory/'figure.json').write_text(json.dumps(meta,indent=2)+'\n')
        for script in ('derive.py','plot.py'):subprocess.run([sys.executable,str(directory/script)],check=True)
        (directory/'MANIFEST.sha256').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(directory.iterdir()) if p.is_file() and p.name!='MANIFEST.sha256'))
        print(name,flush=True)
    directory=DEST/'03-versioned-heads'
    copy('experiments/versioned_objects/data/trace.json',directory)
    for script in ('derive.py','plot.py'):
        subprocess.run([sys.executable,str(directory/script)],check=True)
    (directory/'MANIFEST.sha256').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(directory.iterdir()) if p.is_file() and p.name!='MANIFEST.sha256'))
    print(directory.name,flush=True)
    directory=DEST/'04-publication-policy'
    copy('experiments/publication_profile/data/trace.json',directory)
    for script in ('derive.py','plot.py'):
        subprocess.run([sys.executable,str(directory/script)],check=True)
    print(directory.name,flush=True)
    fonts=ROOT/'assets/fonts/acmart'
    def ship_fonts(directory):
        target=directory/'fonts'
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(fonts,target)
    styles={(DEST/name/'figstyle.tex').read_bytes() for name in ('05-certification-rule','06-revision-histories')}
    assert len(styles)==1,'figures 05 and 06 must share one figstyle.tex'
    directory=DEST/'05-certification-rule'
    copy('experiments/versioned_objects/data/trace.json',directory)
    ship_fonts(directory)
    for script in ('derive.py','plot.py'):
        subprocess.run([sys.executable,str(directory/script)],check=True)
    refresh_sources(directory)
    manifest(directory,recursive=True)
    print(directory.name,flush=True)
    directory=DEST/'06-revision-histories'
    target=directory/'collection'
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ROOT/'experiments/revision_bundles/data',target)
    copy('experiments/revision_bundles/derive.py',directory,'analysis.py')
    copy('experiments/revision_bundles/addendum.py',directory,'analysis_addendum.py')
    copy('experiments/revision_bundles/addendum2.py',directory,'analysis_addendum2.py')
    copy('experiments/revision_bundles/protocol.json',directory)
    copy('experiments/revision_bundles/protocol-addendum.json',directory)
    copy('experiments/revision_bundles/protocol-addendum-2.json',directory)
    ship_fonts(directory)
    for script in ('derive.py','plot.py'):
        subprocess.run([sys.executable,str(directory/script)],check=True)
    refresh_sources(directory)
    manifest(directory,recursive=True)
    print(directory.name,flush=True)
    table=ROOT/'table-artifacts'/'01-identity-probes'
    (table/'traces').mkdir(parents=True,exist_ok=True)
    for source in sorted((ROOT/'experiments/reactivation_probes/data').glob('*.json')):
        shutil.copy2(source,table/'traces'/source.name)
    code=(ROOT/'experiments/reactivation_probes/derive.py').read_text()
    code=code.replace('default=HERE / "data")','default=HERE / "traces")').replace('default=HERE / "derived")','default=HERE)')
    (table/'derive.py').write_text(code)
    for script in ('derive.py','make_table.py'):
        subprocess.run([sys.executable,'-B',str(table/script)],check=True,stdout=subprocess.DEVNULL,cwd=table)
    manifest(table,recursive=True)
    print(table.name,flush=True)
    (DEST/'README.md').write_text('# Figure artifacts\n\nEach numbered directory is independent: derive.py + plot.py + frozen inputs + precise plot-data.csv + PDF/SVG/preview + caption + metadata + SHA-256 manifest. Copy one directory, install its requirements, run derive.py then plot.py. No paper-generation code is required. Figures 05 and 06 are drawn in TikZ and PGFPlots and typeset with XeLaTeX in the acmart typefaces shipped in their fonts/ folders, at the paper\'s column width; they need TeX Live and poppler but no Python package. 01-04 are drawn with Matplotlib.\n\nMain paper: 05 (Figure 1: a native MinIO return and reads in the revisit order) and 06 (Figure 2: complete revision histories). Table 1 is generated in ../table-artifacts/01-identity-probes. Earlier figures are retained as complete mechanism controls: 01 indistinguishable histories, 02 framework validators, 03 native current-key version histories, 04 native permission and retention contrasts.\n')
if __name__=='__main__':main()

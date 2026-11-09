"""Verify the SHA-256 manifest at a chosen artifact directory."""
import argparse,hashlib
from pathlib import Path

def verify(root):
    root=Path(root).resolve();count=0
    for line in (root/'MANIFEST.sha256').read_text().splitlines():
        digest,name=line.split('  ',1);path=(root/name).resolve()
        if not path.is_relative_to(root):raise ValueError('Manifest path leaves artifact')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Checksum mismatch: '+name)
        count+=1
    return count

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',nargs='?',default='.')
    args=parser.parse_args();print('Verified',verify(args.directory),'files')

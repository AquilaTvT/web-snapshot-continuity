"""Fetch a pinned official MinIO release with TLS and a final SHA-256 check.

Uses curl's platform certificate store. A partial .download file is resumable;
no incomplete or unverified file is made executable. No server is started.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--release-file', type=Path,
                        default=Path(__file__).with_name('server-release.json'),
                        help='Pinned asset manifest; defaults to the native server release')
    args = parser.parse_args()
    release = json.loads(args.release_file.read_text())
    matches = [a for a in release['assets']
               if (a['system'], a['machine']) == (platform.system(), platform.machine())]
    if len(matches) != 1:
        raise SystemExit('This platform has no pinned asset in server-release.json')
    asset = matches[0]
    destination = args.output.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        if hashlib.sha256(destination.read_bytes()).hexdigest() == asset['sha256']:
            print('Verified existing executable:', destination)
            return
        raise SystemExit('Output exists with a different hash; choose a new output path')
    partial = destination.with_name(destination.name + '.download')
    if not partial.exists():
        partial.touch()
    size = partial.stat().st_size
    if size > asset['bytes']:
        raise SystemExit('Partial download is larger than the pinned release')
    with tempfile.TemporaryDirectory(prefix='continuity-minio-fetch-') as temporary:
        directory = Path(temporary)
        while size < asset['bytes']:
            end = min(size + 1024 * 1024, asset['bytes']) - 1
            data, headers = directory/'part', directory/'headers'
            for attempt in range(3):
                result = subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                    '--max-time', '120', '--header', 'Accept: application/octet-stream',
                    '--header', f'Range: bytes={size}-{end}', '--dump-header', str(headers),
                    '--output', str(data), asset['api_url'] + f'?range={size}-{end}'])
                if result.returncode == 0:
                    break
            else:
                raise SystemExit('Download incomplete; rerun this command to resume verified ranges')
            ranges = re.findall(r'(?im)^content-range:\s*bytes (\d+)-(\d+)/(\d+)', headers.read_text())
            expected = (str(size), str(end), str(asset['bytes']))
            if not ranges or ranges[-1] != expected or data.stat().st_size != end-size+1:
                raise SystemExit('Server range/length disagrees with the requested pinned asset')
            with partial.open('ab') as stream:
                stream.write(data.read_bytes())
            size = partial.stat().st_size
            print(f'{size}/{asset["bytes"]} bytes', flush=True)
    if hashlib.sha256(partial.read_bytes()).hexdigest() != asset['sha256']:
        raise SystemExit('SHA-256 mismatch: no executable created; retain the partial for diagnosis')
    partial.replace(destination)
    destination.chmod(0o755)
    print('Verified executable:', destination)


if __name__ == '__main__':
    main()

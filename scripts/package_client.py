"""Build a deterministic, standard-library-only LAN_Debug_client release."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'client/LAN_Debug'
FILES = {'jlink_flash.py': 'jlink_flash.py', 'VERSION': 'VERSION', 'README.md': 'README.md',
         'remote-jlink.example.json': 'remote-jlink.json',
         'vscode/tasks.json': 'vscode/tasks.json', 'vscode/launch.json': 'vscode/launch.json'}


def package_bytes():
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for target, source in sorted(FILES.items()):
            info = zipfile.ZipInfo(target, (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (CLIENT / source).read_text(encoding='utf-8-sig').encode('utf-8'))
    return data.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/client')
    args = parser.parse_args()
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT):
        raise RuntimeError('Commit release sources before packaging.')
    version = (CLIENT / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', version):
        raise ValueError('Invalid client VERSION')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(CLIENT / 'tests')], cwd=ROOT, check=True)
    content = package_bytes()
    name = f'LAN_Debug_client-{version}.zip'
    digest = hashlib.sha256(content).hexdigest()
    with tempfile.TemporaryDirectory(prefix='lan-client-') as directory:
        temp = Path(directory)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            archive.extractall(temp)
        entry = temp / 'jlink_flash.py'
        actual = subprocess.check_output([sys.executable, '-B', str(entry), '--version'], text=True).strip()
        if actual != version:
            raise RuntimeError('Packaged script version mismatch')
        subprocess.run([sys.executable, '-B', str(entry), '--check', '--config', str(temp / 'remote-jlink.example.json')], check=True)
    manifest = dict(manifestSchema=2, toolId='LAN_Debug_client', sourceRepository='XJU-Hurricane-Team/LAN_Debug',
                    version=version, upstreamCommit=commit, entrypoint='jlink_flash.py', pythonMinimum='3.10',
                    packageName=name, packageBytes=len(content), packageSha256=digest)
    args.output.mkdir(parents=True, exist_ok=True)
    for filename, data in [(name, content), ('release-manifest.json', (json.dumps(manifest, indent=2) + '\n').encode()),
                           ('SHA256SUMS', f'{digest}  {name}\n'.encode())]:
        with (args.output / filename).open('xb') as output:
            output.write(data)
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()

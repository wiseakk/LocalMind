"""Release engineering: isolated embedded runtime, never copy a developer venv.

Build machine needs Python, .NET csc and Inno Setup 6. End users do not.
Network is used here for runtime/wheels/prerequisites. No deployment is performed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(command, **kwargs):
    subprocess.run([str(c) for c in command], check=True, shell=False, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline-assets', type=Path, help='Previously prepared model directory; validated against release manifest')
    parser.add_argument('--iscc', type=Path, default=Path('C:/Program Files (x86)/Inno Setup 6/ISCC.exe'))
    parser.add_argument('--resume', action='store_true', help='Validate and finish an interrupted build in dist/LocalMind')
    parser.add_argument('--offline-gguf', type=Path, help='Optional reviewed GGUF included for offline import into Ollama')
    parser.add_argument('--offline-license', help='License identifier for the optional GGUF')
    args = parser.parse_args()
    payload = ROOT / 'dist/LocalMind'
    if payload.exists() and not args.resume:
        raise SystemExit('dist/LocalMind already exists; use a fresh build directory/check out. No overwrite of a release.')
    runtime = payload / 'runtime/core'; runtime.mkdir(parents=True, exist_ok=True)
    archive = ROOT / 'dist/python-3.11.9-embed-amd64.zip'
    if not args.resume or not archive.is_file():
        urllib.request.urlretrieve('https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip', archive)
    # Hash is recorded for provenance; publisher TLS is the trust root here.
    runtime_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    if not args.resume:
        with zipfile.ZipFile(archive) as z:
            z.extractall(runtime)
    (runtime / 'python311._pth').write_text('python311.zip\n.\nLib/site-packages\n..\\..\\\nimport site\n', encoding='utf-8')
    import sys
    if not args.resume:
        run([sys.executable, '-m', 'pip', '--isolated', 'install', '--no-cache-dir', '--disable-pip-version-check', '--only-binary=:all:', '--target', runtime / 'Lib/site-packages',
             '-r', ROOT / 'requirements-release.txt'])
        run([sys.executable, '-m', 'pip', '--isolated', 'install', '--no-cache-dir', '--disable-pip-version-check', '--only-binary=:all:', '--target', runtime / 'Lib/site-packages',
             '--no-deps', '--index-url', 'https://download.pytorch.org/whl/cpu', 'torch==2.5.1'])
        # Torch dependencies are separate because no-deps avoids replacing pinned numpy.
        run([sys.executable, '-m', 'pip', '--isolated', 'install', '--no-cache-dir', '--disable-pip-version-check', '--only-binary=:all:', '--target', runtime / 'Lib/site-packages',
             'networkx==3.4.2', 'jinja2==3.1.6', 'sympy==1.13.1'])
    # CPython 3.11.9 embeds VC140; native wheels also need the redistributable
    # VC140_1 shipped by the licensed Qt wheel. Keep it next to python.exe.
    for name in ('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll'):
        source = runtime / 'Lib/site-packages/PySide6' / name
        if source.is_file():
            shutil.copyfile(source, runtime / name)
    for folder in ('localmind', 'static', 'config'):
        shutil.copytree(ROOT / folder, payload / folder, dirs_exist_ok=args.resume,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    if args.offline_gguf:
        if not args.offline_license or len(args.offline_license) > 200:
            raise SystemExit('--offline-gguf requires --offline-license')
        with args.offline_gguf.open('rb') as source:
            if source.read(4) != b'GGUF':
                raise SystemExit('The offline file is not GGUF')
            source.seek(0)
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        folder = payload / 'offline-llm'; folder.mkdir(exist_ok=True)
        shutil.copyfile(args.offline_gguf, folder / 'model.gguf')
        (payload / 'config/offline_model.json').write_text(json.dumps({'model': 'localmind-offline:1.0',
            'sha256': digest, 'bytes': args.offline_gguf.stat().st_size, 'license': args.offline_license}, indent=2), encoding='utf-8')
    if args.offline_assets:
        manifest = json.loads((ROOT / 'config/voice_resources.json').read_text(encoding='utf-8'))
        for asset in manifest['assets']:
            source = args.offline_assets / asset['path']
            with source.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if source.stat().st_size != asset['bytes'] or digest != asset['sha256']:
                raise SystemExit('Offline resource mismatch: ' + asset['path'])
            dest = payload / 'offline-assets' / asset['path']; dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
    prerequisites = payload / 'prerequisites'; prerequisites.mkdir(exist_ok=True)
    if not args.resume or not (prerequisites / 'OllamaSetup.exe').is_file():
        urllib.request.urlretrieve('https://ollama.com/download/OllamaSetup.exe', prerequisites / 'OllamaSetup.exe')
    # Reject an unsigned/tampered prerequisite before distributing executable code.
    run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
         "$s=Get-AuthenticodeSignature -LiteralPath '" + str(prerequisites / 'OllamaSetup.exe').replace("'", "''") +
         "'; if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Ollama') {exit 1}"])
    csc = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    run([csc, '/nologo', '/target:winexe', '/reference:System.Windows.Forms.dll', '/out:' + str(payload / 'LocalMind.exe'), ROOT / 'installer/LocalMind.cs'])
    import os
    environment = {**os.environ, 'LOCALMIND_DATA_DIR': str(ROOT / '.test-artifacts/build-smoke')}
    run([runtime / 'python.exe', '-c', 'import fastapi, av, faster_whisper, torch; from PySide6 import QtWebEngineWidgets; import localmind.server'], cwd=payload, env=environment)
    offline = (payload / 'offline-assets').is_dir() or (payload / 'offline-llm').is_dir()
    (payload / 'build-provenance.json').write_text(json.dumps({'python': '3.11.9', 'runtime_sha256': runtime_hash,
        'offline': offline}, indent=2), encoding='utf-8')
    flags = ['/DOfflineBundle=1'] if offline else []
    run([args.iscc, '/Q', *flags, '/DPayload=' + str(payload), ROOT / 'installer/LocalMind.iss'])


if __name__ == '__main__':
    main()

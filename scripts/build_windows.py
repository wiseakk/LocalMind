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
import platform
import sys
from release_support import (VERSION, source_identity, validate_resume, payload_manifest,
                             validate_payload_sources, validate_payload_layout, copy_committed_sources,
                             write_source_archive, write_checksums, sha256, validate_ui_payload)
from ollama_bundle import stage as stage_ollama

ROOT = Path(__file__).resolve().parents[1]


def run(command, **kwargs):
    subprocess.run([str(c) for c in command], check=True, shell=False, **kwargs)


def dependency_stage(identity, runtime, archive):
    """Resume only the exact completed runtime, including resolved wheel files."""
    if not runtime.is_dir() or not archive.is_file():
        raise ValueError('Completed runtime/archive missing; use a fresh --output directory. Existing files are preserved.')
    return {'inputs': identity, 'runtime_archive_sha256': sha256(archive),
            'runtime_files': payload_manifest(runtime)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline-assets', type=Path, help='Previously prepared model directory; validated against release manifest')
    parser.add_argument('--iscc', type=Path, default=Path('C:/Program Files (x86)/Inno Setup 6/ISCC.exe'))
    parser.add_argument('--candidate-commit', help='Full SHA of the clean checkout for a validation build')
    parser.add_argument('--resume', action='store_true', help='Validate and finish an interrupted build in dist/LocalMind')
    parser.add_argument('--offline-gguf', type=Path, help='Optional reviewed GGUF included for offline import into Ollama')
    parser.add_argument('--offline-license', help='License identifier for the optional GGUF')
    parser.add_argument('--offline-model-name', default='Qwen 2.5 0.5B',
                        help='Reviewed identity of bundled fallback GGUF; override when bundling another model')
    parser.add_argument('--asr-profiles', nargs='+', choices=('cpu-fast', 'balanced', 'gpu-quality'), default=['balanced'],
                        help='ASR profiles to bundle offline; others can be prepared explicitly in setup')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist', help='Fresh directory for this release build')
    parser.add_argument('--runtime-cache', type=Path, default=ROOT / '.test-artifacts/engine-download', help='Hash-verified standalone engine cache')
    args = parser.parse_args()
    # Fail before downloads, dependency installation or payload mutation.
    problems = []
    try:
        source_info = source_identity(ROOT, candidate_commit=args.candidate_commit)
    except (ValueError, subprocess.CalledProcessError) as exc:
        problems.append(str(exc))
    if sys.version_info[:2] != (3, 11) or platform.machine().upper() not in ('AMD64', 'X86_64'):
        problems.append('Build requires x64 CPython 3.11 for the bundled native wheels.')
    csc = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    for required in (args.iscc, csc):
        if not required.is_file():
            problems.append('Build tool missing: ' + str(required))
    if problems:
        raise SystemExit('Build preflight failed:\n- ' + '\n- '.join(problems))
    output = args.output.resolve()
    payload = output / 'LocalMind'
    identity = {'source': source_info, 'asr_profiles': args.asr_profiles,
                'offline_assets': bool(args.offline_assets),
                'offline_gguf_sha256': sha256(args.offline_gguf) if args.offline_gguf else None,
                'offline_license': args.offline_license,
                'offline_model_name': args.offline_model_name}
    marker = output / 'dependency-stage.json'
    runtime = payload / 'runtime/core'
    archive = output / 'python-3.11.9-embed-amd64.zip'
    if args.resume:
        validate_resume(marker, dependency_stage(identity, runtime, archive))
        validate_payload_layout(ROOT, payload, identity)
        validate_payload_sources(ROOT, payload, bundled_gguf=bool(args.offline_gguf))
    if any((output / name).exists() for name in
           ('LocalMind-' + VERSION + '-Setup.exe', 'LocalMind-' + VERSION + '-Offline-Setup.exe',
            'LocalMind-' + VERSION + '-Source.zip', 'SHA256.txt')):
        raise SystemExit('Release artifacts already exist; choose a fresh --output directory.')
    if payload.exists() and not args.resume:
        raise SystemExit('dist/LocalMind already exists; use a fresh build directory/check out. No overwrite of a release.')
    runtime.mkdir(parents=True, exist_ok=True)
    if not args.resume or not archive.is_file():
        urllib.request.urlretrieve('https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip', archive)
    # Hash is recorded for provenance; publisher TLS is the trust root here.
    runtime_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    if not args.resume:
        with zipfile.ZipFile(archive) as z:
            z.extractall(runtime)
    (runtime / 'python311._pth').write_text('python311.zip\n.\nLib/site-packages\n..\\..\\\nimport site\n', encoding='utf-8')
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
    if not args.resume:
        marker.write_text(json.dumps(dependency_stage(identity, runtime, archive), indent=2), encoding='utf-8')
    copy_committed_sources(ROOT, payload, source_info)
    validate_ui_payload(payload)
    if args.offline_gguf:
        if (not args.offline_license or len(args.offline_license) > 200 or
                not args.offline_model_name or len(args.offline_model_name) > 200):
            raise SystemExit('--offline-gguf requires --offline-license')
        with args.offline_gguf.open('rb') as source:
            if source.read(4) != b'GGUF':
                raise SystemExit('The offline file is not GGUF')
            source.seek(0)
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        folder = payload / 'offline-llm'; folder.mkdir(exist_ok=True)
        shutil.copyfile(args.offline_gguf, folder / 'model.gguf')
        (payload / 'config/offline_model.json').write_text(json.dumps({'model': 'localmind-offline:1.0',
            'display_name': 'Лёгкая резервная/тестовая модель · ' + args.offline_model_name,
            'source_model': args.offline_model_name,
            'role': 'lightweight_fallback_test',
            'sha256': digest, 'bytes': args.offline_gguf.stat().st_size, 'license': args.offline_license}, indent=2), encoding='utf-8')
    if args.offline_assets:
        manifest = json.loads((ROOT / 'config/voice_resources.json').read_text(encoding='utf-8'))
        asr_models = {'cpu-fast': 'small', 'balanced': 'small', 'gpu-quality': 'medium'}
        bundled_prefixes = ['silero/', *['whisper/' + asr_models[p] + '/' for p in args.asr_profiles]]
        for asset in manifest['assets']:
            if not any(asset['path'].startswith(prefix) for prefix in bundled_prefixes):
                continue
            source = args.offline_assets / asset['path']
            with source.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if source.stat().st_size != asset['bytes'] or digest != asset['sha256']:
                raise SystemExit('Offline resource mismatch: ' + asset['path'])
            dest = payload / 'offline-assets' / asset['path']; dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
    engine = stage_ollama(ROOT, payload, args.runtime_cache)
    run([csc, '/nologo', '/target:winexe', '/win32icon:' + str(ROOT / 'static/assets/localmind.ico'), '/reference:System.Windows.Forms.dll', '/out:' + str(payload / 'LocalMind.exe'), ROOT / 'installer/LocalMind.cs'])
    import os
    environment = {**os.environ, 'LOCALMIND_DATA_DIR': str(ROOT / '.test-artifacts/build-smoke')}
    run([runtime / 'python.exe', '-c', 'import fastapi, av, faster_whisper, torch; from PySide6 import QtWebEngineWidgets; import localmind.server'], cwd=payload, env=environment)
    # Dependency resolution and every shipped file are recorded, including assets.
    installed = subprocess.check_output([runtime / 'python.exe', '-c',
        'import importlib.metadata,json; print(json.dumps(sorted([(d.metadata["Name"],d.version) for d in importlib.metadata.distributions()])))'],
        cwd=payload, env=environment).decode('utf-8')
    if source_identity(ROOT, candidate_commit=args.candidate_commit) != source_info:
        raise SystemExit('Sources changed during build; no installer published. Payload preserved.')
    bundled_voice = (payload / 'offline-assets').is_dir()
    bundled_llm = (payload / 'offline-llm').is_dir()
    provenance = {**source_info, 'python': '3.11.9', 'runtime_sha256': runtime_hash,
                  'ollama_runtime': engine,
                  'dependencies': json.loads(installed), 'payload_sha256': payload_manifest(payload),
                  'voice_assets_bundled': bundled_voice, 'llm_bundled': bundled_llm,
                  'requires_explicit_model_downloads': not (bundled_voice and bundled_llm)}
    (payload / 'build-provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    offline = bundled_voice or bundled_llm
    flags = ['/DOfflineBundle=1'] if offline else []
    run([args.iscc, '/Q', *flags, '/DReleaseVersion=' + VERSION, '/O' + str(output),
         '/DPayload=' + str(payload), ROOT / 'installer/LocalMind.iss'])
    installer = output / ('LocalMind-' + VERSION + ('-Offline-Setup.exe' if offline else '-Setup.exe'))
    if not installer.is_file():
        raise SystemExit('Compiler returned without the expected installer.')
    archive = output / ('LocalMind-' + VERSION + '-Source.zip')
    write_source_archive(ROOT, archive, source_info)
    artifacts = [installer, archive]
    for name in ('RELEASE_NOTES.md', 'KNOWN_ISSUES.md', 'MANUAL_QA.md'):
        dest = output / name
        shutil.copyfile(ROOT / name, dest)
        artifacts.append(dest)
    shutil.copyfile(payload / 'build-provenance.json', output / 'build-provenance.json')
    artifacts.append(output / 'build-provenance.json')
    write_checksums(output, artifacts)
    print('Built ' + str(installer) + ' from ' + source_info['commit'])


if __name__ == '__main__':
    main()

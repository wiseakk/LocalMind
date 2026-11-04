"""Small, stdlib-only release provenance and integrity helpers."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


VERSION = '1.0.0-rc3'
RELEASE_BASE = '3ead34b00f8ecc712693205f72d0188da349be4c'


def validate_ui_payload(payload):
    """Reject damaged source text after the exact committed bytes are copied."""
    import re
    html = (Path(payload) / 'static/index.html').read_text(encoding='utf-8', errors='strict')
    if '<span class="breadcrumb">Личное пространство</span>' not in html or re.search(r'\?{3,}|\ufffd', html):
        raise ValueError('UI payload contains damaged Cyrillic or an unexpected Russian header.')
    for folder, suffixes in (('localmind', {'.py'}), ('static', {'.html', '.css', '.js'}), ('config', {'.json'})):
        for file in (Path(payload) / folder).rglob('*'):
            if file.is_file() and file.suffix in suffixes:
                file.read_text(encoding='utf-8', errors='strict')


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args]).decode('utf-8').strip()


def source_identity(root):
    commit = git(root, 'rev-parse', 'HEAD')
    branch = git(root, 'branch', '--show-current')
    if git(root, 'status', '--porcelain', '--untracked-files=all'):
        raise ValueError('Release requires a clean committed checkout, including untracked source files. See docs/RELEASE_RECOVERY.md.')
    if branch != 'release/1.0.0-rc3':
        raise ValueError('Build from release/1.0.0-rc3 after orchestrator integration; preserve RC1/RC2 and DevCrew worktrees.')
    try:
        git(root, 'merge-base', '--is-ancestor', RELEASE_BASE, commit)
    except subprocess.CalledProcessError:
        raise ValueError('RC3 must descend from the reviewed RC2 documentation commit ' + RELEASE_BASE) from None
    files = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z']).decode().split('\0')
    hashes = {name: sha256(root / name) for name in files if name and (root / name).is_file()}
    tags = git(root, 'tag', '--points-at', commit).splitlines()
    return {'commit': commit, 'base_commit': RELEASE_BASE, 'tags': tags,
            'branch': branch, 'version': VERSION, 'sources': hashes}


def validate_resume(marker, identity):
    try:
        previous = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('No valid completed dependency stage; use a fresh --output directory. Existing payload is preserved.')
    if previous != identity:
        raise ValueError('Resume inputs differ from the saved build. Use a fresh --output directory; existing payload is preserved.')


def payload_manifest(payload):
    return {p.relative_to(payload).as_posix(): sha256(p)
            for p in sorted(payload.rglob('*'))
            if p.is_file() and p.suffix != '.pyc'
            and p.name != 'build-provenance.json'}


def validate_payload_sources(root, payload, *, bundled_gguf=False):
    """Interrupted copies may be incomplete, but never contain other code."""
    for folder in ('localmind', 'static', 'config'):
        destination = payload / folder
        if not destination.exists():
            continue
        for path in destination.rglob('*'):
            if path.suffix == '.pyc':
                continue
            if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
                raise ValueError('Resume payload contains a link; use a fresh output directory.')
            if not path.is_file():
                continue
            relative = path.relative_to(payload)
            if bundled_gguf and relative.as_posix() == 'config/offline_model.json':
                continue  # Recreated from the hash-bound GGUF and build inputs.
            source = root / relative
            if not source.is_file() or sha256(source) != sha256(path):
                raise ValueError('Resume payload has stale or changed source: ' + relative.as_posix())


def validate_payload_layout(root, payload, inputs):
    """Reject stale payload assets and extras before resuming any mutation."""
    allowed = {name for name in inputs['source']['sources']
               if name.split('/')[0] in ('localmind', 'static', 'config')}
    allowed.update(('LocalMind.exe', 'build-provenance.json', 'prerequisites/OllamaSetup.exe'))
    folders = {'localmind', 'static', 'config', 'runtime', 'prerequisites'}
    if inputs['offline_gguf_sha256']:
        folders.add('offline-llm')
        allowed.update(('offline-llm/model.gguf', 'config/offline_model.json'))
    if inputs['offline_assets']:
        folders.add('offline-assets')
        manifest = json.loads((root / 'config/voice_resources.json').read_text(encoding='utf-8'))
        models = {'cpu-fast': 'small', 'balanced': 'small', 'gpu-quality': 'medium'}
        prefixes = ['silero/', *['whisper/' + models[p] + '/' for p in inputs['asr_profiles']]]
        allowed.update('offline-assets/' + asset['path'] for asset in manifest['assets']
                       if any(asset['path'].startswith(prefix) for prefix in prefixes))
    for path in payload.rglob('*'):
        relative = path.relative_to(payload)
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Resume payload contains a link.')
        if path.is_dir():
            if relative.parts[0] not in folders:
                raise ValueError('Unexpected payload directory: ' + relative.as_posix())
            continue
        if relative.parts[0] == 'runtime' or path.suffix == '.pyc':
            continue  # Runtime is hash-bound separately; pyc is excluded by Inno.
        if relative.as_posix() not in allowed:
            raise ValueError('Unexpected payload file: ' + relative.as_posix())


def copy_committed_sources(root, payload, identity):
    """Ignored developer files must never enter the installer payload."""
    import shutil
    for name, digest in identity['sources'].items():
        relative = Path(name)
        if relative.parts[0] not in ('localmind', 'static', 'config'):
            continue
        source, target = root / relative, payload / relative
        if source.is_symlink() or sha256(source) != digest:
            raise ValueError('Committed source changed during copy: ' + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def write_source_archive(root, output, identity):
    """Ship exactly the committed tree, never .env, caches or a developer venv."""
    if output.exists():
        raise ValueError('Source archive already exists; choose a fresh output directory.')
    subprocess.run(['git', '-C', str(root), 'archive', '--format=zip',
                    '--prefix=LocalMind-' + VERSION + '/', '-o', str(output), identity['commit']], check=True)
    with zipfile.ZipFile(output) as archive:
        for name in archive.namelist():
            relative = name.split('/', 1)[1]
            if relative in identity['sources']:
                # Git archive uses repository bytes, which may differ from a CRLF
                # checkout. Both identities are retained explicitly.
                archive.read(name)


def write_checksums(output, artifacts):
    lines = [sha256(p) + '  ' + p.name for p in artifacts]
    (output / 'SHA256.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')

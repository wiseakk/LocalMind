"""Pinned official standalone package, verified before any executable is staged."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import urllib.request
import zipfile


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def stage(root, payload, cache):
    spec = json.loads((root / 'config/ollama_runtime.json').read_text(encoding='utf-8'))
    # Builder inputs are committed source, never an LLM/user-supplied download URL.
    expected_url = 'https://github.com/ollama/ollama/releases/download/v' + spec['version'] + '/ollama-windows-amd64.zip'
    if spec['url'] != expected_url or spec['version'] != '0.40.14' or spec['bytes'] != 1601954968:
        raise ValueError('Unreviewed Ollama runtime manifest')
    archive = cache / ('ollama-' + spec['version'] + '-windows-amd64.zip')
    cache.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        partial = archive.with_suffix('.partial')
        urllib.request.urlretrieve(spec['url'], partial)
        if partial.stat().st_size != spec['bytes'] or digest(partial) != spec['sha256']:
            raise ValueError('Ollama runtime download hash/size mismatch')
        partial.replace(archive)
    if archive.stat().st_size != spec['bytes'] or digest(archive) != spec['sha256']:
        raise ValueError('Ollama runtime cache hash/size mismatch')
    destination = payload / 'runtime/ollama'
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if sum(row.file_size for row in entries) > 12 * 1024**3 or len(entries) > 10000:
            raise ValueError('Oversized runtime archive')
        allowed = {row.filename.replace('\\', '/') for row in entries if not row.is_dir()}
        allowed.update(('LICENSE-OLLAMA.txt', 'runtime-manifest.json'))
        for existing in destination.rglob('*'):
            if existing.is_symlink() or getattr(existing.lstat(), 'st_file_attributes', 0) & 0x400:
                raise ValueError('Linked runtime destination')
            if existing.is_file() and existing.relative_to(destination).as_posix() not in allowed:
                raise ValueError('Unexpected stale runtime file; use a fresh payload')
        for row in entries:
            fragment = PurePosixPath(row.filename.replace('\\', '/'))
            if (fragment.is_absolute() or '..' in fragment.parts or ':' in str(fragment)
                    or stat.S_ISLNK(row.external_attr >> 16)
                    or any(part.rstrip(' .') != part for part in fragment.parts)):
                raise ValueError('Unsafe runtime archive path')
            target = destination.joinpath(*fragment.parts)
            if row.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(row) as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst, length=1024**2)
    if not (destination / 'ollama.exe').is_file() or not (destination / 'lib/ollama').is_dir():
        raise ValueError('Incomplete standalone Ollama package')
    license_path = destination / 'LICENSE-OLLAMA.txt'
    if not license_path.exists():
        urllib.request.urlretrieve(spec['license_url'], license_path)
    if 'MIT' not in license_path.read_text(encoding='utf-8'):
        raise ValueError('Missing upstream redistribution notice')
    files = {p.relative_to(destination).as_posix(): digest(p) for p in sorted(destination.rglob('*'))
             if p.is_file() and p.name != 'runtime-manifest.json'}
    (destination / 'runtime-manifest.json').write_text(json.dumps({'version': spec['version'],
        'archive_sha256': spec['sha256'], 'files': files}, indent=2), encoding='utf-8')
    return {'version': spec['version'], 'archive_sha256': spec['sha256'], 'files': files}

"""Exercise release orchestration with fake compiler/network, never claim an EXE test."""
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

import pytest


@pytest.fixture
def builder(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('build_windows')


@pytest.mark.parametrize('offline', [False, True])
def test_build_keeps_source_identity_through_runtime_and_asset_copies(tmp_path, monkeypatch, builder, offline):
    root = tmp_path / 'source'
    output = tmp_path / 'release'
    for folder in ('localmind', 'static', 'config', 'installer'):
        (root / folder).mkdir(parents=True)
    for name in ('RELEASE_NOTES.md', 'KNOWN_ISSUES.md', 'MANUAL_QA.md'):
        (root / name).write_text(name)
    asset = tmp_path / 'assets/silero/model.pt'
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b'voice weights')
    (root / 'config/voice_resources.json').write_text(json.dumps({'assets': [
        {'path': 'silero/model.pt', 'bytes': asset.stat().st_size, 'sha256': builder.sha256(asset)}]}))
    gguf = tmp_path / 'fallback.gguf'
    gguf.write_bytes(b'GGUFexample')
    iscc = tmp_path / 'compiler.exe'
    iscc.write_bytes(b'fake compiler')
    source = {'commit': 'a' * 40, 'branch': 'release/1.0.0-rc2', 'version': builder.VERSION, 'sources': {}}
    source['sources'] = {p.relative_to(root).as_posix(): builder.sha256(p)
                         for p in root.rglob('*') if p.is_file()}
    monkeypatch.setattr(builder, 'ROOT', root)
    monkeypatch.setattr(builder, 'source_identity', lambda _: dict(source))
    args = ['build_windows.py', '--output', str(output), '--iscc', str(iscc)]
    if offline:
        args += ['--offline-assets', str(asset.parents[1]), '--offline-gguf', str(gguf), '--offline-license', 'MIT']
    monkeypatch.setattr(sys, 'argv', args)
    monkeypatch.setattr(builder, 'sys', SimpleNamespace(argv=args, executable='python.exe', version_info=(3, 11)))
    monkeypatch.setattr(builder.platform, 'machine', lambda: 'AMD64')
    original_is_file = Path.is_file
    monkeypatch.setattr(Path, 'is_file', lambda p: True if p.name == 'csc.exe' else original_is_file(p))

    def retrieve(url, destination):
        if str(destination).endswith('.zip'):
            with zipfile.ZipFile(destination, 'w') as archive:
                archive.writestr('python.exe', b'fake runtime')
                archive.writestr('Lib/site-packages/PySide6/vcruntime140_1.dll', b'fake dll')
        else:
            Path(destination).write_bytes(b'fake prerequisite')

    def run(command, **kwargs):
        for value in map(str, command):
            if value.startswith('/out:'):
                Path(value[5:]).write_bytes(b'fake launcher')
        if Path(command[0]) == iscc:
            suffix = '-Offline-Setup.exe' if offline else '-Setup.exe'
            (output / ('LocalMind-' + builder.VERSION + suffix)).write_bytes(b'fake installer')

    monkeypatch.setattr(builder.urllib.request, 'urlretrieve', retrieve)
    monkeypatch.setattr(builder, 'run', run)
    monkeypatch.setattr(builder.subprocess, 'check_output', lambda *a, **k: b'[["example","1.0"]]')
    archived = []

    def archive(root, destination, identity):
        archived.append(identity)
        destination.write_bytes(b'fake source archive')

    monkeypatch.setattr(builder, 'write_source_archive', archive)
    builder.main()
    provenance = json.loads((output / 'build-provenance.json').read_text(encoding='utf-8'))
    assert provenance['commit'] == source['commit']
    assert provenance['branch'] == source['branch']
    assert provenance['voice_assets_bundled'] is offline
    assert provenance['llm_bundled'] is offline
    assert archived == [source]
    assert (output / 'SHA256.txt').is_file()


@pytest.mark.parametrize('change', ['runtime', 'added-file', 'archive', 'inputs'])
def test_resume_rejects_changed_dependencies_archive_or_inputs(tmp_path, builder, change):
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    (runtime / 'python.exe').write_bytes(b'original runtime')
    archive = tmp_path / 'python.zip'
    archive.write_bytes(b'original archive')
    inputs = {'source': {'commit': 'abc'}, 'asr_profiles': ['balanced']}
    marker = tmp_path / 'dependency-stage.json'
    marker.write_text(json.dumps(builder.dependency_stage(inputs, runtime, archive)))
    builder.validate_resume(marker, builder.dependency_stage(inputs, runtime, archive))
    if change == 'runtime':
        (runtime / 'python.exe').write_bytes(b'changed runtime')
    elif change == 'added-file':
        (runtime / 'stale.dll').write_bytes(b'old dependency')
    elif change == 'archive':
        archive.write_bytes(b'changed archive')
    else:
        inputs = {**inputs, 'asr_profiles': ['cpu-fast']}
    with pytest.raises(ValueError, match='inputs differ'):
        builder.validate_resume(marker, builder.dependency_stage(inputs, runtime, archive))


def test_resume_cannot_download_missing_runtime_or_archive(tmp_path, builder):
    with pytest.raises(ValueError, match='runtime/archive missing'):
        builder.dependency_stage({}, tmp_path / 'runtime', tmp_path / 'python.zip')

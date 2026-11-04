import json
from pathlib import Path
import subprocess
import sys

import pytest
from scripts import release_support as release


def test_resume_refuses_missing_and_changed_source_or_options(tmp_path):
    marker = tmp_path / 'stage.json'
    identity = {'source': {'commit': 'abc', 'sources': {'a.py': '123'}}, 'offline_assets': False}
    with pytest.raises(ValueError, match='dependency stage'):
        release.validate_resume(marker, identity)
    marker.write_text(json.dumps(identity))
    release.validate_resume(marker, identity)
    for other in ({**identity, 'offline_assets': True}, {**identity, 'source': {'commit': 'def'}}):
        with pytest.raises(ValueError, match='inputs differ'):
            release.validate_resume(marker, other)


def test_source_gate_rejects_uncommitted_files_and_wrong_branch(monkeypatch, tmp_path):
    values = {'rev-parse': 'abc', 'branch': 'release/1.0.0-rc2', 'status': '?? untracked.py'}
    monkeypatch.setattr(release, 'git', lambda root, *args: values[args[0]])
    with pytest.raises(ValueError, match='clean committed'):
        release.source_identity(tmp_path)
    values.update(status='', branch='alpha')
    with pytest.raises(ValueError, match='release/1.0.0-rc2'):
        release.source_identity(tmp_path)


def test_rc2_provenance_requires_reviewed_release_ancestry(monkeypatch, tmp_path):
    calls = []
    def fake_git(root, *args):
        calls.append(args)
        if args[0] == 'merge-base':
            raise subprocess.CalledProcessError(1, ['git', *args])
        return {'rev-parse': 'abc', 'branch': 'release/1.0.0-rc2', 'status': ''}[args[0]]
    monkeypatch.setattr(release, 'git', fake_git)
    with pytest.raises(ValueError, match='descend from'):
        release.source_identity(tmp_path)
    assert ('merge-base', '--is-ancestor', release.RELEASE_BASE, 'abc') in calls


def test_payload_records_assets_and_ignores_only_generated_caches(tmp_path):
    (tmp_path / 'asset.bin').write_bytes(b'weights')
    (tmp_path / 'code.py').write_text('pass')
    (tmp_path / 'code.pyc').write_bytes(b'cache')
    (tmp_path / 'build-provenance.json').write_text('{}')
    (tmp_path / '__pycache__').mkdir()
    (tmp_path / '__pycache__/cache').write_text('cache')
    assert set(release.payload_manifest(tmp_path)) == {'asset.bin', 'code.py', '__pycache__/cache'}
    release.write_checksums(tmp_path, [tmp_path / 'asset.bin'])
    assert (tmp_path / 'SHA256.txt').read_text() == release.sha256(tmp_path / 'asset.bin') + '  asset.bin\n'


def test_resume_source_copy_rejects_stale_extra_and_modified_code(tmp_path):
    root, payload = tmp_path / 'source', tmp_path / 'payload'
    (root / 'localmind').mkdir(parents=True)
    (payload / 'localmind').mkdir(parents=True)
    (root / 'localmind/a.py').write_text('new code')
    release.validate_payload_sources(root, payload)  # Interrupted before this file.
    (payload / 'localmind/a.py').write_text('new code')
    release.validate_payload_sources(root, payload)
    (payload / 'localmind/a.py').write_text('old code')
    with pytest.raises(ValueError, match='stale or changed'):
        release.validate_payload_sources(root, payload)
    (payload / 'localmind/a.py').write_text('new code')
    (payload / 'localmind/deleted_old_module.py').write_text('old code')
    with pytest.raises(ValueError, match='deleted_old_module'):
        release.validate_payload_sources(root, payload)


def test_installer_copy_excludes_ignored_and_untracked_developer_files(tmp_path):
    root, payload = tmp_path / 'source', tmp_path / 'payload'
    (root / 'config').mkdir(parents=True)
    committed = root / 'config/public.json'
    committed.write_text('{}')
    (root / 'config/private.log').write_text('private data')
    (root / 'config/.env').write_text('secret')
    release.copy_committed_sources(root, payload, {'sources': {'config/public.json': release.sha256(committed)}})
    assert sorted(p.name for p in (payload / 'config').iterdir()) == ['public.json']


@pytest.mark.parametrize('extra', ['offline-llm/model.gguf', 'offline-assets/silero/old.pt', 'private.log',
                                  'localmind/__pycache__/hidden.exe'])
def test_resume_refuses_old_unrequested_assets_and_private_files(tmp_path, extra):
    payload = tmp_path / 'payload'
    target = payload / extra
    target.parent.mkdir(parents=True)
    target.write_bytes(b'old payload')
    inputs = {'source': {'sources': {}}, 'offline_gguf_sha256': None, 'offline_assets': False}
    with pytest.raises(ValueError, match='Unexpected payload'):
        release.validate_payload_layout(tmp_path, payload, inputs)


def test_build_preflight_prevents_network_and_payload_writes_when_tools_missing(tmp_path):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / 'scripts/build_windows.py'),
                             '--output', str(tmp_path / 'output'),
                             '--iscc', str(tmp_path / 'missing-compiler.exe')], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Build tool missing' in result.stderr
    assert not (tmp_path / 'output').exists()

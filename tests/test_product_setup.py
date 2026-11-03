import json
from pathlib import Path
import pytest
from localmind.paths import migrate_legacy, python_runtime
from localmind.resource_setup import classify_voice_error


def test_migration_preserves_selection_without_copying_grants_or_secrets(tmp_path):
    source, dest = tmp_path / 'old', tmp_path / 'new'
    (source / 'results/private').mkdir(parents=True)
    (source / '.env').write_text('OLLAMA_MODEL=gemma4:12b\nHOME_ASSISTANT_TOKEN=secret\nDEMO_MODE=false\n', encoding='utf-8')
    (source / 'results/private/active-model.json').write_text('{"model":"gemma4:12b"}')
    (source / 'results/private/personal_mode.json').write_text('{"enabled":true}')
    model = source / 'models/whisper/small/model.bin'; model.parent.mkdir(parents=True); model.write_bytes(b'model')
    migrate_legacy(source, dest)
    assert json.loads((dest / 'private/active-model.json').read_text())['model'] == 'gemma4:12b'
    assert 'secret' not in (dest / '.env').read_text()
    assert 'DEMO_MODE' not in (dest / '.env').read_text()
    assert not (dest / 'private/personal_mode.json').exists()
    (dest / 'private/active-model.json').write_text('{"model":"owner-choice"}')
    migrate_legacy(source, dest)
    assert 'owner-choice' in (dest / 'private/active-model.json').read_text()
    assert model.read_bytes() == b'model'


def test_partial_legacy_resource_is_not_migrated(tmp_path):
    (tmp_path / 'old/models').mkdir(parents=True)
    (tmp_path / 'old/models/bad.partial').write_bytes(b'incomplete')
    migrate_legacy(tmp_path / 'old', tmp_path / 'new')
    assert not (tmp_path / 'new/models/bad.partial').exists()


@pytest.mark.parametrize('error,code', [(ModuleNotFoundError('torch'), 'dependency_missing'),
    (FileNotFoundError('file'), 'path_invalid'), (RuntimeError('DLL load failed'), 'library_incompatible'),
    (RuntimeError('CUDA out of memory'), 'gpu_error'), (ValueError('invalid model'), 'resource_corrupt')])
def test_voice_failures_are_distinct(error, code):
    assert classify_voice_error(error) == code


def test_worker_runtime_is_python_not_gui():
    assert python_runtime().name.lower() in ('python.exe', 'python', 'python3')

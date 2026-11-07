import json
from pathlib import Path
import pytest
from localmind.paths import migrate_legacy, legacy_preferences_plan, python_runtime
from localmind.resource_setup import classify_voice_error


def test_onboarding_progress_persists_without_completing_or_overwriting_choices(tmp_path, monkeypatch):
    from localmind import paths, product_state
    from localmind.setup_routes import OnboardingRequest, save_onboarding

    monkeypatch.setattr(paths, 'CONFIG', tmp_path)
    assert product_state.read()['onboarding'] == {'completed': False}
    save_onboarding(OnboardingRequest(step=2, profile='gpu-quality', skip_asr=True))
    assert product_state.read()['onboarding'] == {
        'completed': False, 'step': 2, 'profile': 'gpu-quality', 'skip_asr': True,
    }
    save_onboarding(OnboardingRequest(completed=True))
    save_onboarding(OnboardingRequest(step=1))
    assert product_state.read()['onboarding'] == {
        'completed': True, 'step': 1, 'profile': 'gpu-quality', 'skip_asr': True,
    }


@pytest.mark.parametrize('step', [-1, 6, True, '3', 3.0])
def test_onboarding_rejects_invalid_steps(step):
    from pydantic import ValidationError
    from localmind import product_state
    from localmind.setup_routes import OnboardingRequest

    with pytest.raises(ValidationError):
        OnboardingRequest(step=step)
    with pytest.raises(ValueError):
        product_state.update('onboarding', {'step': step})


def test_migration_preserves_selection_without_copying_grants_or_secrets(tmp_path):
    source, dest = tmp_path / 'old', tmp_path / 'new'
    (source / 'results/private').mkdir(parents=True)
    (source / '.env').write_text('OLLAMA_MODEL=gemma4:12b\nHOME_ASSISTANT_TOKEN=secret\nDEMO_MODE=false\n', encoding='utf-8')
    (source / 'results/private/active-model.json').write_text('{"model":"gemma4:12b"}')
    (source / 'results/private/personal_mode.json').write_text('{"enabled":true}')
    model = source / 'models/whisper/small/model.bin'; model.parent.mkdir(parents=True); model.write_bytes(b'model')
    plan = legacy_preferences_plan(source, dest)
    migrate_legacy(source, dest, consent=True, reviewed_plan=plan)
    assert json.loads((dest / 'private/active-model.json').read_text())['model'] == 'gemma4:12b'
    assert 'secret' not in (dest / '.env').read_text()
    assert 'DEMO_MODE' not in (dest / '.env').read_text()
    assert not (dest / 'private/personal_mode.json').exists()
    (dest / 'private/active-model.json').write_text('{"model":"owner-choice"}')
    migrate_legacy(source, dest, consent=True, reviewed_plan=legacy_preferences_plan(source, dest))
    assert 'owner-choice' in (dest / 'private/active-model.json').read_text()
    assert model.read_bytes() == b'model'


def test_legacy_preferences_require_consent_and_unchanged_preview(tmp_path):
    source, dest = tmp_path / 'old', tmp_path / 'new'
    source.mkdir()
    (source / '.env').write_text('OLLAMA_MODEL=gemma4:12b')
    plan = legacy_preferences_plan(source, dest)
    assert migrate_legacy(source, dest, reviewed_plan=plan) == []
    assert not dest.exists()
    (source / '.env').write_text('OLLAMA_MODEL=owner-choice')
    with pytest.raises(ValueError, match='План'):
        migrate_legacy(source, dest, consent=True, reviewed_plan=plan)
    assert not dest.exists()


def test_legacy_import_does_not_replace_file_created_during_publication(tmp_path, monkeypatch):
    from localmind import paths
    dest = tmp_path / '.env'
    original = paths.os.link
    def race(source, target):
        target.write_text('owner-choice')
        original(source, target)
    monkeypatch.setattr(paths.os, 'link', race)
    with pytest.raises(FileExistsError):
        paths._publish_migrated(dest, 'old-choice')
    assert dest.read_text() == 'owner-choice'
    assert not list(tmp_path.glob('*.tmp'))


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


@pytest.mark.parametrize('interactive,answer,expected', [(False, 'y', False), (True, 'n', False), (True, 'y', True)])
def test_source_start_respects_reviewed_migration_consent(monkeypatch, interactive, answer, expected):
    from types import SimpleNamespace
    import start
    from localmind import paths
    plan = [{'source': 'old-settings', 'target': 'new-settings'}]
    copied = []
    monkeypatch.setattr(paths, 'legacy_preferences_plan', lambda: plan)
    monkeypatch.setattr(paths, 'migrate_legacy', lambda **kw: copied.append(kw))
    monkeypatch.setattr(start.sys, 'stdin', SimpleNamespace(isatty=lambda: interactive))
    monkeypatch.setattr('builtins.input', lambda prompt: answer)
    monkeypatch.setattr(start.uvicorn, 'run', lambda *a, **kw: None)
    start.main()
    assert bool(copied) is expected
    if expected:
        assert copied == [{'consent': True, 'reviewed_plan': plan}]

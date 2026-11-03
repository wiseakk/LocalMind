"""An owner-approved parent never authorizes edits to the assistant itself."""
from pathlib import Path
from localmind.paths import APP_ROOT, DATA_ROOT
from localmind.personal_permissions import ordinary_path
from localmind.file_access import FileAccess
from localmind.file_mutations import FileMutations


def test_runtime_configuration_and_grants_are_not_ordinary_documents():
    for path in (DATA_ROOT/'private/personal_mode.json', DATA_ROOT/'private/home-assistant.json',
                 APP_ROOT/'config/voice_resources.json', APP_ROOT/'config/offline_model.json',
                 APP_ROOT/'localmind/settings.py', APP_ROOT/'static/assets/app.js',
                 APP_ROOT/'runtime/core/python311._pth', APP_ROOT/'models/silero/v5_6_ru.pt'):
        assert not ordinary_path(path), str(path)


def test_approved_parent_cannot_prepare_a_self_permission_overwrite(tmp_path):
    access=FileAccess()
    # Root is ordinary, but a protected descendant remains excluded.
    parent=DATA_ROOT.parent
    parent.mkdir(parents=True,exist_ok=True)
    access.set_personal_mode(True,[str(parent)])
    scope=next(iter(access.personal_mode.roots()))
    relative=str((DATA_ROOT/'private/personal_mode.json').relative_to(parent))
    result=FileMutations(access).prepare('owner','overwrite',scope,relative,'{"enabled":true}')
    assert not result.success and result.execution_status!='confirmation_required'

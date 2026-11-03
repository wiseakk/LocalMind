"""Workspace test scratch space compatible with Windows restricted tokens.

Python 3.14's mkdir(mode=0o700), used by pytest's normal tmp_path, installs a
user-only DACL that excludes this runner's sandbox SID. This fixture inherits the
workspace ACL instead. Production temporary-audio permissions are unchanged.
"""
from pathlib import Path
import shutil
import uuid

import os
os.environ['LOCALMIND_DATA_DIR'] = str(Path(__file__).resolve().parents[1] / '.test-artifacts' / 'user-data')

import pytest


@pytest.fixture
def offline_desktop_planner(monkeypatch):
    """Legacy HTTP regressions also exercise the safe planner-unavailable path.

    LLM-first protocol/execution is tested separately in test_llm_desktop*.py.
    No regression suite should contact a developer's live Ollama daemon.
    """
    import httpx
    from localmind import llm_planner
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError('Deliberately offline planner for compatibility regression')
    monkeypatch.setattr(llm_planner, 'choose', unavailable)


@pytest.fixture
def tmp_path():
    workspace = Path(__file__).resolve().parents[1]
    scratch = workspace / '.test-artifacts'
    scratch.mkdir(exist_ok=True)
    generated = scratch / uuid.uuid4().hex
    generated.mkdir()
    try:
        yield generated
    finally:
        # Both paths are server-generated; verify before recursive cleanup.
        if generated.resolve().parent == scratch.resolve() and generated.name.isalnum():
            shutil.rmtree(generated)

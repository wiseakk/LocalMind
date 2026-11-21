import sys
from pathlib import Path

import pytest

from localmind import paths


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux XDG layout')
@pytest.mark.parametrize('xdg', [None, '', 'relative', 'absolute'])
def test_linux_default_data_root(monkeypatch, tmp_path, xdg):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'windows'))
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'home')
    expected = tmp_path / 'home' / '.local/share'
    if xdg == 'absolute':
        expected = tmp_path / 'custom data'
        xdg = str(expected)
    if xdg is None:
        monkeypatch.delenv('XDG_DATA_HOME', raising=False)
    else:
        monkeypatch.setenv('XDG_DATA_HOME', xdg)
    assert paths.default_data_root() == expected / 'LocalMind'

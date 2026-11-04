import json

import pytest

from localmind.desktop_state import read_state, visible_rect, write_state


@pytest.mark.parametrize('content', ['', '{', '[]', 'null', '{"version":2}',
                                      '{"version":1,"rect":[true,0,900,700]}'])
def test_corrupt_preferences_do_not_prevent_window_start(tmp_path, content):
    path = tmp_path / 'window.json'
    path.write_text(content)
    assert 'rect' not in read_state(path)


def test_state_round_trip_uses_user_data_and_preserves_normal_bounds(tmp_path):
    path = tmp_path / 'config/window.json'
    write_state(path, (-1200, 80, 1000, 700), True, 'light')
    assert read_state(path) == {'rect': [-1200, 80, 1000, 700], 'maximized': True, 'theme': 'light'}
    raw = json.loads(path.read_text())
    raw.update(maximized='false', theme='invalid', rect=[0, 0, -1, 600])
    path.write_text(json.dumps(raw))
    assert read_state(path) == {'maximized': False}


@pytest.mark.parametrize('screens,saved', [
    ([(0, 0, 1920, 1040)], [4000, 200, 1200, 900]),
    ([(0, 0, 960, 500)], [20, -400, 1400, 1000]),
    ([(-1920, 0, 1920, 1040), (0, 0, 1536, 824)], [-1800, 90, 1100, 700]),
    ([(0, 0, 1536, 824), (1920, -120, 1280, 680)], [1600, -500, 900, 600]),
])
def test_monitor_removal_and_mixed_dpi_keep_entire_window_visible(screens, saved):
    x, y, w, h = visible_rect(saved, screens)
    assert any(sx <= x and sy <= y and x + w <= sx + sw and y + h <= sy + sh
               for sx, sy, sw, sh in screens)


@pytest.mark.parametrize('scale', [1, 1.25, 1.4, 1.5, 2])
def test_qt_logical_coordinates_are_not_scaled_twice(scale):
    # Qt supplies the logical available geometry already divided by the DPI.
    screen = (0, 0, int(1920 / scale), int(1040 / scale))
    x, y, w, h = visible_rect([80, 80, 1000, 700], [screen])
    assert x >= 0 and y >= 0 and x + w <= screen[2] and y + h <= screen[3]

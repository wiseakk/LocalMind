"""Validated logical-pixel window preferences; no Qt or display required."""
import json

from .paths import atomic_json, ordinary_tree


def read_state(path):
    try:
        value = json.loads(ordinary_tree(path).read_text(encoding='utf-8'))
        if not isinstance(value, dict) or value.get('version') != 1:
            return {}
        result = {'maximized': value.get('maximized') is True}
        if value.get('theme') in ('light', 'dark'):
            result['theme'] = value['theme']
        rect = value.get('rect')
        if (isinstance(rect, list) and len(rect) == 4
                and all(type(n) is int and abs(n) <= 100000 for n in rect)
                and rect[2] > 0 and rect[3] > 0):
            result['rect'] = rect
        return result
    except (OSError, ValueError, RuntimeError, TypeError):
        return {}


def visible_rect(saved, screens):
    """Fit normal bounds to one real work area after DPI/monitor changes.

    Do not multiply coordinates by devicePixelRatio: Qt 6 already uses DIPs.
    Screens can have negative coordinates or gaps on mixed-DPI Windows.
    """
    if not screens:
        return (40, 40, 1100, 760)
    x, y, w, h = saved or (screens[0][0] + 40, screens[0][1] + 40, 1280, 900)

    def overlap(screen):
        sx, sy, sw, sh = screen
        return max(0, min(x + w, sx + sw) - max(x, sx)) * max(0, min(y + h, sy + sh) - max(y, sy))

    sx, sy, sw, sh = max(screens, key=overlap)
    # Reserve room for native borders/title bar, including small laptop screens.
    margin = 12
    w = min(max(w, 480), max(1, sw - 2 * margin))
    h = min(max(h, 360), max(1, sh - 2 * margin))
    return (max(sx + margin, min(x, sx + sw - w - margin)),
            max(sy + margin, min(y, sy + sh - h - margin)), w, h)


def write_state(path, rect, maximized, theme):
    atomic_json(path, {'version': 1, 'rect': list(rect), 'maximized': bool(maximized),
                       'theme': theme if theme in ('light', 'dark') else 'dark'})

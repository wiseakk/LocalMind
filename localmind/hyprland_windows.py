"""Inspect the current Hyprland session and focus verified application windows."""
import json
import os
from pathlib import Path
import re
import subprocess

from .windows_state import ApplicationState, VerifiedWindow

HYPRCTL = '/usr/bin/hyprctl'


def available():
    return bool(os.environ.get('HYPRLAND_INSTANCE_SIGNATURE') and Path(HYPRCTL).is_file())


def _ipc(*args):
    if not available():
        raise OSError('Hyprland IPC unavailable')
    output = subprocess.check_output([HYPRCTL, *args], timeout=2, stderr=subprocess.DEVNULL)
    if len(output) > 2 * 1024 * 1024:
        raise ValueError('Hyprland response too large')
    return output


def _window(row):
    address = row.get('address')
    pid = row.get('pid')
    if (not isinstance(address, str) or not re.fullmatch(r'0x[0-9a-fA-F]{1,16}', address)
            or type(pid) is not int or not 1 <= pid <= 2**31 - 1 or row.get('mapped') is not True
            or row.get('hidden') is True):
        return None
    process = Path('/proc') / str(pid)
    try:
        if process.stat().st_uid != os.getuid():
            return None
        started = int((process / 'stat').read_text().rsplit(')', 1)[1].split()[19])
        exe = process / 'exe'
        target = Path(os.readlink(exe))
        if not target.is_absolute() or not exe.samefile(target):
            return None
    except (OSError, ValueError, IndexError):
        return None
    stable_id = row.get('stableId')
    # Use the compositor's stable window ID in the fourth identity slot when
    # supported. Older Hyprland reports address and process identity only.
    instance = stable_id if type(stable_id) is int and stable_id > 0 else 0
    return target, VerifiedWindow(int(address, 16), pid, started, instance, str(row.get('title', ''))[:256])


class HyprlandWindowBackend:
    native_markers = False

    def inspect_many(self, targets):
        states = {target: [] for target in targets}
        if not states:
            return {}
        try:
            rows = json.loads(_ipc('-j', 'clients'))
            if not isinstance(rows, list) or len(rows) > 1024:
                raise ValueError('Invalid Hyprland window list')
            for row in rows:
                match = _window(row) if isinstance(row, dict) else None
                if match and match[0] in states:
                    states[match[0]].append(match[1])
        except (OSError, subprocess.SubprocessError, ValueError):
            return {target: ApplicationState('unavailable') for target in states}
        return {target: ApplicationState('visible_window' if windows else 'absent', windows=tuple(windows))
                for target, windows in states.items()}

    def inspect(self, target):
        return self.inspect_many((target,))[target]

    def _active(self):
        row = json.loads(_ipc('-j', 'activewindow'))
        return _window(row) if isinstance(row, dict) else None

    def is_active(self, target, expected):
        try:
            active = self._active()
            return bool(active and active[0] == target and self._identity(active[1]) == self._identity(expected))
        except (OSError, subprocess.SubprocessError, ValueError):
            return False

    @staticmethod
    def _identity(window):
        return window.hwnd, window.pid, window.created, window.thread_id

    def operate(self, target, expected, property_name, marker, operation):
        if operation == 'release':
            return 'released'
        if operation not in ('verify', 'focus'):
            return 'unavailable'
        if not any(self._identity(win) == self._identity(expected) for win in self.inspect(target).windows):
            return 'stale'
        # Hyprland exposes no per-window user properties. Re-observe the
        # compositor address and exact process identity for every selection.
        if operation == 'verify':
            return 'verified'
        try:
            selector = f'address:0x{expected.hwnd:x}'
            version = json.loads(_ipc('-j', 'version'))
            tag = re.match(r'^v?(\d+)\.(\d+)', str(version.get('tag', version.get('version', ''))))
            if not tag:
                return 'foreground_denied'
            if tuple(map(int, tag.groups())) >= (0, 55):
                # Only a bounded compositor address enters the fixed command.
                # No tool argument, title or other user string is executable.
                reply = _ipc('dispatch', f'hl.dsp.focus({{ window = "{selector}" }})')
            else:
                reply = _ipc('dispatch', 'focuswindow', selector)
            if reply.strip() == b'ok' and self.is_active(target, expected):
                return 'focused'
        except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
            pass
        return 'foreground_denied'

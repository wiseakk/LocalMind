# Verified window tools — 2026-10-28

`window_tools.WindowTools` adds bounded, opaque, expiring window selections to
the existing catalog and launch coordinator. App launch permissions stay bound
to the catalog source/executable fingerprint. Revocation and changed binaries
invalidate selections at use time. Titles are display metadata, never selectors.

Native inspection checks exact image, current user SID, current session, PID
creation FILETIME and live process handles. Each window adds HWND and owning
thread ID. A server-instance-specific native window property with a random value
detects HWND recycling even inside the same process/thread. Windows removes a
window's properties when it is destroyed. Properties are removed best-effort
when selections expire; stale selections never authorize another native window.
The store retains at most 128 selections for 15 minutes. Native window snapshots
are capped at 128 per application; tool results at 32 per application and 64 apps.

Focus revalidates identity and permission immediately before calling
`SetForegroundWindow`. Minimized windows can receive `SW_RESTORE`. Success is
reported only if Windows both accepted the request and observed the selected
HWND as foreground. The assistant does not synthesize keyboard input, attach
input threads, or bypass Windows foreground restrictions.

Close is deliberately conservative. Arbitrary catalog applications, including
Obsidian and document editors, return an explanation that safe closure cannot
be guaranteed. They never receive WM_CLOSE. The only automated path is a
verified calculator image (`calc.exe`, `calculator.exe`, `calculatorapp.exe`),
where closing does not discard a mutable document. This retains the permitted
scenario A explanation path until per-app document-safety behavior is tested.
The adapter posts only WM_CLOSE, preserves all application dialogs and never
uses process termination, WM_QUIT, simulated clicks, Enter, or dialog dismissal.
Each selection can submit one close request. Posting a message is reported as
request acceptance; disappearance of the selected HWND must be observed to
report closure. A denied/unknown post-close inspection never becomes success
with an invented closed state.

Native APIs cannot give callers an atomic, immutable HWND reference across
foreign-process message dispatch. Holding process handles prevents PID reuse;
the window property and immediate PID/thread checks detect observed HWND reuse.
The conservative no-document close restriction limits the residual dispatch
race. This is not a claim of a race-free Windows window-handle primitive.

## Verified evidence

Using the existing project Python 3.14 environment:

```powershell
& 'C:/Users/ExampleUser/Desktop/LocalMind_MVP_01/.venv/Scripts/python.exe' -m pytest -q tests/test_window_tools.py tests/test_windows_state.py
```

53 tests passed. Tests cover exact selection, ambiguous multiple windows,
title changes, PID/creation/thread/HWND changes, same-process HWND reuse,
revocation, binary replacement, foreground denial, at-most-once concurrent
closing, observed versus accepted closure, unknown inspection, document safety,
capacity, expiry, partial verification, shutdown cleanup and malformed IDs.
The UI can call `verify_selection(window_id)` to revalidate a selected window
and grant without focusing or closing it. Unavailable native verification cannot
refresh an old selection. Listing reports verified application names for people;
window titles remain display metadata in structured results.
Tests use controlled native mocks and fakes; they are not
real application close/focus integration measurements.

A real read-only probe verified this Python process PID/creation identity.
Native EnumWindows is unavailable in this restricted desktop; the result was
`state=unavailable`, current process verified, zero verified window records.
No personal application was launched, focused or closed. Real Obsidian,
calculator, multiple-window, save-dialog and foreground behavior remain
unverified in the interactive Windows desktop.

## Primary API references checked

- [GetWindowThreadProcessId](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowthreadprocessid): gets the owning thread/PID; an invalid HWND returns zero.
- [WM_CLOSE](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-close): application code decides whether to prompt; posting is not proof of closure.
- [SetForegroundWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow): Windows restricts foreground activation.
- [Window properties](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-properties): properties are associated with individual windows and must be cleaned up by the application.
- [SetPropW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setpropw): UIPI can deny property creation, which makes a window unavailable here. The data is an opaque integer with no allocated payload. Orderly shutdown/expiry removes this instance's entries best-effort; abrupt process termination cannot perform cleanup on still-open foreign windows.

One-command startup, offline operation after asset downloads and the existing
defense questions remain documented in README.md and docs/DEFENSE_QA.md.

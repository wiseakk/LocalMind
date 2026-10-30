"""Read-only Windows catalog reconciliation; no grants, launches or private files.

Queries the dedicated live service, then diagnoses the same bounded providers.
Only counts and fixed rejection messages are written, never application paths.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from localmind import apps
from localmind.settings import settings


class ScanReport(dict):
    def __init__(self):
        super().__init__(truncated=False, unavailable_providers=[])
        self.bounds = Counter()

    def __setitem__(self, key, value):
        if key == 'truncated' and value:
            caller = inspect.currentframe().f_back
            self.bounds[f'{caller.f_code.co_name}:{caller.f_lineno}'] += 1
        super().__setitem__(key, value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/evidence/redemption-regression-apps.json')
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('Windows is required')
    headers = {'X-LocalMind-Key': settings.key} if settings.key else {}
    # Fixed loopback service configured for this checkout; never grant or launch.
    with httpx.Client(base_url=f'http://127.0.0.1:{settings.port}', headers=headers,
                      trust_env=False, timeout=90) as client:
        client.post('/api/apps/refresh').raise_for_status()
        response = client.get('/api/apps')
        response.raise_for_status()
        payload = response.json()
    statistics = payload['statistics']
    accepted = sum(source['accepted'] for source in statistics['sources'].values())
    assert accepted - statistics['duplicates'] == len(payload['apps']) == statistics['applications']

    roots = []
    known_roots = apps._known_roots()
    # The Win32 provider can omit unavailable roots; do not silently relabel
    # subsequent folders if that happens on another Windows installation.
    for index, root in enumerate(known_roots):
        count, examined, complete, started = 0, 0, True, time.monotonic()
        for directory, dirs, files in os.walk(root, followlinks=False):
            examined += len(files)
            if examined > 100000 or time.monotonic() - started > 5:
                complete = False
                break
            depth = len(Path(directory).relative_to(root).parts)
            dirs[:] = [name for name in dirs if depth < 6 and not apps._is_reparse(Path(directory) / name)]
            count += sum(name.casefold().endswith('.lnk') for name in files)
        roots.append({'provider_root_index': index, 'shortcuts': count, 'inventory_complete': complete,
                      'emitted_candidates': 0})

    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    # Fixed count query; no user/model/registry text is interpolated into code.
    raw = subprocess.run([str(executable), '-NoLogo', '-NoProfile', '-NonInteractive', '-Command',
        '@(Get-StartApps -ErrorAction Stop).Count'], shell=False, capture_output=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW)
    raw.check_returncode()
    start_apps_count = int(raw.stdout.strip())
    packaged_rows = apps._powershell_rows(apps._PACKAGE_DISCOVERY)
    running_rows = apps._powershell_rows(apps._RUNNING_DISCOVERY)
    scan, cache = ScanReport(), {}
    reasons, candidates = defaultdict(Counter), Counter()
    started, diagnostic_complete = time.monotonic(), True
    for index, source in enumerate(apps.discover_sources(scan)):
        if index >= 10000 or time.monotonic() - started > 45:
            diagnostic_complete = False
            break
        candidates[source.origin] += 1
        if source.origin == 'shortcuts':
            path = Path(source.key.removeprefix('shortcut:'))
            for root, counts in zip(known_roots, roots):
                if path.is_relative_to(root):
                    counts['emitted_candidates'] += 1
                    break
        try:
            apps._entry(source, cache)
        except (apps.AppError, OSError, ValueError, apps.ET.ParseError) as exc:
            # AppError messages are declared safe strings. Other exceptions can
            # include local paths, so retain only their class names.
            reasons[source.origin][str(exc) if isinstance(exc, apps.AppError) else type(exc).__name__] += 1
    report = {'generated_utc': datetime.now(timezone.utc).isoformat(),
        'kind': 'live loopback /api/apps plus independent bounded read-only provider diagnostics',
        'http_status': response.status_code, 'statistics': statistics,
        'accepted_minus_duplicates_equals_unique': True,
        'supplied_baseline': {'get_start_apps': 167, 'start_menu_shortcuts': 160},
        'contemporaneous': {'get_start_apps': start_apps_count, 'shortcut_roots': roots,
            'manifest_intersection_rows': len(packaged_rows), 'visible_process_rows_before_validation': len(running_rows)},
        'independent_diagnostic_candidates': candidates, 'candidate_rejection_reasons': dict(reasons),
        'diagnostic_completed_within_budget': diagnostic_complete,
        'bounded_scan_truncation_sites': scan.bounds, 'diagnostic_unavailable_providers': scan['unavailable_providers'],
        'limitations': ['Provider-internal registry skips before candidate emission are not individually classified.',
            'Get-StartApps is intersected with executable-bearing package manifests; its raw count is not a candidate count.',
            'Diagnostic scan is subsequent to the HTTP snapshot; running processes or installations may change.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()

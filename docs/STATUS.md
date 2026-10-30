# DevCrew — проверяемый статус LocalMind 1.0

## 2026-10-30 — Focused regression implementation; browser gate pending

Provisioned Python 3.14.5 reproduced the exact file overwrite regression. The
pathname/handle probe differed only in ctime nanoseconds. Preparation and execution
now share bounded fstat snapshots and hashing, including birthtime where available.
Real disposable Windows fixtures verify rapid create/overwrite/delete, preserved
size/mtime byte changes, identical-byte replacement, parent replacement, locks,
late move destinations and replay. Final full Python: **439 passed, 35 subtests
passed**, plus the existing pytest-cache ACL warning. Independent review caught
and verified restored pre-open file bounds and pathname-to-handle identity checks.

Live loopback HTTP upload of the original 1x1 PNG returns **200 / ready**; malformed
WEBP returns **409** and only the PNG ID is retained in the conversation. Exact
responses are in `docs/evidence/redemption-regression-png-http.json`. The old
browser fixture mixed a mocked instance with a real conversation, which the session
code correctly rejects before upload. A new controlled DOM reproduction confirms
one conversation request and zero uploads for this mismatch. Its browser test uses consistent
live metadata, a realistic 900x700 PNG and asserts HTTP acknowledgement, explicit
ready state and context exclusion of malformed WEBP. No validation was weakened.

Real installed **qwen3.5:9b** inference passed all four fixture scenarios (image
description, image-only, page-22 PDF question and follow-up), without downloads.
The observer forwarded actual local HTTP requests and compared decoded outgoing
image hashes with server-retained sanitized JPEGs; both image turns matched. Answer
checks separately found the red triangle and LMV-8142 text. Evidence is in
docs/evidence/redemption-regression-multimodal.json; this is not browser evidence.

DPR sampling now uses existing frames, lifecycle events and one non-rendering
one-second check only in visible quiet modes. Controlled DOM tests verify repeated
1.4/2/1.25/1 transitions, approximately 1.083 at capped geometry, <=1.6M pixels,
no idle drawing, single animation/timer chains, detached listeners and hide/restore.
All **49 DOM checks** (34 UI, 8 attachment, 7 history), seven JS syntax checks,
browser test syntax and 76 local asset checks pass. Final diff check passes.

Both focused Playwright commands and the full 33-scenario suite were attempted,
but worker startup fails with
`spawn EPERM`; direct Chromium launch also fails at Mojo platform-channel creation
with Windows `Access is denied (0x5)`. Browser acceptance and native monitor/zoom
transitions are **not verified** in this checkout. Do not treat this milestone as
fully accepted or merge it. Windows microphone/speaker, GPU execution/telemetry,
GPU STT and CPU inference fallback were not tested by this repair.

### Actual Windows app reconciliation (read-only)

Dedicated loopback `/api/apps/refresh` then unmocked `/api/apps` returned HTTP 200.
No launch permissions were granted and no applications were launched.

| Provider | Candidates | Accepted records | Rejected |
| --- | ---: | ---: | ---: |
| Start Menu + Desktop shortcuts | 187 | 83 | 104 |
| App Paths | 116 | 36 | 80 |
| Uninstall metadata | 49 | 34 | 15 |
| Get-StartApps/package manifests | 12 | 11 | 1 |
| Steam | 12 | 11 | 1 |
| Total | 376 | 175 | 201 |

**175 accepted records − 80 global duplicates = 95 unique applications**. Accepted
records are not unique applications: source aliases and repeated registrations
can name the same validated target. The running-process adapter returned zero
visible-process rows in this session; portable roots were not configured.
Unavailable providers: none reported. Truncation: **true**.

Contemporaneous Get-StartApps count is **168** versus the supplied **167**; current
Start Menu `.lnk` counts are **64 user + 110 common = 174**, versus supplied **160**.
There is no historical inventory list to attribute the +1/+14 differences to
specific installations. Get-StartApps is intersected with executable-bearing
package manifests: only 12 candidate rows emerge, of which one fails registration
revalidation. Do not interpret the remaining raw entries as parser failures.

Desktop inventory adds **13 user + 19 public** shortcuts. The independent bounded
diagnostic sees all 206 shortcuts, but the production scan emits 174 Start Menu +
13 user Desktop = 187 candidates: its shared **10,000-files** traversal budget is
exhausted and the public Desktop's 19 candidates are not visited. Reported
truncation is therefore material, not a complete-catalog claim.

Measured shortcut exclusions: 37 with arguments, 33 without an absolute local
target, 17 shells/scripts/system launchers, 6 service/settings components,
5 missing targets, 4 invalid paths, 1 unreadable shortcut and 1 installer. App Paths
rejects 8 non-GUI executables, 8 helpers, 18 shells/launchers, 6 missing targets,
16 changed registrations and 24 unsupported registrations. Uninstall candidates
reject 11 non-GUI executables, 2 installers and 2 shells/launchers; Steam rejects
1 service/settings component. Provider-internal skips before candidate emission
(for example registry entries without matching install metadata) are not fully
classified and are not assigned invented counts.

Reproduce diagnostics with `LOCALMIND_PORT` set to the dedicated service port and
`python scripts/verify_app_discovery.py`. Counts, rejection reasons, traversal
bound sites and limitations: `docs/evidence/redemption-regression-apps.json`.

Start remains `powershell -ExecutionPolicy Bypass -File .\start_windows.ps1` after
setup/model downloads. Offline DEMO and troubleshooting remain in `README.md`;
the existing 40 explanatory defense answers remain in `docs/DEFENSE_QA.md`.
No commit, push, deployment or merge: the required browser gate remains blocked.

## 2026-10-29 — Blacksite workspace implementation; browser acceptance blocked

Unified fullscreen scene replaces the permanent chat/right-graph split. Added
Ambient/Focus/Map/Devices/Files, contextual edges, elegant local-font composition,
dock controls and native Settings/Files/Devices/History drawers. Live history has
separate drafts, rename/delete and opt-in text-only persistence; reload/expiry
produces read-only archives without action replay or restored server grants.

Real bounded TXT/MD/CSV/PDF/DOCX ingestion now reaches local inference. Disposable
PDF/DOCX workers enforce 10 seconds/256 MiB; extracted text is conversation-scoped.
Images remain browser previews without a vision claim. Added-to-context requires
server acknowledgement. Source/truncation metadata stays explicit. Existing CSP,
allowlists, streaming replay/cancellation and speech review are preserved.

Actual local integration on a dedicated localhost8877 instance launched through
start_windows.ps1 used installed qwen3:4b to recover three unique codes from TXT,
PDF and DOCX in a real streamed answer. No model download; no mock on that path.
Default port8765 was occupied and left untouched. Reproduction and startup logs
are in ignored .test-artifacts/. DEMO devices were reported by the live server.

Automated evidence: 403 Python tests and 35 subtests green (two optional speech tests
skip without numpy/faster-whisper); 32 existing/updated DOM checks, eight attachment
lifecycle checks and seven history checks pass. JS syntax, local asset resolution,
synthetic renderer metrics and diff whitespace checks pass. Browser coverage now
has 33 scenarios, including desktop/mobile CSS-scale100/125/140%, but execution
fails before tests with spawn EPERM. Both before/after Canvas benchmarks likewise
produce failure artifacts, no new FPS/GPU numbers. Native browser fallback was
rejected for Zen. No new screenshots or native zoom acceptance are claimed.

Read-only frontend/backend reviews exposed attachment group, archive graph,
reset/deletion race, result metadata, mobile focus and narrow dock issues; fixes
were verified with focused DOM/security regressions where executable. No scoped
unresolved P0/P1 security issue remains. Visual polish, actual microphone, GPU STT,
physical speakers/HA and full external-network-blocked browser demo still require
hardware/browser acceptance. This milestone is implemented, not conference-ready
acceptance. Earlier performance numbers are historical and do not validate this UI.

Start: .\start_windows.ps1. Offline demo, troubleshooting and privacy semantics:
docs/BLACKSITE.md and README.md. Forty explanatory defense answers are preserved
in docs/DEFENSE_QA.md. No push, publication, deployment or unrelated server changes.

## 2026-10-29 — current Canvas builder revalidation (browser gate blocked)

Base `e4a71c8`. Scoped reconciliation/cache/DPR fixes preserve Canvas design,
existing animation/voice interfaces and backend. Fourteen-node controlled
submission tests reproduce the old observation-refresh cache churn and verify
zero added label rasterization/measurement/contexts after the fix. Unchanged
observations keep physics settled and preserve drag targets. Resolution-only
transitions and hide/restore retain capped backing resolution and one rAF chain.
Benchmark polling now avoids timing sorts and separates active streamed output,
Canvas submissions, rAF callbacks and trace frame events.

Current checks: **391 Python tests + 35 subtests**, **31 DOM checks**, synthetic
benchmark reducers/sampler, JS syntax, 76 local assets and diff whitespace pass.
The baseline request-expiry test race was made deterministic without backend
changes. The documented entry command starts the loopback app; actual installed
qwen3:4b produced a streamed answer with final engine ollama and no actions.

Required Playwright rerun discovers 23 scenarios but cannot start its worker
(`spawn EPERM`). The 30000 ms native-zoom benchmark cannot launch Chromium
(`spawn EPERM`), with zero completed cases. No current FPS, p95, browser CPU/GPU,
native 100/125/140% zoom, visual comparison or displayed-frame evidence exists.
Windows physical microphone, TTS audibility and GPU STT remain untested.
**The 60 FPS hardware target and browser gate remain open; no commit was made.**
Full evidence, environment, remaining checks and reproduction:
[CONSTELLATION_PERFORMANCE_REVALIDATION.md](CONSTELLATION_PERFORMANCE_REVALIDATION.md).
Earlier sections below retain their historical results and limitations.

Start: `powershell -ExecutionPolicy Bypass -File .\start_windows.ps1`.
Offline demo/troubleshooting remain in README.md; 40 explanatory defense answers
remain in docs/DEFENSE_QA.md. No model downloads, push, merge or deployment.

Дата: 28.10.2026. Исходный checkout `5a140c6`; первоначально чистый.
Изменения реализованы в существующем worktree. **Полная аппаратная и визуальная
приёмка не завершена.** Новых Git-коммитов нет: `git add`/`git commit` получили
Permission denied при создании index.lock в общей `.git/worktrees` вне writable
root. Обход прав, push, merge, публикация и изменения системной конфигурации не выполнялись.

## M0 — baseline и offline startup

- Provisioned Python: `C:\Users\ExampleUser\Desktop\LocalMind_MVP_01\.venv\Scripts\python.exe`.
  В worktree `.venv` отсутствовал; использовалось готовое окружение только для запуска.
- Baseline `-m pytest --collect-only -q`: **18 collected**; `-m pytest -q`:
  **18 passed, 35 subtests passed in 0.50s**, warning недоступного pytest cache.
- Первый `start.py` упал на UnicodeEncodeError cp1252 при печати русского.
  Исправлено UTF-8 stdout. Повтор: Application startup complete, Uvicorn127.0.0.1:8765;
  реальный `GET /api/info`200. Прежняя ошибка импорта FastAPI не присутствовала.
- `setup_windows.ps1` отделён от offline `start_windows.ps1`; pip на обычном
  запуске не вызывается. Proxy headers в официальном старте отключены.

## M1 — результат до комментария и дедупликация

- ActionResult, независимые prepare/complete, tool-free structured Ollama composer,
  failure fallback, lengths и отдельные action/LLM ms. JSON route совместим;
  NDJSON route выдаёт status перед final. Shared RequestStore bounded128/workers4/TTL300s.
- Проверены concurrency, changed payload409, отмена shared futures, потеря
  соединения, неожиданный composer exception, malformed JSON и ложные success-фразы.
- Первичный focused run responses/apps: **48 passed in1.45s**. Последующие
  дополнительные регрессии вошли в общий набор. Полный протокол: M1_VERIFICATION.md.
- Реальный Ollama `GET /api/tags`200, `qwen3:4b`. Первый successful composer smoke:
  action1ms/LLM1000ms. Более поздний реальный HTTP smoke: status **2ms**, final **921ms**,
  действие DEMO lamp; replay JSON/stream идентичен. Safe-close отказ прошёл через
  настоящую модель без закрытия окна. Это единичные smoke timings, не benchmark.
- Найденный в real educational smoke self-reasoning Qwen исправлен structured
  dialogue envelope и request-local Qwen prefill без изменения модели.
  Повторный реальный HTTP smoke вернул прямой RSA-ответ, LLM1585ms.
  На пельменях остались фактические ошибки самой модели; canned answers не добавлялись.

## M2 — интерфейс и rendering

- Новый русский layout, sidebar/settings/apps/native dialogs, статусные чипы,
  технический журнал, pending/recording/processing/error, responsive CSS/reduced motion.
  Голос только в редактируемом input; duplicate draft bubble удалён.
- Исправлены mic getUserMedia race/start exception, retry старше120s/restart,
  mute delayed playback, скрытая mobile sidebar inert.
- `npm run test:dom`: **4 DOM behavior checks passed**. Настоящие JS/DOMPurify/KaTeX:
  Markdown/code/table/list/math/XSS/media/plain-text, staged transcript, repeated
  submit, status before delayed commentary, mic recovery, mute in-flight TTS.
- DOMPurify обновлён3.4.10→3.4.17, KaTeX0.16.22→0.19.1; runtime assets/fonts vendored.
  `npm audit --omit=dev`: **found0 vulnerabilities**. JS syntax checks passed.
- CUA inventory не предоставил браузер; createBrowserTab unavailable. Установка
  Playwright Chromium и запуск7 browser tests остановились с **spawn EPERM**.
  Browser tests не прошли и скриншотов нет. Точный checklist: UI_QA.md.

## M3 — локальный голос

- Профили base/small/medium, русский VAD, CPU fallback, 30s/8MB,
  forced audio containers, isolated process120s, concurrency1, cleanup, Piper Denis.
  Setup/download отдельно, inference local_files_only/HF offline, av18.1.0 сохранён.
- Voice focused suite: **17 passed**. Реальны PyAV decode и isolated silence;
  CUDA fallback и API WAV success — mocks.
- Explicit setup загрузил base/small и Denis внутри проекта. Piper1.8.0 и
  pathvalidate распакованы в `.voice-deps` из official PyPI wheels с проверкой SHA256;
  системное окружение не менялось. Обычный pip-target упёрся в sandbox temp ACL.
- Реальный direct offline worker: Piper3244ms, WAV1.474s для «Включи настольную лампу.»;
  CPU base708ms → «Клечи на стольную лампу.»; small1835ms → «Ключим на стольную лампу.».
  Это **ошибки синтетической записи**, не доказательство хорошей русской речи.
  Exact-command prompt и padding эксперименты не вошли в код (overfit/нет улучшения).
- Нормальный private-temp HTTP voice путь блокируется ACL restricted-token Python3.14:
  теперь safe503 без путей. Eval synthetic: successful0/failed1, WER/CERnull.
  Runtime ACL не ослаблялась; direct engine smoke не выдаётся за HTTP/mic test.
- `nvidia-smi` реально обнаружил RTX4070,12282MiB, драйвер616.92; snapshot used5417MiB.
  CUDA inference/fallback на реальном GPU, микрофон и TTS playback не проверены.

## M4 — установленный каталог и разрешения

- Native read-only Start Menu/Desktop COM и App Paths; stable IDs/aliases,
  GUI PE allowlist, source/exe fingerprints, target revalidation/file guard,
  session permissions default deny, exact selected ID при одинаковых именах.
- Focused apps: **26 passed** (OS process launch mocks). Реально прочитан Windows COM shortcut.
- Реальный read-only scan: **17 безопасных GUI кандидатов за1.35s**, среди них
  Obsidian/Office/7-Zip/VLC/OBS/PyCharm. Все denied. Codex/VSCode/Discord каталогом не обнаружены;
  это не доказывает отсутствия установки — UWP/updater способ может не поддерживаться.
- Пять реальных запусков окон не демонстрировались. Неизвестные/неоднозначные цели,
  подмена ярлыка/exe, stale permission и direct API bypass проверены тестами.
- Безопасный отказ закрытия сохранён, несохранённый Notepad не затрагивался.

## M5 — review, защита, воспроизводимость

- Независимый агент провёл review/security и добавил **12 adversarial API tests**:
  permission/substitution,8 concurrent retries, Host/Origin/proxy,15s upload timeout,
  admission4 перед buffering, reusable slots и preview bypass.
- Конкретные дефекты repaired и повторно проверены: future cancellation,
  composer failure truth, mic race, stale retry, catalog race, false denial prose,
  unbounded request body time/concurrency. В reviewed checkout не установлен
  нерешённый P0/P1. Произвольную семантику LLM математически не гарантируем;
  failure TTS использует только доверенный status.
- README: one-command start, setup, offline demo, troubleshooting, acceptance run.
  ARCHITECTURE/HOW_IT_WORKS/VOICE/APPLICATIONS/EXPERIMENTS/KNOWN_LIMITATIONS/CHANGELOG
  и **40 объяснённых вопросов** DEFENSE_QA.md. Eval CLI считает WER/CER и latency
  mean/max/p50/p95 только по успешным записям, failures показаны отдельно.

## Финальная проверка после последнего ремонта

Команды выполнялись из worktree указанным выше provisioned Python:

```text
python -m pytest --collect-only -q
134 tests collected in 0.24s
python -m pytest -q
134 passed, 1 warning, 35 subtests passed in 2.29s
npm run check:ui
оба first-party JS syntax checks прошли
npm run test:dom
4 DOM behavior checks passed (not browser visual QA).
npm audit
found 0 vulnerabilities
python -m compileall -q localmind scripts start.py
exit 0
git diff --check
exit 0 (только сообщения об LF/CRLF)
```

Warning pytest относится только к недоступному cache, тесты выполнились.
Повторный реальный `start.py`: Application startup complete. После dialogue fix
`scripts/smoke_local.py`: exit0, status2ms/final836ms, LLM835ms; JSON replay
идентичен, safe-close refused, tool-free RSA response1585ms. Это один запуск,
не статистика. Никакие реальные окна/устройства не переключались.

Полная приёмка pending: real mic/человеческая WER, normal voice HTTP/playback,
CUDA inference, пять окон приложений, физически отключённая сеть и rendered-browser
checklist. Git commit заблокирован ACL metadata. Эти пункты не объявлены пройденными.

Версии реально provisioned: Python3.14.5; FastAPI0.162.0; Uvicorn0.54.0;
httpx0.28.1; pytest9.1.1; PyAV18.1.0; faster-whisper1.2.1; CTranslate2 4.8.4;
Node24.19.0; Ollama0.40.11. Версии — наблюдение этого прогона, не выдуманный benchmark.
# Overhaul milestone 1 — 2026-10-28

Baseline at `6ee4231`: 134 Python tests and 35 subtests passed. Added a fully
consumed Russian token grammar, request-local model settings, bounded replayable
text deltas, local model controls and collapsed per-message diagnostics.
Application inspection uses image identity, session and user SID; cross-request
launch coordination is implemented. Native read-only Windows probe verified the
current Python PID/creation time and an absent image. This sandbox denies
EnumWindows: real Steam windows/background/startup are NOT VERIFIED. No personal
application was launched for this milestone. Model comparison is in progress;
no quality or speed improvement is claimed yet. UI dependencies are being
installed locally; PowerShell execution policy requires `npm.cmd`.

## Overhaul milestone 2 — behavior and security verification

293 Python tests + 35 subtests pass; six DOM checks and JS syntax checks pass;
`npm.cmd audit` reports zero vulnerabilities. Dependencies installed with
`npm.cmd ci --cache .npm-cache --no-fund --ignore-scripts` (no policy change).
Independent testing found and verified fixes for compound catalog-alias grants,
false window/new-launch/light prose, isolated surrogate output and unbounded
unterminated model lines. Inference now bounds decompressed bytes, chunk count,
elapsed time and lock wait; UI transport has a timeout. Action generation is
tool-free, nonstreamed until validated, and capped at 256 tokens even in reasoning
mode; dialogue emits decoded answer deltas with replay sequence numbers.

Real `start.py` startup passed on loopback. Playwright runner failed with
`spawn EPERM`; connected browser host unavailable; native browser access rejected
as `Computer Use was not approved to use Zen`. No visual/zoom/browser-first-text
claim is made. Current 4B measurements retain factual errors; comparison downloads
are still in progress. Windows microphone, real Steam state transitions and GPU
STT coexistence remain unverified.

## Overhaul milestone 3 — retained evidence and final checks

Final `-m pytest -q`: **297 passed, 35 subtests passed in2.59s**, one existing
cache-write ACL warning. JS syntax, six DOM checks, npm audit (zero vulnerabilities)
and `git diff --check` pass. Independent regression review found no unresolved
P0/P1 in the exercised changes. Real HTTP evidence verifies incremental text,
same-ID replay, model-not-installed fallback, follow-up, DEMO and safe Steam
inspection uncertainty; exact observations are in OVERHAUL_ACCEPTANCE.md.

qwen3:4b cold/warm/CPU experiments and all answers are retained. Larger model
downloads stalled repeatedly despite reconnect and were stopped, preserving
resumable partial assets. No measured replacement default or intelligence gain
is claimed. Visual/microphone/GPU-STT/real Steam state gates remain unverified.
Startup/offline instructions, troubleshooting and existing40 explanatory defense
answers are preserved. Detailed limitations: MODEL_COMPARISON.md and
OVERHAUL_ACCEPTANCE.md.

Git staging attempted in this invocation, but failed exactly:
`fatal: Unable to create 'C:/Users/ExampleUser/Desktop/LocalMind_MVP_01/.git/worktrees/devcrew-LocalMind_MVP_01-20261028-161515-388f25de/index.lock': Permission denied`.
Changes remain safely in this worktree; no commit, push, merge or publication.

## 2026-10-28 — Constellation UI milestone (browser gate blocked)

Implemented the Russian Constellation interface: compact rail, split dialogue /
interactive Canvas, floating voice controls, tabbed settings, licensed local
Cyrillic fonts/SVG controls and bounded attachment prototype. Backend files,
API schemas, Windows controls and filesystem permissions are unchanged.
File names are private by default; no file upload/context ingestion, persistent
memory or arbitrary folder/device grant is implied. DEMO/REAL stays visible.

Actual baseline and post-change Python suite:391 passed,35 subtests passed,
one existing cache ACL warning. All seven module syntax checks and28 DOM
behavior checks pass. 76 linked local resources resolve, and all76 were served
successfully by the running loopback app with matching bytes and unchanged CSP.
Independent test/review fixes were rerun. No unresolved scoped security issue.
Evidence hashes, browser scenarios and limitations: docs/CONSTELLATION_UI.md.

Browser verification cannot be reported as passed: Playwright worker/downloader
spawn EPERM, independent Chromium IPC Access is denied, connected browser host
unavailable, native Zen action rejected by automatic approval review. No actual
screenshots/video, desktop/mobile visual approval, true100/125/140% zoom,
blocked-external-HTTP browser evidence or local-generation performance trace.
Windows microphone/speaker/GPU and real HA devices remain untested. No models
installed; no merge, push, publication or unrelated backend work. Preserve the
existing start_windows.ps1, offline demo, troubleshooting and40 defense answers.

## 2026-10-28 — responsive zoom repair verified

Both reported 125%/140% browser regressions pass. Full original 19-scenario
Playwright suite: **17 passed, 2 expected skips** (headed chrome zoom and opt-in
real Ollama trace). DOM: **28 passed**. Python: **391 passed, 35 subtests passed**,
existing pytest cache ACL warning. Seven JS syntax checks and diff check pass.
Original browser assertions/tests are unchanged. Reviewed browser screenshots.

Inspected computed styles, bounding rectangles and ancestor overflow at
100/125/140% CSS zoom and equivalent reduced viewports. Before at 1440x1000:
workspace rendered heights 1000/1250/1400; message tops 809/1012/1133.45;
microphone bottoms 972/1215.25/1361.22. Ancestors had visible overflow;
conversation had auto overflow but the oversized containing workspace placed
essential controls outside the viewport. Reduced-viewport reflow did not
reproduce this specific error: CSS zoom differs from browser chrome zoom.
After: workspace height 1000 at every scale; message bottoms 865/832/811.84;
microphone bottoms 972/965.25/961.22. Percent viewport sizing fixes the cause.

Constellation becomes a toggleable drawer at <=1100 CSS pixels of available
main width. Closed drawer is inert; Escape restores focus. Independent chat
scroll leaves the composer fixed in place. Additional geometry checks pass at
390x600, 844x390 and 760x560. Reproduce with `node scripts/inspect_layout.mjs`;
JSON computed-style/overflow reports and PNGs: `.test-artifacts/layout/` (ignored).
Backend/API/security unchanged. Windows microphone/speaker/GPU not tested here.

Start: `powershell -ExecutionPolicy Bypass -File .\start_windows.ps1`.
Offline demo after asset downloads and troubleshooting remain in README.md;
40 explanatory defense answers remain in docs/DEFENSE_QA.md. No push/deploy.

## 2026-10-28 — Constellation Canvas performance verified

Profiled original and optimized Canvas with Chrome DevTools Performance traces
on real Windows 10 build 19045 / RTX 4070 (D3D11 hardware acceleration confirmed).
Genuine native Chrome tab zoom 100/125/140% was set and read back in an isolated
benchmark browser profile. Fourteen nodes, six-second windows, actual installed
qwen3:4b generation; no mock LLM on this benchmark path. Final response diagnostics
confirmed engine ollama in all three cases. No models downloaded.

Idle FPS improved from 11.8 to approximately 165 at every scale. Ollama request
windows improved from 25.2/23.8/25.3 to 165.0/165.0/165.0 FPS. p95 frame intervals
improved from approximately 85-91 ms to 6.1 ms. Renderer CPU and whole-device GPU
samples are recorded honestly, including the higher absolute idle CPU needed for
14 times as many frames (about 4.4% of one core). Raw traces, metadata, raw JSON
and visual screenshot: .test-artifacts/canvas-native-evidence/. Committed numeric
snapshot and methodology: docs/CONSTELLATION_PERFORMANCE.json and .md.

Removed normal 12/30 FPS timeouts; use rAF timestamps, cached backgrounds/text/
glow sprites, bounded fixed-time physics with settling, capped/adaptive DPR and
explicit drawer/document/offscreen suspension. Optional developer FPS overlay is
off by default: localmindScene.setDiagnostics(true). Theme, colors, interactions,
voice consent/playback behavior, security controls and server API are preserved.
Physical microphone/speaker and GPU STT were not tested in this scoped repair.

Verification: original 19 browser scenarios plus two focused cache/lifecycle/
zoom-drag/typing regressions: 19 passed, 2 expected skips. 28 DOM checks pass.
391 Python tests and 35 subtests pass. Seven JS syntax checks, benchmark syntax
and diff check pass. Independent Reviewer/Security review found no remaining
blocker after CPU timing, suspended overlay and observable drag-test corrections.

Start: powershell -ExecutionPolicy Bypass -File .\start_windows.ps1
Offline demo after asset downloads and troubleshooting remain in README.md;
40 explanatory defense answers remain in docs/DEFENSE_QA.md. No push/deployment.

## 2026-10-30 — Checkpoint A: real-world follow-up and attachment repair

Extended complete-request Russian routing for modal foreground requests, selected
document questions, selected-file opening and latest PDF naming. App focus is now
a registered capability: bounded cancellation-aware discovery after authorization,
verified executable/session/native window identity, ambiguity selection, minimized
restore and observed foreground verification. Denial, inspection, timeout and stale
selection remain distinct. No always-on-top or forced close.

Sent attachments transfer only on request/conversation/server/ID-matched inference
acknowledgement. Immutable message snapshots retain real image thumbnails in the
in-memory chat history. Draft IDs are removed from future submissions; failures
retain drafts, and reconnect uses the existing request ID. Persistence stays text-only.
Metadata naming now revalidates selected-file hashes; permission failures retain
specific reasons. Extracted text is excluded from public action metadata.

Verified on Windows: 458 Python tests plus 35 subtests; all 34 main DOM checks,
8 attachment checks and 7 history checks; seven JS syntax checks and diff check.
Python runtime: existing project Python 3.14 environment, current worktree sources.
A separate Python 3.11 environment setup was attempted; no system setup changed.
Playwright collected 35 scenarios but worker launch failed with spawn EPERM.
Browser connector reported browser host unavailable. These are blockers, not passes.
Real Obsidian, PDF open, microphone, GPU ASR, speaker listening and browser image
inference lifecycle are not yet certified by this checkpoint. Model installed:
qwen3.5:9b, retained unchanged. No push, deployment or personal-file changes.

Start: `python start.py` in the installed environment. Offline setup/demo and
troubleshooting remain in README.md and docs/VOICE.md; docs/DEFENSE_QA.md retains
40 explanatory defense answers. Full real-device completion remains pending.

## 2026-10-30 — Checkpoint B: speech channels, voice diagnostics and grounding

Implemented additive display_text/speech_text/structured_result channels, preserving
answer/action_results. File search speaks only the selected filename; exact metadata
and further matches are collapsed. Document summaries replace the initial read
acknowledgement in speech. RU technical pronunciation and EN filename rendering do
not modify disk names. Existing TTS streaming, interruption and cancellation remain.

Inspected faster-whisper 1.2.1/PyAV 18.1.0/CTranslate2 4.8.4. Retained baseline
decoding, provider, per-request model isolation and CUDA→CPU fallback. Added measured
RMS/peak/clipping, diagnostic segment logprob/no-speech, honest uncalibrated confidence
and editable final review. No live partial recognition is claimed. Expanded the corpus
to 50 phrases and documented a repeatable consented microphone protocol. The evaluator
compares baseline/technical-ru/technical-auto on the same bytes, records hashes,
settings/device/fallback/load-inclusive latency/WER/CER/technical names, and prints raw
transcripts only with explicit --include-transcripts. No consented recordings supplied;
real recognition improvement, microphone quality and GPU STT remain unmeasured.

Compact registry/outcome facts replace raw tool status in system instructions.
Context budgeting protects instructions/current question, drops old history first,
reranks document passages to preserve relevant later pages, and discloses truncation.
Insufficient budgets fail explicitly. Public-source Warcraft checks live only in test
fixtures, with a checked Blizzard reference; production has no hardcoded lore answers.

Review corrections: Canvas sent thumbnails preserve img-src 'none' (no external image
allowance); manual retries after transport loss reuse the original request and user
message for two minutes. Revoked file grants retain bounded owner-only denial reasons
without restoring old IDs. Output channels stay consistent after cancellation/errors.

Current evidence (Windows 10 build 19045; Python 3.14.5; Node 24.19.0; Ollama 0.40.12):
- 472 Python tests and 35 subtests passed, including negations, revoked/changed files,
  scanned/encrypted PDFs and explicit write confirmation. These are automated tests;
  native/LLM doubles are identified in test modules.
- 51 DOM checks passed, including real message Canvas lifecycle with simulated
  transport failure/retry, image-only and mixed image/text. These are not screenshots.
- Seven production JS syntax checks, changed browser-test syntax checks, 76 local
  assets and diff whitespace checks passed. No separate typecheck/build configured.
- Real qwen3.5:9b: four production multimodal flows passed (PNG object/text,
  image-only, page-22 PDF content, document follow-up); two checked-source factuality
  screenings passed. These are narrow real inference results, not a broad accuracy score.
- Real Downloads search/read: 12,000 extracted characters; a bounded 6,199-character
  source with matching selected ID/content was observed in actual local Ollama input.
  No personal contents, paths or names were written to the evidence report.
- Real file open returned request_accepted; visible PDF opening is unverified.
- Obsidian launch first returned process_created. Follow-up discovered multiple
  matching windows and correctly required selection. No intended foreground HWND
  was verified; minimized/activation-denied success paths are only tested with doubles.
- Final python start.py smoke returned HTTP 200 for info/home, qwen3.5:9b selection,
  loopback binding and strict image CSP. Temporary test server stopped afterward.
- Playwright collects 35 cases but worker creation fails with spawn EPERM. Browser
  connector reports host unavailable. Actual browser composer/history rendering and
  human speaker listening remain unverified. No performance/GPU claims added.

Checkpoint commits A and B could not be created: worktree Git metadata is outside
the writable root; index.lock creation is denied. A partial early snapshot is in
.test-artifacts/checkpoint-A.patch; it predates review corrections and is not a final
deliverable. Final combined diff is saved separately. Changes remain in this worktree.
The local Python 3.11 environment bootstrap stalled and was interrupted; it contains
only pip/setuptools. Automatic approval review rejected cleanup of that generated
.venv and a hidden runner launch without an additional specific reason. Production
security/Windows settings were not weakened. Populate dependencies with setup_windows.ps1
in a normal permitted session, or use the existing installed project environment.

Start after setup: `python start.py`. Offline demo after explicit model downloads,
setup and troubleshooting remain in README.md/docs/VOICE.md. The existing 40 defense
answers remain in docs/DEFENSE_QA.md. No push, publishing or deployment occurred.
This mission is not certified complete: real Windows/browser/microphone gates and
the two repository commits remain outstanding.

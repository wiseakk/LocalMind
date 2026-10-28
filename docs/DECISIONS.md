# Архитектурные решения DevCrew

## 2026-10-28 — M0 запуск и установка

Обычный запуск не должен обращаться к сети для pip. `setup_windows.ps1` создаёт окружение и устанавливает зависимости явно; `start_windows.ps1` использует готовое окружение. `start.py` задаёт UTF-8 для redirected Windows stdout и отключает доверие proxy headers. Базовый тест-набор: 18 passed, 35 subtests; сервер реально стартовал на loopback.

Пустой журнал для проверяемых design decisions. По каждому решению записывай:
- дата/роль, проблема, варианты, почему выбран вариант, безопасность, измерение/тест.
- важное ограничение и план отката.

Исходная позиция: Windows first; Ollama local; STT multilingual RU; разрешённые OS tools с динамическим проверенным каталогом; привилегированные действия только с подтверждением.

## 27.10.2026 — Security / LM-SEC-01…04

- **Проблема:** глобальный `taskkill /IM /F`, PATH-поиск встроенных приложений, автоматическая отправка STT в исполнитель и разрешённый LAN-listener нарушали границу доверия.
- **Решение закрытия:** пока нет надёжного window/process handle конкретного экземпляра, `close_app` ничего не завершает и просит закрыть окно вручную. Это функциональное ограничение безопаснее риска потери чужих данных.
- **Решение запуска:** ID приложения выбирается только из серверного allowlist; системный каталог получает Windows API `GetSystemDirectoryW`; перед `Popen` проверяются абсолютность, существование обычного файла и точный родительский каталог. `shell=False`, аргументов от LLM нет.
- **Решение по действиям:** `/api/transcribe` только возвращает raw transcript, а UI помещает его в редактируемое поле без отправки. Отдельный вызов `/api/chat` считается явной отправкой и сохраняет старую семантику API; клиент может передать `actions_authorized=false` для режима preview. `assess_action` допускает ровно одно действие/цель; `dispatch` независимо сверяет точное имя, набор аргументов, значения и выданный grant. Ollama получает пустой список tools и отвечает только текстом.
- **Решение по сети:** официальный старт всегда передаёт Uvicorn `127.0.0.1`; настройка bind-адреса удалена; middleware отклоняет не-loopback peer даже при альтернативном запуске ASGI-сервера.
- **Откат:** вернуть предыдущую реализацию нельзя без повторного security review. Безопасное адресное закрытие или LAN можно добавить только отдельным milestone с реальным Windows window handle либо paired TLS/auth протоколом и новыми тестами.
- **Проверка:** 18 unit/API/security тестов через stdlib `unittest` прошли; обязательный pytest-gate был попытан, но `pytest` в текущем venv отсутствует и не был скачан из-за заблокированной сети. Зависимость зафиксирована в `requirements-dev.txt`. Hardware/integration claims не делались.

## 2026-10-28 — M1 execution и commentary

Builder разделил prepare_reply/complete_reply. Immutable ActionResult отделяет
DEMO observation от process_created/HA request_accepted. Composer tool-free,
JSONschema с точными facts; ошибочная генерация сохраняет status. Shared RequestStore
bounded128/four workers/TTL300s не вытесняет неистёкшие ID и не отменяется с клиентом.
Browser retry связан с instance и120s wall/monotonic deadline. Никаких гарантий
после restart/TTL без проверки состояния. Real Ollama/HTTP status2ms→final921ms
подтвердил отдельные фазы, concurrent replay протестирован mocks. Новые commits
не создаются: общий Git index вне разрешённого корня, Permission denied.

## 2026-10-28 — M2 UI и offline rendering

First-party app.js/app.css вынесены из HTML. Native dialog обеспечивает базовую
focus boundary, mobile sidebar inert; motion transform/opacity и reduced-motion.
Speech transcript остаётся draft. Статус адаптера и probabilistic commentary
показаны отдельно. DOMPurify/KaTeX обновлены после audit и vendored с font assets;
single-dollar literal, external media запрещены renderer+CSP, ссылки только по
клику. DOM regression4 passed, rendered browser check blocked spawnEPERM;
никакого утверждения о скриншотах. Отказ TTS говорит только trusted status.

## 2026-10-28 — M3 voice

Выбраны multilingual base/small/medium с явным download и local-only inference,
CPU defaults. Native decode/model вынесен в killable child120s, одна операция,
8MB/30s входа. Модель загружается каждый раз ради освобождения ресурсов после
зависания. Фиксированный контейнер блокирует upload playlist. Piper Denis chosen
с documented engine/voice licensing; browser speech fallback отсутствует.
Реальные direct CPU/Piper smoke прошли на synthetic WAV, STT ошибся; prompt,
overfit под фразу и бесполезный padding не подменяют результаты. Temp ACL sandbox
возвращает safe503; системные ACL не ослабляются.17 voice tests passed.

## 2026-10-28 — M4 каталог

Discovery metadata считается недоверенной. Native COM только читает, Resolve не
вызывается. Обнаружение отделено от разрешения: GUI PE known basenames only,
никаких arguments/shells/URL/CLI. ID привязан к источнику; fingerprint включает
exe; file guard/повторная валидация перед CreateProcess. Право session-only,
обновление приложения отзывает его. Unique id alias разрешает одинаковые имена.
26 tests и actual17 read-only candidates; actuallaunch pending. Закрытие refused.

## 2026-10-28 — M5 тесты и границы отчётности

Independent review исправил реальные race/timeout/grounding defects;12 cross-module
adversarial tests добавлены. Request body admission4/deadline15s/size caps перед
дорогим parsing; Host/Origin/peer/key до body. Тесты используют inheritance ACL
только workspace scratch, production audio private. p50/p95 nearest-rank и WER/CER
имеют явный denominator; failed processing не исчезает из отчёта.40 explanatory
jury answers не заменяют real engineering experiments. Полная приёмка pending
до hardware/normalvoice/browser; git write limitation записан, push/merge отсутствуют.
# 2026-10-28 — extend the existing assistant

- Preserve immutable execution results, catalog authorization and request-ID
  replay. Add an independent application launch lock and identity inspection.
- Token grammar consumes the whole request and exact catalog alias; a polite
  modal question may authorize a request, informational questions may not.
- Snapshot model, reasoning, context, response budget and residency into replay
  identity. Local inference verifies installed metadata; cloud stubs are refused.
- Stream only conversational answer strings, never reasoning or unvalidated
  action commentary. Replay deltas with sequence numbers and bounded memory.
- Keep the existing model provisionally until sequential measurements support a
  replacement. Qwen3 prefill is a compatibility workaround, not proof that this
  installed template supports native non-thinking generation.

## 2026-10-28 — fail closed on composition and stream defects

Independent adversarial tests showed factual JSON echoes alone do not validate
prose. Reject unobserved window assertions, invented relaunches, opposite/negated
light observations and invalid Unicode; keep the immutable completed result on
generation failure. Accepted model wording is preserved. This is conservative
text validation, not a proof of arbitrary natural-language correctness.
Use bounded byte iteration before NDJSON line parsing; per-read timeout alone
does not bound a continuously trickling response. Model settings are ContextVars
scoped to one completion, with a separate non-thinking action composition scope.

## 2026-10-28 — retain the default pending real comparison

Do not promote a larger model without the requested sequential quality/latency/
VRAM evidence. Two candidate downloads repeatedly stalled and rolled back chunks
after a reconnect; partial assets and failure evidence are retained for `--resume`.
The measured4B model still fails factual/practical regressions. Therefore the
existing4B default is provisional compatibility only, not a quality recommendation.
Keep the full acceptance explicitly incomplete rather than interpreting unit/DOM
success as microphone, desktop-window or intelligence evidence.

## 2026-10-28 — Constellation UI implementation milestone

Use isolated DevCrew checkout based on localmind-next-wip; keep backend/API,
filesystem grants and model integration intact. Choose bounded Canvas2D rather
than WebGL/framework: max36 nodes,35 edges,1.6M canvas pixels, timed idle/active
frames, offscreen/hidden suspension. Only observed session/catalog entities;
no persistent-memory or reasoning simulation. Keep filename disclosure opt-in.
Bundle licensed Cyrillic Onest/Unbounded and first-party rounded SVG controls.

Attachment selection/paste/drop is browser-memory preparation only. No upload
endpoint/context integration exists. Preview indexing/processing is labelled
as a UI demonstration; no synthetic progress percentage. Size/MIME/raster
header checks precede decoding. Canvas previews preserve img-src 'none'.
Keep application discovery read-only; grants/fingerprints/PDF read-vs-open
remain server-enforced. Arbitrary folders/device-group scopes stay explicitly
unavailable. Keep a persistent actual DEMO/REAL badge and mode-aware lamp text.

## 2026-10-28 — Constellation verification milestone

Independent testing/review found and verified fixes for microphone/reset
controls, stale STT errors, reset/send races, overlapping catalog grants,
paused-audio activity/scheduling and stale tool details. Abort STT on reset/page
exit; never retry tool requests with new identities. Keep reduced-motion and
low-performance settings effective in JavaScript as well as CSS.

Backend, syntax,28 DOM checks, local asset and real loopback asset checks pass.
Browser worker launch is blocked by spawn EPERM; independent Chromium IPC also
fails Access is denied. Native Zen access was denied by automatic review. Do
not fabricate screenshots, real zoom, performance traces or hardware evidence.
UI milestone remains pending browser gate; do not merge/integrate yet. Details,
repeatable commands and before/after report: docs/CONSTELLATION_UI.md.

## 2026-10-28 — focused responsive layout repair

CSS root zoom scales 100dvh without reducing its computed value. Use percent
heights through html/body and remove workspace/mobile minimum-height floors.
Retain min-height:0 and independent conversation overflow. At main-container
widths <=1100 CSS pixels, use a Constellation drawer with toggle/close, Escape,
focus restoration, aria-expanded and inert closed content. Container width
responds to CSS zoom and narrow windows. Preserve backend/API/CSP, voice and
original browser tests/assertions. No browser scrollIntoView workaround.

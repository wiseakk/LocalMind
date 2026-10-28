# DevCrew — проверяемый статус LocalMind 1.0

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

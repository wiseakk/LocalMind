# RC2 — решение о состоянии выпуска после сборки

## 2026-11-21 — Linux, границы первого этапа

Сохраняем Qt WebEngine и отдельный HTTP-вход. Для Linux используем отдельную
зависимость Qt и единый переносимый корень данных под `XDG_DATA_HOME`.
Это сохраняет атомарность существующего механизма смены хранилища и его
проверки защищённых путей. Windows продолжает использовать `LOCALAPPDATA`.
Для первого запуска Ollama подключается как внешний loopback-сервис.
Linux-каталог, окна и привязку файловых операций к дескрипторам вводим отдельно.
В подтверждаемых файловых запросах обратный слеш зарезервирован за Windows:
на POSIX такие относительные имена отклоняются до формирования подтверждения.

## 2026-11-08 — RC3 Bug Bash

Парные кавычки вокруг явного аргумента пути разбираются в файловой грамматике.
Лексическая проверка, разрешения и отдельное подтверждение сохраняются.
Точные запросы состояния окон и устройств обходят выбор инструмента моделью.
При смене беседы поле блокируется до восстановления черновика. На экране
доступа прокручивается тело диалога, заголовок и кнопка закрытия закреплены.
Проверки на текущем Windows не заменяют чистую установку и запись с микрофона.

## 2026-11-08 — просмотр каталога через разрешение поиска

Явный запрос с путём выбирает `files.list_directory` до планировщика и
показывает наблюдение без генерации. Действующий контроллер проверяет
`search` для каталога и каждого показанного элемента. Адаптер исключает
ссылки и reparse points, возвращает только непосредственные элементы и
сортирует папки перед файлами по имени. Сканирование ограничено 2000
элементами и бюджетом 5 секунд, выдача — 50 элементами. При неполном
сканировании общее число неизвестно. Имена отображаются буквально, а
непрозрачные идентификаторы файлов доступны в диагностике.

## 2026-11-08 — приёмка опубликованного зеркала Whisper

Настроены прямые ссылки external ASR mirror с предоставленными SHA‑256 и размерами.
В опубликованном ZIP каталог называется faster-whisper-small или
faster-whisper-medium. Внутри лежат четыре файла модели и README.md.
Три текстовых файла содержат CRLF после Windows checkout. После нормализации
их SHA‑256 совпадает с закреплённым манифестом. Разрешены только эти два
варианта обёртки для соответствующего профиля и ограниченный README,
который не извлекается. Хеши весов, проверки путей и проба faster-whisper
сохранены. Конфигурация проверена через штатное копирование payload и
запуск API из отдельного каталога в структуре установленного приложения.

## 2026-11-07 — прямое HTTPS-зеркало Whisper

Действующий поток подтверждения зеркала принимает тип direct_https.
URL и SHA‑256 хранятся в конфигурации релиза. Для прямого файла используем
потоковый GET с TLS и без перенаправлений. Сохраняем частичный ZIP при обрыве
или отмене, когда известны размер и сильный ETag. Повтор сверяет If-Range,
ETag и точный Content-Range. Финальный SHA‑256 проверяется по всему файлу
на диске, затем ZIP проходит прежнюю проверку состава и нативную пробу.
Записи Яндекс Диска без типа и ранее подтверждённые задачи сохраняют
совместимость. Приёмка реального VPS остаётся после заполнения URL и хешей.

## 2026-11-07 — дополнительные источники Whisper

Оставляем закреплённые артефакты Systran, текущие профили и журнал загрузок.
Сетевой отказ Hugging Face даёт предложение зеркала с отпечатком его
конфигурации. Для публичной ссылки используем API Яндекс Диска, проверяем
домен каждого перехода, TLS, размеры и SHA‑256. Локальный импорт передаёт
байты файлов через ограниченный loopback-запрос с прежними проверками доступа.
Временный каталог проходит проверку закреплённых файлов и нативную CPU-пробу
до публикации. При замене сохраняем предыдущий каталог. Инструкция издателю
архива и сценарий проверки находятся в ASR_SOURCES.md.

## 2026-11-07 — последовательная первоначальная настройка

Старт мастера зависит от onboarding. Новый профиль начинает с приветствия,
незавершённый продолжает с сохранённого шага, завершённый открывает мастер
вручную. Обнаружение Ollama и моделей заполняет данные четвёртого шага.
Черновик хранится в существующем product-state отдельно от признака завершения.

## 2026-11-07 — повторное использование существующих весов

Причина пустых tags в Engine Build: supervisor безусловно задавал OLLAMA_MODELS
в собственный пустой models/llm и отдельный HOME, поэтому upstream не мог найти
стандартный пользовательский .ollama/models. Дополнительно inventory возвращал
сохранённое active/default даже при отсутствии имени в tags.

Добавляем read-only обнаружение фиксированных источников и явный выбор каталога
в существующем мастере без нового дизайна. HTTP принимает только выданные сервером
ID/fingerprint, повторно проверяет manifests/blobs, сохраняет root+identity.
Выбор не копирует/не скачивает веса, не меняет глобальное окружение. Только свой
дочерний процесс получает OLLAMA_MODELS и NOPRUNE=1, чтобы upstream не очищал
неиспользуемые blobs при запуске. Shared совместимый сервер всегда используется
раньше discovery и никогда не останавливается/перенастраивается. Для пустого ПК
сохраняется мастер явной загрузки. Saved preference показывается отдельно от
доступной модели; готовность требует /show и реального /chat с проверкой digest.
Ограничение cold-load пробы увеличено с 60 до 180 секунд: реальная Gemma 12B
загружалась и прогревалась около минуты. Контроллер, файловые инструменты и голос
не менялись. Приёмка и ограничения фиксируются в STATUS/ENGINE_SETUP.
Polling мастера продолжается также при ready supervisor + ещё unavailable tags:
между этими независимыми снимками возможна гонка запуска. Переход проверяется DOM.
Финальная приёмка использует установленный payload: реальные API и Gemma, DOM-shell
JSDOM вместо native окна. Проверены выбор без pull, ответ /api/chat и настоящий
перезапуск с сохранённым verified digest. QA-инсталлятор отделён AppId и не создаёт
ярлыков/записи uninstall владельца. Это не подмена LLM mock-ответами и не доказательство
чистой Windows/ручного GUI. Самостоятельный security gate: PASS, границы доступа,
файловые инструменты и глобальное окружение пользователя не менялись.

## 2026-11-07 — самостоятельный движок LocalMind

База 762b082. Используем официальный standalone Ollama v0.40.14 Windows x64,
https://github.com/ollama/ollama/releases/download/v0.40.14/ollama-windows-amd64.zip,
1601954968 bytes, SHA256 65d68cade6cf6375f398b518224f8c8a15e062387f38cf477abfc848de7e7e29.
Официальная документация https://docs.ollama.com/windows разрешает embedding;
базовый ZIP содержит CLI/NVIDIA libraries. Все notices/licenses пакета сохраняются,
MIT upstream LICENSE включается дополнительно. MLX/ROCm не нужны для целевого
RTX 4070/CPU и не загружаются скрытно. Модели не включаются в базовый installer.

Runtime стартует фоново: сначала проверка version/tags существующего API, затем
только при свободном loopback-порту запуск абсолютного bundled exe без shell.
Собственный процесс — отдельный Windows Job Object, закрытие не затрагивает
общий Ollama. Данные/модели находятся вне каталога установки. Автовосстановление
ограничено, явная кнопка retry запускает новую попытку. OLLAMA_NO_CLOUD=1 и
127.0.0.1 задаются только окружению собственного дочернего процесса.

Расширяем существующий мастер/каталог/загрузки, не переписываем агент или policy.
«Готово» требует короткой настоящей генерации выбранной моделью. VM чистой Windows
у владельца нет; это обязательная непроверенная часть, а не mock-подтверждение.

## 2026-11-06 — реальные команды файлов и явные UI-действия

На базе 4282bfb отсутствуют summary-prefix «про что/о чём файл» и поиск
последнего PDF без императива. Добавляем общие точные parser-ветки для planner
и fallback: пересказ сначала читает фактический файл через live-policy, затем
передаёт текст LLM; прямое чтение остаётся verbatim. Последний PDF определяется
по mtime, а не по выдуманному времени скачивания; Download/Downloads/Загрузки
обозначают только системную папку Downloads.

Backend confirmation уже одноразовый, связан с разговором, ревизией, TTL и
identity файла. UI должен показывать точную операцию/путь и отдельные кнопки
подтверждения/отмены; текст чата не подтверждает удаление. Кнопки привязаны к
исходным conversation_id/server_instance, блокируются при запросе/истечении,
не повторяют неясный результат автоматически. История не восстанавливает
живые подтверждения. Выбор окна — отдельная адаптивная сетка с точными IDs,
никакой выбор по заголовку. Контроллер, голос и сборщик не меняются.

## 2026-11-05 — источники вложений и контракт прямого чтения

База fd26eee: READ-маркер «что написано» направляет вопрос о вложении в
planner, где нет цели файлового инструмента; mode=policy заканчивается
clarification_required раньше обычного dialogue и передачи document_facts.
Planner получает только признак наличия серверного контекста вложений. При
пустом envelope и информационном запросе без intent/clarification/grant/deny
он возвращает управление обычному маршруту. Настоящие document_facts затем
проходят существующие inference_attachments/budget_messages/attachment_sources;
метаданные источников не добавляются отдельно от обработки документа.
Содержимое вложений по-прежнему не передаётся planner и не даёт полномочий.

Прямое «Прочитай этот документ» сохраняет file-content без LLM; вопросы и
пересказ используют извлечённый текст текущего выбранного файла. Разделяем
ожидания старой регрессии, не отменяя _verbatim_file_read. Проверки: сначала
затронутые наборы, затем полный pytest; без DevCrew, сборки и изменений голоса
или контроллера безопасности. Один итоговый commit по запросу владельца.

## 2026-11-05 — адресное чтение файла и экран возможностей

Причина отказа на базе 24e5d84: planner предлагает чтение только уже выбранного
file_id; pc_intent понимает ссылки на выбранный документ, но не явный путь или
имя файла в папке Desktop. Сохранённая restricted-политика до адаптера вообще
не доходит (пустой envelope, clarification_required, action_ms=0).
Добавляем общий детерминированный resolver запроса: только указанные пользователем
путь/имя → ID сохранённой области + точный относительный путь. Модель получает
только эти enum-значения. Адаптер повторно проверяет действующую политику read,
identity корня/файла и извлекает текст существующим read_selected. Поиск/открытие
не подменяют чтение; read не требует выдачи дополнительных прав search/open.
Контроллер PersonalMode и формат сохранённых разрешений не меняются.
Для UI устраняем наследование width:100% у radio, минимальную ширину grid/flex
детей и растягивание карточек. Проверки — только связанные Python/DOM, без
оркестратора/установщика, один итоговый commit по прямому запросу владельца.

Собранные Setup/Source.zip/provenance/SHA256 относятся строго к31fad862e248f729208f90f6e08551058ab42d10.
Этот последующий commit содержит только документы с фактическим результатом;
артефакты не подменяются и source identity не переименовывается в новый HEAD.
Сборка успешна, но Windows GUI/микрофон/GPU/install/offline gates остаются
NOT TESTED. Статус кандидата сохраняется; Stable/tag/publish/merge не выполняются.
Для source desktop использовать x64 Python3.11: закреплённый PySide6 6.8.3
поддерживает Python>=3.9,<3.14 (проверено installed package metadata).

## Реализация RC2

# RC2 — решения 2026-11-04

- Release a229fff — обязательный предок; независимая ветка release/1.0.0-rc2
  в разрешённом rc2 checkout. Alpha/RC1 и прежние артефакты не изменяются.
  finalize_release.ps1 не запускается. Builder проверяет чистоту, ancestry,
  payload/source identity, resume и хеши.
- Оставить QtWebEngine и системную Windows рамку. Qt6 масштабирует DIPs;
  второго множителя нет. Native recovery, tray, enum-only theme sync,
  фиксированный navigation origin и явный audio-only permission без JS OS bridge.
- Хранить normal bounds/maximized/theme отдельно в пользовательских данных.
  Повреждённые prefs не блокируют запуск; отключённый монитор → visible area.
- Два режима small/medium; balanced совместим, env base → small. Не удалять
  пользовательские файлы. Shared small verification и process lock предотвращают
  конфликт подготовки. Manifest2 не даёт прежнему stamp ложную готовность.
- Exit закрывает renderer и owned STT/TTS/setup subprocess, отменяет чат,
  закрывает admission. Уже выполненные действия сохраняют правдивый результат.
  Не завершать чужие процессы; прежний Ollama network timeout остаётся ограничением.
- QML1.1 — отдельный прототип/решение; цена переноса и критерии в
  RC2_DESKTOP_DECISION.md. Ни UI, ни сервер не переписываются в RC2.
- Mock/DOM/policy тесты не являются реальной микрофонной/GPU/Windows GUI приёмкой.
  Непроведённые сценарии явно NOT TESTED; Chromium sandbox не обходить.

## Исторические решения до RC2

# Архитектурные решения DevCrew

## 2026-11-03 ? final release: ??????????, scoped integration, ??????? RC gate

1. Alpha ?? ??????????????. ??????????? dirty worktree ????????? ?????????? ZIP
   ? ???????????/?????? ? binary patch; ????? ?? source ???????????? ? ???????
   checkout. Metadata Git ??? writable root ??????????: ?? ???????? ???????????.
   scripts/finalize_release.ps1 ??????? snapshot branches ? integration commit
   ?????? ??? ?????????? ????????? ??????????, ??? staging ????? ??????/push/????????.
2. Transcript ?? ????????????. ?????????? JSON floats ????????????? ? ???????????
   ?? worker/legacy/HTTP ???????? ?? ???????????; ??? ???? ?? ?????????? reload/fallback.
3. Gemma4 ???????? default ????? ?????????, ??????????? ????? ????????????.
   Temperature ???????? [0,2], ????????? controls ?????????? ? ??????????? ?? ??????;
   omitted HTTP controls ??????? ?? ?? ????????. Ministral ???? ?????, ??????????????
   ?????????? ???. ???? ???????? RSA smoke ?? ?????????? ???????? ?????? ??? ????????????.
4. ????? ??????? ??????? ?? ????????? ????; foreground denial ?? ?????? ????
   ???????? ????????. ????????????? ???????? Notepad ? ????? ? ??????????, ??? force kill.
5. ???? legacy preferences ??????? ????????? ??????????????? ????? ? ????????;
   ?????????? exclusive, ???????????? ???? ??????????. ?????? ???????? in-place,
   ????? Ollama ?? ???????????????. ??????? ??????? ?????? ???? idle ??? ???????????.
6. ?????? ?????? clean committed release branch, ???? 1.0.0-rc1. Payload ??????
   ?? committed ??????; provenance ???????? source hash, commit/tags, dependency
   versions ? hashes payload/assets. Resume ????????? ?????????/?????????/runtime,
   ????????? stale/extra files ? ????????????? offline bundles. ?????? artifacts
   ?? ????????????????. Stable-??? ?? ??????????? ??????????????? RC.
7. ?????????? Inno Setup/Git write ? ???????? ??????? ?????????. ?? ???????????
   ???? ? ?? ???????? mocked compiler tests ?? Setup.exe. Python3.14 unit tests,
   ????????? local Ollama smoke ? Win32 adapter observations ?? ???????? bundled
   Python3.11 runtime, ????????, GPU ? clean-Windows installation. ?????? ??????
   ??????? NOT TESTED ???????? ? MANUAL_QA.md; 60 ???????? ? DEFENSE_QA ?????????.


## 2026-11-03 — три этапа hardening

STT: история 66f6c10/3e0a228 не доказывает рабочий acoustic baseline; модели
base/small/medium и декодирование не меняем без одинакового реального корпуса.
Фактическую идентичность сообщает загрузивший worker, а не выбранный пункт UI.
Происхождение объявляется pinned только при совпадении всех контрольных сумм.
Измерения RSS/VRAM относятся к процессу после запроса, не к пику или одним весам.
Пустой transcript не скрывает факт успешной загрузки модели. Захват audio:true
сохранён; собираются разрешённые getSettings поля без device ID и audio retention.
WHISPER_MODEL задаёт только declared default; явный профиль приоритетнее.

Storage: bootstrap выбора root расположен стабильно под LOCALAPPDATA, до dotenv;
явное окружение имеет приоритет, resolved root наследуется workers.
Автоматический перенос пользовательских моделей при запуске удалён.
План копирования фиксирует источник/назначение/размер/SHA; consent отдельно;
исходник не удаляется, различающиеся файлы не перезаписываются. Эксклюзивная
hard-link публикация проверенной временной копии обеспечивает no-overwrite;
при неподдерживаемой ФС — безопасная ошибка и сохранение старого root.
Перед descent проверяются reparse points через lstat, включая dangling links.
Незавершённые HTTP/фоновые запросы и загрузки блокируют миграцию; после переноса
root новые изменения ждут перезапуска. Bootstrap/current/pending root исключены
из файловых полномочий даже при разрешении родительского каталога.
Старый private layout сохраняется ради совместимости; история обычного браузера
не объявляется автоматически перенесённой в EXE. Генерационные параметры
сохраняются сервером по моделям; stale save с другим model ID отклоняется.

Ollama: environment клиента не подтверждает environment сервера. Путь берётся
по listening process (адрес, порт, Windows case-insensitive environment);
managed процесс дополнительно связывается с PID и временем старта.
Общий сервер не останавливаем и не перенастраиваем автоматически. Для него есть
согласуемое copy-only копирование и инструкции явного OLLAMA_MODELS/Quit/restart.
Запуск нового серверного процесса задаёт OLLAMA_MODELS именно в Popen env,
использует фиксированный `ollama serve`, shell=False и loopback.
Lifecycle отделяет loaded, active, inactive и being-used. /ps и PID ownership
не доказывают отсутствие внешних запросов: автоматическая очистка пропускается.
Cleanup вызывается и на ошибках/отмене benchmark/healthcheck. Ручная выгрузка
согласуется, сохраняет активные leases и проверяет /ps + /tags после keep_alive:0.
Malformed/недоступный ответ означает unverified, а не успех; DELETE отсутствует.

Downloads: используется один JobStore с атомарной записью и совместимым старым
журналом. UI навигация не управляет жизнью реального pull. Байты агрегируются
по digest без удвоения событий; начальные cached слои не измеряют сеть.
Unknown total — indeterminate; скорость/ETA только после измеримого прироста.
Закрытый поток не доказывает остановку Ollama: cancelled_unverified сохраняется
и после рестарта не запускает работу заново. Installed требует завершённого
потока и проверки артефакта, включая offline weight SHA. Dismiss скрывает запись,
не удаляет модель. Retry повторно проверяет fingerprint/license/disk;
изменившийся артефакт требует нового согласия. Известную нехватку места обходить
нельзя; unknown-disk override доступен в экспертном UI. Активная LLM не меняется.

Проверенные первичные интерфейсы: https://docs.ollama.com/api/ps ,
https://docs.ollama.com/api/generate , https://docs.ollama.com/faq ;
faster-whisper и HF pinned metadata перечислены в HARDENING_STT_QA.md.
Git metadata недоступно для записи: этапы не выдаются за созданные коммиты.
Реальная Windows-приёмка и STT regression остаются обязательными отдельными gate.

## 2026-10-30 — Focused Redemption regression repair

Keep the existing interface and safety boundaries. Reproduce each regression on
Windows before edits. Snapshot probe on provisioned Python 3.14.5 shows only
`st_ctime_ns` differs between pathname stat and locked-handle fstat (creation vs
change timestamp); identity, size, mtime and SHA256 agree. Use one bounded,
handle-based fingerprint implementation at preparation and confirmation, retaining
exact identity, nanosecond timestamps, hash, owner, expiry and one-shot checks.

Raster integration must use live /api/info and conversation metadata together;
keep deterministic UI mocks separate. Capture actual upload acknowledgement and
exclude malformed images from context without relaxing parser validation. Verify
a 900x700 fixture against a real installed local vision model and compare sanitized
JPEG hashes in the actual outgoing Ollama request, separately from answer quality.

Diagnose resolution events, quality state and DPR with fixed CSS geometry. Sample
DPR in existing frames and lifecycle events; if quiet modes need a fallback, use
one low-frequency non-rendering check while visible, suspended on hide/offscreen.
Retain the pixel cap, quality adaptation and reduced-motion behavior. Query actual
/api/apps and reconcile provider records/duplicates with contemporaneous Windows
inventory, explicitly documenting provider skips and unavailable evidence.

Implementation verification: Windows fixture, full Python, DOM, syntax, assets
and real local multimodal checks pass. Independent Reviewer/Security required
restoring pre-open regular-file bounds and pathname/handle identity comparison
around the shared hash; that correction and regression test pass. Keep browser
acceptance explicitly blocked by worker/Chromium IPC permission failures; no
commit/merge until the requested browser gates can pass. No discovery permission
was broadened: diagnose the existing 10,000-file scan truncation rather than
change catalog scope in this focused regression repair.

## 2026-10-29 — Blacksite scene and trustworthy context

Keep the existing Canvas/audio/streaming modules and override the layout as one
fullscreen scene. Cache Canvas layers, maintain one animation chain, settling,
DPR<=1.5 and the 1.6M-pixel cap. Atmosphere uses static CSS gradients; no continuous
blur or animated full-window filters. Native dialogs contain drawer focus.
Map hides/inerts the conversation without recreating its draft, restores the
previous mode and returns focus to a visible opener. Narrow composers wrap.

Conversation history is presentation, not authority. Session entries retain their
server identity only in RAM; localStorage opt-in serializes bounded text/title/
draft only. Reloaded/expired entries are archives. Never replay history to rebuild
server memory. Serialize switches, destructive history changes and capture reset;
ignore late STT by epoch. Attachments migrate local draft groups to opaque server
IDs, retaining initial image-only drafts without cross-conversation leakage.

Use additive APIs and optional attachment_ids. Validate IDs before routing any
action. Store extracted text in expiring conversations; never accept client paths.
Pass document reference text only to dialogue inference with no tools. Do not feed
it to action planning or authorization. Acknowledgement exposes context_sources;
a ready upload alone is not model-context evidence. REAL HA request acceptance is
separate from observed physical state; result chips show target/status/observation.

Use pypdf>=6.21.3,<7 for bounded PDF extraction and stdlib ZIP/XML for DOCX. Complex
parsing occurs in a disposable fixed-module process with memory/time/concurrency
limits, archive/XML and page limits; fail closed if isolation is unavailable.
Parser arguments never include filenames, model output, paths or commands.
Initial dependency/model provisioning is explicit; inference stays local.

Visual/browser and native performance gates remain mandatory before acceptance.
Managed sandbox spawn EPERM and native browser access rejection cannot be replaced
with DOM or historical GPU measurements. Report real local document integration
separately from mock-based CI and untested microphone/GPU/physical HA behavior.

## 2026-10-29 — scoped Canvas reconciliation and evidence repair

Builder follows the existing architecture on `e4a71c8`: no visual redesign,
renderer rewrite or speculative GPU scheduling changes without live profiling.
Controlled fourteen-node submission probes demonstrate repeated observations
discarding 28 label surfaces and restarting settled physics. Reconcile bounded
observations by visible identity/content, preserve live nodes and dragged targets,
invalidate only changed labels and wake physics on topology changes. Explicit
reset still refreshes selection/activity even when observations are unchanged.

ResizeObserver alone does not observe DPR-only changes. Re-arm a resolution
media query, retain window resize handling and refresh on page restore. Keep
the existing quality/pixel caps, cached glows/layers and motion/audio behavior.
Source: https://developer.mozilla.org/en-US/docs/Web/API/Window/devicePixelRatio .

Keep default diagnostic snapshots compatible; allow polling without sample
sorting. Benchmark the first-delta-to-final streamed-output window separately
from startup/idle tails, retain actual duration, distinguish Canvas submissions
from rAF/presentation and retain timestamped whole-device NVIDIA utilization.
Trace summaries are clipped to explicit sample markers; raw dropped/presented
event counts require DevTools Frames inspection rather than an FPS assumption.

Verification and remaining gaps are recorded in
docs/CONSTELLATION_PERFORMANCE_REVALIDATION.md. Python/DOM/static checks pass,
including the deterministic expiry-test correction; Chromium/Playwright launch
is blocked by EPERM in this session. Do not reuse historical FPS as current
evidence, commit before browser verification or weaken system permissions.
Changes remain in this isolated checkout, with no backend/API or model changes.

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

## 2026-10-28 — Canvas performance architecture

Profile the existing renderer with Chromium DevTools Protocol Performance traces,
frame intervals and NVIDIA read-only utilization before changing it. Distinguish
CSS scale stress from real browser/DPR reflow; keep the drawer open for profiling.
Use rAF timestamps with bounded fixed-time physics substeps, adaptive settling,
reusable node coordinates, cached raster labels/glow sprites and decorative layers.
Invalidate caches only for geometry/font/quality changes. Retain subtle drift,
colors, audio reactivity, reduced-motion and bounded graph size. Never silently
cap normal animation at 30 FPS; low-resource mode remains explicit opt-in.
Cap backing-store DPR 1–1.5 (absolute pixel budget), adapt quality to measured
CPU draw cost with hysteresis; measure Chrome backend before claiming GPU gains.
Optional developer overlay must be off by default and contain no private data.
MDN primary API references: https://developer.mozilla.org/en-US/docs/Web/API/Canvas_API/Tutorial/Optimizing_canvas
and https://developer.mozilla.org/en-US/docs/Web/API/Window/requestAnimationFrame .

## 2026-10-30 — Checkpoint A: preserve capability and attachment boundaries

Use apps.focus(app_id) for app-context foreground requests; resolve HWND only inside
the authorized adapter, including a maximum five-second wait. Reuse existing native
markers, image grants and Win32 foreground observation; never simulate input or
change topmost state. Multiple windows return selectable opaque IDs. Failed/stale
native operations cannot become spoken success.

Resolve file pronouns only in the active file topic and keep the server-owned file
reference through read/describe/open. Reuse bounded FileAccess extraction and local
Ollama; do not infer authority from model prose. Metadata display also rechecks hash.

Transfer attachment ownership on final inference acknowledgement with original
request, server instance, owning conversation and all selected IDs. A message keeps
frozen display metadata and a bounded local Canvas-derived thumbnail; composer IDs
cannot include sent entries. Keep original uploads for replay; only text persists
across page reload. Failed inference/transport never consumes draft attachments.

Automated checks use synthetic files and fake window/LLM adapters. Browser execution
and human audio evidence cannot be inferred from passing Python/DOM suites.

## 2026-10-30 — Checkpoint B: measured voice, explicit channels and bounded evidence

Keep qwen3.5:9b for real checks and retain installed models. Do not promote an ASR
experiment without identical consented recordings and a demonstrated improvement on
reported phrases, ordinary speech and negations. Preserve audio:true and the baseline
decoder; compare finite offline-only hotword/language variants through the evaluator.
RMS/clipping and segment diagnostics support correction, not an invented confidence
percentage. Batch recordings remain batch recordings; no provisional execution.

Keep exact file metadata in structured_result and collapsible display details. Speak
one selected filename with pronunciation assistance and recompute speech after document
generation. Do not use raw adapter text as a dialogue system prompt. Keep only compact
registry and outcome facts. Estimate the combined input/response budget conservatively,
reserve images, drop older history, reretrieve relevant source passages and disclose
truncation. Reject budgets unable to retain every selected source.

Retain img-src 'none'. Decode bounded, browser-created PNG snapshots into Canvas for
sent-message previews. Preserve original request IDs and bubbles on manual transport
retry; server restarts and the replay deadline prevent unsafe automatic retries.
File revocation tombstones retain only opaque ID, owning conversation and fixed denial
reason, bounded to 256; they cannot restore authority or reveal another owner's reason.

Primary API checks: faster-whisper transcribe.py and tests (hotwords, optional language,
avg_logprob/no_speech_prob): https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py
Windows foreground restrictions: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow
Public factuality fixture: Blizzard's Three Sisters announcement, linked inside
tests/data/warcraft_grounding.json. Two real source-bound screenings passed; no
universal anti-hallucination claim. Models, audio and personal document text stay out of Git.

The environment denies Git metadata writes, browser workers and desktop observation.
Record these as outstanding gates. Do not replace required real evidence with automated
test counts or describe the blocked checkpoint commits as created.

## 2026-10-30 — bounded speech and sequential execution

Render filename speech with a finite reviewed romanized vocabulary and known
technical pronunciations. Separate title/type from exact display metadata. Render
1900–2099 title years as «за … год»; dotted versions and other numbers keep their
conservative pronunciation. IB→ИБ is letter transliteration, not a guessed expansion.
Opaque identifiers become a short type description. Do not infer document contents.

ASR reuses the existing supervised pipe transport with one profile-bound child and
one resident model. Changing a profile reaps the prior process first; changing only
language/decoder retains its model. Decode uploaded containers in memory with the
same duration/size/protocol restrictions; clear idle audio/transcript references.
Remember actual CPU fallback, expose requested and actual compute type, and preserve
killable deadlines and shutdown. No benchmark evidence justifies a default change.
The installed faster-whisper signature and its primary source support multilingual;
unsupported installations receive an explicit experiment error.

Preflight every sequence clause before executing any. Resolve provisional typed
references only inside validation; execute each real step through the existing exact
grant boundary. Stop after failure, clarification, cancellation or confirmation.
Launch→focus resolves the same authorized app, with at most six steps and the shared
deadline. Compound safe-close remains an explicit separate-window request; preflight
must not stamp or close native windows. Preserve display/speech separation in plans.

Read selected documents via files.read_selected_file and require nonempty extracted
text before generation. Reviewed content requests route to extraction; unsupported
content wording asks for clarification. Pass extracted passages as untrusted data;
keep truncation disclosure. Use a random source-only fact in real Ollama verification.

Recheck HWND marker/PID/thread after asynchronous restore, before foreground dispatch,
and after observation. Windows denial remains failure with a manual fallback. No
input spoofing, elevation, AttachThreadInput or foreground-lock changes were added.
Primary Windows references: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow
and https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-showwindowasync.
ASR reference: https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py.

Verification decision: do not promote models or decoding based on four synthetic
recognitions. They establish real CPU reuse/fallback only, and contained acronym
errors. Matrix eligibility requires every evaluated phrase's three recording
conditions, not a union of conditions across different phrases. Content clarification
responses skip the action composer so no LLM can turn a missing-source clarification
into a guessed summary. Report playback API completion separately from human hearing.
Compound replies containing document generation propagate speech_deferred, matching
the single-document path. Otherwise the browser's existing actionSpoken latch would
silence summary deltas. This is covered without changing Blacksite UI or styling.
# 2026-10-31 — preserve Silero xenia for mixed-language speech

The declared runtime configuration, not a guessed voice/model, is authoritative:
v5_6_ru.pt, speaker xenia, CPU/four threads, 24 kHz, accent/ё handling enabled.
The loaded package exposes a Cyrillic-only symbols table and no enabled phoneme
mode; pure Latin input raises ValueError. Mixed Latin text can be stripped silently.
Use a small speech-only dictionary and letter spelling for unknown Latin words.
Keep normalize_speech's Russian filename contract; clean_speech preserves Latin
before language_spans and voice-specific prepare_speech. Never alter display or
action data to improve speech. No per-language process restart or audio joining.

Evaluate v3_en/en_0 separately at 24 kHz; do not add it to automatic routing or the
public voice selector until listening establishes an improvement and the owner
explicitly opts into a different speaker. Upstream lists distinct English speakers,
not xenia: https://github.com/snakers4/silero-models#v3 and models.yml. Use local
torch.package only; setup downloads are separate from offline inference.

Open/focus is a separate change: await bounded image-based window discovery after
launch, bind focus to the original grant, and preserve all native identity checks.
Obsidian may hand off to another PID. A background Obsidian win32 instance may
receive one serialized executable activation; all other background apps retain
the prior no-relaunch policy. Never infer foreground from launch/SetForegroundWindow
return. Windows may deny activation even under documented conditions:
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow
Electron's single-instance behavior is documented at:
https://www.electronjs.org/docs/latest/api/app#apprequestsingleinstancelockadditionaldata
Do not work around denial with simulated input, elevation, lock changes or
AttachThreadInput. Keep the reported Obsidian bug open until physical verification.

## 2026-10-31 - evidence and sign-off decision

Keep the Silero pronunciation repair reviewable without asserting perceptual
success: successful WAV/HTTP generation does not rate intelligibility or voice
consistency. Preserve failed legacy attempts, model hashes and measured timings.
Keep v3_en as an explicit local evaluation asset, not an automatic route.
The English evaluation prepares PDF/C++/Warcraft III using English words/letters
before synthesis because those symbols/numerals are not evidence of correct
English pronunciation merely by surviving WAV generation.

Keep the Obsidian foreground bug open after native ambiguity. Do not filter out
candidate windows or choose by title to turn this test into an apparent success.
The recorded native launch did not demonstrate a usable interactive editor.
Check cancellation again after launch inspection and immediately before spawn;
revoked/cancelled requests must not trigger background-instance activation.
No app/window permission is broadened by the TTS changes. Browser runner/host
restrictions and the rejected Zen inspection remain explicit verification limits.
# 2026-10-31 — scoped pronunciation regression policy

Supersede the previous unknown-Latin letter-spelling default. Parse Roman
numerals only after the known Warcraft/Diablo title families, before ordinary
Latin adaptation; preserve standalone I and version boundaries. Whole reviewed
entities precede individual words and never match dictionary prefixes inside
unknown names. Explicit initialisms retain letter names; uppercase alone is
not an initialism classifier. Use a small deterministic English sound function
for unknown ordinary names, with no runtime downloads/dependencies/services.
Keep normalize_speech's legacy filename role and the original displayed text.
Streaming protects complete/partial entities, including whitespace variants;
guard Python/JavaScript vocabulary drift with a focused test.

Evaluate original CMUdict data through a local ARPAbet-to-Cyrillic renderer rather
than adopting a Python wrapper or adding a TTS service. Actual coverage was 15/18
words (including unseen names); 33 comparison WAVs were generated but not heard.
Text-level advantages on Phoenix do not outweigh absent novel names, loss of
Russian conventional Diablo pronunciation, and unrated stress. Retain this as
an optional evaluation script; do not silently promote lexicon/G2P to runtime.
CMUdict data has its own notice-retaining license; the separately licensed
Python wrapper was not installed. Do not claim a learned G2P was evaluated.

All four text stages belong to a single immutable preparation object. The exact
worker input is separate even when it equals pronunciation_text, so a future
adapter cannot hide a rewrite. LOCALMIND_TTS_DIAGNOSTICS=1 alone enables bounded
per-request JSON text logging in parent stderr, with unique request ID plus
generation/voice. Worker framed stdout, default privacy and xenia settings stay
unchanged. Evaluation audio retention remains explicit opt-in.

Automated tests and generated WAVs are implementation evidence, not perceptual
approval. Keep audible correctness and real streamed playback open after
Playwright EPERM, unavailable browser host and rejected Zen access. Never fill
reviewer/quality fields from synthesis success or claim microphone/GPU testing.

## 2026-10-31 — general numeral, numeric-context and ampersand repair

Supersede the Warcraft/Diablo numeral whitelist with syntactic title context:
an ordinary Latin word of at least two letters followed by a separate canonical
Roman numeral (through 3999), case-insensitively. Exclude known initialisms in
either position, canonical-Roman title cues, standalone I, embedded characters
and version-like suffixes. The existing single-letter V rule yields to a title
cue. Ambiguous Civil IV is a title by convention; unseen Zephyr XLII exercises
the same rule. This is not semantic title detection or another franchise list.

Preserve numeric spelling in cleaned_text. Consume technical/version/date tokens
before contextual years, explicit ordinal suffixes, decimals and ordinary
cardinals. Share the ordinal renderer with filename «за … год» speech. Bound
integer conversion before int(): twelve cardinal digits, four ordinal/year
digits, six fractional digits. Larger/leading-zero tokens use digit speech;
existing request/worker expansion limits remain. Preserve IPv4 v2.1 exactly.
Ampersand decisions use original adjacent scripts before name replacement:
Latin pairs get энд, other contexts и; single Latin letters beside & are spoken
as letters. No engine, model, inference settings or network dependency changes.

Protect syntactic context and pending tokens in streaming rather than maintaining
parallel franchise tables. Python alone determines pronunciation. Preserve exact
display/history/file/action data, worker reuse, queues and cancellation.

Evidence is separated: 76 direct CPU xenia WAVs, 33 real HTTP synthesis requests,
119 local Ollama deltas passed through the real chunker into ten clauses, and
exact four-stage diagnostic correlation. Display text equality and API retired/
successor/stale-cancel behavior passed. Queue-only chunking does not establish UI
playback. Current listening fields remain null. Browser host unavailable,
Playwright spawn EPERM and rejected Zen Computer Use inspection prevent the
required UI/listening gate. Keep the repair unapproved for audible quality.
See BILINGUAL_SILERO.md and evidence/silero-normalization-20261031.json.

## 2026-10-31 — final contextual normalization policy

Apply the new numeric contexts only to the Silero synthesis copy. Preserve
the shared filename/legacy renderer's digit/comma behavior. Recognize software
cues before Latin pronunciation and before dates/IPs: reviewed software names,
explicit version/версия cues with an optional product, and existing v-prefixed
or multi-dot identifiers. Speak version components as bounded cardinals joined
by «точка». An explicit software cue resolves date-shaped version ambiguity.
Valid IPv4 octets use digit speech joined by «точка»; dates retain their existing
separators. Uncued two-component decimals, negative decimals and fractions retain
their mathematical rendering. No global period or number replacement is added.

Recognize four-digit coordinated year lists sharing году/годах before ordinary
numbers. Inflect every year with the existing ordinal renderer, including 2000
and 2003 exceptions, preserving conjunctions, commas and the shared noun. Require
whitespace after a list comma so a decimal such as 1997,2002 stays a decimal.
Do not cross intervening words or clause punctuation. Single-year behavior stays.

Add whole-token, case-insensitive Apple → Эппл and Node.js → Нод джей эс mappings.
The browser only preserves complete/partial software expressions and year lists
across deltas; Python remains the pronunciation authority. Display/history,
engine/speaker/settings, queues, cancellation and permissions are unchanged.
Exact independent text literals and captured worker inputs establish the text
contract; generated audio cannot establish audible quality. Human listening
and real browser playback remain separate gates, recorded in STATUS.md.

## 2026-11-01 - model management contract before implementation

Extend the existing BLACKSITE model tab; retain loopback, authentication, CSP and action gateway. Selected model is atomically persisted in results/private, separate from loaded models and response identity. Request replay identity uses the original wire payload; immutable generation settings remain in the first accepted closure. Never unload another workload. Optional NVML/psutil telemetry reports unknown per missing field. Placement uses only Ollama ps sizes, never memory estimates.

API facts checked against official Ollama chat/ps/API and Hugging Face Hub API/Ollama docs on 2026-11-01: response durations are nanoseconds, final response has model identity; GGUF references accept explicit quantization. Sources: https://docs.ollama.com/api/chat , https://docs.ollama.com/api/ps , https://github.com/ollama/ollama/blob/main/docs/api.md , https://huggingface.co/docs/hub/ollama , https://huggingface.co/docs/hub/api , https://docs.nvidia.com/deploy/nvml-api/index.html . Installed runtime observed: Ollama 0.40.13.

## 2026-11-01 - catalog milestone decisions

Use bounded unauthenticated Hub REST metadata requests, never HTML, repository
scripts or downloaded code. Only conservative text GGUF architecture/version
pairs and explicit quantizations can form hf.co references. Unknown architectures,
shards, ambiguous quantizations, mmproj, private/gated and missing licenses block.
No external metadata URL is followed. Source benchmarks are unavailable for the
listed quantized variants; never copy full-precision claims as their accuracy.
The curated registry is dated and sourced; all pre-install compatibility is an
estimate. Static config KV metadata sources:
https://huggingface.co/Qwen/Qwen3-4B/blob/main/config.json and
https://huggingface.co/Qwen/Qwen3-8B/blob/main/config.json .

Pull starts only after explicit license/disk acknowledgement and server-side
revalidation. One bounded task, no automatic switch/resume/retry. Cancellation
disconnects the stream and is honestly labelled daemon-stop-unverified. Disk free
is unknown until the operator confirms the actual daemon store via environment;
never substitute the repository volume. Runtime errors remain sanitized.

## 2026-11-01 - benchmark milestone and final review

Use a versioned fixed 12-case deterministic screening protocol with an explicit
JSON answer envelope for non-tool cases, a separate structured schema, exact
text/JSON and AST comparisons. No eval/exec/subprocess or action gateway is used.
Same system/user/assistant-prefill, seed/context/budget/think settings for both
models; no active selection change or unloading. Persist hash, digest before/after,
quant, actual response identity, raw synthetic visible content, checks and timings.
Native tools unsupported means N/A. Errors/truncated responses mean incomplete;
manual ratings are separate and atomically persisted. A rejected busy chat never
reserves its ID; accepted replays retain their initial immutable settings.

Real Windows tests found sticky CPU placement in qwen3:4b even with num_gpu -1
after explicit num_gpu 0 fallback. Do not infer GPU placement from the setting.
Record actual post-run ps placement and warn against speed comparisons across
different/unknown modes. No overall quality score or popularity benchmark.
The preliminary unconstrained protocol is superseded by the versioned JSON
envelope protocol and is not reused as current evidence.

Final skeptical/security review covered auth/Origin/Host/peer inheritance, source
allowlists, malformed metadata, raw exception redaction, request replay, selection
atomicity, cancellation terminal races, checkpoint failures, bounded jobs/streams,
output non-execution and metadata XSS. Fixed an old model-select change listener
that could still overwrite the actual-response badge; the new regression test
dispatches change explicitly. No unresolved critical/high security issue found
in the changed scope; real browser and download gates remain unverified.

Bind download acknowledgement to a fingerprint of source/revision/license/quant/
size/architecture/context metadata; re-fetch and reject stale acknowledgement
before starting a pull. A changed repository must not silently substitute another
license or artifact. Tests verify stale rejection, explicit retry and thread-start
rollback. CPU/RAM and NVIDIA bindings are included in new installations, remain
optional at runtime, and degrade to unavailable when the vendor driver is absent.

## 2026-11-03 — Productization: решения пяти этапов

1. APP_ROOT только для ресурсов/кода, LOCALAPPDATA/LocalMind — для моделей и
   состояния; LOCALMIND_DATA_DIR только операторский/test override. Миграция
   повторяемая и не удаляет источник, не переносит разрешения или HA-токен.
   Private CPython 3.11.9 поставляется отдельно от GUI EXE, workers запускаются
   python.exe -m, без попытки использовать frozen launcher как интерпретатор.
   На реальном embedded runtime найдено различие ../.. и ..\..\ в ._pth;
   исправлено по фактическому sys.path. Драйверы/Windows protection не меняются.
2. Один атомарный ограниченный JobStore для LLM/ASR/TTS/offline. После рестарта
   incomplete становится interrupted, автоматических повторов нет. Отмена Ollama
   означает закрытие потока, не доказанную остановку daemon. Подтверждение HF
   связано с metadata/artifact fingerprint, после pull сверяется SHA-256 weights.
   Активный tag не перезаписывается загрузкой. /api/blobs перед offline upload
   проверяется HEAD: реальный опыт выявил reset соединения при отправке уже
   существующего blob без этого шага; свежий upload и повтор теперь проверены.
3. Основной UX исключает декоративную сцену. Старые scene browser tests доступны
   только явным legacy opt-in, новые user-mode tests охватывают 100/125/140/150%.
   Они не выданы за выполненные: браузерная среда блокирует запуск worker.
4. LLM выбирает инструмент/аргументы внутри server-owned envelope, а не только
   подтверждает один заранее выбранный intent. Envelope ограничивает семейство
   действий и названные/выбранные IDs; содержимое документов/страниц не планирует
   действия и не создаёт права. Registry и OS adapters проверяют снова. Native
   tools берутся из локально проверенных capabilities; schema fallback остаётся
   на той же LLM. Результаты адаптера первичны, оценка LLM их не переписывает.
   При недоступном planner сохранён проверенный точный compatibility path.
   Дополнительный privileged companion/UAC bypass не добавлен; foreground отказ
   воспроизведён, GUI-проверка в обычной интерактивной сессии ещё обязательна.
5. HA принимает только локальный numeric IP без credentials/path/redirect/proxy.
   Разрешаются отдельно обнаруженные light/switch. Токен шифруется DPAPI текущего
   пользователя, не возвращается API и не отражается в validation error.
   При смене origin/token grants очищаются. POST service не равен наблюдению:
   после него перечитывается состояние; ошибка чтения сохраняет unverified.
   Явный переход в DEMO удаляет токен и сохраняет только режим.

Проверенные внешние интерфейсы: CPython embedded package
https://docs.python.org/3.11/using/windows.html#the-embeddable-package ; HF reference
https://huggingface.co/docs/hub/ollama ; Ollama structured outputs/API create
https://github.com/ollama/ollama/blob/main/docs/api.md и https://docs.ollama.com/api/create ;
HA REST https://developers.home-assistant.io/docs/api/rest/ ; Windows foreground
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow .
Это источники интерфейсов, а не доказательства аппаратной/продуктовой приёмки.

- Файлы собственного приложения и DATA_ROOT исключены из обычных файловых
  разрешений: разрешение родительской папки не даёт инструментам права менять
  собственную политику, HA-подключение, runtime или манифест ресурсов. Проверено
  targeted regression tests и полным Python-набором.

## 2026-11-03 — STT regression boundary decisions

- Normalize copies of STT JSON payloads with one stdlib-only recursive helper.
  Preserve text and finite values; replace non-finite floats with null and expose
  only their exact paths in optional response diagnostics. Repeated normalization
  preserves paths. Do not log audio/transcripts or native exception details.
- Invalidate an entire quality aggregate if any segment is contaminated; do not
  publish a plausible partial metric. Aggregation overflow also recommends review.
  Diagnostics are handled outside model failure/reload and GPU fallback decisions.
- Use strict STT serialization at framed/file writers and defend consumer/HTTP
  boundaries. Keep shared TTS framing and error policy unchanged; add no global
  exception handler. Map media decode errors at the decoding boundary only.
- Render bounded validation locations/messages as text, excluding input/ctx.
  Poll job status only for a visible open interface with active work; serialize
  refreshes and invalidate pending timer continuations on close/hide/reopen.
- Automated checks are distinct from hardware acceptance. No human microphone
  recording or consented fixture is available; Windows UI access/Chromium launch
  were blocked. The actual incident field and CPU/GPU behavior remain unverified.
  `docs/STT_HTTP_REGRESSION.md` records evidence and the remaining live gate.
# RC3 — 2026-11-04

- Работать от `3ead34b` в существующем DevCrew-worktree; занятую ветку
  `release/1.0.0-rc3` не переключать и исходный репозиторий не изменять.
- История: stdlib SQLite в пользовательском HISTORY, версионированная схема,
  короткие транзакции synchronous FULL и DELETE journal. Полный журнал не
  ограничивается TTL/окном LLM. Закрытые соединения упрощают согласованный перенос.
- Старый browser-only архив импортируется атомарно и идемпотентно; даты,
  которых в нём нет, остаются неизвестными. Полномочия, tokens и действия не
  восстанавливаются из текста. Ошибка сохранения не становится успешным final.

## RC3 — контрольная точка ввода до stream (2026-11-04)

Черновик фиксируется до очистки поля и допуска генерации/действий. При аварии
до final он остаётся доступным без завершённого ответа. Пара сообщений и
поглощение совпадающего черновика — одна SQLite-транзакция. Ранний status/delta
не является подтверждением commit. Повтор транспорта сохраняет ID только в
исходном server_instance; восстановление истории выполняет чтение. Проверка
перезапуска теперь запускает отдельный настоящий сервер с фикстурой LLM.

## RC3 — обнаружение ресурса и UI-контракт (2026-11-04)

Найденная Medium предпочитается отсутствующей Small, но состояние unverified
сохраняет явную необходимость native-пробы. Проверенный Silero и перечень
установленных Ollama-моделей не запускают загрузку при чтении мастера.
Общее small-файл хранилище cpu-fast/balanced и общий Silero защищены
файловыми OS-lock, проверенными также отдельным процессом. Завершение мастера
и тура хранится независимо от текущего наличия моделей.

## RC3 — итоговый gate и передача (2026-11-04)

Сохраняем рабочее дерево, не обходим отказ доступа к внешней Git metadata и
не ослабляем release preflight ради EXE. Нужны чистый интегрированный commit
и Inno Setup. Диагностический source-copy/снимок не выдаётся за Source.zip
релиза. Самостоятельное code/security review и зелёные Python/DOM gates
не заменяют независимый Reviewer/Security этап оркестратора, Playwright,
Windows GUI, микрофон и GPU. Эти пункты остаются открытыми.

Browser fixtures используют согласованные server_instance и conversation API;
исполнение Playwright по-прежнему заблокировано spawn EPERM. Python HTTP-test
проверяет реальные процессы/SQLite/загруженные документы, но заменяет только LLM
фикстурой и не выполняет реальные OS-действия. Данные и модели владельца
не меняются. Финальный gate остаётся закрыт до сборки и реальной приёмки.

## RC3 — единый контроллер доступа (2026-11-04)

PersonalMode сохраняет schema 2, SID, restricted/full_user, корни с identity,
операции, app grants и явные deny. Старый expanded не становится full_user.
Политика не хранится в product-state или истории. Preview русских правил
детерминирован, хранится на сервере с ревизией/TTL и применяется явно целиком.
Приоритет обязательных исключений и deny не изменяется подтверждением/LLM.

Полный доступ ограничен текущим профилем/Known Folders фиксированных дисков;
ProfileList закрывает чужие профили на нестандартных путях. Произвольное
подтверждение владения всем диском не предлагается. Поиск и чтение разделены:
без read не хешируются байты документа. Все изменения сохраняют точное
одноразовое подтверждение, источник и назначение проверяются повторно.

App allow привязан к image fingerprint, deny включает aliases/identity.
Открытие документа/закладки не использует ShellExecute command-template:
проверяется приложение и передаётся только точный документ/фиксированный URL.
Калькулятор считается безопасным для закрытия только по OS-resolved identity.
Порядок блокировок policy → catalog/window; файлы удерживают policy во время I/O.
Сбой журнала после успешной записи прав показывается отдельным предупреждением,
а не ложным сообщением об откате. Чистые проверки не заменяют реальную Windows
GUI/микрофон/GPU/CPU/offline приёмку; окружение sandbox не ослабляется.

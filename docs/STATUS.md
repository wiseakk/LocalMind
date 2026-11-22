# RC2 — сборка и окончательная проверка 2026-11-04

## 2026-11-22 — rc3-4, повторный запуск Desktop

На установленном rc3-3 воспроизведён errno 98 без LISTEN при TIME-WAIT.
Финальный архив rc3-4 после извлечения прошёл 20 последовательных циклов
Wayland/HTTP/закрытие. Отдельно проверены занятый порт, аварийный запуск
backend и сбой Qt. Pytest: 1745 passed, 31 skipped, 35 subtests passed.
Системное обновление оставлено для ручной приёмки. Модели, Ollama, голосовой
runtime и пользовательские настройки в исправлении не менялись.
[Доказательства и команда обновления](LINUX_RC3_4_RELAUNCH.md).

## 2026-11-22 — rc3-3, загрузки Linux

На установленном rc3-2 воспроизведены три HTTP 409 до создания задач.
В rc3-3 системный Python получает упакованный runtime, мастер даёт явно
подтвердить загрузку при неизвестном месте Ollama, а активная LLM проверяется
по tags. Живой Chromium из staged payload скачал Qwen 0.5B и Silero,
дозагрузил файл Whisper Small, проверил Medium на CUDA и сохранил выбор после
рестарта. Отдельно прошли ASR CPU fallback, отказ сети и отмена.
Python 1740 passed, 31 skipped, 35 subtests passed. Chromium из архива 37 passed.
Системное обновление rc3-3 ожидает пароль sudo. Windows GPU и микрофон в этой
приёмке не проверялись. [Подробности](LINUX_RC3_3_DOWNLOADS.md).

## 2026-11-22 — финальная приёмка Linux Alpha

Архив `1.0.0rc3-2` из `3e803fa` прошёл проверки извлечённого payload под
Wayland, генерации на GPU, доступа к файлам и сохранности XDG при смене
payload. Python 1735 passed, 31 skipped, 35 subtests passed. Chromium 37 passed.
Системный Ollama 0.40.16 доступен, его каталог пуст. Локальная Gemma из QA
хранилища переиспользована офлайн. При конкуренции за VRAM Whisper Medium
перешёл на CPU, а Gemma продолжила отвечать. Вердикт LINUX ALPHA BLOCKED до
системной установки и проверки физического микрофона.
[Отчёт, команды и чек-лист](LINUX_ALPHA_ACCEPTANCE.md).

## 2026-11-22 — Linux, ядро приложения и офлайн-контур

Реальная Gemma 4 12B Q4_K_M, native tools и LocalMind API проверены на RTX 4070.
Проверены реальный запуск Kitty, перечисление и фокус окон Hyprland,
чтение и пересказ разрешённого файла, история после перезапуска. Silero xenia,
Whisper Small CPU, Medium CUDA и CPU fallback прошли на синтетическом аудио.
В отдельном сетевом namespace с одним loopback прошёл полный голосовой контур.
Python: 1734 passed, 31 skipped, 35 subtests passed. Chromium: 37 passed.
Собран локальный Arch payload. Установка pacman, физический микрофон,
Windows-аудио и Windows GPU остаются отдельной приёмкой.
[Данные прогонов и ограничения](LINUX_PORT_STATUS.md).

## 2026-11-21 — Linux, аудит и первый запуск

Ветка `port/linux-arch`, исходный коммит `0615b9e`. На CachyOS в отдельном
venv с Python 3.14.10 установлены FastAPI 0.165.0, Uvicorn 0.54.0,
PySide6 6.12.0 и Qt WebEngine 6.12.0.140. Процесс `start.py` ответил HTTP 200
на `/`, `/api/info` и `/api/diagnostics`. В нативном Wayland под Hyprland
`localmind.desktop` загрузил локальный документ в WebEngine и завершился
штатно. Использован временный профиль. Portal сообщил об отсутствующем
регистрационном desktop entry, Chromium выбрал Vulkan вместо GBM.

Linux-профиль учитывает `XDG_DATA_HOME`. Исправлен отказ для Windows-путей
с обратным слешем в POSIX-ветке подготовки файловых изменений. Три теста
запуска Windows используют явные фикстуры инспекции и образа. Реальный
запуск Windows в этом прогоне отсутствовал.

Полный `python -m pytest -q` с доступом к локальным сокетам: 1719 passed,
37 skipped, 35 subtests passed за 24.03 с. Одно предупреждение о совместимости
Starlette TestClient с `httpx`. Действия Windows и сервисы в тестах используют
фикстуры. Реальный HTTP/Wayland smoke выполнен отдельно.

Ollama, GPU inference, микрофон, слышимый TTS, автоматизация приложений и
окон, чистая установка и offline voice demo остаются открытыми. Системные
пакеты и модели в этом этапе не устанавливались. Карта адаптеров, зависимости
и запуск: [LINUX_PORT.md](LINUX_PORT.md).

## 2026-11-08 — RC3 Bug Bash

Проверены 96 русских фраз, полный Python, DOM, JavaScript и 36 Chromium-тестов.
В реальном Qt прошли 38 проверок, включая подтверждение и отмену удаления
в папке QA, 20 ответов Gemma, восстановление истории и масштабирование
экрана доступа. Встроенный Ollama запущен с пустым каталогом и восстановлен
после завершения собственного процесса. Whisper Small и Silero проверены
на CPU с синтетическими русскими фразами и ограничением сети QA-процессов.
Вердикт RELEASE BLOCKED до проверки чистой Windows, микрофона и голосового
контура GPU. Подробности в [отчёте аудита](RC3_BUG_BASH_REPORT.md).

## 2026-11-08 — просмотр содержимого папки RC3

Установленный RC3 с provenance `a28e6c3` отправлял вопрос о папке DEMO в
Ollama без файловых действий. В отдельном экземпляре с исправлением и
настоящим окном Windows (PySide6/Qt WebEngine) список совпал с Windows:
`demo_analyze.txt`, `demo_cancel.txt`, `demo_delete.txt`, `demo_read.txt`.
Диагностика показала `files.list_directory`, `observed` и `llm_ms=0`.
`demo_read.txt` вернул фактический текст, `demo_analyze.txt` пересказала
локальная Gemma 4 12B после `files.read_file`. Использован отдельный профиль
с правами поиска и чтения только для DEMO.

Python: 1622 passed, 2 skipped, 35 subtests passed. DOM и проверка JavaScript
прошли. Chromium `product.spec.mjs`: 7 passed. Дополнительный
`access.spec.mjs` падает на видимости `#accessClose` при масштабировании
также на `a28e6c3`. Setup.exe не собирался. Микрофон и GPU отдельно не проверялись.
Команды и ожидаемые результаты приведены в [ручной приёмке](../MANUAL_QA.md#просмотр-содержимого-папки).

## 2026-11-08 — живое зеркало Whisper Small и Medium

Оба адреса вернули HTTPS 200 и 206 с указанными размерами и стабильными ETag.
QA использовала Windows, прямое HTTPS-подключение без прокси и изолированный
профиль. Отказ Hugging Face для проверки UI/API симулирован. Запуск по умолчанию
вызвал Hugging Face, а обращение к зеркалу произошло после передачи
отпечатка подтверждения.

Small (486368781 байт) скачан с внешнего зеркала. После отмены сохранилось 9977540 байт.
Повтор отправил Range bytes=9977540- и If-Range. Получен 206 с тем же ETag
и Content-Range bytes 9977540-486368780/486368781. SHA‑256 совпал.
Пройдена проба faster-whisper. Повторная подготовка установленной модели
не вызвала GET. После перезапуска ASR с блокировкой внешних DNS и сокетов
в QA-процессах вернул «Я готовлю пельмени.» и «Поставь таймер на 5 минут.»
для синтетических русских фраз. Физический микрофон не использовался.

Medium (1530728145 байт) скачан один раз. Полный SHA‑256 и четыре файла
манифеста после безопасной распаковки совпали. Повторная проверка использовала
тот же архив, короткий Range и сохранённый ETag. Проба модели Medium
не входила в этот прогон.

Штатный копировщик релиза включил config/asr_mirrors.json байт в байт.
Правило Inno Setup копирует config рекурсивно. Тест сборщика проверяет файл
и его SHA‑256 в provenance. API для настоящего теста работал из QA payload
в структуре установленного приложения. Новый Setup.exe не собирался.
Отчёты сохранены в .test-artifacts/whisper-vps-acceptance.

Python: 1607 passed, 2 skipped, 35 subtests. DOM и check:ui прошли.
Chromium: 6 passed. Инструкция и ручной чек-лист находятся в ASR_SOURCES.md.

## 2026-11-07 — прямые HTTPS-зеркала Whisper

Добавлен тип direct_https для Small и Medium. Конфигурация содержит пустые URL,
SHA‑256 и размер. При отказе Hugging Face настроенное зеркало требует отдельного
подтверждения. ZIP скачивается на диск, а повтор использует сохранённый остаток
с сильным ETag и проверяет 206, Content-Range и полный SHA‑256.

Python: 1599 passed, 2 skipped, 35 subtests. DOM и check:ui прошли.
Chromium: 6 passed. Проверены отмена, тайм-аут, несовпадение ETag и диапазона,
недоверенный источник, повреждённый ZIP и неверный SHA‑256.

На отдельном локальном TLS-сервере скачан реальный ZIP Whisper Small размером
486212794 байта. После обрыва сохранены 16777216 байт, повтор запросил
Range bytes=16777216- и успешно завершил установку после пробы faster-whisper.
Повторная задача для установленной модели не обращалась к серверу.
Клиент отклонил сертификат без доверенного корня. Доверенный тестовый корень
добавлялся только в SSL-контекст проверки. Пользовательский VPS и реальный
Medium остаются в ручной приёмке. Setup.exe не пересобирался.
Инструкция для NGINX и чек-лист находятся в ASR_SOURCES.md.
Проверка границ источника: `DEV_CREW_VERDICT: PASS`.

## 2026-11-07 — зеркала и офлайн-импорт Whisper

Мастер и настройки голоса показывают профиль, источник, размер, прогресс,
скорость и ошибки. При сетевой ошибке Hugging Face кнопка Яндекс Диска
появляется для валидной конфигурации и требует отдельного нажатия.
Локальный ZIP и папка передаются потоком в отдельный временный файл.
Проверенные файлы публикуются после CPU-пробы faster-whisper.

Полный Python: 1579 passed, 2 skipped, 35 subtests. DOM и check:ui прошли.
Chromium: 5 passed. Проверены HTTP-контракт Яндекс Диска на тестовом транспорте,
отмена, повтор, неверный SHA‑256, повреждённый ZIP, traversal, ссылка внутри
архива, избыточный размер и сохранение старой модели при сбое пробы.
Нативный Qt WebEngine показал 25% для тестовой задачи Яндекс Диска и «Готово»
после реального потокового импорта ZIP Whisper Small через loopback.

Официальный Whisper Small загружен с Hugging Face. После отдельного офлайн-импорта
и нового процесса настоящий ASR на CPU распознал синтетические фразы
«Я готовлю пельмени» и «Поставь таймер на 5 минут». Физический микрофон, нативный
выбор папки, веса Medium и публичное зеркало без VPN остаются в ручной проверке.
Ссылки и хеши зеркал ещё нужно заполнить. Подготовка ZIP, настройка зеркала и
ручной чек-лист с фразами описаны в ASR_SOURCES.md. Проверка границ импорта:
`DEV_CREW_VERDICT: PASS`.

## 2026-11-07 — первый запуск мастера

Удалён автоматический переход к шагу «Нейросеть» при обнаружении хранилища
Ollama. Новый профиль начинает с приветствия. Незавершённый мастер сохраняет
шаг, профиль и отметки ASR/TTS в product-state. «Настроить позже» и Escape
сохраняют черновик. Завершённый мастер открывается вручную с первого шага.
На четвёртом шаге показаны встроенный Ollama и найденные модели. Этап завершения
показывает фактический статус голосовых ресурсов.

Python: 1564 passed, 2 skipped, 35 subtests. DOM и проверка JavaScript прошли.
Chromium: 4 теста, включая проход вперёд и назад, сохранение выбора,
возобновление после перезагрузки, закрытие по Escape и ручное открытие.
В нативном Qt с отдельным новым профилем дерево доступности показало
«Добро пожаловать» и шесть шагов. Реальный API в этом запуске сообщил
storage_choice_required, пять моделей (включая gemma4:12b) и model_missing
для ASR/TTS. Полный нативный маршрут ограничен ошибками
`coordinate input geometry is unavailable` и `FrameArrived timed out`.

Запуск исходников: `python start.py`. Для офлайн-демо после подготовки ресурсов,
устранения проблем запуска и вопросов защиты см. ENGINE_SETUP.md и DEFENSE_QA.md.

## 2026-11-07 — обнаружение ранее скачанных моделей, реальные проверки

Финальный артефакт: dist/rc3-engine-models-final/LocalMind-1.0.0-rc3-Setup.exe,
2000728051 байт, SHA256 223d4b4e77d6c98ca11827cca04d19eb97a518b69a7f1427809ed258dfbe180b.
Исходники сборки: ff80a91b96d0832a31ea6163d219c74ae6c814b4 в изолированной
Git-копии; Source.zip и SHA256.txt лежат рядом. Release preflight не ослаблялся.
Коммит в основном checkout заблокирован sandbox: git add --all не смог создать
.git/index.lock (Permission denied). Изменения оставлены; CHANGED_FILES.txt рядом
с установщиком содержит точные пути. После сборки обновлены только итоговые
документы приёмки; исполняемые исходники совпадают со снимком сборки.
Финальный QA Setup использует тот же payload, отдельный AppId, без uninstall
registry и ярлыков. Установка успешна, сверены SHA256 19855 файлов, существующая
запись uninstall владельца не изменилась. Нормальные ярлыки финального Setup
и полный native GUI не проверялись этим QA-вариантом.

Из установленного payload запущен настоящий LocalMind API на 8881, свой bundled
Ollama на 11544. Установленные HTML/setup.js загружены в JSDOM: симулируется только
DOM, все HTTP-запросы и inference настоящие. Клики «Использовать эти модели» и
«Проверить и использовать gemma4:12b» прошли; ни одного POST загрузки моделей.
/api/chat вернул engine=ollama, actual_model=gemma4:12b и «Два плюс два равно
четыре.» (actions=[]). После настоящего перезапуска API/owned runtime:
active=gemma4:12b, active_installed=true, active_verified=true; повторный выбор
каталога не потребовался. Снимок хранилища до/после совпал. Отчёты:
.test-artifacts/installed-models-report.json и models-qa-install-result.json.
Все собственные QA API/engine процессы корректно завершены. Это реальный inference,
но не ручной native GUI walkthrough и не проверка чистой Windows VM.

Исправлена причина пустых tags: собственный движок всегда получал пустой каталог
LocalMind вместо существующего хранилища. Теперь read-only discovery проверяет
процессный/Windows OLLAMA_MODELS, стандартный .ollama/models и каталоги LocalMind.
В прежнем мастере предлагается явное использование обнаруженных весов; HTTP
принимает ID/fingerprint, каталог проверяется снова и сохраняется с identity.
Только дочерний процесс получает выбранный OLLAMA_MODELS и NOPRUNE=1. Shared
совместимый сервер используется без второго процесса/смены его каталога. Сохранённая
отсутствующая модель отделена от доступной; чистая установка сохраняет мастер
загрузки. Голос, контроллер, файловые инструменты и дизайн не менялись.

Затронутые Python-тесты: 111 passed. Полный pytest после увеличения bounded
cold-load пробы до 180 секунд и исправления polling: 1558 passed, 2 skipped,
35 subtests, 36,48 с;
пропуски — PySide6 в тестовом интерпретаторе и 8.3 alias. Результат в
.test-artifacts/model-discovery-full-pytest.txt. DOM suite и check:ui PASS,
включая явный выбор existing-store без pull, отсутствие формальной ready до
проверки генерации и недоступную сохранённую модель. Самостоятельный review
read-only discovery/локальных путей/opaque IDs/child env/shared ownership: PASS.

Настоящий bundled Ollama 0.40.14 на изолированном порту 11543 обнаружил существующие
gemma4:12b, qwen3:4b, qwen3.5:9b и другие модели. Через ModelManager.select выполнен
реальный /show и /chat: Gemma 12B подтвердила генерацию; ответ на 2+2 — «Четыре.».
Первый успешный probe занял 59,48 с (load 30,82 с), предшествующая попытка превысила
старый лимит 60 с; лимит увеличен до 180 с с пояснением в мастере. Reuse вторым
клиентом не создаёт второй процесс. После остановки только собственного job и
создания нового runtime выбор каталога/модели/digest восстановлен; новый реальный
ответ — «Привет». Модели не скачивались и не копировались. Снимок 39 файлов
(размеры/mtime blobs и SHA256 manifests) до/после совпал. Глобальные переменные
и чужие процессы не менялись. Отчёт: .test-artifacts/existing-models-report.json;
журнал: .test-artifacts/existing-models-ollama.log. Это не mock inference.

Предыдущая Engine-сборка подготовлена: dist/rc3-engine/LocalMind-1.0.0-rc3-Setup.exe,
SHA256 39697d3d1460a0c4297069cf082c7b2e884f41a846ab3730cd5783b21cfac144,
source commit 8305bc2af71097aedb8acf367486f8d6e36dff08 в изолированной Git-копии.
Отдельный QA Setup с отдельным AppId установлен в workspace, 19854 файла сверены
с manifest; запись uninstall владельца не менялась. Native GUI показал welcome
и реальные сведения RTX4070/RAM, но полный проход по экранным кнопкам не завершён.
Обновлённая сборка discovery готовится отдельно в dist/rc3-engine-models-final.
При проверке установленного payload добавлено автоматическое повторное чтение
статуса, если supervisor уже ready, но tags ещё unavailable: мастер не должен
останавливаться на устаревшем снимке API. DOM-регрессия воспроизводит это пересечение.
Чистой Windows VM нет (согласовано владельцем), этот сценарий не проверен;
физический CPU-only ПК, микрофон и полный native GUI walkthrough не заявляются
проверенными. DevCrew не запускался. Запуск исходников: python start.py;
offline demo/troubleshooting: docs/ENGINE_SETUP.md; вопросы: docs/DEFENSE_QA.md.

## 2026-11-07 — встроенный движок, реализация и реальные пробы

База 762b082. Добавлен hash-pinned standalone Ollama v0.40.14 с NVIDIA/CPU
библиотеками/лицензиями, фоновый loopback supervisor с Windows Job Object и
ограниченным восстановлением, retry в мастере. PATH/OllamaSetup.exe больше
не нужны. Модели в базовый installer не включаются. Существующие каталог,
загрузки и мастер расширены выбором/согласием/размером/RAM/лицензией и реальной
проверкой генерации перед ready. Отмена закрывает также проверочный HTTP-поток.
Активный выбор/digest проверки сохраняются и сверяются с текущими tags.

Полный pytest Windows Python 3.14.5: 1546 passed, 2 skipped,
35 subtests passed, 43.04 s. Пропуски: PySide6 отсутствует в этом
тестовом интерпретаторе; том не дал 8.3 alias. npm run test:dom PASS,
включая новый wizard-test; контроллер/файловые регрессии сохранены.
Самостоятельная проверка границ процесса/loopback/архива: PASS.
Логи: .test-artifacts/engine-full-pytest.txt, .test-artifacts/engine-dom.txt.

Реальная проверка на комплектном Python 3.11.9 (не mock): runtime запускается
из .test-artifacts/engine-payload на отдельном порту 11540 с отдельными данными.
Проверены пустой tags, reuse без второго процесса, явный pull Qwen2.5 0.5B
Q4_K_M (~398 МБ) с настоящим прогрессом и успешной проверкой, реальный ответ
«Ответ: четыре», сохранение digest/выбора после загрузки настроек, восстановление
после завершения собственного PID. /api/ps подтвердил GPU (size_vram==size)
и отдельный принудительный CPU-прогон (size_vram==0), ответ «Привет».
Глобальный Ollama/модели владельца не останавливались и не изменялись.
Отчёты .test-artifacts/real-engine-first-pull-report.json и real-engine-report.json.

Сборка готовится в изолированной локальной Git-копии для сохранения clean
source provenance без изменения основного checkout. Компилятор Inno Setup
6.6.1 получен с официального release и проверен опубликованным SHA256,
установлен portable только внутри .test-artifacts/tools/inno6. Core Python/Qt
для сборки будет повторно проверен по manifest предыдущего payload перед reuse.
Результат установщика/GUI фиксируется отдельным следующим пунктом после прогона.

Чистой Windows VM нет — владелец подтвердил это и согласовал явное ограничение
проверки. Windows без установленного Ollama и физический CPU-only ПК не заявляются
проверенными. Микрофон не тестировался; DevCrew не запускался. Подробности, интернет,
диск, модели, offline demo и troubleshooting: docs/ENGINE_SETUP.md; вопросы защиты:
docs/DEFENSE_QA.md. Запуск исходников: python start.py.

## 2026-11-06 — реальные команды RC3 и UI подтверждения

База: 4282bfbbf15bb79cf7011a3e19696ca9dd77c14a. Исправлены четыре
сообщённых сценария; голосовые модули, контроллер и сборщик не менялись.

- «Про что/о чём файл <путь>», «Перескажи файл», «Расскажи о файле» сначала
  получают подтверждённое содержимое через files.read_file и live-policy,
  затем передают его LLM. «Прочитай файл» сохраняет verbatim без генерации.
  Фактический отказ/отсутствие файла не отправляет запрос на пересказ;
  существующий fallback ложного отказа модели сохраняет успешное чтение.
- «Последний скачанный PDF файл в папке Download» и варианты Download,
  Downloads, Загрузки идут через файловый инструмент. Сравниваются реальные
  mtime; ответ явно сообщает, что время скачивания неизвестно. Пустая область
  и запрет поиска не превращаются в выдуманный найденный документ. Planner
  использует тот же краткий file_output, что и точный маршрут.
- UI показывает точный путь/операцию, TTL, отдельные «Подтвердить удаление»
  и «Отменить». Только клик отправляет approved boolean на /api/files/confirm
  с исходными conversation_id, server_instance и одноразовым confirmation_id.
  Чат «УДАЛИ» не подтверждает операцию. Двойной клик, replay status/final,
  смена разговора/сервера, истечение и потерянный ответ не повторяют действие.
  Backend повторно проверяет разрешения/identity/TTL как раньше.
- Выбор нескольких окон Modrinth App вынесен в вертикальную сетку с переносом
  длинных заголовков. Передаётся точный window_id выбранной кнопки, заголовок
  остаётся недоверенным текстом; сам выбор не активирует/закрывает окно.

Реальные проверки Windows Python 3.14.5 из существующей соседней .venv:

- Затронутые Python-наборы: 447 passed. Новые 112 регрессий затем отдельно
  повторно прошли. Каждый файловый сценарий проверен в restricted/full_user;
  known folders в full_user указывают на синтетические тестовые папки.
- Полный python -m pytest -q -rs: 1532 passed, 2 skipped,
  35 subtests passed, 35.73 s. Skip: отсутствие PySide6 в тестовом
  интерпретаторе и отсутствие 8.3 alias на томе.
- Полный npm run test:dom: PASS, включая новый action-controls-dom.test.cjs.
  Проверены подтверждение/отмена, неверный/устаревший контекст, потерянный
  ответ без повтора, отзыв права, экранирование путей/заголовков и точный
  выбор окна; существующая регрессия истории не восстанавливает live controls.
- node tests/action-controls-browser.cjs: PASS, 6 CSS viewport 320–1280 px
  (731 px также соответствует окну 1024 px при 140%). Проверены фактические
  прямоугольники трёх кнопок окон и confirm/cancel: без наложений, переполнения,
  с высотой >=44 px. Скриншоты 1280/390 просмотрены. Первый sandbox-запуск
  Chromium дал spawn EPERM; разрешённый изолированный запуск прошёл. Страница
  получает localhost-origin через route.fulfill, реальной сети/сервера нет.
- Самостоятельное code/security review, node --check static/assets/app.js,
  git diff --check: PASS. Правила deny, исключения и auth не изменены.

Логи: .test-artifacts/rc3-routing-full-pytest.txt,
.test-artifacts/rc3-routing-dom.txt; геометрия/скриншоты:
.test-artifacts/action-controls/. Файловые тесты выполняют настоящее I/O
только в .test-artifacts; Ollama, Modrinth и окна — фикстуры. Пользовательская
LocalMind_QA/политика не менялись. Настоящий Modrinth, Qt DPI, микрофон/GPU,
физический offline-demo не проверялись. DevCrew/установщик не запускались.

Запуск исходников после подготовки зависимостей: python start.py. Offline-demo
после загрузки локальных моделей и troubleshooting: docs/RC3_HANDOFF.md;
60+ вопросов с объяснениями: docs/DEFENSE_QA.md. Если старая маршрутизация
сохраняется, перезапустить именно процесс с этими исходниками. При отказе
проверить сохранённую область/read/search/delete и deny; для удаления нажать
кнопку подтверждения с точным путём. Это не сборка обновлённого установщика.

Git-коммит не создан: git add заблокирован sandbox при создании
C:/Users/ExampleUser/Desktop/LocalMind_RC3/.git/index.lock — Permission denied.
По указанию владельца обход не выполнялся, изменения оставлены в worktree.
HEAD остаётся 4282bfbbf15bb79cf7011a3e19696ca9dd77c14a. Изменены только:
docs/DECISIONS.md, docs/STATUS.md, localmind/file_requests.py,
localmind/llm_planner.py, localmind/orchestration.py, localmind/results.py,
package.json, static/assets/app.js, static/assets/desktop.css,
tests/test_command_routing_rc3.py, tests/action-controls-dom.test.cjs,
tests/action-controls-browser.cjs.

## 2026-11-05 — две регрессии pytest на базе fd26eee

Исходное воспроизведение затронутых трёх наборов: 62 passed, 2 failed.
Вопрос «Что написано в документе?» попадал в READ-envelope без файловой цели
и завершался tool-policy до обычного dialogue. Planner теперь знает только
факт наличия серверного контекста вложений и возвращает информационный запрос
без файловой цели в стандартный маршрут. Текст настоящего вложения проходит
inference_attachments и budget_messages, а final получает attachment_sources
из обработанных document_facts. Формальное добавление метаданных не делалось.

Устаревший realworld-тест разделяет прямое чтение без LLM и вопросы/пересказ
с LLM. _verbatim_file_read, prepare_file_read, отказоустойчивость успешного
чтения, голосовые модули и контроллер безопасности не менялись.

Проверено в существующем Windows-окружении Python 3.14.5 соседнего проекта
LocalMind_MVP_01/.venv (его файлы/зависимости не изменялись):

- Сначала test_attachments, test_realworld_followups,
  test_speech_agent_reliability, test_explicit_file_reads,
  test_access_policy, test_vision_attachments: 396 passed, 1 skipped.
- Затем полный python -m pytest -q -rs: 1420 passed, 2 skipped,
  35 subtests passed, 33.86 s. Skip: test_desktop_shell — PySide6 отсутствует
  в этом интерпретаторе; test_access_policy — том не предоставил 8.3 alias.
  Это фактические результаты текущего окружения, не прежние 1437/7 владельца.
  Лог: .test-artifacts/document-regressions-full-pytest.txt.
- Регрессии проверяют фактический текст, переданный генератору, ID и имя
  источника в HTTP и final stream, отсутствие команд/полномочий из документа,
  отсутствие фиктивных источников без вложений, приоритет текущего файла над
  посторонним вложением и сохранение отказа на запрещённое чтение/удаление.
  Существующие проверки ложного отказа модели и прямого чтения также прошли.
- Финальный diff проверен самостоятельно; git diff --check: PASS.

Ollama/OS-действия в регрессиях подменены; это не реальный inference-тест.
DevCrew и сборка установщика не запускались. Микрофон/GPU/Qt в этой задаче не
проверялись; вывод о полной готовности релиза не делается. Запуск исходников
после подготовки зависимостей: python start.py. Offline-сценарий и
troubleshooting: docs/RC3_HANDOFF.md; 60+ вопросов с ответами:
docs/DEFENSE_QA.md.

Коммит не создан: git add отказал при создании
C:/Users/ExampleUser/Desktop/LocalMind_RC3/.git/index.lock (Permission denied).
По прямому указанию владельца изменения оставлены без обхода sandbox.
HEAD: fd26eee28ff0d80fc3c2ce746321c753579bd8d1. Изменены только
localmind/agent.py, localmind/llm_planner.py, tests/test_attachments.py,
tests/test_realworld_followups.py, docs/DECISIONS.md, docs/STATUS.md.

Milestone release build: SUCCESS, аппаратная приёмка заблокирована средой.
Установщик, Source.zip и provenance собраны из одного source-коммита
31fad862e248f729208f90f6e08551058ab42d10 на release/1.0.0-rc2, предок
RC1 a229ffff4ab5dafd607c755e4f74090d6a965ece проверен. После сборки меняется
только документация с этим evidence; исполняемый код релиза не изменён.

Команда выполнена с exit0:
py -3.11 scripts/build_windows.py --output dist/rc2 --iscc .test-artifacts/tools/inno6/ISCC.exe

Артефакты в rc2/dist/rc2 (относительно родительского предоставленного worktree):
- LocalMind-1.0.0-rc2-Setup.exe: 2119081203 bytes;
  SHA256 911adc92f96bebfae184749463200848aae68dec22631b78f4b71ee071de8ba7.
- LocalMind-1.0.0-rc2-Source.zip, SHA256.txt, build-provenance.json,
  RELEASE_NOTES.md, KNOWN_ISSUES.md, MANUAL_QA.md.
- Проверены все артефактные SHA256,19770 payload hashes, идентичность копий
  committed app/static/config, Git ZIP commit и отсутствие base в каталоге.
- Launcher FileVersion1.0.0.0/ProductVersion1.0.0-rc2. Настоящие .NET csc и
  Inno Setup6.7.4 выполнены, это не fake build. Private CPython3.11.9 smoke
  импортировал fastapi/av/faster_whisper/torch/QtWebEngine/server.
- Финальные автотесты после установки decoder dependencies:1049 passed,
  35 subtests,0 skipped (13.41s), Python3.11.9/PyAV18.1.0/faster-whisper1.2.1.
  npm check:ui/test:dom/check:assets, compileall, pip check, git diff --check PASS.
- Модели не загружались. Сеть использовалась для runtime/wheels и официального
  Ollama prerequisite; его подпись проверена builder. Inference здесь не измерялся.

Оставшиеся обязательные аппаратные/browser/install gates: NOT TESTED.
QtWebEngine упал на Chromium pipe Access denied0x5; Playwright spawn EPERM,
browser host unavailable. Микрофон, CPU/GPU speech accuracy, DPI/Alt+Tab/tray,
установленный EXE, clean install/upgrade/uninstall/offline demo не проверены.
Подробный протокол — MANUAL_QA.md. Нельзя считать RC2 принятой Stable-сборкой.
Релиз не опубликован, push/deploy отсутствуют, RC1/Alpha сохранены.

## Предыдущий milestone RC2

# RC2 — фактический статус 2026-11-04

Milestone: desktop/STT implementation and automated review.
Ветка release/1.0.0-rc2 от a229ffff4ab5dafd607c755e4f74090d6a965ece.
Исходные RC1/Alpha не изменены. Из-за запрета записи Git metadata родительского
worktree новый независимый checkout находится в rc2/; скопированы Git objects,
история и ancestry сохранены. Это не merge обратно в Alpha.

Реализованы native рамка/иконки/tray/геометрия/recovery, обе темы/reduced motion,
small/medium с совместимостью настроек, отсутствие base fallback и shared-resource
locks. Закрытие останавливает только owned workers и setup probes, отменяет
чат, запрещает late respawn. Текущий Ollama network read может ждать до30с.
QML1.1 оценён отдельно; полная миграция RC2 не выполнялась.

Проверено в rc2 на x64 CPython3.11.9 и PySide6 6.8.3:
- .venv/Scripts/python.exe -m pytest -q: 1049 passed,0 skipped,
  35 subtests (13.41s). Установлены PyAV18.1.0/faster-whisper1.2.1,
  выполнены реальные decoder/framed-process тесты с синтетическим аудио;
  neural inference в этих проверках подменён, microphone/accuracy ими не доказаны.
- npm run check:ui; npm run test:dom; npm run check:assets: PASS,
  43 основных DOM проверки плюс остальные suites,85 локальных assets.
- Независимые desktop method/policy/state тесты:49 passed.
- git diff --check: PASS. Reviewer/Security не нашли P0/P1;
  замечания initial geometry/dragdrop/shortcut grouping исправлены.
- Portable Inno Setup6.7.4 подготовлен только в .test-artifacts/tools/inno6;
  Authenticode Valid, publisher Pyrsys B.V. Системная установка не изменялась.

Настоящий desktop запуск предпринят: Chromium fatal named-platform-channel-pipe,
Access denied0x5 до проверки GUI. Playwright27 тестов не исполнились из-за spawn
EPERM; fallback browser host unavailable. Sandbox не отключался.
Реальные Windows GUI/DPI/mic, CPU/GPU inference/accuracy, clean install/upgrade,
installed EXE и offline demo: NOT TESTED. Сценарии в MANUAL_QA.md.

Следующий этап: clean committed build, команда
py -3.11 scripts/build_windows.py --output dist/rc2 --iscc .test-artifacts/tools/inno6/ISCC.exe.
Результат сборки на момент этого milestone ещё не установлен; evidence в dist
и следующий статус фиксируют фактический исход. Не объявлять Stable.

## Исторические статусы до RC2

# DevCrew — проверяемый статус LocalMind 1.0

## 2026-11-03 ? ?????????? final release / stabilization: 1.0.0-rc1, ?????? ????????????

Milestone 1: ????????? ??????????? ?????? 50 ? 16 ??????????/untracked source ??????
???? ???????? worktree ? build/recovery/worktree-{1,2}.zip; SHA256 ? ??????????
???????? ?????????. ?????????/?????/Alpha ?? ????????. ??? ?????? ?????????????
? ??????? ????? ? ??????????? ??????????, ??????? ??? ????? ?????. Git switch
??????? Permission denied ?? index.lock ??? workspace: release-?????, snapshot
??????? ? integration commit ?? ???????. HEAD ???????? 66f6c10.

Milestone 2: STT strict JSON + ???????????, ???????????? transcript, warm-worker
?????????; ??????????? per-model ????????? Ollama ? temperature; gemma4 default
??? ?????? ???????????? ??????; ???????????? Ministral; ?????? thinking;
launch/window/activation ?????????; UI dedup/reset ? ???????????? polling;
?????????? data root, ??????????? copy-only ????? ? ????? ???????? ???? ??? legacy
????????. ?????? ?????? ???????????? in-place, ????? Ollama ?????? ?? ???????????.

Milestone 3: builder ??????? ?????? release/1.0.0-rc1, ?????? RC-????? ? provenance
commit/tags/?????? ????????????/????. ???????? ?????? committed sources; resume
????????? ?????????? runtime, ????????? ????????? ? ??????/offline ?????. ??????????
review ?????? ?????????? ? ????????? ???????????. Security review ?? ????? ??????????
????????????? P0/P1. ???????? ?????? ???????? ? voice-offline ????????? ????????????
?? ????: dirty/uncommitted checkout ? ?????????? Inno Setup 6. Setup.exe, release
Source.zip, ?? SHA256 ? ??????????????? ????????? tag/commit ?? ??????????.

??????????? ???????? ??????? ??????????:
- 971 passed, 35 subtests passed (12.31 s), pytest -q -p no:cacheprovider;
  interpreter C:/Users/ExampleUser/Desktop/LocalMind_MVP_01/.venv/Scripts/python.exe,
  Python 3.14.5, cwd ??????? worktree, ?????? .test-artifacts. ??? ?? bundled 3.11.
- npm check:ui, test:dom (41 ???????? + ????????? ??????), check:assets (83) PASS.
- git diff --check, compileall ??? Python 3.11 ? PowerShell parser finalize_release.ps1 PASS.
- C# launcher ??????? ????????????? .NET csc, FileVersion 1.0.0.0 / ProductVersion
  1.0.0-rc1. ??? ?????? launcher ??? runtime, ?? ????????? Setup ? ?? EXE QA.
- Playwright: spawn EPERM ?? ??????? ?? 25 ??????; CUA browser host unavailable.
  ?????????? ???????? NOT TESTED.
- ???????? ????????? RSA ? gemma4 ? ?????? ??????: ??????? ?????, 5557 ms,
  thinking off / temperature .2 / context 4096 / response 384. ????? ??????????
  docs/evidence/release-real-smoke.json; ?????? ?? /api/ps ????? ??????, ?? peak.
- ???????? Python Notepad adapter: ??????? ??????, ????? ??????? ???? ???? ?? PID;
  foreground activation_denied, ?????????? ???????? ????????. ?????? ???? ?????????
  ????????; ????? ???????? ?? ???????????. ??? ?? ???????? ?????????/EXE.
- ????????, STT GPU/CPU acoustic test, Silero xenia, ?????? voice-????????,
  restart persistence, real download cancel/retry, ?????? Windows/EXE/uninstall,
  gemma4 vs ????????????? ministral-3:8b: NOT TESTED.

?????? source ????? ????????? ????????????: python start.py. Release notes,
KNOWN_ISSUES.md, MANUAL_QA.md ? docs/RELEASE_RECOVERY.md ????????????. ?????????
???????? ?????? ?????????? ??????? ???????? ? ?????? ??? sandbox. ?????? ?? ?????????
??????????? ???????. ???????? Stable ?? ?????????? ? installer gates ?????????.


## 2026-11-03 — STT / Storage / Download Manager hardening, кандидат без аппаратной приёмки

Три запрошенных этапа реализованы в рабочем checkout. Отдельные Git-коммиты
создать невозможно: `git add` получил Permission denied при создании index.lock
в metadata основного checkout за пределами разрешённого worktree. Обходов ACL,
push и публикации не было. Изменения остаются незакоммиченными.

1. STT: прежние модели/параметры декодирования сохранены; фактические path/hash/runtime,
   device/fallback, beam/VAD и измеряемые ресурсы приходят от worker. Все три профиля
   можно явно подготовить. Микрофон сообщает параметры фактического захвата.
   Первый focused снимок: 229 passed; full общего checkout: 871 passed и 35 subtests.
   После независимой проверки исправлена диагностика загруженной модели при пустом
   transcript. Реальная регрессия «Пак варить пельмени» не воспроизведена и не считается
   исправленной: прежняя сборка и согласованный корпус Windows-записей не предоставлены.
   [Русская QA, сравнение EXE/Python, запуск и восстановление](HARDENING_STT_QA.md).
2. Storage: сохраняемый root, согласуемый copy-only план с SHA-256 и проверкой места,
   совместимые старые пути; наблюдение окружения реального Ollama listener,
   согласуемое копирование его store и безопасный запуск нового daemon.
   Сохранение параметров генерации по моделям и lease/retention/verified unload.
   Автоочистка потенциально общего сервера пропускается с объяснением.
   Focused итог: 90 passed. Проверены защита bootstrap/pending root, reparse points,
   занятые запросы, гонки settings/switch и malformed /ps. Независимое ревью не нашло
   нерешённых P0/P1; последние dangling-link проверки исправлены и покрыты тестами.
   [Русская QA, перенос, совместимость истории и troubleshooting](HARDENING_STORAGE_QA.md).
3. Downloads: единый durable журнал/renderer, bytes/progress/speed/ETA, honest cancel,
   проверка установленного артефакта, retry metadata/disk/license и persistent dismiss.
   Qwen 0.5B отмечена как лёгкая резервная/тестовая. Focused: 63 passed;
   независимый combined STT/download прогон: 294 passed. Подмена offline GGUF и отмена
   до POST create покрыты тестами. [Русская QA](HARDENING_DOWNLOAD_QA.md).

Финальный Python-прогон: **906 passed, 35 subtests passed**. UI syntax, DOM
(включая новые storage/download сценарии), 83 local assets, compileall,
build script --help, pip check и git diff --check прошли. Типизация отдельным
инструментом в проекте не настроена. Новый EXE/installer не собран и не принят.
Playwright не смог запустить worker: spawn EPERM. Browser tool также сообщил
недоступность browser access host; визуальный просмотр не состоялся.

Реальная проверка запуска `python start.py` в изолированном DATA_ROOT:
пять новых/существующих GET API, отрицание запуска калькулятора, DEMO-лампа и
отрицание прошли по HTTP. Ollama для этого smoke намеренно недоступен;
это не тест Gemma/планировщика. Отдельные read-only запросы к настоящим HF/Ollama
подтвердили шесть GGUF-вариантов, SHA-256, Ollama 0.40.13, фактический внешний store,
установленную Gemma 4 12B и обнаружение RTX 4070. Ни перенос реальных моделей,
ни выгрузка общего сервера не выполнялись.

**Не проверено:** реальные Windows-микрофон и 30×3 корпус/baseline; новый EXE/installer;
слышимая xenia; реальная генерация Gemma с прежними настройками; GPU STT и совместная
нагрузка; настоящие pull/cancel/retry/restart и перенос пользовательских данных;
ручной Windows launch; физическое отключение сети. Unit/mock/DOM и обнаружение
оборудования эти пункты не заменяют. Релиз пока нельзя считать завершённым.
Одна команда после подготовки: `python start.py`; offline demo и восстановление
описаны в трёх QA-документах. Существующие 60 вопросов с ответами: DEFENSE_QA.md.

## 2026-10-31 — contextual TTS fixes; listening and browser playback pending

Implemented speech-only Apple/Node.js mappings, coordinated four-digit years
with shared году/годах, software version components and IPv4 «точка» separators.
Mathematical decimals, fractions, dates, legacy filename speech, displayed text
and Silero v5_6_ru / xenia settings are preserved. Streaming retains complete
and partial expressions through product/version whitespace and year-list commas.

Verified in this checkout using the installed project environments (dependencies
reused locally, model copied from the original checkout; no model download):

- Focused Python command: **215 passed**. Full Python: **716 passed, 35 subtests
  passed**. Both report the existing pytest-cache Windows ACL warning.
- DOM: **39 checks passed**, including every delta split near the chunk boundary,
  character deltas, unchanged displayed text, pause/resume, stop, mute and
  successor behavior. These use DOM/audio doubles, not real browser playback.
- All seven JavaScript syntax checks and final diff whitespace checks pass.
- Real local CPU xenia evaluation: **90 samples, zero synthesis errors**, with
  v5_6_ru, four threads, mono PCM16 24 kHz, accent/ё enabled. All required rows
  and franchise regressions are in the listening worksheet.
- Real supervised worker: **12 exact literal / diagnostic tts_input / outgoing
  worker-frame correlations**, one resident worker reused. Retired generation
  rejected before dispatch; successor synthesis succeeds. Twelve loopback HTTP
  TTS requests return **200** with valid nonempty 24 kHz WAVs.
- Independent Reviewer/Security inspection found no blocking code issues.

Private evidence: `.test-artifacts/contextual-tts/listen.html`, `evaluation.json`,
`worker-correlation.json`, `http.json` and WAVs. All human-listening fields remain
unrated. No human listening report has been received for this build; audible
quality has **not** passed. Windows microphone and GPU were not tested.

The checkout server started with `start_windows.ps1` on isolated loopback port
8896. Direct script invocation is disabled by the Windows execution policy;
the test used a process-only PowerShell invocation, without persistent policy
changes. The focused Playwright test was attempted but cannot start its worker
(`spawn EPERM`). Browser access host is unavailable; automatic approval review
rejected native Zen inspection because Zen is not approved for Computer Use.
Real playback, pause/resume/stop/mute and successor playback remain unverified
in a browser. Do not treat generated WAVs or DOM doubles as audible approval.

Reproduction, offline demo, troubleshooting and the remaining listening protocol
are in [BILINGUAL_SILERO.md](BILINGUAL_SILERO.md). Existing explanatory defense
questions are in [DEFENSE_QA.md](DEFENSE_QA.md). No publication or deployment.

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

## 2026-10-30 — speech/agent implementation milestone

Checkout began clean at cdfd1d3 on devcrew/20261030-180745-0ad300a7.
Added deterministic filename titles/years, one supervised warm ASR process,
paired language experiments, sequence preflight/stop-on-failure, nonempty selected
document extraction gating and HWND identity checks across asynchronous activation.
Blacksite assets, public voice profile IDs, default decoding and permission policy
are preserved. Shared speech/ASR pipe buffers are cleared while idle.

The complete Python suite passed: 540 tests and 35 subtests. Native action and
generation doubles in tests remain doubles. Real selected-PDF extraction and local
qwen3.5:9b source inclusion/answer passed separately; access revocation prevented
further reading. Actual Piper generated five WAVs and Windows playback APIs returned
success, but listener feedback is absent. A synthetic waveform exercised real small
CPU reuse and medium CUDA→CPU fallback/reuse; it is not a microphone benchmark.

Rollback branch creation was attempted and denied at the external shared Git metadata
directory. No branch or checkpoint commit was created. An untouched HEAD archive is
retained locally in .test-artifacts/baseline-cdfd1d3.zip. This is a recovery artifact,
not a substitute for the required orchestrator rollback branch.

Product completion remains pending. See SPEECH_AGENT_RELIABILITY.md for the separate
verification categories, exact reproduction commands and physical-device blockers.

Verification milestone: seven JS syntax checks and 52 DOM checks passed. Real
loopback DEMO/Ollama smoke passed. Browser runner creation failed with spawn EPERM;
automatic approval review rejected Zen inspection. Physical foreground success,
30+ microphone phrases, listener feedback and GPU execution/coexistence remain
unverified. The final tests include sequence speech separation, malformed/incomplete
recording manifests, and suppression of model generation on content clarifications.
The original checkout's installed environment was reused read-only; local Python
3.11 lacked dependencies. No new model downloads, cloud inference or UI redesign.
Final fresh start.py startup returned HTTP 200 in DEMO mode; real local Ollama smoke
passed again and the owned test server was stopped. Compound document speech now
defers initial action audio so summary deltas reach TTS; the DOM regression passed.
# 2026-10-31 — Silero bilingual implementation milestone (verification pending)

Started at fee423c. Default API/UI/warm-up now use the existing declared Silero
v5_6_ru / xenia / CPU / four threads / 24 kHz. Explicit voice IDs are preserved;
Piper readiness and setup no longer depend on the default ID. UI persists an
explicit voice preference. Speech-only script spans precede name adaptation;
the Russian model's Cyrillic-only alphabet was inspected in the actual downloaded
package. Unknown Latin words are spelled rather than silently removed. Display
text and tool arguments are untouched. Clause queues, bounded worker reuse and
cancellation remain; cancellation after a reply is explicitly checked.

New launch-to-focus integration snapshots/revalidates the image grant, waits at
most ten seconds for a verified window, supports PID-independent Electron handoff,
and keeps foreground equality as the success criterion. Only the granted Obsidian
win32 image opts into bounded background-instance activation. Obsidian foreground
bug remains OPEN until actual desktop cold/existing/minimized cases pass.

At this milestone: 559 Python tests and 35 subtests passed, four dependency skips;
JS syntax checks passed. Playwright runner failed before tests with spawn EPERM.
Browser access host is unavailable; automatic approval review rejected Zen
inspection because Computer Use was not approved. Audio comparisons are being
generated locally; listening, browser playback start, microphone and GPU are
unverified. No completion or listening-quality claim is made.

## 2026-10-31 - bilingual verification milestone

Final Python verification: 562 passed, 4 optional-dependency skips, 35 subtests;
JS syntax, 54 DOM behavior checks and all 76 local asset references passed.
The Playwright runner still cannot spawn its worker (EPERM). No build/typecheck
script is declared in package.json. Final scoped diff review found no new
security blocker; launch grants, native identity, ambiguity and observed
foreground checks remain enforced.

Actual Silero comparisons retained WAVs for all eight adapted phrases, with six
supervised attempts each. Three legacy English-only phrases failed all attempts;
no replacement/silent baseline files were fabricated. Literal Latin experiments
and twelve English Silero excerpts were also generated. Runtime identities,
model hashes, load/repeated timings and the unrated listening worksheet are in
BILINGUAL_SILERO.md and evidence/bilingual-silero-20261031.json. Warm adapted
synthesis medians were 36.3-98.3 ms; first calls including worker/model/warm-up
were 3.34-3.43 s. These are synthesis measurements, not browser/acoustic latency.
All eight phrases also returned actual mono PCM16/24 kHz WAVs through the running
current-checkout API. Real cancellation while loading and after dispatch of a
warm request stopped the owned worker; successor synthesis and stale-cancel
isolation passed. No physical network disconnection was performed.

Obsidian native attempt reused an exact fingerprint already allowed in the
existing LocalMind runtime. From absent state, cold launch created a process but
window discovery found three candidates and correctly refused ambiguity; repeated
open also refused. Two candidates were input-indicator windows and one a dialog;
the interactive inventory did not expose them. This is not successful editor
foreground verification. The original bug remains OPEN. No forced close or
arbitrary candidate selection was used. The separate existing server was left
untouched; only the Builder's isolated test server was stopped.

Completion remains blocked on listening feedback, interactive Obsidian cases and
browser playback-start verification. Browser host access was unavailable and
automatic approval review rejected Zen inspection as not approved for Computer
Use. Microphone and GPU remain unverified. English routing remains disabled.
# 2026-10-31 — pronunciation regression repair, listening still required

Scoped repair implemented: contextual Warcraft/Diablo Roman numerals before Latin
processing, whole multiword names, explicit initialisms, sound-based unknown-word
fallback, and version-prefix spacing. Silero v5_6_ru / xenia and synthesis settings
are unchanged. Speech stages are inspectable; only explicit
LOCALMIND_TTS_DIAGNOSTICS=1 logs original/cleaned/pronunciation/exact worker input
with per-request correlation through parent stderr. Default mode retains no
diagnostic text/audio. Display, file/action data and unrelated agent/UI behavior
were not changed. Stream cuts retain complete and partial entities; exhaustive
delta-split tests cover required names around the 240-character boundary.

Final verification: 607 Python tests and 35 subtests passed (Python 3.14.5;
cache provider disabled after a worktree cache-write warning). JavaScript syntax
checks, 76 local asset references, 38 main DOM checks, ten attachment-context
checks and seven history checks passed. git diff --check passed. package.json
declares no separate typecheck/build step. Source environments were reused
read-only via ignored local .pth links with matching interpreter versions;
initial attempts using mismatched binary-package versions failed collection
and were corrected before the final full run.

Actual Windows CPU synthesis: 32 current Russian xenia WAVs, including all 24
required standalone/sentence cases, zero synthesis errors. Python 3.12.10,
PyTorch 2.6.0+cpu, four threads, 24 kHz; model SHA256 unchanged. Existing local
model copied into this worktree; no model download. A real isolated current
server on 8879 returned HTTP 200 and mono PCM16/24 kHz (5.45 s) for the combined
Warcraft II / Diablo Immortal / Blizzard Entertainment sentence. Its opt-in
stderr diagnostic record showed all four stages. No default-mode text logging
was added. Offline environment flags used; physical disconnection not tested.

CMUdict versus compact fallback evaluation: 18 supplied/unseen words, 15 lexicon
hits, 33 optional xenia WAVs. Text inspection shows benefits for Phoenix but
undesired English Diablo/Warcraft forms and missing novel names; lexicon/phoneme
approach stays evaluation-only. No runtime dependency/service added. License,
Windows setup, limitations, commands and results are in BILINGUAL_SILERO.md;
WAV identities and unrated review fields are in
docs/evidence/silero-pronunciation-20261031.json and ignored listening worksheets.

Required actual listening remains UNVERIFIED: no reviewer/observations were
available. Browser streamed playback/pause/stop/mute was not verified on real
audio: Playwright worker spawn failed with EPERM, browser host was unavailable,
and automatic approval review rejected Zen access because Computer Use was not
approved to use Zen. DOM playback/cancellation checks use doubles and do not
establish hearing. Windows microphone and GPU remain untested. Do not declare
speech quality or this task fully signed off until all required WAVs and the
same streamed sentences receive listening review. Other historical open issues
remain unchanged. The owned isolated test server was stopped after verification;
the pre-existing LocalMind server was not changed or stopped.

## 2026-10-31 — three pronunciation bugs: implementation milestone

General Roman title context replaces the franchise whitelist; explicit
initialisms, English I, canonical parsing and version boundaries have precedence.
Numbers are retained until classification, then become bounded Russian
cardinals/ordinals/decimal fractions with explicit year inflection. Technical
versions, IPs and dates are consumed first. Ampersands use original scripts:
English titles/letter initialisms get энд, Russian contexts и. Shared filename
year rendering remains stable. Streaming protects generic contexts and partial
tokens. No voice/engine/worker settings or displayed response changes.

## 2026-10-31 — three pronunciation bugs: verification milestone, gate open

Final automated results: 172 focused Python tests; 678 full-suite tests and 35
subtests; 38 main DOM, ten attachment-context and seven history checks; JS syntax,
76 asset references and git diff --check passed. Exact whole-result regressions
cover the requested matrix, unseen titles, initialisms, invalid/version Roman
tokens, negative/zero/teen/tens/hundreds/thousands, ordinal exceptions, technical
counterexamples and oversized numeric expansion. No separate build/typecheck/
Python lint command is configured. Python 3.14.5 app/tests reused installed
packages read-only; pytest cache provider disabled because cache creation was
denied. No dependency or model downloads.

Actual CPU synthesis: 76 current xenia WAVs with zero errors (Python 3.12.10,
PyTorch 2.6.0+cpu, four threads, 24 kHz). An isolated current server on 8879
also produced 33 HTTP WAVs, including 23 standalone cases and ten clauses from
119 real qwen3.5:9b streamed deltas fed into the production JavaScript chunker.
Every recorded HTTP row matched original_text, cleaned_text, pronunciation_text
and exact tts_input in correlated opt-in stderr diagnostics. Original final
display text equals the streamed text; no pronunciation rewrite leaked into it.
Actual API retired-generation rejection, successor synthesis and stale-cancel
isolation passed. The chunker ran queue-only, without browser playback. Private
synthetic WAVs/worksheet are under .test-artifacts/numeric-ampersand; aggregate
evidence is docs/evidence/silero-normalization-20261031.json. The owned test
server was stopped; existing unrelated servers were untouched.

NOT finished: actual listening and live UI pause/resume/stop/mute/successor
playback remain UNVERIFIED. Browser access host is unavailable; Playwright
fails before tests with spawn EPERM. Automatic approval review rejected Zen
inspection because Computer Use was not approved to use Zen. No acoustic rating
is inferred from successful WAVs/HTTP or DOM doubles. Windows microphone and GPU
remain untested. Current commands, offline listening worksheet, troubleshooting
and the existing defense-question document are linked in BILINGUAL_SILERO.md.

## 2026-11-01 — installed models milestone

Implemented transactional active model, installed metadata, real request-owned metrics and optional NVML/psutil hardware telemetry inside existing settings. Removed automatic unloading of other workloads. Replay after selection change retains original accepted generation and side effects execute once.

Verification: focused 13 passed; full 725 passed, 4 skipped; JS syntax, 39 DOM checks plus attachment/history checks and 77 asset audit passed. Playwright attempted: worker spawn EPERM, no browser assertions executed. Real Windows Ollama 0.40.13: qwen3:4b health, JSON and streamed agent response identity/metrics passed; NVML detected RTX 4070 and real VRAM/utilization. API placement matches `ollama ps` 100% GPU at context 4096. Real CPU fallback, microphone, simultaneous ASR, listening and visual scale QA NOT tested. No complete-product claim. See MODEL_MANAGER_QA.md for exact Russian prompts, troubleshooting and evidence.

Focused commit attempted but blocked: this worktree's Git index is in
`C:/Users/ExampleUser/Desktop/LocalMind_MVP_01/.git/worktrees/...`, outside the writable
workspace. Git add/commit both fail creating index.lock (Permission denied).
No commit was created; no attempt to bypass the filesystem boundary. Continue
independent implementation in this checkout, keeping milestone evidence separate.

## 2026-11-01 - catalog milestone

Implemented curated Ollama registry, bounded HF REST search and GGUF variants, strict reference/quantization validation, architecture/version estimates, conservative memory/KV assumptions, honest unknown disk capacity, explicit license/disk acknowledgements and bounded pull jobs with digest progress and manual retry. Cancellation closes the HTTP stream and explicitly does not claim daemon-stop verification. No automatic download, model switch or restart resume.

Focused tests: 44 passed across manager/catalog. Full: 756 passed, 4 skipped. UI syntax, DOM including focused model/XSS/no-silent-download checks, asset audit and diff whitespace passed. Playwright attempted again: spawn EPERM before execution. Real HF API search and five explicit quantized variants passed on Windows; no model assets downloaded, no real cancellation/retry/disk-exhaustion claim. Regression prompts and actual limits recorded in MODEL_MANAGER_QA.md. Focused commit remains blocked by external Git index write permission; no commit exists.

## 2026-11-01 - benchmark milestone and final verification

Implemented a fixed 12-task Russian screening protocol, identical one/two-model
inputs/settings, inert native tools, non-executing AST check, separate factual,
instruction/reasoning/coding/uncertainty/structured/tool checks and performance.
Persist suite version/hash, requested/actual identity, model digest/quant, answers,
errors, metrics, post-run placement, checkpoints and separate manual ratings.
Unknown/unsupported stays unknown/N/A; incomplete runs do not become comparisons.
Busy admission precedes request ID reservation; accepted retries keep their settings.

Final tests: 68 focused passed; full pytest 780 passed, 4 skipped, one TestClient
deprecation warning. JS syntax, all DOM suites (39 primary plus attachment/history/
model checks), 77 local assets, compileall and diff whitespace passed. New browser
scenario included; Playwright discovers 36 but cannot spawn worker (EPERM), zero
browser assertions executed. No separate configured typechecker or build exists.

Real Windows/Ollama 0.40.13: CPU fallback qwen3:4b has size_vram 0; earlier GPU
run matched ollama ps 100% GPU / context 4096. Completed current v2 comparison
qwen3:4b vs qwen3.5:9b, 24 tasks, active selection unchanged. Both: fixed factual
3/3, instructions 2/2, reasoning 2/2, code 1/1, uncertainty 1/1, structured 1/1,
native tools 0/2. Different actual placements CPU/GPU prohibit a speed winner;
these are narrow deterministic screening counts, not general quality/accuracy.
Real HTTP start.py on owned port 8879: benchmark 200, busy chat 429, same-ID retry
after completion 200, actual model/metrics in JSON and NDJSON. Final bounded helper
inventory/health and real HF fingerprints also passed. Evidence:
docs/evidence/model-manager-20261101.json; exact prompts and per-milestone manual
results in MODEL_MANAGER_QA.md; defense questions expanded from 40 to 50.

Final review fixes: selection badge could still be changed by a legacy event
listener; removed and tested. Downloads now require a metadata/license/artifact
fingerprint and explicit acknowledgements. Fixed terminal cancellation race,
ghost jobs on thread/save failures, bounded streams/caches and safe optional
telemetry. No unresolved critical/high security issue identified in changed scope.

NOT accepted as a complete feature: real model pull/cancel/retry, simultaneous
GPU ASR, microphone, audible xenia, physically offline and visual scale QA remain
unverified. Automatic approval review rejected Zen window inspection because
Computer Use was not approved for Zen. No bypass attempted. Three focused commits
cannot be created because Git index metadata is outside writable workspace.
Source changes and evidence remain in this checkout; no push/publish/deploy/merge.

## 2026-11-03 — Productization: состояние Builder, продукт не принят

Этап 1: подтверждён регресс путей worktree (models/.voice-envs исключены из Git).
Добавлены пользовательские пути, повторяемая миграция без переноса прав/секретов,
приватный embedded CPython, GUI launcher, Inno Setup, мастер подготовки/ремонта
Balanced ASR и Silero xenia. Подготовка проверяет SHA-256 и реальный CPU probe.
Промежуточный набор: 792 Python tests прошли после обновления контракта runtime.
Чистые Win10/11 и установка/удаление на них не проверены.

Этап 2: общий сохраняемый журнал LLM/ASR/TTS/офлайн-импорта, interrupted после
рестарта, явные отмена/повтор, короткие причины и очищенная диагностика всех
этапов HF. Текстовый GGUF не блокируется только из-за соседнего mmproj.
Подтверждённый HF GGUF дополнительно сравнивается по SHA-256 из Modelfile Ollama,
без чтения/выполнения пути daemon. Промежуточный набор: 801 Python tests прошли.
Реально установлен hf.co/bartowski/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M (397808192
байта), tags/show и SHA-256 совпали. Отмена дала cancelled_unverified; явный повтор
успешен. Отдельно проверен импорт в пустое локальное хранилище через blobs/create
и повтор с уже существующим blob. Активный выбор до/после не менялся.

Этап 3: меню Чат/Модели/Умный дом/Загрузки, настройки снизу; история внутри чата,
единая кнопка вложений; управление речью только во время воспроизведения.
Пять категорий настроек, экспертная диагностика, скрыта декоративная сцена.
DOM-проверки новых переходов/фокуса/очереди добавлены. Реальная визуальная проверка
не прошла: Playwright не может spawn worker (EPERM); browser access host недоступен;
Qt WebEngine в restricted token получает Access denied при создании IPC pipe.
Последняя попытка браузерного набора: 25 пользовательских сценариев обнаружены,
ни один не выполнен. Legacy scene browser tests сохранены отдельно за
LOCALMIND_LEGACY_SCENE_TESTS=1; DOM-регрессии компонентов остаются в обычном наборе.

Этап 4: HTTP-чат использует LLM-first native tools либо строгую JSON-схему на той
же модели. Политика независимо ограничивает операции/цели, затем адаптеры снова
проверяют разрешения и идентичность. Есть границы шагов/времени, журнал, точные
подтверждения файлов, focus/minimize/restore/safe close, фиксированные workspace,
закладка и страницы настроек Windows. Native и schema реально проверены на малой
Qwen2.5 из тестового HF download. Gemma в этом worktree не предоставлена для
реального прогона; её выбор/данные не изменялись. Реальные «Открой блокнот» и
«Выведи блокнот на передний план» получили activation_denied от Windows;
foreground-успех НЕ подтверждён, ложного «Готово» нет. Отрицание не выполнило действие.
Полное произвольное управление браузером/каталогами/настройками ОС не реализовано.

Этап 5: необязательный локальный HA, DPAPI токена, отдельное обнаружение/разрешение
light/switch, service + повторное чтение состояния. REAL-ошибка не становится DEMO.
Транспорт/состояния проверены моками; DPAPI round-trip реально проверен Windows API.
Реального контроллера, токена и оборудования нет, физическая приёмка не выполнена.

Реальная речь: small CPU и Silero v5.6 xenia загрузились и выполнили inference.
Synthetic WAV xenia «Как сварить пельмени? Что такое RSA?» распознан small как
«Как сварить пельмени? Что такое РСА?». GPU был намеренно скрыт только в отдельном
тестовом процессе: запрос cuda перешёл на cpu/int8_float32, fallback=true.
Это не запись микрофона, не прослушивание и не GPU benchmark. Физически отключённая
сеть, совместная нагрузка Gemma/STT на GPU и качество человеческой речи не проверены.

Итог исходников: 857 passed, 35 subtests passed; JS syntax,
все DOM suites, 82 локальных assets, compileall, pip check и git diff --check прошли.
Отдельного настроенного typechecker нет. Исправлен путь ._pth embedded runtime.
Финальный installer с GGUF и текущим кодом собран; hashes и результаты приватных
workers указаны ниже.

Git: запись index.lock отклонена во внешнем metadata основного checkout.
Атомарные коммиты не созданы, ACL не обходились; worktree и рабочие снимки сохранены.
Нельзя выдавать этот набор за пять принятых этапов или завершённый продукт.
Автоматическая проверка Computer Use также отказала в чтении системного диалога
ошибки Qt: csrss не разрешён. Повторных попыток/обхода не было.
Инструкции запуска, ремонта, офлайн-демо и русский ручной чек-лист:
PRODUCTIZATION_1_0.md. Дополнительные вопросы для защиты: DEFENSE_QA.md.

Финальное ревью: файловые инструменты теперь исключают собственные runtime,
config/UI/манифесты и все пользовательские данные LocalMind, даже если владелец
разрешил родительский каталог. Два новых regression tests и полный набор прошли.
Встроенный CPython повторно выполнил xenia → WAV в памяти → small CPU STT;
результат «Как сварить пельмени? Что такое РСА?», аудио не сохранено.
Актуальные машиночитаемые свидетельства и полный список непроверенного/неполного:
`evidence/productization-20261103.json`. Перенос произвольного старого браузерного
профиля/истории и другого checkout не реализован автоматически.

Финальная офлайн-сборка Inno завершилась с exit 0: `dist/LocalMind-Offline-Setup.exe`,
3058411974 байт; SHA-256 `7c4957e22a93aeb32561f1248754345a988c926471b52a193fd56e91a1286ef9`.
Все localmind/static/config исходники совпадают с payload побайтно. Runtime imports
и реальные приватные workers прошли. Установщик не является подписанным релизом;
чистая установка/удаление не проверены. Старый промежуточный online-installer
перемещён в `.test-artifacts/earlier-installer`, чтобы не выдать его за текущий.

## 2026-11-03 — STT HTTP serialization regression

Software fix and automated regression milestone: non-finite diagnostics become
null with exact paths in `diagnostics.non_finite_fields` at all STT JSON boundaries.
Worker writers are strict, text/decoding remain unchanged, corrupt audio has a
readable 422, validation arrays are readable in the UI, and download polling stops
when idle/hidden/closed. Gemma, xenia, storage and download execution are unchanged.

Verification: 883 Python tests and 35 subtests passed; 26 focused STT regressions;
all JS syntax/DOM/polling checks, 82 assets, compileall, pip check and diff whitespace
checks passed. Loopback `python start.py` smoke passed with isolated workspace data.
The missing-audio 422 body was observed: location `body.audio`, message
`Field required`; the earlier reported recording's 422 body is unavailable.

Physical microphone acceptance is OPEN. No consented human browser-audio/response
fixture was supplied, and the original non-finite field has not been reproduced.
Windows Computer Use denied Zen access; automated Chromium launch failed EPERM.
Real CPU/GPU inference and visual verification are not claimed for this change.
Details, start/demo/repair steps and remaining live gate:
`docs/STT_HTTP_REGRESSION.md`. This milestone is not full task completion.

Git commit could not be created: the sandbox denied creation of the external
worktree metadata index.lock. Source changes remain in this checkout; no push
or merge was attempted. The focused patch is saved under
`.test-artifacts/stt-http-regression.patch`.
# RC3 — 2026-11-04, этап 1: постоянное серверное хранилище

Исходная точка проверена: чистый DevCrew-worktree, HEAD `3ead34b`,
`31fad86` присутствует в ancestry; исходный RC3 и релизы не изменялись.
SQLite сохраняет полный журнал, ID, черновик и выбранный контекст отдельно от
ограниченного окна LLM. CRUD и ограниченный идемпотентный импорт защищены тем же
loopback/Host/Origin/auth барьером. Временные полномочия не восстанавливаются.
Транзакции закрываются до переноса данных; используется DELETE journal, не WAL.

Проверено: 54 целевых Python-теста истории/вложений, включая выход дочернего
процесса, восстановление и продолжение трёх бесед, откат записи и запрет
неподтверждённого удаления. Команда: RC2 `.venv/Scripts/python.exe -B -m pytest -q`
с текущим cwd; старое окружение использовано только для чтения зависимостей.
Микрофон, GPU и установленный RC3 EXE: NOT TESTED. Следующий этап: мастер и загрузки.

## RC3 — 2026-11-04, продолжение этапа истории

Сохранён WIP HEAD 0134e2e. Перед stream интерфейс подтверждает запись черновика;
сервер также сохраняет ввод до генерации/действий. Только успешная транзакция
пары сообщений поглощает совпадающий черновик. Pagehide во время stream не
ставит пустой autosave за блокировкой хода. Инициализация SQLite повторно
проверяет schema version внутри транзакции при гонке разных процессов.

Проверено: 35 Python-тестов истории, включая настоящий loopback HTTP, SQLite,
выход серверного процесса, три беседы и продолжение каждой, аварийный выход до
final, отказ диска, TTL/capacity/pinning. LLM в HTTP-тесте — фикстура, не Ollama.
14 DOM-сценариев истории проходят. Зависимости Python читаются из прежнего
LocalMind_MVP_01/.venv; это CPython 3.14, не runtime будущей сборки 3.11.
Полный набор: 1055 passed, 1 skipped, 35 subtests; два старых build-fixture
теста не создают теперь обязательный UTF-8 index.html и требуют исправления.
Реальные микрофон, GPU, Qt GUI и установщик RC3 пока НЕ ПРОВЕРЕНЫ.

## RC3 — 2026-11-04, onboarding и параллельные ресурсы

Мастер выбирает уже найденную Medium также в состоянии unverified: наличие
файлов не выдаётся за пройденную native-пробу. Установленные Silero и Gemma
показываются без повторной загрузки. Обновлены DOM-проверки под пошаговый
мастер и единое окно моделей. Добавлен постоянный regression test завершения,
пропуска/повтора тура, отказа сохранения и последующего отсутствия моделей.
Добавлена реальная межпроцессная проверка OS-lock Silero: Whisper независим;
аварийный выход владельца освобождает lock без удаления lock-файла.

Проверено: 27 Python tests ресурсов/product-state/build fixtures и DOM-навигация,
новый onboarding/tour DOM-сценарий. Это фикстуры файлов/LLM, не скачивание
пользовательских моделей и не реальные native-пробы. Git milestone-коммит
недоступен: внешняя metadata Desktop checkout запрещает создание index.lock.
Файлы сохранены в DevCrew-worktree; доступы не обходились. Сборка требует
интеграции оркестратором и чистого release-коммита.

## RC3 — 2026-11-04, интерфейс и итоговая проверка Builder

Сохранены WIP-темы с фиолетово-розовыми акцентами, боковая постоянная история,
вертикальные настройки и Qt-код. Исправлены устаревшие DOM/polling fixtures:
модели находятся в общем окне настроек, мастер пошаговый. Добавлены browser
сценарии onboarding/тура, отмены stream и двух независимых загрузок; всего
собирается 31 Playwright test. tour.js включён в обязательный check:ui.
Текст ошибки stream больше не утверждает, что неподтверждённый ответ сохранён.

Итоговые автоматические факты:
- Полный pytest: 1062 passed, 1 skipped, 35 subtests passed. Единственный skip:
  tests/test_desktop_shell.py — в тестовом interpreter отсутствует PySide6.
- npm run test:dom, npm run check:ui, npm run check:assets проходят; 86 assets.
- CPython 3.11 разобрал AST 75 production/build Python-файлов.
- HTTP/SQLite: три чата с ID/порядком/черновиками/выбранными документами/контекстом,
  полный выход сервера, восстановление и продолжение каждого; авария до final;
  закрытие stream, отмена и replay одного committed turn без дублирования.
  LLM — фикстура. Реальную Ollama-интеграцию этот тест не доказывает.
- Диагностическая копия 153 source/payload-файлов побайтно совпадает с worktree,
  validate_ui_payload проверяет UTF-8; это НЕ собранный installer payload.
- git diff --check проходит. Проведено самостоятельное review транзакций,
  stream/autosave и границ полномочий: код не добавляет shell/LLM paths/URLs,
  не меняет loopback/auth/Origin/Host/CSP и не восстанавливает grants из истории.

Открытые блокеры и непроверенное:
- Git add/commit: Permission denied на внешнем index.lock основного Desktop
  checkout. Milestone-коммиты не созданы, оркестратор в tools отсутствует;
  основной checkout/ветки/ACL не изменялись. HEAD остаётся
  0134e2e873c547877b10ce862d79dcf47b9d249c; изменения не входят в этот commit.
- py -3.11 scripts/build_windows.py --output dist/rc3: preflight отказал из-за
  грязного дерева и отсутствия стандартного Inno Setup 6/ISCC.exe. Setup.exe,
  release Source.zip, SHA256.txt и provenance не созданы. Нужна интеграция
  оркестратором в чистую release/1.0.0-rc3; clean guards не ослаблялись.
- npm run test:ui запущен с настоящим изолированным start.py, но worker не
  стартовал: spawn EPERM. Computer Use: browser access host unavailable.
  Browser visual QA, DPI, Qt/tray и установленный EXE — НЕ ПРОВЕРЕНЫ.
- Настоящий микрофон, слышимый TTS, CPU/GPU inference, физический offline demo —
  НЕ ПРОВЕРЕНЫ. Тестовый сервер остановлен; данные тестов только в workspace.

Русская передача, запуск одной командой, offline demo, troubleshooting и полный
ручной чек-лист: docs/RC3_HANDOFF.md. README/RELEASE_NOTES/MANUAL_QA актуализированы
для RC3; docs/DEFENSE_QA.md содержит 60+ вопросов и дополнение об SQLite/stream/
идемпотентности/onboarding/блокировках. Stable не публиковался.
Логи: .test-artifacts/rc3-verification/; диагностическая копия:
.test-artifacts/rc3-ui-copy-check.json. Восстановительный снимок изменений:
.test-artifacts/rc3-builder-recovery/builder-working-snapshot.zip (не релиз).

## 2026-11-05 — исправление адресного чтения и layout возможностей

База: 24e5d84adc59fcf6c5e0d3c46ed09fc3f6a0ac27. Изменение ограничено
файловым routing/planner/адаптером, CSS экрана возможностей и регрессиями.
Сохранение разрешений в API/PersonalMode работало; чтение по явному пути не
попадало в envelope и не доходило до проверки этих прав. Обе заявленные формы
теперь связываются с files.read_file (ID сохранённого корня + точный
относительный путь). Read проверяется контроллером до I/O и повторно под
удерживаемыми Windows handles; текст передаётся в document_facts для ответа,
а не в публичные action_results. Политика, SID, deny и обязательные исключения
не менялись. Не требуется дополнительно включать полный доступ.

Проверено на Windows, Python 3.14.5 из существующего окружения соседнего
проекта (его файлы/зависимости не изменялись); данные всех тестов синтетические
в .test-artifacts, пользовательская LocalMind_QA и её политика не изменялись.

- Связанные Python-тесты: 223 passed, 1 skipped, 35 subtests passed.
  Skip: тест 8.3 alias — том не предоставил короткое имя для фикстуры.
  Набор: test_explicit_file_reads, test_llm_desktop, test_file_access,
  test_personal_files, test_access_policy, test_access_policy_http,
  test_realworld_followups, test_conversations_next,
  test_speech_agent_reliability, test_agent. Полный pytest не запускался.
- Новые 26 регрессий: обе формулировки, настоящий абсолютный Windows-путь
  с пробелами, exact/schema/native/offline-fallback, сохранение и перезагрузка
  restricted-политики через HTTP, отказ вне корня, deny/отзыв/no-read,
  обязательные исключения, traversal/ADS/UNC, подмена моделью и подтверждение.
  Ollama подменена фикстурой; проверка настоящего inference не заявляется.
- node tests/access-dom.test.cjs и node tests/access-layout-dom.test.cjs: PASS.
- node tests/access-layout-browser.cjs: PASS, изолированный Chromium без
  сетевых запросов. 8 CSS viewport от 320 до 1280 px, в том числе эквиваленты
  окна 1024 px при 125%/140%; длинные пути, границы текста, высота карточек и
  нулевое горизонтальное переполнение. Скриншоты просмотрены. Первичный
  sandbox-запуск браузера дал spawn EPERM; изолированный повтор с разрешённым
  запуском процесса прошёл, системные настройки/ACL не менялись.
- Самостоятельное code/security review и git diff --check: PASS.
  Регрессия совместимости старого read_selected-контракта найдена связанными
  тестами и исправлена; итоговый набор выше повторно прошёл.

DevCrew, установщик, полный Python/DOM suite не запускались. Qt DPI,
микрофон, GPU/CPU inference и физический offline-demo в этой задаче не
проверялись. Это адресное исправление исходников, не новая проверка релиза.
Запуск сервера после подготовки зависимостей: python start.py. Offline-demo
после загрузки локальных моделей, troubleshooting и инструкции запуска:
docs/RC3_HANDOFF.md; объяснения и 60+ вопросов защиты: docs/DEFENSE_QA.md.
Если отказ сохраняется: перезапустить процесс с обновлёнными исходниками,
проверить в «Возможности» сохранённый корень и read; deny сохраняет приоритет.
Артефакты этого прогона: .test-artifacts/file-read-fix-python.txt и
.test-artifacts/access-layout/{geometry.json,width-1280.png,width-731.png,width-390.png}.

## 2026-11-04 — новая система доступа RC3, реализация

Добавлены restricted/full_user, единая SID/schema-политика с атомарным
сохранением и безопасной миграцией, preview/apply русских правил, отдельный
экран возможностей, операции приложений, журнал причин/ревизий, проверки
ассоциаций и источников retrieval. GUI-движок, LLM и голос не переписаны.
Ручной чек-лист, запуск, offline-сценарий и troubleshooting: ACCESS_POLICY.md.

Промежуточный полный прогон Windows CPython 3.11: 1164 passed, 7 skipped,
35 subtests, одна StarletteDeprecationWarning. Проверки синтаксиса JS,
DOM и 86 локальных assets проходят. После финальных уточнений проверок
политики и авторизации журнала выполняется повторный полный gate.
В текущем checkout независимый review перепроверил исправления обходов через
shared alias, retrieval, ассоциации, имя calc.exe, relocated profile и
сбой журнала; воспроизведённых открытых P0/P1 не осталось.

Реальный `.venv/Scripts/python.exe -m localmind.desktop` запущен с отдельными
данными workspace и портом 8879: Chromium отказал на named-platform-channel-pipe,
Access is denied (0x5); окно LocalMind для UI-приёмки не появилось.
Playwright со своим работающим сервером на 8878: 32 теста обнаружены,
worker не стартовал (spawn EPERM). Browser access host также unavailable.
Sandbox/ACL не ослаблялись. Оба тестовых процесса остановлены.
Реальные DPI/GUI, микрофон, GPU/CPU inference, слышимый TTS и offline demo
не подтверждены; другой диск и 8.3 aliases требуют ручного прогона.
Функция не объявляется готовой до этого прогона.

## Подготовка витрины GitHub

В отдельном worktree проверены связанные Windows и Linux истории, хеши пакетов, работа исходников и документы для защиты. Свежие результаты и ограничения перечислены в [доказательствах](DEVELOPMENT_EVIDENCE.md). Авторизация GitHub CLI отсутствует. Публикация ожидает оценки метаданных истории и подтверждения условий распространения. [Аудит](PUBLICATION_AUDIT.md)

Проверка источников для публикации уточнила условия KaTeX: текст OFL 1.1
и сведения из метаданных шрифтов включены отдельно от MIT для JS/CSS.
Исходники и упакованные зависимости оцениваются отдельно.

## Публичная копия

Собственный код лицензирован по MIT с разрешения владельца. В публичной копии
маскированы локальные пути и адрес стороннего зеркала. Пакеты Linux и Windows
остаются локальными до проверки условий распространения встроенного runtime.

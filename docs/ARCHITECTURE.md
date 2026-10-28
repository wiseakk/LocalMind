# Архитектура LocalMind 1.0

```text
Кнопка микрофона → ограниченная запись → /api/transcribe → изолированный STT
                                                  ↓ только текст
Клавиатура → редактируемое поле → явная отправка → /api/chat[/stream]
                                                  ↓
RequestStore(request_id, fingerprint, instance) → prepare_reply
                                                  ↓
     строгий parser → ровно один grant → повторная проверка → adapter
                                                  ↓
                     immutable ActionResult → status (NDJSON сразу)
                                                  ↓
                      complete_reply → tool-free Ollama → commentary
                                                  ↓
                        UI: status + текст → локальный Piper WAV
```

## Компоненты и границы доверия

- `start.py` слушает IPv4 loopback и отключает доверие proxy headers.
  `setup_windows.ps1` выполняет сетевую установку отдельно от offline startup.
- `server.py` проверяет peer, Host, Origin, fetch metadata и optional API key до
  обработки запроса. JSON/voice bodies ограничены по размеру, времени и четырём
  одновременным загрузкам. Pydantic ограничивает длины, роли истории и параметры.
  Diagnostics не возвращает токены, пути или сырые исключения.
- `agent.py` распознаёт только целую однозначную команду. Отрицание, цитата,
  смешанная просьба и лишний контекст не превращаются в инструмент. `dispatch`
  сверяет имя, точный набор аргументов и grant повторно. Модель не получает tools.
- `results.py` — `ActionResult`: success/action/resolved_target/execution_status/
  observed_state/error/mode/duration_ms/status_text. DEMO хранит наблюдаемое
  состояние симулятора; Windows launch подтверждает только создание процесса,
  HA — принятие HTTP-запроса. Автоматического закрытия нет.
- `requests.py` — один bounded store для двух chat endpoints: 128 записей,
  четыре исполнителя, TTL пять минут после завершения. Блокировка защищает
  создание ID до начала действия. Shared futures не отменяются при disconnect;
  генерация не возвращается к dispatch. Другой payload с тем же ID даёт 409.
  Browser связывает retry с server_instance и максимумом 120 секунд, включая
  wall clock после сна. Это не persistent exactly-once после crash/TTL.
- `apps.py` — native COM/реестр только для чтения. Динамические alias появляются
  после обнаружения. Разрешение привязано к SHA-256 источника/пути/exe. Проверка
  повторяется под Windows file guard перед `Popen([absolute_exe], shell=False)`.
  Любые arguments/CLI/scripts/URLs/installers отказаны. Один каталог сканируется
  single-flight с cooldown. Уникальный ID позволяет выбрать одинаковые названия.
- `voice.py` — фиксированные multilingual RU профили base/small/medium, VAD,
  CPU fallback и Piper Denis. Подготовка assets отдельная; inference offline.
  Дочерний процесс ограничивает native decode/model time до 120 секунд. Доступна
  одна STT/TTS операция, аудио до 8 МБ/30 секунд, TTS до 1200 символов. Форсируется
  контейнер аудио, чтобы загруженная playlist не открыла URL/посторонний файл.
- `static/assets/app.js` — DOM через textContent для metadata/пользовательского
  текста, staged transcript без дублирующего пузыря, streaming status и stop/mute.
  Failure TTS произносит только детерминированный статус. Success TTS начинает
  со статуса перед accepted commentary. UI не хранит секреты/историю на диск.
- `localmind-rich.js` использует локальные Marked → DOMPurify → ограниченный
  KaTeX. Сохраняет plain-text fallback, блокирует media, поддерживает три math
  delimiters и оставляет одинарный доллар текстом. CSP закрывает внешние загрузки.

## Почему разделены исполнение и генерация

Пользователь может потерять соединение после того, как лампа уже переключилась.
Повторная генерация ответа не должна включать повторное действие. Поэтому статус
хранится независимо от комментария. Ошибка Ollama оставляет исходный status, а
request_id повторно отдаёт уже вычисленный ответ в пределах сессии и TTL.
Согласованная JSON schema composer не является математическим доказательством
правдивости произвольного русского текста: исходный status всегда авторитетен.

## Проверка

Python-тесты отдельно атакуют parser/executor, каталожные разрешения, подмены,
дедупликацию/отмену и HTTP boundary. Voice-тесты используют mocks моделей плюс
реальный PyAV/child silence check. DOM-проверки исполняют UI, DOMPurify и KaTeX;
Playwright покрывает реальные zoom/keyboard/viewport, когда браузер доступен.
Реальные Ollama/CPU/Piper smoke отделены от mocks в STATUS/EXPERIMENTS. Документы
не утверждают, что Windows mic, GPU inference, HA и окна приложений проверены.

## Не реализовано

LAN pairing, публикация, постоянный wake word, cloud fallback, универсальная
активация UWP/MSIX, закрытие окон, persistent history и crash-persistent delivery.
Это требует отдельных проектов с собственными границами безопасности.

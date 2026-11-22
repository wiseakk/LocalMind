# LocalMind на CachyOS / Arch

Исторический аудит первого запуска. Для текущего состояния см.
[результаты приёмки](LINUX_PORT_STATUS.md) и [установку](LINUX_INSTALL.md).

Срез аудита — ветка `port/linux-arch`, исходная ревизия `0615b9e`. Первый этап
проверен с Python 3.14.10 и PySide6 6.12.0. Полноценная Linux-поставка требует
отдельной приёмки приложений, окон, генерации, голоса и пакета.

## Карта архитектуры и совместимости

| Слой | Текущая реализация | Linux и следующий рубеж |
|---|---|---|
| Точки входа | `localmind.desktop` создаёт QApplication, слушатель loopback, Uvicorn в потоке и DesktopWindow. `start.py` запускает только Uvicorn. | Оба входа проверены. Qt WebEngine загрузил штатный UI под Wayland. |
| UI | `desktop_shell.py` ограничивает навигацию и выдачу разрешений Qt. `static/index.html` и локальные JS/CSS обслуживает FastAPI. | Windows AppUserModelID и DWM ограждены проверкой платформы. Node нужен для JS/Playwright QA. Нативная регистрация приложения в portal ждёт установленного desktop entry. |
| API и политика | `server.py` валидирует peer/Host/Origin, запросы и подтверждения. `agent.py`, `intents.py`, `llm_planner.py` маршрутизируют запросы. `capabilities.py` определяет доступность действий. | Общие контракты сохраняются. Capability flags должны получать доступность от адаптеров. |
| Профиль | `paths.py` и `storage.py` ведут выбор корня, конфигурацию, модели, журнал и историю. `conversation_db.py` использует SQLite. | Единый корень `$XDG_DATA_HOME/LocalMind`, по умолчанию `~/.local/share/LocalMind`. Настройки остаются внутри профиля, включая `config/` и `.env`. Override `LOCALMIND_DATA_DIR` сохраняется. |
| Приложения | `apps.py`, `agent.py` используют Start Menu, COM, Win32 registry, PowerShell для discovery, Win32/packaged/Steam и системные EXE. | Нужен freedesktop-каталог с fingerprint и направленной активацией. Текущий Linux-режим не умеет безопасно запускать приложения из этого каталога. |
| Окна | `windows_state.py`, `window_tools.py` используют HWND, дескрипторы процессов, SID/session и Win32 focus/close. `desktop_tools.py` использует системные URI через `os.startfile`. | Адаптеры Wayland зависят от возможностей композитора. X11/EWMH применим только к видимым ему окнам. |
| Файлы | `file_access.py`, `file_mutations.py`, `personal_permissions.py`, `file_requests.py` поддерживают области и одноразовые подтверждения. Windows опирается на Known Folders, DriveType, reparse checks, открытые handles и ассоциации. | Базовые файловые операции имеют POSIX-ветви. Требуется дескрипторное обходное разрешение пути, отдельная проверка mount/owner и XDG user dirs. Открытие документа в приложении сейчас Windows-only. |
| Секреты | `secret_store.py` хранит HA-токен через Windows DPAPI. | Для UI подключения HA нужен Secret Service с проверкой доступности. Сам HTTP-адаптер HA независим от ОС. |
| LLM | `ollama_runtime.py` проверяет loopback, а собственный daemon стартует из Windows bundle с Job Object. `model_manager.py` и `model_catalog.py` работают по HTTP. | Для начала отдельный Ollama на loopback. Существующий процесс остаётся внешним. Проверки tags и реальной генерации на Linux впереди. |
| Речь | `static/assets/speech.js` захватывает запись из WebEngine. `voice.py`, `asr_worker.py`, `speech_worker.py` вызывают нативные движки в дочерних процессах. | Проверить Qt → PipeWire/PulseAudio → PyAV → faster-whisper, затем локальный Silero → WAV → устройство вывода. PyAV, CTranslate2 и Torch требуют отдельной проверки матрицы wheel и ABI. |
| Поставка | `scripts/build_windows.py`, Inno Setup и C# launcher в `installer/`, PowerShell и приватный `python.exe`. | Нужны Arch PKGBUILD, launcher/desktop entry и проверка установки, обновления и удаления на отдельном профиле. |

## Предлагаемые Linux-адаптеры

1. **Каталог и запуск.** Читать desktop entries из XDG data roots с учётом
   приоритета desktop ID, Hidden/NoDisplay и TryExec. Проверять тип, владельца,
   целостность записи и поддерживаемый способ активации. Существующие разрешения
   привязывать к проверенной записи и исполняемой цели. Для первого среза
   поддерживать ограниченный Exec с фиксированным argv. D-Bus-активацию и
   форматы наподобие Flatpak проверять отдельно. Запрос модели адресует только ID.
2. **Окна.** Общий контракт list/focus/close с указанием доступности. Для
   Hyprland читать структурированные данные compositor IPC, а адрес и
   идентичность заново сверять перед действием. Состояние подтверждать повторным
   чтением. Для других композиторов подключать только заявленные протоколы.
   Разрешать закрытие при доказанной идентичности и действующей политике,
   без отправки сигналов всему приложению.
3. **Файлы.** Сохранять ID областей и подтверждения. Начинать обход от
   проверенного дескриптора каталога, отклонять ссылки и специальные файлы,
   сверять идентичность и закреплять родителей на время операций. Default MIME
   handler проверять через каталог и разрешение приложения. Для перемещения
   требуется атомарное отсутствие перезаписи.
4. **Сервисы и аудио.** Проверять Ollama по API и фактическую генерацию.
   Внешний daemon не принадлежит LocalMind. Если потребуется управляемый
   daemon, привязать жизненный цикл к отдельной пользовательской service unit
   или иной проверяемой группе собственных процессов. Уведомления — через
   freedesktop D-Bus/portal. Автозапуск через XDG Autostart только по opt-in.
   Проверить физический вход и выход PipeWire отдельно от работы модели на CPU.

## Пакеты и первый запуск

- **Runtime:** `python`, `python-pip`. Для Qt в venv используйте
  `requirements-linux-desktop.txt`. `qt6-wayland` относится к системной
  сборке Qt; venv с wheel использует свой Qt. Для проверки XWayland нужен
  `xorg-xwayland`. [Arch Qt Wayland](https://archlinux.org/packages/extra/x86_64/qt6-wayland/)
- **Аудио:** `pipewire`, `pipewire-pulse`, `wireplumber`. В целевой среде
  пакеты уже присутствовали. Проверка устройств нужна в активной сессии.
  [Arch PipeWire Pulse](https://archlinux.org/packages/extra/x86_64/pipewire-pulse/)
- **LLM:** `ollama-cuda` для NVIDIA или `ollama` как CPU-вариант.
  Проверить пакет и зависимости в выбранной ветке репозиториев CachyOS
  и доступность GPU через `nvidia-smi`. [Arch Ollama CUDA](https://archlinux.org/packages/extra-testing/x86_64/ollama-cuda/)
- **Интеграции:** `glib2` для GIO, `xdg-utils`, `xdg-desktop-portal` с
  backend сессии для тестов portal, Secret Service provider для хранения HA.
  Для сборки пакета нужны `base-devel`, для JS QA — `nodejs` и `npm`.
- **STT на GPU:** отдельно сверить CTranslate2 с cuBLAS CUDA 12 и cuDNN 9.
  Начать с CPU-профиля Small. Windows-фикс PyAV сохраняется. Silero
  сначала проверить в отдельном окружении с совместимой парой Python/Torch.
  [faster-whisper](https://github.com/SYSTRAN/faster-whisper)

Из корня checkout один раз подготовить окружение. Это сетевой шаг для wheel.

```sh
python -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: -r requirements-dev.txt -r requirements-linux-desktop.txt
```

Одна команда для Desktop. Сервер входит в запуск.

```sh
QT_QPA_PLATFORM=wayland .venv/bin/python -m localmind.desktop
```

Веб-режим — `.venv/bin/python start.py`. Открыть `http://127.0.0.1:8765`.
При занятом порте закрыть предыдущую копию или выбрать свободный
`LOCALMIND_PORT`. При ошибке Qt сверить запуск API отдельно и при наличии
XWayland повторить с `QT_QPA_PLATFORM=xcb`. Если portal сообщает
`App info not found for 'localmind'`, это открытый пункт упаковки и проверки
portal. В проверенном исходном запуске загрузка UI прошла.

Следующий этап после согласования пакета — запустить Ollama на
`127.0.0.1:11434` с `OLLAMA_NO_CLOUD=1`, проверить `/api/version` и `/api/tags`,
выбрать уже установленную модель либо явно подготовить одну. Выполнить один
запрос генерации, сверить `ollama ps`, объём VRAM и диагностику приложения.
Для микрофона проверить default source и sink через `wpctl status` в сессии
Hyprland, разрешить захват для LocalMind, проверить фактический WAV и слышимость.

## Сценарий офлайн-демо

В чистом профиле заранее подготовить локальную LLM, Whisper Small и Silero
xenia через мастер. С отключённым внешним подключением оставить доступным
loopback и запустить Ollama и Desktop. Проверить демо-лампу, текстовый вопрос
про RSA, редактирование распознанной русской фразы до отправки и слышимый
ответ Silero. Для честной защиты записать результаты по каждому шагу.
На Linux сейчас подтверждены старт сервера и загрузка UI, голосовой сценарий
целиком ещё предстоит проверить. [60 вопросов с ответами для защиты](DEFENSE_QA.md)

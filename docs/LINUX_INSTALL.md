# Установка LocalMind на CachyOS и Arch

Для текущего архива `1.0.0rc3-4` см. [обновление и проверку повторного запуска](LINUX_RC3_4_RELAUNCH.md).
Результаты исправления загрузок описаны в [приёмке rc3-3](LINUX_RC3_3_DOWNLOADS.md).

## Запуск из исходников

Проверенная среда — x86_64, Python 3.14.10, Hyprland / Wayland. Qt
WebEngine поставляется Python wheel. Обновление системного Python может
потребовать пересоздания отдельного venv.

```sh
python -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: -r requirements-linux-desktop.txt -r requirements-voice.txt
.venv/bin/python -m pip install --only-binary=:all: --index-url https://download.pytorch.org/whl/cpu 'torch==2.15.0+cpu'
```

Для Whisper Medium на NVIDIA установите совместимые cuBLAS/CUDA 12 и cuDNN 9.
LocalMind подключает библиотечные каталоги этих wheel только к ASR-процессу.
Small работает на CPU.

```sh
.venv/bin/python -m pip install --only-binary=:all: nvidia-cublas-cu12 'nvidia-cudnn-cu12==9.*'
```

Для графического сеанса нужны работающие PipeWire, WirePlumber и
PulseAudio-совместимый сервер PipeWire. Для LLM используйте Arch-пакет
`ollama-cuda` на NVIDIA или `ollama` для CPU. Тестовый Ollama 0.40.16 работал с
официальной моделью Gemma 4 12B Q4_K_M. Внешний daemon отвечает на loopback, и
LocalMind сохраняет его жизненный цикл независимым от окна приложения.

Запустите Ollama в отдельном терминале, если одобренный локальный daemon
ещё не запущен. Проверка `ollama list` показывает, нужна ли загрузка.
После проверки модели, её лицензии и свободного места можно один раз выполнить
`ollama pull gemma4:12b-it-q4_K_M` или подтвердить загрузку этой карточки в мастере.
Дисковый объём проверенного тега — около 8,0 ГБ.

```sh
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 OLLAMA_NOPRUNE=1 ollama serve
```

Одна команда для Desktop после подготовки:

```sh
QT_QPA_PLATFORM=wayland .venv/bin/python -m localmind.desktop
```

Если обычный профиль ещё пуст, онбординг предложит подготовить Whisper Small
и Silero xenia. Для отсутствующего Small или Medium можно явно подтвердить
проверенное зеркало. Подготовка проверяет закреплённый SHA-256, затем выполняет
локальную пробу. После этого текст, голос и синтез работают через loopback.

На компьютере, где проходила приёмка этого checkout, уже есть отдельные
проверенные ресурсы. Их можно использовать напрямую без повторного скачивания.
В первом терминале из корня checkout:

```sh
env HOME="$PWD/.test-artifacts/linux-offline-home" OLLAMA_HOST=127.0.0.1:18766 \\
  OLLAMA_MODELS="$PWD/.test-artifacts/linux-ollama" OLLAMA_NO_CLOUD=1 OLLAMA_NOPRUNE=1 ollama serve
```

Во втором терминале одна команда запуска Desktop с этим профилем:

```sh
env LOCALMIND_DATA_DIR="$PWD/.test-artifacts/linux-profile" OLLAMA_URL=http://127.0.0.1:18766 \\
  QT_QPA_PLATFORM=wayland .venv/bin/python -m localmind.desktop
```

## Arch-пакет из checkout

Начиная с `1.0.0rc3-3` архив содержит голосовой runtime для Python 3.14 x86_64.
Установите готовый архив через `sudo pacman -U /путь/к/пакету.pkg.tar.zst`.
Для пересборки нужен `base-devel`, `python-pip` и комплект wheel с хешами
из `installer/linux/voice-wheels.lock`. Подготовьте его из корня checkout:

```sh
python -m pip download --no-deps --only-binary=:all: --require-hashes \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  --dest .test-artifacts/rc3-runtime-wheels -r installer/linux/voice-wheels.lock
makepkg -si
```

Повтор той же команды на новом checkout обновляет пакет. Если версия или
релиз совпадают, локальную пересборку запускайте через `makepkg -fsi`.
Пакет добавляет `/usr/bin/localmind`, desktop entry и иконку. В меню он
называется **LocalMind**, команда запуска — `localmind`. Рецепт и payload
проверены сборкой. Установка с системными зависимостями требует ручной
приёмки на CachyOS.

Для голоса в установленной копии откройте мастер и подготовьте модели.
Пакет использует отдельный каталог зависимостей под `/usr/lib/localmind`.
Модели сохраняются в пользовательском профиле. Вручную создавать venv для
установленной копии больше не требуется.

Обновление и удаление пакета меняют только файлы пакета.
`sudo pacman -R localmind` оставляет профиль, историю и модели, размещённые
под `$XDG_DATA_HOME/LocalMind` или `~/.local/share/LocalMind`, а также отдельное
хранилище Ollama. Для автозапуска по явному выбору можно добавить копию
desktop entry в `$XDG_CONFIG_HOME/autostart` или `~/.config/autostart`.

## Диагностика

- Сервер и Ollama раздельны. При ошибке модели проверьте `ollama --version`,
  `ollama list`, `ollama ps` и адрес в `OLLAMA_URL`. Сохранённую модель меняйте
  через «Проверить и выбрать».
- При ошибке окна укажите `QT_QPA_PLATFORM=xcb`, если в сессии доступен
  XWayland. Отдельный веб-вход из checkout — `.venv/bin/python start.py`.
- При ошибке звука проверьте `wpctl status`, доступность звукового входа
  и разрешение WebEngine. Смена устройства применяется к следующей записи.
  Если сразу после старта Silero занят прогревом, повторите через несколько секунд.
- При нехватке VRAM выберите Whisper Small / CPU. Средний профиль проверен
  на CUDA и в режиме fallback на CPU. Совместное размещение Medium и
  Gemma при других GPU-нагрузках зависит от свободной памяти.
- Для хранения токена Home Assistant нужны `secret-tool` из `libsecret`
  и доступная разблокированная коллекция Secret Service. LocalMind выводит
  ошибку при отказе хранилища. Токен передаётся через stdin.

# Доказательства разработки

| Проверка | Результат | Область |
| --- | --- | --- |
| Pytest, свежий запуск подготовки | 1745 passed, 31 skipped, 35 subtests passed | Linux, Python 3.14, изолированный профиль. CI-конфигурация использует отключённый адрес Ollama и DEMO. |
| Chromium, свежий запуск подготовки | 37 passed | Настоящий локальный UI, отдельный backend и фикстуры в сценариях. 23,5 с за прогон. |
| Проверки исходников | Синтаксис Python и импорт FastAPI/Desktop, 18 Linux-тестов, DOM и 86 локальных ассетов | Локальные аналоги задач GitHub Actions. |
| Повторный старт Qt, прежняя приёмка rc3-4 | 20/20, HTTP 200, после остановки отсутствует LISTEN | Свежие процессы с извлечённым rc3-4 под Wayland. [Протокол](LINUX_RC3_4_RELAUNCH.md) |
| Текстовый диалог, свежий запуск подготовки | LocalMind ответил на демонстрационный вопрос через `gemma4:12b-it-q4_K_M` | Chromium, FastAPI, локальный Ollama. `ollama ps` показал 100% GPU на RTX 4070. [Снимок](screenshots/chat.png) |
| Голос, прежняя интеграция | Аудиофайл «Что такое алгоритм?» → Whisper → Ollama → Silero, 17,15 с сгенерированного аудио | Зафиксировано в локальном `linux-offline-smoke.log` в сети только с loopback. Это длительность аудио, а не задержка системы. |
| Arch-пакет | В архиве 19 895 записей. Содержимое 169 файлов приложения совпало с `5ffcc3b`. Установленный экземпляр rc3-4 прошёл `pacman -Qkk localmind`, 0 изменённых файлов. | Проверка существующей установки и архива. Чистую установку в этом цикле не выполняли. |
| Windows RC3 | Контрольные суммы архива и установщика совпали с локальным манифестом. 381 файл source ZIP совпал с `0615b9e` после нормализации переводов строк. | Чтение NTFS. Windows Setup, микрофон и GPU в этом сеансе не запускались. |

Исторические результаты сверены с локальными журналами `rc3-4-release-pytest.log`, `linux-release-playwright.log`, `rc3-4-relaunch-final.log` и `linux-offline-smoke.log`. Журналы остаются в локальном `.test-artifacts`. Условия прежних GPU-замеров перечислены в [приёмке Linux](LINUX_ALPHA_ACCEPTANCE.md). Время inference одной фразы не даёт оценки точности распознавания.

## Воспроизведение

В подготовленном окружении из корня checkout:

```sh
python -m pip install -r requirements-dev.txt
DEMO_MODE=true OLLAMA_URL=http://127.0.0.1:9 python -m pytest -q
python -m compileall -q localmind scripts start.py
python -m pytest -q tests/test_linux_paths.py tests/test_linux_integration.py tests/test_desktop_listener.py
npm ci
npm run check:ui
npm run check:assets
npm run test:dom
```

Для Chromium подготовьте браузер через `npx playwright install chromium`. В отдельном терминале запустите приложение с временным профилем и тестовым портом:

```sh
LOCALMIND_PORT=58626 LOCALMIND_DATA_DIR="$(mktemp -d)" OLLAMA_URL=http://127.0.0.1:9 python start.py
```

Затем выполните `LOCALMIND_TEST_URL=http://127.0.0.1:58626 npm run test:ui`. Для реальных моделей и аудио используйте отдельную [локальную приёмку](LINUX_MANUAL_QA.md). Проверки GitHub Actions доступны на [вкладке Actions](https://github.com/wiseakk/LocalMind/actions).

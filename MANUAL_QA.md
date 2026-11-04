# Короткая ручная приёмка 1.0.0-rc2

Фиксировать Windows, hardware, commit из build-provenance.json, SHA256 установщика,
дату и наблюдение. Повторить через исходники и установленный EXE.

| Проверка | Реальная приёмка RC2 |
|---|---|
| Чистая Windows без Python/Node: установка и два запуска | NOT TESTED |
| Обновление RC1: история, профиль, каталог данных и настройки сохранены | NOT TESTED |
| Единая иконка setup/EXE/ярлыка/заголовка/taskbar/tray; Alt+Tab без дублей | NOT TESTED |
| Resize, snap, maximize/restore, minimize, клавиатура и Alt+F4 | NOT TESTED |
| DPI 100/125/140/150/200%, переход между мониторами | NOT TESTED |
| Перезапуск normal/maximized, отключённый монитор, испорченные настройки окна | NOT TESTED: unit-тесты отдельно |
| Светлая/тёмная тема: рестарт, диалоги, поля, код/формулы и native frame | NOT TESTED: DOM-тесты отдельно |
| Reduced motion; отсутствие URL/menu/error pages; load/renderer recovery | NOT TESTED: policy/method tests отдельно |
| Трей «Открыть»/«Выход», крестик во время записи/inference/подготовки: порт и workers освобождены | NOT TESTED |
| Вложение drag/drop, редактируемый transcript, чат, модель, DEMO-лампа | NOT TESTED |
| Старые base/balanced настройки: small; base файлы сохранены; нет small → явная подготовка | NOT TESTED: моки отдельно |
| small/medium на одной разрешённой записи: CPU/GPU; нет/сбой CUDA → тот же medium CPU/int8 | NOT TESTED |
| «Как сварить пельмени?» — начало дословно; «Не открывай калькулятор», «Не закрывай блокнот» — отрицания дословно | NOT TESTED |
| «Расскажи как открыть калькулятор», оба отрицания: действие не выполняется | NOT TESTED: текстовые регрессии отдельно |
| Холодный запуск и 10 голосовых запросов, actual worker/device/RSS/VRAM | NOT TESTED |
| Удаление/повторная установка сохраняют данные | NOT TESTED |
| Offline demo после подготовки STT/TTS/LLM с физически отключённой сетью | NOT TESTED |

Desktop после установки зависимостей: `python -m localmind.desktop` (активировать
проектный venv). Установленное приложение: ярлык LocalMind или
`& "$env:LOCALAPPDATA\Programs\LocalMind\LocalMind.exe"`.
`python start.py` запускает только сервер и не проверяет native оболочку.

В этой сессии запуск desktop предпринят, но Chromium завершился до визуальной
приёмки: `named-platform-channel-pipe: Access is denied (0x5)`. Playwright не
запустил worker (`EPERM`), browser host недоступен. Защита Chromium не отключалась.

Перед offline demo явно подготовить small/medium, Silero xenia и локальную LLM
в настройках. Затем отключить сеть: вопрос про пельмени/RSA, разрешённый запуск
Блокнота, оба отрицания, DEMO-лампа. Для измерений — `scripts/eval_stt.py --help`,
один recording manifest и `--consent`. STT_TEST_SET.csv — сценарии, не аудиокорпус.
Без отдельного согласия записи не сохранять.

Troubleshooting:

- Нет small после RC1: «Настройки → Подготовить голос». Base файлы сохраняются,
  но не используются. Inference не загружает модели автоматически.
- 422: проверить размер/длительность/формат, повторить запись; текст править вручную.
- 503: проверить ресурсы и actual device. Компоненты EXE восстанавливать
  установщиком. CUDA не обязательна и автоматически не устанавливается.
- Окно за экраном: после выхода переименовать только config/desktop-window.json
  в каталоге данных и запустить снова. Webprofile/модели/историю не удалять.
- Recovery: «Повторить»; при повторном сбое восстановить установку.
  Не обходить Chromium sandbox ради демонстрации.
- Порт занят: штатно закрыть предыдущий LocalMind. Не завершать все Python/Ollama.
- Прервана подготовка: повторить из загрузок после завершения операции;
  общие small файлы защищены от параллельной подготовки.

Объяснения: docs/DEFENSE_QA.md (30+ вопросов), docs/HOW_IT_WORKS.md,
docs/RC2_DESKTOP_DECISION.md.

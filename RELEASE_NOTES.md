# LocalMind 1.0.0-rc1 — кандидат, не Stable

Интеграция от Alpha `66f6c101b91596936721313840684501c75dad1a`, 3 ноября 2026.
Изменения двух исходных worktree сохранены отдельно, включая untracked source.
Коммит интеграции и бинарник пока отсутствуют: запись Git index запрещена sandbox,
Inno Setup 6 отсутствует. Не распространять этот checkout как готовый релиз.

- STT: расширенная диагностика и строгий JSON на границах worker/legacy/HTTP;
  NaN и ±Infinity становятся `null` с путями полей, текст распознавания не заменяется.
  Добавлены регрессии warm worker и понятных ошибок 422/503.
- LLM: default новой установки `gemma4:12b`, прежний выбор сохраняется.
  Thinking, temperature, context, response tokens и keep-alive сохраняются по модели
  и используются фактически. Thought-channel и think-теги исключены из ответа.
  `ministral-3:8b` — необязательный кандидат, загрузка не запускается автоматически.
- Windows: запуск, обнаружение окна и foreground activation учитываются отдельно.
  Отказ активации сохраняет успешный результат запуска. Закрытие адресное;
  небезопасное закрытие Блокнота получает честный отказ.
- UI: защита от повторных сообщений, очистка контекста новой беседы,
  прекращение polling скрытых/закрытых диалогов и завершённых загрузок.
  Дизайн сохранён; технические сведения находятся в раскрываемой диагностике.
- Данные: постоянный `%LOCALAPPDATA%\LocalMind` и явный override;
  перенос после просмотра плана и согласия, проверка копий без удаления источника.
  Старый журнал загрузок используется по прежнему пути без скрытого переноса.
  Общие модели Ollama не удаляются и автоматически не выгружаются.
- Сборка: versioned RC-имена, clean release branch, исходники только из Git,
  Source.zip, SHA256, commit, версии зависимостей и хеши payload в provenance.
  Resume проверяет исходники, параметры, runtime и отсутствие старых/лишних файлов.

Реальные наблюдения: gemma4 ответила по-русски на RSA в пустом текстовом диалоге
за 5557 мс с фиксированными параметрами; Python создал процесс Блокнота и нашёл
его окна, Windows отказала в активации. Это отдельные smoke-проверки, не голосовая
приёмка. См. `docs/evidence/release-real-smoke.json` и `MANUAL_QA.md`.

Запуск подготовленного source-окружения: `python start.py`.
После установки: `& "$env:LOCALAPPDATA\Programs\LocalMind\LocalMind.exe"`.
Установщик ещё НЕ СОБРАН. Продолжение: `docs/RELEASE_RECOVERY.md`.

Обычный комплект содержит runtime и интерфейс, но модели требуют явной подготовки
через настройки. Сеть при скачивании моделей не является offline inference.
Комплект `--offline-assets` содержит проверенные STT/TTS assets выбранных профилей;
локальная LLM требуется отдельно либо явно добавляется через `--offline-gguf`.
Лёгкий GGUF не заменяет default gemma4 и обозначается резервным.

Проверенные интерфейсы: [Ollama chat](https://docs.ollama.com/api/chat),
[SetForegroundWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow),
[CPython embedded](https://docs.python.org/3.11/using/windows.html#the-embeddable-package),
[Inno filename](https://jrsoftware.org/ishelp/topic_setup_outputbasefilename.htm).
Эти документы не подтверждают испытания установщика.

# LocalMind — передача в DevCrew

Этот ZIP — **проект LocalMind с последними исправлениями 0.1.2 и новым ТЗ**, а НЕ готовая версия 1.0. В нём нет .venv, .env, Ollama model, реальных аудиозаписей или приватных ключей. У пользователя голос уже работал в исходной версии; качество русского STT и обнаружение произвольных приложений всё ещё требуют разработки.

## Три действия

1. Распаковать содержимое ZIP в отдельную папку, например `C:\Users\ExampleUser\Desktop\LocalMind-DevCrew`. Не складывать поверх существующего `.venv`/старого проекта.
2. В PowerShell из папки проекта выполнить `powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_devcrew.ps1` (создаст локальный Git-репозиторий с clean commit; Git должен быть установлен). Если Git у пользователя уже настроен и используется, можно сделать init/commit вручную.
3. Запустить `DevCrew.cmd` или открыть DevCrew Studio → выбрать этот репозиторий → вставить содержимое `DEV_CREW_START.txt` → Start crew. Дальнейшая инструкция лежит в `docs/DEVCREW_MASTER_MISSION.md`; правила разработки в `AGENTS.md`.

## Важная честность

ChatGPT не имеет прямого доступа к локальной программе DevCrew на ПК пользователя и не может из этого чата запустить её или обеспечивать фоновую работу 48 часов. Это локальный *handoff*. Не давайте одним агентам обещаний о 2 днях: важны этапы, чекпоинты в Git и реальные проверки. DevCrew Studio/терминал должны работать на пользовательском ПК; в DevCrew могут быть собственные лимиты или вопросы подтверждения.

## Старый базовый запуск

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-voice.txt
Copy-Item .env.example .env
ollama pull qwen3:4b
.\.venv\Scripts\python.exe start.py
```

Открыть http://127.0.0.1:8765 (на самом ПК). При проверке Windows STT известен `PyAV 19` regression, поэтому в requirements-voice.txt закреплён av==18.1.0. Не пересобирать пайплайн вслепую.

# RC3: текущая передача

Продолжение WIP и актуальные команды/блокеры: [RC3_HANDOFF](RC3_HANDOFF.md).
Цель: чистая release/1.0.0-rc3; `py -3.11 scripts/build_windows.py --output dist/rc3`.
Не запускать finalize_release.ps1 для RC3. Текущий sandbox запрещает внешний
Git index.lock; Inno Setup по стандартному пути не найден. Нельзя выдавать
старые RC2 artifacts или диагностический снимок за RC3 release.

## Архив предыдущей процедуры

# RC2: текущая сборка и provenance

Ветка release/1.0.0-rc2 уже создана от a229fff в изолированном checkout rc2.
Не запускать finalize_release.ps1 для RC2: ниже сохранена только архивная
процедура RC1. Alpha/RC1 не изменяются. В корне RC2 после clean commit:

```powershell
py -3.11 scripts/build_windows.py --output dist/rc2
```

Нужны x64 Python3.11, .NET csc, Inno Setup6. Если Inno размещён переносимо внутри
проекта, добавить `--iscc .test-artifacts/tools/inno6/ISCC.exe`.
В текущей сессии Inno6.7.4 получен с официального GitHub release, подпись
Pyrsys B.V. проверена как Valid; portable mode не меняет системную установку.
Документация: https://jrsoftware.org/ishelp/topic_technotes.htm .

Builder отказывает до downloads при грязном дереве/чужой ветке/неверном ancestry.
При сбое payload сохраняется. Resume допускается только с тем же commit,
параметрами, архивом runtime и всеми хешами; иначе новый каталог output.
Готовые Setup/Source/SHA256 не перезаписываются. Нельзя заменять payload вручную
или обходить проверку происхождения. Models подготавливаются явно и не включены
в обычный установщик. После загрузки inference локальный.

## Архив восстановления RC1 — не выполнять для RC2

# Фиксация и сборка кандидата после ограниченной сессии

Сейчас HEAD по-прежнему `66f6c101b91596936721313840684501c75dad1a`, тег Alpha
`localmind-v1.0-alpha-20261103` сохранён. Release-ветка и коммиты НЕ созданы:
Git получил Permission denied при создании index.lock в metadata основного checkout
`C:/Users/ExampleUser/Desktop/LocalMind_MVP_01/.git/worktrees/...`, вне разрешённого workspace.
Запрет не обходился, ACL не менялись. Inno Setup 6 на машине не найден.

Два независимых снимка сохранены в `build/recovery/`, источники не изменены:

| Файл | Изменённых/untracked source файлов | SHA256 |
|---|---:|---|
| worktree-1.zip | 50 | 16ed1e663732c3c2010c87b0f84d082aea434a529f0de6f58a44eeea137945f0 |
| worktree-2.zip | 16 | 61a5a904fa00e2418bc680285ef939e4e629c64840f99aa91b9695490b91e74d |

В каждом ZIP: binary patch относительно Alpha, `files/` с точными байтами и
manifest с базовым commit, исходным worktree и хешами. Содержимое перечитано и
проверено после записи. Игнорируемые `.env`, аудио, пользовательские модели,
история и окружения в снимки не включались. Кандидат интегрирован в текущие файлы
трёхсторонним слиянием с ручным разрешением конфликтов и сохранением обоих наборов
тестов. Это пока не Git merge и не зафиксированный релиз.

В обычном PowerShell вне sandbox выполнить из текущего checkout:

```powershell
Set-Location -LiteralPath 'C:\Users\ExampleUser\.codex\worktrees\devcrew-LocalMind_MVP_01-20261103-204712-79574389'
Get-FileHash -Algorithm SHA256 -LiteralPath .\build\recovery\worktree-1.zip, .\build\recovery\worktree-2.zip
Get-Content -LiteralPath .\scripts\finalize_release.ps1
& .\scripts\finalize_release.ps1
```

Скрипт проверяет отсутствие чужих staged-изменений, исходный HEAD, перечни и хеши
файлов обоих worktree. Создаёт две отдельные backup-ветки и snapshot-коммиты,
сохраняя старые ветки; затем `release/1.0.0-rc1` от Alpha и интеграционный коммит
с уже проверенным разрешением конфликтов. Staging ограничен явными списками.
Исходные worktree, теги и ZIP не удаляются, push не выполняется. При остановке
проверить показанную причину; не запускать повторно вслепую и не удалять index.lock.
Имена уже созданных веток не перезаписывать. Если PowerShell запрещает выполнение
скриптов, просмотреть и вставить его команды в интерактивную сессию без изменения
системной execution policy. Git identity должна быть настроена владельцем.

После фиксации повторить gates в подготовленном окружении:

```powershell
git diff --check
python -m pytest -q -p no:cacheprovider
npm ci
npm run check:ui
npm run test:dom
npm run check:assets
npm run test:ui
```

В этой сессии Python-тесты выполнялись существующим interpreter
`C:/Users/ExampleUser/Desktop/LocalMind_MVP_01/.venv/Scripts/python.exe` (Python 3.14),
в текущем cwd, с данными только внутри `.test-artifacts`. Системный `python`
здесь 3.11.9 без pytest; новый `.venv` не подготовлен. Не изменять чужое окружение:
для повторной проверки подготовить собственное по `requirements-dev.txt`.
Это отличие тестовой среды от приватного 3.11 runtime надо проверить сборкой.
Playwright в sandbox не запустил worker (`spawn EPERM`); браузерный gate пока закрыт.

После успешных автоматических проверок можно создать отдельный RC-тег
(Stable-тег до ручной приёмки запрещён):

```powershell
git tag -a localmind-v1.0.0-rc1 -m 'LocalMind 1.0.0-rc1, manual Windows release gates pending'
git rev-parse HEAD
git status --short
```

Сборочная машина требует x64 CPython 3.11 с pip, .NET Framework csc и Inno Setup 6
из официального источника. Сборка скачивает embedded CPython, wheels и подписанный
OllamaSetup; это сетевой этап подготовки, не работа офлайн. Скрипт не устанавливает
драйверы/системные компоненты и не развёртывает приложение. Один обычный комплект:

```powershell
py -3.11 scripts/build_windows.py --output dist/rc1-online
```

Ожидаемые результаты после реального успешного компилятора:
`dist/rc1-online/LocalMind-1.0.0-rc1-Setup.exe`,
`LocalMind-1.0.0-rc1-Source.zip`, `SHA256.txt`, `build-provenance.json`,
`RELEASE_NOTES.md`, `KNOWN_ISSUES.md`, `MANUAL_QA.md`.
Пока этих бинарных артефактов нет. Нельзя переименовывать RC в Stable.

Для отдельного комплекта с заранее проверенными голосовыми assets (указать
реальный каталог с `whisper/small/...` и `silero/...`, не запускать placeholder):

```powershell
py -3.11 scripts/build_windows.py --output dist/rc1-voice --offline-assets 'D:\ReviewedLocalMindModels' --asr-profiles balanced
```

Он получает имя `LocalMind-1.0.0-rc1-Offline-Setup.exe`, но без установленной локальной
LLM полный офлайн не обеспечен. Для явно согласованного GGUF дополнительно
`--offline-gguf` с реальным файлом, `--offline-license` и `--offline-model-name`;
его роль резервная. Основной gemma4 не загружается автоматически вместе с Ministral.

`--resume` допускается только с теми же исходниками, опциями и полностью завершённым
неизменённым runtime. Старые, посторонние, private и незапрошенные offline-файлы
отклоняются; существующие артефакты не перезаписываются. После сбоя pip использовать
новый `--output`, сохраняя старую папку для диагностики.

Затем выполнить `MANUAL_QA.md` на чистой Windows без Python/Node, сверить SHA256,
commit/tag в provenance с `git rev-parse HEAD`. Установка, запуск, микрофон, GPU,
рестарт и удаление не заменяются unit-тестами. Выпуск Stable остаётся отдельным
решением после фактического прохождения всех gates.

# Ограничения 1.0.0-rc3

- Новая сборка RC3 заблокирована: Git index.lock недоступен, стандартный путь Inno Setup отсутствует. Точные факты и команды: docs/RC3_HANDOFF.md.
- Изменения Builder сохранены в worktree, milestone-коммиты пока не созданы.

- Реальный микрофон, начало русской фразы, отрицания ASR, CPU/GPU inference,
  десять голосовых запросов: NOT TESTED. Разрешённого аудиокорпуса нет.
- GUI launch предпринят, Chromium IPC pipe завершился Access denied (0x5).
  DPI, Alt+Tab, tray, drag/drop, real lifecycle: NOT TESTED. Sandbox не обходился.
- Playwright worker не стартует (spawn EPERM), browser host недоступен.
  DOM/статические/policy-тесты не являются browser visual QA.
- Чистая установка/обновление RC1, EXE, удаление с сохранностью данных,
  физически offline demo: NOT TESTED. Не называть RC2 Stable.
- Small требует около 486 MB, medium около 1.53 GB плюс runtime. Medium CPU
  может быть медленным; преимущество качества на русском не измерено.
- Manifest v2 требует повторного подтверждения готовности. Подготовка хеширует
  корректные существующие файлы повторно, base остаётся на диске.
- Без подготовленных STT/TTS/LLM первый offline запуск не даёт голосовой сценарий.
  Inference не устанавливает модели, CUDA или компоненты автоматически.
- Native тёмный заголовок зависит от Windows DWM; иначе остаётся системная рамка.
- При выходе текущий network read Ollama может ждать прежний timeout (до30 с).
  Запрос отменяется до downstream действий; чужой Ollama не завершается.
- Качество TTS, real Home Assistant и сравнение LLM не переоценивались в RC2.

Запуск, troubleshooting и ручные шаги: MANUAL_QA.md. Фактический результат
сборки и проверок: docs/STATUS.md и итоговый отчёт.

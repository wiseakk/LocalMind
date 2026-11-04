# LocalMind 1.0.0-rc3 — продолжение WIP

Сохранены SQLite, onboarding, параллельные загрузки и UI из 0134e2e.
Перед stream сохраняется ввод; авария до final оставляет черновик, а успешный
commit атомарно сохраняет пару сообщений и поглощает совпадающий ввод.
Pagehide не перезаписывает незавершённый ход пустым autosave. Схема SQLite
инициализируется безопасно при конкурирующих процессах. Найденная Medium
выбирается без скачивания отсутствующей Small, но явно требует native-пробы.

Обновлены проверки настоящего HTTP/SQLite после полного перезапуска, аварии,
межпроцессной блокировки ресурсов, мастера и мини-тура. Две темы, история сбоку,
вертикальные настройки, Qt, иконка и трей сохранены из WIP.

Новый commit и EXE не созданы: Git metadata вне writable root, Inno Setup не найден
по стандартному пути. Playwright worker получил spawn EPERM, browser host недоступен.
Аппаратные и GUI gates открыты. Это не Stable. Подробности: docs/RC3_HANDOFF.md.

## Архив RC2

# LocalMind 1.0.0-rc2

Основа — RC1 a229ffff4ab5dafd607c755e4f74090d6a965ece, отдельная ветка
release/1.0.0-rc2. RC1 и Alpha не изменены. Из-за read-only Git metadata
предоставленного worktree создан изолированный checkout rc2/ внутри него;
объекты истории скопированы без изменения оригинала. Builder проверяет ancestry.

- Native рамка Windows, единая иконка и tray, сохранение normal/maximized,
  восстановление окна после отключения монитора.
- Светлая/тёмная тема, reduced motion, native recovery вместо Chromium errors.
  Старые webprofile и пользовательские настройки сохранены.
- Два STT режима: small CPU/int8; medium CUDA/float16 с fallback на тот же
  medium CPU/int8. Balanced остаётся совместимым идентификатором small.
- Base исключён из каталога/загрузок/CLI/упаковки/fallback. Старый
  WHISPER_MODEL=base выбирает small; base файлы не удаляются. Small готовится
  явно; общие файлы защищены process lock и единой проверкой готовности.
- Release provenance сохраняет source/payload identity, clean/resume checks,
  ветку RC2, ancestry RC1 и хеши. Полной миграции UI или сервера нет.
- Выход закрывает owned ASR/TTS и setup probes, отменяет запросы чата,
  запрещает поздний respawn. Сетевой read текущего Ollama ограничен прежним
  timeout (до30 с); чужой daemon не останавливается.

QML отложен до отдельного решения 1.1: docs/RC2_DESKTOP_DECISION.md.
Реальные микрофон, CPU/GPU accuracy, Windows GUI/DPI, установленный EXE и
offline demo — NOT TESTED. Это release candidate, не Stable. Автоматические
факты — docs/STATUS.md; ручной протокол — MANUAL_QA.md.

Обычный установщик не содержит моделей; их подготовка требует сети.
После подготовки STT/TTS/LLM inference выполняется локально.

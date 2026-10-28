# LocalMind Next: локальная потоковая речь

Piper остаётся рабочим CPU baseline. Приложение сохраняет редактируемую STT-
расшифровку. Синтез получает только публичные текстовые дельты, а подтверждения
действий — проверенные результаты адаптеров. При наличии законченной фразы
синтез начинается до события final. Если модель выдаёт одну короткую фразу
целиком, раннее начало технически невозможно; это не объявляется стримингом.

`static/assets/speech.js` отделяет сегментацию, синтез и воспроизведение. Очередь
содержит максимум 12 текстовых фрагментов по примерно 240 символов, два готовых
WAV и один воспроизводимый WAV. Один синтез выполняется одновременно. Пауза
останавливает проигрыватель и продвижение очередей; продолжение сохраняет
порядок. Mute, остановка, новый запрос и начало записи отменяют fetch, удаляют
очереди и URL, меняют поколение проигрывателя. Опоздавший ответ старого поколения
не воспроизводится. Повтор NDJSON с прежним sequence не повторяет речь.

У каждого поколения 32-символьный случайный токен. `/api/tts/cancel` отзывает
точный токен, включая запоздалые запросы, которые ещё не были допущены. Сервер
хранит до 256 отзывов 10 минут. При переполнении новые поколения временно
отклоняются: недавняя отмена не забывается ради освобождения места. Отмена
останавливает только принадлежащий LocalMind TTS worker этого поколения.

Синтез вынесен в `localmind.tts_worker`: процесс сохраняет модель и выполняет
пробный прогрев. Supervisor использует ограниченные кадры pipe, одно активное
обращение, общий таймаут загрузки и синтеза 120 секунд. WAV ограничен 12 MiB,
двумя минутами, mono PCM16; это проверяется повторно основным процессом. После
ошибки worker освобождается и может быть создан заново. Если ОС не позволяет
завершить child, handle сохраняется и замена не запускается. Никакого завершения
посторонних процессов. STT сохраняет прежнюю отдельную ограниченную изоляцию.
Нативная память пока не ограничена Windows Job Object: байтовые, временные,
очередные и thread-лимиты не являются жёстким OS commit-limit.

Словарь произношения хранится в `speech_text.py`: Python, C#, C++, RSA, Obsidian,
Steam, World of Warcraft и др. Markdown очищается независимо от отображаемого
текста, URL заменяются словом «ссылка», код не читается, математические символы
произносятся без вычисления выражений. Числа читаются по цифрам: безопасно для
длинных номеров, но не заменяет полноценную русскую морфологию числительных.
Неизвестные английские слова сохраняются. Это явно ограниченная эвристика, а не
гарантия идеальной интонации или произношения каждого технического термина.

## Проверенные upstream identities (28 октября 2026)

- [Piper Python API](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md):
  `PiperVoice.load(..., use_cuda=False)`, затем `synthesize_wav`; движок GPL-3.0,
  исходный датасет Denis CC0 (см. VOICE.md). Существующая Python3.14 среда работает.
- [Silero model registry](https://github.com/snakers4/silero-models/blob/master/models.yml)
  действительно объявляет `v5_6_ru.pt`. Release tag v5.6 описывает также SAPI5,
  но это не повод незаметно подменять модель на v5_5_ru из старого README.
  Adapter `silero-v5_6-ru` загружает локальный torch.package, speaker xenia,
  24 kHz, CPU, четыре потока. Standalone upstream требует PyTorch1.12+.
  [Лицензия репозитория](https://github.com/snakers4/silero-models/blob/master/LICENSE)
  CC-BY-NC-SA-4.0; MIT для других CIS моделей не приписывается русской модели.
- [Chatterbox source](https://github.com/resemble-ai/chatterbox/blob/5de7a54aa4e5e2baadb0182dde554908b48b85c2/src/chatterbox/mtl_tts.py)
  содержит `t3_mtl23ls_v3.safetensors`; default upstream — v2, поэтому adapter
  `chatterbox-v3-ru` явно передаёт `t3_model='v3'`, `language_id='ru'` и вызывает
  `from_local`. Код и модель MIT; встроенный watermark сохраняется.
  [pyproject](https://github.com/resemble-ai/chatterbox/blob/5de7a54aa4e5e2baadb0182dde554908b48b85c2/pyproject.toml)
  версии0.1.7 требует Python>=3.10, torch/torchaudio2.6 для Python<3.14 и>=2.9
  для Python3.14, transformers5.2.0, diffusers0.29.0 и дополнительные зависимости.
  Chatterbox сначала использует CUDA, если она доступна, иначе CPU; успешная
  загрузка не является доказательством совместной работы с LLM в12GB VRAM.

В inference нет from_pretrained, torch.hub.load, скачивания и облачного fallback.
Подготовка кандидатов отдельная, в `.voice-envs/silero` и `.voice-envs/chatterbox`.
Имена интерпретаторов и пути моделей фиксированы сервером; HTTP не принимает
путь, URL, команду или executable. Чужие модели/архивы не следует подменять:
Silero torch.package исполняет код доверенного автора модели при загрузке.

## Явная подготовка кандидатов

Рекомендуемая отдельная среда Python3.11 (должна быть установлена владельцем).
Эти команды не меняют `.venv` приложения; сеть используется только здесь:

```powershell
py -3.11 -m venv .voice-envs/silero
.\.voice-envs\silero\Scripts\python.exe -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
.\.voice-envs\silero\Scripts\python.exe -m pip install -r requirements-tts-silero.txt
.\.voice-envs\silero\Scripts\python.exe scripts/setup_voice_assets.py silero

py -3.11 -m venv .voice-envs/chatterbox
.\.voice-envs\chatterbox\Scripts\python.exe -m pip install -r requirements-tts-chatterbox.txt
.\.voice-envs\chatterbox\Scripts\python.exe scripts/setup_voice_assets.py chatterbox
```

Chatterbox package source закреплён commit5de7a54aa4e5e2baadb0182dde554908b48b85c2;
model snapshot закреплён5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18. Его upstream
ссылается на Perth master: для воспроизводимого распространения дополнительно
фиксируйте зависимости через pip freeze; на проверенную дату Perth commit был
ff1c8ac55a976971245cdd53c18d6131ca00d993. Локальный download-manifest.json
содержит фактические SHA256 скачанных assets; это учёт содержимого, а не
независимая криптографическая аттестация поставщика. Silero URL upstream mutable.
Загрузка модели доверенного поставщика отделена от запуска и не выдаётся за
полностью герметичный supply-chain lock.

После подготовки выберите голос в настройках. Если зависимостей или assets нет,
сервер возвращает понятную ошибку, сохраняя текстовый ответ и базовый голос.

## Фактическая проверка в текущем checkout

CPU Piper1.8.0/Denis на Python3.14.5: настоящий supervisor создал WAV без облака.
Первый запрос (с загрузкой и пробным прогревом)3.413s,4.365s аудио; следующий
запрос0.059s,2.717s аудио. Тексты различались: это smoke evidence, не сравнимые
p50/p95 и не доказательство естественности. Измерения одинакового материала
должны храниться отдельно у benchmark runner.

Установлен только Python3.14. Попытка provision `.voice-envs/silero` прервалась
на ensurepip: WinError5 у временного каталога с Python3.14 mode0700. Попытка
с TMP/TEMP внутри workspace дала ту же ошибку. ACL и системная конфигурация
не менялись. Поэтому Silero/Chatterbox реальные synthesis/listening/12GB
coexistence здесь пока НЕ ПРОВЕРЕНЫ; adapters и missing-assets поведение готовы.

Python-тесты проверяют normalization, reuse, timeout cleanup, привязку отмены,
запоздалый допуск, предел tombstones и malformed protocol. DOM-тесты удерживают
final, наблюдают начало синтеза/проигрывания раньше него, проверяют pause/order,
повтор sequence и late response после interruption. Browser suite содержит
такой же сценарий с подменённым Audio; даже успешный запуск этого теста не
доказывает фактический звук устройства.

`window.localmindVoiceMetrics` содержит относительные first_synthesis_ms и
first_playback_ms текущего поколения. Первое — готовый WAV, второе — разрешённый
браузером Audio.play; это не акустически измеренный first-audible latency.
Прослушивание носителем русского, microphone/STT corpus и совместная нагрузка
LLM/GPU необходимы для заявления о качестве голоса. Пользовательские записи
не создавались и не сохранялись.

Дополнительный реальный CPU Piper smoke: после разогрева начат длинный синтез
в отдельном потоке и отозвано его точное поколение. Worker завершился, поток
вернул503 за0.004s после отмены, а новое поколение создало корректный RIFF WAV.
Это проверка прекращения server synthesis; звук устройства не измерялся.

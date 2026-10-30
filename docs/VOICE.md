# Локальный голос

Все запросы распознавания и синтеза выполняются на этом компьютере. Загрузка
моделей — отдельная явная операция с сетью. Обычный запуск и inference ничего
не скачивают. Браузерные speechSynthesis-голоса не используются: их локальность
не гарантирована. Запись начинается только кнопкой микрофона, максимум 30 секунд.
Текст после распознавания остаётся редактируемым черновиком до отправки.

Установка из корня проекта (интернет нужен на этом этапе):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-voice.txt
.\.venv\Scripts\python.exe -m localmind.voice setup-stt --profile balanced
py -3.11 -m venv .voice-envs/silero
.\.voice-envs\silero\Scripts\python.exe -m pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
.\.voice-envs\silero\Scripts\python.exe -m pip install -r requirements-tts-silero.txt
.\.voice-envs\silero\Scripts\python.exe scripts/setup_voice_assets.py silero
.\.venv\Scripts\python.exe -m localmind.voice status
```

Можно отдельно загрузить `--profile cpu-fast` или `--profile gpu-quality`.
Профили: base/int8/CPU для скорости; small/int8/CPU для баланса; medium/float16/CUDA
для качества. Все модели многоязычные, язык inference — русский, VAD включён.
Имена Codex, Obsidian, Discord и Visual Studio Code даны как подсказка словаря,
а не как исправление фактически распознанного текста. Обещаний точности нет.

GPU необязателен. При ошибке инициализации или inference CUDA профиль medium
повторяется на CPU/int8, и ответ явно содержит `fallback: true`. Это может быть
медленно: под Ollama и STT одна видеопамять. Операция целиком ограничена 120 с,
после чего процесс завершается. На этом checkout реальная GPU-проверка ещё
не выполнена. Установка CUDA-библиотек не меняется приложением автоматически.

Запись ограничена 8 МБ, декодирование — 15 сек внутреннего времени и 30 сек
декодированного моно-сигнала, модель и native decoder изолированы процессом с
жёстким таймаутом 120 сек. Одновременно выполняется одна STT операция; TTS имеет отдельный ограниченный worker;
параллельная получает 429. Временные файлы удаляются и после ошибок/таймаутов.
Аудио, текст и native-ошибки не пишутся в логи. STT модель загружается в дочерний процесс на каждый запрос, чтобы можно было прекратить зависший native inference. TTS сохраняет прогретую модель в отдельном supervised worker; его поведение, отмена и кандидаты описаны в [NEXT_VOICE.md](NEXT_VOICE.md).

Это ограничение времени и длительности сигнала, а не жёсткий лимит native RAM:
FFmpeg может выделять память до возврата кадра Python. В текущей версии нет
OS commit-limit. PyAV `buffer_size` ограничивает только Python I/O для file-like
objects, а не память декодера. Дальнейшее усиление — отдельный проверенный
[Windows Job Object с ProcessMemoryLimit](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information)
для worker, совместимость которого нужно проверить с моделью и GPU; случайного
ограничения памяти основного сервера или изменений системной конфигурации нет.

По умолчанию используется существующий Silero `v5_6_ru`, speaker `xenia`,
CPU / четыре потока / 24 kHz. Полные имена остаются в отображаемом тексте;
произношение готовится только для TTS. Поддерживаемые имена, сравнения и текущие
ограничения: [BILINGUAL_SILERO.md](BILINGUAL_SILERO.md).
Для явно выбранного Piper используется голос `ru_RU-denis-medium` на CPU.
Команда `python -m localmind.voice setup-tts` по-прежнему скачивает только Piper;
она не устанавливает Silero и не переключает выбранный голос.
Текст ограничен 1200 символами, результат — 2 минутами и 12 МБ. В интерфейсе
озвучивание начинается по фразам; его можно приостановить, продолжить, остановить или выключить. Ошибки действий должны
озвучиваться как ошибки; TTS не имеет доступа к инструментам управления ПК.

Совместимость PyAV сохраняется явной зависимостью `av==18.1.0`. API проверены по
[исходникам faster-whisper](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py)
и [официальному Piper Python API](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md).
Piper 1.3+ использует `PiperVoice.load(...).synthesize_wav(...)`. Отсутствующий
движок, модель или повреждённый файл даёт понятную ошибку без облачного fallback.

Лицензии: движок [Piper GPL-3.0](https://github.com/OHF-Voice/piper1-gpl/blob/main/LICENSE.md);
репозиторий голосов помечен MIT, а [карточка Denis](https://huggingface.co/rhasspy/piper-voices/blob/main/ru/ru_RU/denis/medium/MODEL_CARD)
указывает CC0 для исходного датасета. Это разные уровни лицензирования. Модели
не включены в Git. При распространении приложения с движком/моделями сохраняйте
соответствующие лицензии и выполняйте их условия. Irina не выбрана: её карточка
сообщает Unknown для лицензии датасета. Ссылки проверены 28.10.2026; качество
звучания и реальное воспроизведение на этом запуске ещё требуют проверки.

## Ошибки и проверка

- 503: установите зависимости и загрузите выбранный профиль явной командой выше.
- 422: тишина, повреждённый файл или слишком короткая запись; проверьте микрофон.
- 413: сократите запись до 30 секунд и 8 МБ.
- 429: дождитесь окончания текущей STT/TTS операции.
- 504: выберите CPU-fast или сократите запись; не запускайте повтор автоматически.

После загрузки моделей отключите сеть, перезапустите сервер, запишите фразу,
исправьте её в поле ввода, отправьте и включите TTS. Отдельно проверьте остановку,
mute, тишину, отказ микрофона и отсутствие модели. Это ручная проверка реального
устройства; unit-тесты её не заменяют.

## Измерения на согласованных записях

Создайте CSV `id,path,reference`, пути относительно CSV. Используйте только записи
с согласием говорящего. `docs/STT_TEST_SET.csv` содержит фразы, но не аудиофайлы.

```powershell
.\.venv\Scripts\python.exe scripts/eval_stt.py recordings.csv --consent --profile balanced
```

Скрипт печатает WER (расстояние Левенштейна по словам / число слов эталона), CER
по буквам без пробелов и latency включая загрузку модели: среднее, максимум,
p50/p95 методом ближайшего ранга. Нормализация приводит
к нижнему регистру, заменяет ё на е и удаляет пунктуацию. Ошибки не исключаются
молча: число неуспешных записей отдельно. Аудио в отчёт не выводится. Метрики по
умолчанию не включают текст; `--include-transcripts` явно включает исходную
расшифровку и эталон в приватный локальный отчёт для разбора ошибок.
Без предоставленных записей нельзя заявлять реальную WER/CER или сравнение GPU.

## Что проверено на этом checkout

Реально загружены base/small STT и Denis; Piper1.8 Windows wheel проверен
отдельно через `.voice-deps` без изменения внешнего окружения. Direct worker
создал синтетический русский WAV, обе CPU-модели вернули текст с ошибками;
точные результаты в `EXPERIMENTS.md`. Это не опыт с микрофоном и не оценка
точности живой речи. Человеческое прослушивание и GPU не проверены.

Нормальный API voice путь в restricted-token sandbox остановлен private-temp
ACL Python3.14; приложение возвращает понятный 503 без раскрытия путей.
Права production temp не ослаблялись. Повторите STT/TTS API в обычной Windows
сессии после штатной установки зависимостей. Исследовательские `.voice-deps`
не являются автоматически используемой средой приложения.

## Повторяемый микрофонный протокол (30.10.2026)

Поставщик остаётся faster-whisper: base/small/medium, PyAV → mono 16 kHz,
VAD, beam_size=5, condition_on_previous_text=False. Один ограниченный warm worker
сохраняет загруженную модель между запросами; при смене профиля прежний процесс
завершается до запуска нового. Декодирование в памяти, без сохранения аудио.
Production использует прежний baseline с language=ru.
API не скачивает модели и не заменяет слова команды после распознавания.

С согласия говорящего запишите как минимум 30 фраз из `STT_TEST_SET.csv`, обязательно
36–50. Для каждой сохраните три повторения: тихая комната/обычный уровень,
обычный фоновый шум/обычный уровень, тихая комната/пониженный уровень. Используйте
один микрофон, расстояние и формат записи; каждый файл до 30 секунд/8 МиБ. Не
создавайте перегрузку намеренно. Зафиксируйте модель микрофона, Windows, CPU/GPU,
расстояние, уровень входа и условия. Не нормализуйте разные варианты по-разному.
Храните согласованные записи и отчёт в приватной папке вне Git.

Манифест: `id,path,reference,condition,input_level,technical_terms`. Имена technical_terms
разделяются `|`. WER/CER считаются по исходному transcript; технические имена —
строго по написанию, без скрытой замены Downloads на «Загрузки». SHA256 записи
позволяет убедиться, что варианты получили одинаковые байты. Скрипт не выполняет
распознанные команды: отрицания оцениваются до отдельной ручной проверки роутинга.

```powershell
python scripts/eval_stt.py recordings.csv --consent --profile balanced --compare --include-transcripts --hardware-note "микрофон; CPU; GPU; расстояние; уровни" > private-balanced.jsonl
python scripts/eval_stt.py recordings.csv --consent --profile cpu-fast --compare --include-transcripts > private-fast.jsonl
python scripts/eval_stt.py recordings.csv --consent --profile gpu-quality --compare --include-transcripts > private-quality.jsonl
python scripts/eval_stt.py recordings.csv --consent --profile gpu-turbo --compare > private-turbo.jsonl
python scripts/eval_stt.py recordings.csv --consent --profile gpu-large --compare > private-large.jsonl
python scripts/eval_stt.py recordings.csv --consent --matrix --include-transcripts > private-matrix.jsonl
```

Запускайте только заранее установленные профили. Кандидаты gpu-turbo (large-v3-turbo)
и gpu-large (large-v3) доступны для явной загрузки через setup-stt, но не меняют UI.
`--compare` сравнивает baseline/baseline-auto и technical-ru/technical-auto:
в каждой паре отличается только language, prompt/hotwords совпадают.
multilingual включает отдельный эксперимент с поддержкой установленного API;
при отсутствии поддержки возвращается явная ошибка. `--matrix` требует минимум
30 фраз, каждую в quiet/noisy/low-volume, и все шесть фраз из текущего задания.
Эти варианты доступны в оценочном CLI и не меняют HTTP defaults. Их API проверены по
[исходникам faster-whisper](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py).
Сначала сравните ошибки на трёх reported примерах, обычной речи и отрицаниях, затем
общие WER/CER, technical-name accuracy, ошибки, p50/p95 и фактический CUDA→CPU fallback.
Полная latency включает запуск worker/загрузку при холодном запросе; model_load_ms
отдельно включает попытку загрузки GPU и fallback, model_reused показывает повторное
использование. Отчёт разделяет cold/warm, inference, p50/p95 и включает ошибки как
пустые расшифровки в WER/CER. Сохраняйте ошибочные/отрицательные фразы при сравнении.
Автоязык на коротких фразах может ухудшать результат.
Доказательств улучшения на микрофоне в этом запуске нет; defaults не продвигались.

Браузер сохраняет прежний audio:true; echo cancellation/noise suppression/auto gain
определяются браузером и драйвером. Без сравнительных записей фильтры и усиление
приложением не менялись. Ответ STT показывает RMS dBFS,
peak, долю clipping, предупреждения тихого/перегруженного входа и диагностические
segment logprob/no-speech. Это не калиброванный процент точности. Текст всегда
остаётся редактируемым до отправки; provisional updates не исполняются. Текущий
путь обрабатывает законченную запись и не заявляет live partial recognition.

Речь ответа отделена от отображения: display_text и structured_result содержат
точные имена/метаданные, speech_text произносит только выбранное имя по умолчанию.
Downloads, Obsidian, Warcraft, PDF, RSA имеют RU-произношение; helper также умеет
сохранять EN-написания и произносить английские аббревиатуры. Это не добавляет
английский голос в Piper. Имя на диске не меняется. TTS streaming/interrupt сохранены.
Прослушивание через реальные динамики всё ещё требуется.

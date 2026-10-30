# Silero bilingual repair — 31 October 2026

Implementation and automated checks are available; product sign-off is pending
listening, browser playback and the interactive Obsidian foreground test.

## Runtime identity and input support

This checkout started at `fee423c`, with no models or voice environments. The
separate existing LocalMind server on port 8765 reported Silero/Piper/Chatterbox
assets ready, but its API does not expose the browser's chosen voice. That server
was not changed or stopped. The user's Silero choice is the requested default.

The actual model downloaded for this checkout is `v5_6_ru.pt`, speaker `xenia`,
CPU, four threads, 24 kHz, `put_accent=True`, `put_yo=True`. Python 3.11.9 and
PyTorch 2.15.0+cpu were used in `.voice-envs/silero`. No CUDA assumption is made.
Its SHA256 is `04cc9b1d08ce38bcaa9d02c488d80d3e6806d17f7eaa7c95982f36a3cbf50b2e`.
The loaded package's symbols are Cyrillic; no enabled phoneme mode was exposed.
Its preprocessing removes Latin characters. Pure English input can raise
ValueError; mixed Russian/English can synthesize while omitting English names.

The [upstream model registry](https://github.com/snakers4/silero-models/blob/master/models.yml)
lists Russian v5_6_ru and English v3_en separately. The [speaker documentation](https://github.com/snakers4/silero-models#v3)
lists en_0 through en_117 for v3_en, without xenia. Both tested models used
24 kHz. The applicable repository [license](https://github.com/snakers4/silero-models/blob/master/LICENSE)
is CC-BY-NC-SA-4.0; the MIT license of other CIS models is not assigned here.
[SSML documentation](https://github.com/snakers4/silero-models/wiki/SSML) describes
pauses/prosody, not an English voice for xenia.

## Implementation

- API, browser defaults and optional warm-up use Silero. Explicit existing voice
  IDs remain valid. A changed voice preference persists locally; absent assets
  cause an error, with no automatic engine replacement.
- `clean_speech` preserves Latin spelling while removing Markdown/code/URLs.
  Lossless `language_spans` identifies Russian, ASCII English candidates and
  neutral text before pronunciation. Only the synthesis copy is adapted.
- A small dictionary supplies Russian sound approximations for the eight test
  phrases. Unknown Latin names/acronyms are spelled with the same speaker because
  this Russian model would otherwise discard them. This is a limited fallback,
  not natural pronunciation of arbitrary English sentences.
- `normalize_speech` retains its legacy Russian filename-rendering role. Display,
  transcripts, filesystem names and tool arguments are not rewritten.
- One resident model synthesizes each clause. No cross-model audio joins, sample
  rate conversions or per-span worker restarts were introduced. Length cuts keep
  the reviewed multiword names together, even across incoming deltas. Existing
  bounded queues/pause/mute/deadlines remain. Cancelled replies are checked again
  before returning audio.

## Actual audio and latency

Private artifacts: `.test-artifacts/bilingual/listen.html`, `evaluation.json`,
per-phrase `legacy-*.json`, `current-*.json`, `literal-*.json` and WAVs. Tracked
aggregate evidence: [bilingual-silero-20261031.json](evidence/bilingual-silero-20261031.json).
Each benchmark used six attempts per phrase/preparation, retaining successful
WAVs. Legacy means the original pronunciation behavior with the same model and
speaker; literal means cleaned original Latin text. Failures are retained as
failures, without fabricated baseline audio.

| Phrase | Legacy warm median ms | Adapted warm median ms | Adapted audio s |
| --- | ---: | ---: | ---: |
| Расскажи про Arthas Menethil из World of Warcraft | 73.2 | 98.3 | 2.575 |
| Warcraft III: Reign of Chaos | 43.3 | 87.3 | 2.288 |
| The Frozen Throne | failed 6/6 | 51.3 | 1.175 |
| Heroes of the Storm | failed 6/6 | 49.4 | 1.200 |
| Hearthstone | failed 6/6 | 36.3 | 0.763 |
| Открой Obsidian | 46.3 | 46.1 | 1.038 |
| Найди PDF в Downloads | 63.0 | 62.8 | 1.538 |
| Я программирую на Python и C++ | 89.5 | 90.5 | 2.338 |

The first adapted supervised-worker calls took 3.34–3.43 seconds, including
interpreter start, model loading and warm-up. These are desktop observations,
not hardware-isolated performance guarantees. Added names increase spoken
content, so shorter legacy audio is not evidence of better performance/quality.
The separate evaluation records package loading apart from synthesis and its
first versus five repeated inference timings. Downloads occurred only in setup.
Subsequent runs used fixed local files and offline flags; physical network
disconnection was not tested.

English v3_en / en_0 was also loaded locally and synthesized the twelve English
excerpts from these phrases, with explicit English forms for PDF, C++ and
Warcraft III. Its SHA256 is
`02b71034d9f13bc4001195017bac9db1c6bb6115e03fea52983e8abcff13b665`.
These separate WAVs are evaluation assets; they are not joined into Russian
responses. Human intelligibility, recognizable names, voice consistency, pauses
and joins remain **unrated**. English routing is not enabled without listening
evidence and an explicit choice. No additional TTS engine was introduced.

A real current-checkout HTTP request with omitted voice returned 200 and mono
PCM16 WAV at 24 kHz; a warm Frozen Throne request took about 59 ms to WAV response.
Browser playback-start and acoustic latency are **unmeasured**. A successful WAV
or HTTP response is not a pronunciation-quality result.

## Reproduce

After the explicit setup in [VOICE.md](VOICE.md), start with one command:

```powershell
.\.venv\Scripts\python.exe start.py
```

Offline text demo after assets are downloaded: enable speech, leave Silero
selected and send the eight phrases above. To avoid requiring an LLM, use the
local comparison runner:

```powershell
.\.voice-envs\silero\Scripts\python.exe scripts/eval_bilingual.py --retain-audio
```

It does not download assets. Missing English assets are reported without changing
the application voice. Optional setup for English evaluation only:

```powershell
.\.voice-envs\silero\Scripts\python.exe scripts/setup_voice_assets.py silero --english-evaluation
```

Example supervised comparison; repeat with each phrase and distinct filenames:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_next.py --kind voice --voices silero-v5_6-ru --direct-voice --speech-preparation legacy --n 6 --retain-audio --text "The Frozen Throne" --output .test-artifacts/bilingual/legacy-frozen-throne.json
.\.venv\Scripts\python.exe scripts/benchmark_next.py --kind voice --voices silero-v5_6-ru --direct-voice --n 6 --retain-audio --text "The Frozen Throne" --output .test-artifacts/bilingual/current-frozen-throne.json
```

Troubleshooting: 503 means check the selected engine's environment/model; installing
Piper does not install Silero. 422 after expansion means use shorter clauses.
Spelling an unknown name is intentional fallback; add a reviewed dictionary entry
only after listening. Stop/mute cancels the exact generation. Port 8765 may already
be occupied: use `$env:LOCALMIND_PORT='8876'` for an isolated test server. No current
server or unrelated process should be terminated to free the port.

## Obsidian: open bug, separate from speech

`apps.open` now binds launch-to-focus to the initial executable grant and waits
up to ten seconds for a verified window. It discovers the receiving Electron
instance by image/session/user identity rather than the returned launch PID.
Only a fingerprint-granted win32 Obsidian image opts into serialized background
activation, bounded by the existing handoff grace and pending-process tracking.
Other background apps keep their prior no-relaunch behavior. Revocation,
fingerprints, PID creation time, HWND/thread markers and ambiguity checks remain.
Only observed foreground equality means success; launch and SetForegroundWindow
return values do not establish it.

A native test reused exactly the Obsidian executable/source fingerprint already
allowed by the separate running LocalMind server. Initial inspection was absent,
so this required no manual open/minimize preparation. The launch created a process
but exposed three candidate windows (two input-indicator windows and a dialog).
Both cold and repeated open returned **ambiguous**, without selecting a window.
The interactive desktop inventory did not expose these windows. This does not
demonstrate a usable Obsidian editor or successful foreground activation. No
filters or forced activation were added to turn that outcome into success.
The original bug remains OPEN; interactive cold/existing/minimized/background
cases and activation denial still require verification. No app was force-closed.

## Checks and remaining evidence

Focused tests cover supplied/unknown names, acronyms, numeral context, punctuation,
Markdown/code/URLs, filename regressions, chunk boundaries, missing assets,
bounded expansion, worker reuse and cancellation/stale replies. Windows doubles
cover cold discovery/PID handoff, changed/revoked grants, cancelled discovery,
multiple windows and honest activation denial. They are not desktop integration.
Real supervised-worker cancellation and successor synthesis were exercised
separately; see aggregate evidence for timings and dispatch limitations.

The Playwright suite is blocked before execution by `spawn EPERM`. The browser
host is unavailable, and automatic approval review rejected Zen inspection as
not approved for Computer Use. No browser listening/playback result is claimed.
Windows microphone, GPU and owner listening remain unverified. See
[DEFENSE_QA.md](DEFENSE_QA.md) for more than twenty defense questions with explanatory
answers, and [QUALITY_GATES.md](QUALITY_GATES.md) for required product sign-off.

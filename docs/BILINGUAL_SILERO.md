# Silero bilingual repair — 31 October 2026

## Final contextual fixes: implementation verified, human listening pending

The latest policy supersedes the old IP/version comma speech below for Silero
only. The compatibility filename renderer keeps its legacy outputs. The new
reviewed, whole-token spellings are `Apple` → `Эппл` and `Node.js` → `Нод джей эс`.
They are case-insensitive and do not match inside longer words.

Before Latin adaptation, software cues (`Python`, `Node.js`, other reviewed
software names, or explicit `version/версия` with optional product) select cardinal
version components separated by `точка`. Software cues precede date/IP matching,
so `Версия Node.js 31.10.2026` is a version. Existing v-prefixed and multi-dot
identifiers also use cardinal components and `точка`. Valid IPv4 octets instead
use individual digits and `точка`; invalid octets remain dotted identifiers.
Uncued `31.10.2026`, `2026-10-31`, `31/10/2026` retain date separators. Uncued
`3.14`, `3,14`, negative decimals and fractions retain mathematical speech.
No general language parser or global punctuation replacement is involved.

Four-digit year lists sharing `году/годах` inflect every year with the existing
ordinal renderer. Comma lists, и/или, repeated whitespace and three or more years
are supported, including `2000` → `двухтысячном` and `2003` → `две тысячи третьем`.
A list comma requires following whitespace to distinguish it from a decimal.
Lists do not cross unrelated words, decimals, technical tokens or clause endings.
Streaming holds complete/partial products, versions, year lists and shared nouns
across character deltas and cuts; Python alone determines pronunciation.

Required listening worksheet rows (plus sentence-context variants):

| Input | Exact speech text |
| --- | --- |
| Apple II | Эппл два |
| В 1977 году | В тысяча девятьсот семьдесят седьмом году |
| Вышли в 1997 и 2002 годах | Вышли в тысяча девятьсот девяносто седьмом и две тысячи втором годах |
| В 2026 году | В две тысячи двадцать шестом году |
| Python 3.14 | Пайтон три точка четырнадцать |
| Версия Node.js 24.19.0 | Версия Нод джей эс двадцать четыре точка девятнадцать точка ноль |
| Число пи примерно равно 3.14 | Число пи примерно равно три целых четырнадцать сотых |
| IP-адрес 192.168.1.1 | ай пи-адрес один девять два точка один шесть восемь точка один точка один |
| Warcraft II | Варкрафт два |
| StarCraft II | стар крафт два |
| Diablo IV | Диабло четыре |
| Command & Conquer | комманд энд конквер |

Current checkout evidence: **215 focused Python tests**, **716 full Python tests
and 35 subtests**, **39 DOM checks**, seven JS syntax checks and `git diff --check`
pass. The existing pytest-cache ACL warning remains. Real CPU xenia generated
**90 worksheet WAVs without errors**. Model SHA256:
`04cc9b1d08ce38bcaa9d02c488d80d3e6806d17f7eaa7c95982f36a3cbf50b2e`.
Twelve real supervised-worker calls matched independent expected literals,
diagnostic `tts_input` and outgoing framed text exactly, reusing one worker.
A retired generation was refused before dispatch; successor synthesis worked.
Twelve real HTTP requests returned valid nonempty mono PCM16 24 kHz WAVs. Model,
speaker, CPU/four threads, rate, accent/ё, queues and cancellation are unchanged.
Independent Reviewer/Security inspection found no blocking issues.

After setup, one-command start and offline demo (no LLM needed for the worksheet):

```powershell
.\start_windows.ps1
.\.voice-envs\silero\Scripts\python.exe scripts/eval_bilingual.py --retain-audio --current-only --iterations 1 --output .test-artifacts/contextual-tts
```

Open `.test-artifacts/contextual-tts/listen.html` locally and listen to every row
above and the franchise regressions. Record reviewer, observations and WAV hash
in `evaluation.json`; do not populate listening fields from synthesis success.
The worksheet, `worker-correlation.json`, `http.json` and WAVs are private ignored
artifacts. Assets were reused from the installed checkout, with no download.
Offline inference flags were used; physical network disconnection was not tested.

For browser checking, set `LOCALMIND_TTS_DIAGNOSTICS=1` only in the verification
session and compare each correlated text with worker input. Stream splits near
240 characters around Node.js, product/version whitespace and the shared noun;
exercise pause/resume, stop, mute and a successor reply while checking unchanged
displayed text. DOM checks cover these controls with doubles, not audible playback.

**Human listening and real browser playback remain unverified.** Playwright's
focused speech test stops at `spawn EPERM`; the browser access host is unavailable
and automatic approval review rejected Zen inspection as not approved for Computer
Use. No human listening report has been received. Windows microphone and GPU
were not tested. These are still open sign-off gates.

Troubleshooting: if PowerShell blocks `.ps1` execution, run
`.\.venv\Scripts\python.exe start.py`; no permanent execution-policy change is
needed. If a local voice environment/model is missing, use [VOICE.md](VOICE.md)
setup first; the evaluation never downloads models. A 422 after expansion requires
shorter clauses. Keep an occupied port intact and choose `LOCALMIND_PORT` for an
isolated server (this verification used 8896). Defense explanations remain in
[DEFENSE_QA.md](DEFENSE_QA.md).

## Roman numerals, numbers/years and ampersands: preceding repair

This section supersedes the franchise-specific numeral and digit-by-digit rules
described below. Implementation and synthesis checks pass; **audible and browser
playback sign-off remains open**. Older WAVs do not validate this repair.

`cleaned_text` now retains numeric spelling/separators and Latin spelling after
display cleanup. Context is resolved before ordinary word pronunciation in
`pronunciation_text`; `tts_input` is the exact worker input. `original_text`, the
displayed answer, history, filenames and action data are preserved.

- Roman recognition uses a separate canonical Roman token after an ordinary
  Latin word of at least two letters, independent of title vocabulary and case.
  `StarCraft II/III`, `Diablo IV`, and unseen `Zephyr XLII` become cardinal
  numerals. A title cue cannot itself be a known initialism or canonical Roman
  token; explicit multi-letter initialisms such as CLI also take precedence in
  the numeral position. Single I always remains the English pronoun; V following
  a title cue is a numeral, otherwise its existing letter-name rule applies.
  Embedded/version suffixes (`IIIx`, `IV2`, `IV.2`, `IV+`) and noncanonical IIV
  are excluded. Ambiguous `Civil IV` is classified as a title by this syntax;
  this is intentionally a deterministic convention, not semantic English parsing.
- Ordinary signed integers become Russian cardinals, with thousands/millions/
  billions agreement. Bare 2014 stays cardinal. Explicit `год/года/году/годом`
  selects the last ordinal component and its ending; 2000 has the exceptional
  `двухтысячном` form. Existing filename `за … год` speech uses the same ordinal
  renderer and remains idempotent. Explicit suffixes such as `42-й` and `21-я`
  are also supported. This does not infer case/gender for arbitrary surrounding
  nouns. Integer conversion is bounded to twelve digits; years/explicit ordinals
  to four. Leading-zero identifiers and larger tokens retain digit speech and
  the existing 2400-character worker expansion limit still applies.
- Technical prefixes IPv/v, explicit `version/версия/версии [ПО]`, multi-dot
  identifiers and date structures are consumed before year matching. IP/version
  components retain existing digit/`запятая` speech, including exactly
  `IPv4 v2.1` → `ай пи ви четыре ви два запятая один`. Dates speak numeric
  components with `точка`, `дефис` or `дробь`; they do not become inflected years.
  Otherwise dot/comma numeric pairs are decimal fractions: `3.14` and `3,14`
  become `три целых четырнадцать сотых`. Up to six fractional places use Russian
  denominators; longer fractions fall back to spoken digits after `запятая`.
- Ampersands between adjacent original Latin tokens use `энд`; other contexts
  use `и`. Single Latin letters next to & use letter names, giving `C&C` →
  `си энд си`, `R&D` → `ар энд ди`. Spaced/unspaced forms share the rule;
  neighboring names still use their existing pronunciation.

The browser protects generic title/numeral pairs, ampersand expressions, numeric
tokens and year phrases, including partial deltas. It holds a trailing unfinished
token until context or final flush arrives. Pronunciation stays in Python; no
second browser numeral converter or franchise list was added. The voice remains
Silero v5_6_ru / xenia / CPU / four threads / 24 kHz / accent and ё enabled.

### Current verification and reproduction

After installing assets, start with one command:

```powershell
.\.venv\Scripts\python.exe start.py
```

Offline synthesis and listening worksheet, without needing Ollama:

```powershell
.\.voice-envs\silero\Scripts\python.exe scripts/eval_bilingual.py --retain-audio --current-only --iterations 1 --output .test-artifacts/numeric-ampersand
```

Open `.test-artifacts/numeric-ampersand/listen.html` and record observations for
names, numerals, conjunctions, stress and pauses in `evaluation.json`. The current
run produced **76 actual xenia WAVs, zero synthesis errors**, on Windows/Python
3.12.10/PyTorch 2.6.0+cpu. The existing model was copied locally, packages reused
read-only, and no model or package download occurred. Its SHA256 is unchanged.

An isolated current-checkout server on 8879 also synthesized **33 real HTTP
requests**, including 23 standalone cases and ten production-chunker clauses
from **119 real local Ollama deltas** (qwen3.5:9b). The complete generated answer
retained the requested original spelling. Each request's original/cleaned/
pronunciation/exact TTS input matched its opt-in stderr diagnostic, correlated
by generation ID and unique request ID. Retired-generation rejection, successor
synthesis and stale-cancel isolation passed through the actual API/worker.
This used the real JavaScript chunker with queue-only execution; it was **not a
browser playback test**. No audible observations were recorded. The owned test
server was stopped; the pre-existing app was not changed or stopped.

See [current aggregate evidence](evidence/silero-normalization-20261031.json).
Final automated checks: 172 focused Python tests; 678 full-suite tests and 35
subtests; 38 DOM, ten attachment-context and seven history checks; JavaScript
syntax, 76 asset references and `git diff --check`. There is no separate build,
typecheck or Python lint configuration in this repository.

**Remaining required gate:** live UI streaming with pause/resume, stop, mute,
immediate successor responses, and human listening. The browser access host is
unavailable; Playwright fails before tests with `spawn EPERM`; automatic approval
review rejected Zen inspection because Computer Use was not approved to use Zen.
DOM playback doubles and successful synthesis do not close this gate. Windows
microphone and GPU were not tested.

Troubleshooting: use [VOICE.md](VOICE.md) for missing local Silero assets (503),
shorter clauses for expansion errors (422), and a free `LOCALMIND_PORT` for an
isolated server. Opt-in `$env:LOCALMIND_TTS_DIAGNOSTICS='1'` logs synthetic test
text; disable it after review. No default text/audio retention was added. See
[DEFENSE_QA.md](DEFENSE_QA.md) for more than twenty defense questions and answers.

## Previous pronunciation regression repair (historical, 31 October)

The implementation below supersedes the earlier letter-spelling fallback. The
older benchmark and Obsidian notes further down are historical evidence, not
verification of this repair. **Listening sign-off is still pending.**

`speech_text.speech_preparation` now processes contextual Warcraft/Diablo Roman
numerals before Latin words: II → два, III → три, IV → четыре (also V–X).
Standalone I, unrelated initialisms and version suffixes are excluded from this
rule. Reviewed whole entities precede component words, with case-insensitive
matching, whitespace normalization and word boundaries. Written pronunciations
include «Диабло Иммортал», «Близзард Энтертейнмент», the existing game names and
common software/technology names. These spellings have not been audibly rated.

Ordinary unknown words use a compact deterministic English sound approximation
with digraphs, silent-e and positional vowel/consonant rules. Genuine initialisms
use an explicit table: AI «эй ай», API «эй пи ай», PDF «пи ди эф», RSA «эр эс эй»;
C++ remains «си плюс плюс». Uppercase alone never enables letter spelling;
NASA/NATO are speakable acronyms. Unknown names remain approximate, especially
irregular vowels and stress. This is not general English TTS or translation.
Display/history/action arguments and filename rendering retain their contracts.
The engine remains silero-v5_6-ru, xenia, CPU/four threads/24 kHz, accent and ё on.

`speech.js` protects complete and partial entities across deltas and cuts, with
case-insensitive matching and repeated whitespace. Tests feed every character
split of the required multiword titles at starts 216–244, verify final flushing
and exact text preservation, and check Python/JavaScript phrase-list agreement.

### Diagnostics and privacy

Default mode writes no pronunciation text/audio files. Explicit diagnostic mode:

```powershell
$env:LOCALMIND_TTS_DIAGNOSTICS='1'; .\.venv\Scripts\python.exe start.py
```

Each synthesis call emits one JSON record through the parent process's stderr
logger `localmind.pronunciation`: unique `request_id`, `generation_id`, `voice`,
`original_text` (incoming speech chunk), `cleaned_text`, `pronunciation_text`, and
the exact `tts_input`. The last two currently match because the worker performs
no additional text rewrite. No diagnostics enter the worker's stdout protocol.
Explicitly captured console logs contain text; disable with
`Remove-Item Env:LOCALMIND_TTS_DIAGNOSTICS` when review ends. Diagnostic mode does
not record audio. CLI evaluation retains synthetic WAVs only with `--retain-audio`.

### Local English lexicon/G2P evaluation

The experiment in `scripts/eval_pronunciation.py` loads the original
[CMUdict data](https://github.com/cmusphinx/cmudict) locally and renders ARPAbet
phonemes to Cyrillic. It compares 18 words, including ten names unseen by the
reviewed dictionary, against the compact rules. The downloaded data has 126,052
word keys, takes 3,618,488 bytes, and covers 15 of the 18 words. Hearthstone,
Qzora and Kubernetes are absent. Both variants produced 33 xenia WAVs in
`.test-artifacts/g2p/listen.html`; reviewer and sound-quality ratings remain null.

Text inspection: CMUdict produces «финикс» for Phoenix where compact rules give
«фоеникс», but «дайэблоу» for Diablo and «воркрэфт» for Warcraft conflict with the
requested Russian forms. Crystal and Silver agree. Coverage alone is not a
quality score. Lexicon lookup does not infer novel words, resolve title numerals
or select Russian conventional brand pronunciations. ARPAbet stress is omitted
by this experimental renderer; Silero still selects stress. Therefore this
lexicon is evaluation-only; runtime keeps the small pronunciation function and
has no new dependencies, service, subprocess or inference-time downloads.

Windows setup cost for the experiment: one explicitly downloaded UTF-8 data
file, stdlib parser/phone renderer, and the existing Silero environment only for
optional audio. It runs offline after setup. CMUdict's original
[license](https://github.com/cmusphinx/cmudict/blob/master/LICENSE) permits use and
redistribution with its notice/disclaimer. Keep that license alongside downloaded
data. The optional [Python wrapper](https://github.com/prosegrinder/python-cmudict)
has a separate GPL-3.0-or-later license and importlib dependencies; it was neither
installed nor added to the application. A learned G2P could cover novel names,
but would still need Russian brand overrides, local model assets and listening
evidence before promotion. No claim of learned-G2P evaluation is made here.

### Current evidence and reproduction

Start after the existing documented setup with one command:

```powershell
.\.venv\Scripts\python.exe start.py
```

Offline demo without Ollama, after downloading the assets:

```powershell
.\.voice-envs\silero\Scripts\python.exe scripts/eval_bilingual.py --retain-audio --current-only --iterations 1
```

Open `.test-artifacts/bilingual/listen.html`. The 24 required rows cover every
requested standalone expression and a complete Russian sentence containing each;
eight prior regression samples are included too. Each row records all four text
stages, model/speaker, WAV identity/SHA256 and empty reviewer/observation fields.
Record names, numerals, stress, pauses and joins for every required row, then
exercise streamed playback, pause, stop and mute with the same sentences.

For the optional lexicon comparison after explicitly obtaining CMUdict:

```powershell
.\.voice-envs\silero\Scripts\python.exe scripts/eval_pronunciation.py --lexicon .test-artifacts/g2p/cmudict.dict --retain-audio
```

Current run: Windows 10, Python 3.12.10/PyTorch 2.6.0+cpu for Silero;
Python 3.14.5 for the app/tests. Reused installed packages read-only through
ignored local environment links and copied the existing model into this worktree;
no model download occurred. All 32 current WAVs synthesized without errors. One
actual current-checkout HTTP request returned mono PCM16/24 kHz (5.45 seconds),
and its stderr log showed the expected four stages. This establishes synthesis
and diagnostics, not listening quality. See
[current aggregate evidence](evidence/silero-pronunciation-20261031.json).

Playwright could not start its worker (`spawn EPERM`). Browser access host was
unavailable; automatic approval review rejected Zen inspection because Computer
Use was not approved to use Zen. No streamed browser playback or actual listening
is claimed. Windows microphone and GPU remain untested. For at least twenty
defense questions with explanatory answers, see [DEFENSE_QA.md](DEFENSE_QA.md).

Troubleshooting: missing environment/model produces 503; follow [VOICE.md](VOICE.md)
for Silero setup rather than installing another engine. Do not point a Python
3.12 environment at Python 3.14 binary packages. Missing Russian assets or failed
current synthesis makes the evaluator exit nonzero. Missing English comparison
assets do not change xenia. A 422 expansion limit means use shorter clauses.
Use `LOCALMIND_PORT=8879` in an isolated test shell if 8765 is occupied; never
terminate an unrelated server. Offline flags were used; physical network
disconnection was not tested. Audible correctness remains the release blocker.

---

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

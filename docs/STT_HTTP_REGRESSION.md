# STT HTTP regression — 2026-11-03

The software regression is covered by automated tests. Physical Windows microphone
verification and a consented browser-audio/response fixture remain outstanding.
This is not a completed hardware acceptance report.

## Change and diagnostic visibility

`voice_diagnostics.normalize_stt_payload` copies a JSON-shaped result recursively.
Non-finite floats become `null`; text, finite numbers, booleans and existing nulls
are preserved. Exact paths, including array indices, are returned in
`diagnostics.non_finite_fields`. The expert STT trace in the UI exposes these
paths. The normalizer does not log audio, transcripts, values or native errors.
Paths persist when the payload crosses another boundary.

The two confirmed static sources are `quality.mean_segment_logprob` and
`quality.max_no_speech_probability`. A contaminated segment invalidates its whole
aggregate instead of returning a misleading partial metric; aggregation overflow
also becomes null and recommends transcript review. Recognition settings and text
assembly are unchanged. Optional metrics cannot trigger GPU fallback or reload.
The field from the originally reported physical recording is **not yet known**.
Do not label either candidate as the observed incident field without reproduction.

Normalization protects recognition output, framed worker emission, the ASR
consumer, the legacy STT result-file boundaries and `/api/transcribe`. STT writers
use `allow_nan=False`. No global exception handler was introduced. TTS transport,
Gemma selection, xenia, storage and download execution were not changed.

PyAV invalid-data, end-of-stream, unavailable-codec and invalid media-value errors
at decoding now yield a fixed, readable 422. Dependency/model/GPU failures retain
their separate handling. Existing size and format limits remain 413 and 415.

The live loopback server on test port 8877 returned this actual response when the
multipart audio field was omitted:

```json
{"detail":[{"type":"missing","loc":["body","audio"],"msg":"Field required","input":null}]}
```

The UI now displays `body.audio: Field required` instead of just HTTP 422. It
limits the number/length of validation locations and messages, excludes `input`
and `ctx`, and uses `textContent`. String domain errors remain intact. A 100-byte
recording returned 422 with `Запись пустая или слишком короткая.` on that same
server. The separate 422 from the user's earlier recording cannot be attributed
to a specific validation error without that recording's response body.

Downloads and model-catalog status polling requires an open relevant dialog,
a visible document and queued/starting/downloading/verifying/cancelling jobs.
Opening, returning to a visible page and explicit actions refresh the list.
Terminal/idle states stop timers. Pending requests are serialized, and closure
invalidates their ability to restart timers. The model catalog follows its actual
dialog after product navigation moves it out of settings.

## Verification

- Python: 883 passed, 35 subtests passed. Command: `python -m pytest -q
  -p no:cacheprovider`. The cache plugin was disabled because this Windows sandbox
  rejects pytest's temporary cache-directory ACL. The interpreter used was the
  existing project venv at `C:/Users/ExampleUser/Desktop/LocalMind_MVP_01/.venv/Scripts/python.exe`
  (Python 3.14.5); default system Python 3.11 lacks project dependencies.
- 26 focused strict-JSON regressions: NaN and both infinities in both quality
  fields and nested arrays/maps; overflow; exact paths; unchanged text; legacy
  file output; contaminated older-worker frames; real FastAPI response rendering.
- A real child process runs the framed STT worker and real PyAV decoder with a
  neural-model double. Three successful HTTP requests separated by corrupt,
  short and silent WAV uploads reuse the same process/model. Generated WAVs and
  model doubles are **not** human recordings or real inference evidence.
- `npm run check:ui`, `npm run test:dom`, `npm run check:assets`: passed. Includes
  40 main DOM checks, all other DOM suites and controlled-timer lifecycle/race
  coverage for both download lists; 82 local assets resolve. Existing node_modules
  from the main checkout were used through `NODE_PATH`.
- `python -m compileall -q localmind`, `python -m pip check`, `git diff --check`:
  passed. No separate configured typechecker or compiled application build applies
  to this Python/first-party JS fix; no installer was rebuilt.
- `python start.py` with isolated workspace data and port 8877: started successfully;
  real HTTP GET `/` returned 200; missing multipart audio and short upload returned
  the 422 bodies above. No user configuration or model files were changed.
- The legacy rule smoke suite now uses the existing offline-planner fixture; its
  first run otherwise reached the user's running Ollama and selected the LLM path.
- Visual/browser verification could not run: Windows Computer Use refused access
  to Zen (`Computer Use was not approved to use Zen`); automated Chromium launch
  failed with `spawn EPERM`. No access bypass was attempted.
- Physical microphone, consented real audio/response fixture, actual incident
  field, real CPU inference and GPU inference: **not verified in this change**.
- The requested focused commit could not be created: Git was denied creation of
  `index.lock` in the worktree metadata outside the writable workspace. No ACL or
  metadata workaround, merge or push was attempted. The complete focused patch
  is saved locally as `.test-artifacts/stt-http-regression.patch`.

## Run, offline demo and troubleshooting

With the project dependencies installed and its environment activated, start with:

```text
python start.py
```

After models have already been downloaded explicitly, open localhost, record a
short Russian phrase, edit the resulting draft and submit only when ready. STT
uses local files; no model downloads or cloud inference are part of recognition.
See [the offline demo and repair guide](PRODUCTIZATION_1_0.md) and
[60 defense questions with explanatory answers](DEFENSE_QA.md).

If recognition fails, read the visible error message first. For a 422, check the
named multipart field, microphone permission, sufficient recording duration,
speech level and supported container. A 503 still calls for checking installed
dependencies, prepared model files and GPU/CPU profile. For a successful response
with null diagnostics, inspect only `diagnostics.non_finite_fields`; do not copy
the entire trace into logs or issue reports because it also contains the text.

The remaining live gate requires three human microphone recognitions in the
same process, HTTP 200, strict JSON, editable unaltered text, subsequent
`model_reused=true`, a readable short-recording error and polling cessation in
idle/closed/hidden states. Record CPU and GPU results separately, including any
fallback. Retain audio plus its response fixture only with explicit consent;
no consented pair was supplied during this run. Never substitute generated audio
for this gate. Record the original non-finite path if it recurs, without logging
audio or transcript. Do not mark the task complete until this gate passes.

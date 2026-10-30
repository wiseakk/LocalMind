# Speech and real-agent verification — 30 October 2026

Implementation is verified by automated checks and narrow real local inference.
The product is **not certified complete**: microphone corpus, listener assessment,
actual foreground activation, browser scenarios and rollback branch remain pending.

| Area | Current evidence | Remaining gate |
|---|---|---|
| Filename normalization | Exact reported wording; reviewed vocabulary, natural title years, technical/opaque names; original display/data preserved; sequence speech regressions | Human assessment of varied titles |
| ASR | Warm supervised worker; real child decodes silent WAVs twice; real small CPU model reused on synthetic speech; medium CUDA request falls back to CPU and reuses it | 30+ real phrases in all three conditions, full model/language matrix, GPU coexistence |
| Audible TTS | Five actual Piper CPU WAVs; five Windows playback API completions | Heard transcript/corrections/intelligibility; API completion alone is insufficient |
| Windows activation | Native callback tests check HWND equality, restore, reuse, cancellation and honest denial | Obsidian launch→focus, existing/minimized/multiple actual windows in interactive server session |
| PDF reading | Real synthetic PDF search→name→read→qwen3.5:9b summary, source-only random code and budget verified in outbound source and answer; revoke→read denied | Same flow in real browser; physical PDF opening |
| Total latency | Real API timings below | Microphone→ASR→review→action→audible answer end to end |

Python: **540 tests + 35 subtests passed**, including parser/permission/changed-file,
scanned/encrypted PDF, request replay, interruption and document-source tests.
DOM: **52 checks passed**. All seven production JavaScript syntax checks passed.
No independent typecheck or build is configured in package.json.

`npm.cmd run test:ui` collected 35 browser cases but failed before execution with
`spawn EPERM`. Computer Use could list desktop applications, but automatic approval
review rejected inspection of Zen: “Computer Use was not approved to use Zen”.
No visual/browser success is claimed. The native runner observed NULL foreground
HWND and could not enumerate its own temporary window as visible; that does not
diagnose the previous user's Obsidian denial. The application still reports actual
denial honestly, without bypassing Windows foreground restrictions.

Real local Ollama smoke passed: DEMO lamp status/commentary, identical request replay,
safe-close refusal, RSA answer. Synthetic PDF selection took 15 ms, name lookup 6 ms,
extraction+real summary 5034 ms, revoked read 2 ms in one run. A 76-character actual
source containing the random code reached Ollama. These are single API observations,
not p50/p95 performance claims or a microphone end-to-end benchmark.

Actual Piper sample generation used already installed assets read-only: model load
3161.476 ms; reported sample synthesis 236.986 ms, duration 6.525 s, mono PCM16 at
22050 Hz, RMS −18.557 dBFS, clipped fraction 0.000014. Waveform measurements cannot
establish naturalness. No audio was captured from the microphone or retained without
consent; these are explicitly retained, generated test samples in ignored artifacts.
Listener answers are currently null.

The same generated waveform was passed to real small/CPU-int8 and medium/CUDA-FP16
recognizers twice, with forced Russian and automatic language using identical prompts.
Small actually ran `cpu/int8_float32`: 2706 ms cold, 2062 ms reused. Medium actually
fell back to `cpu/int8_float32`: 7085 ms cold including failed GPU attempt, 5910 ms
reused; no second GPU attempt. Recognition contained errors in technical/acronym words.
These four synthetic runs establish integration/reuse/fallback only; no human-speech
WER/CER, large-model performance or CUDA improvement is asserted. Model download and
inference remain separate; no models were downloaded for these checks.

## Reproduce

After normal project setup, start with one command:

```powershell
.\start_windows.ps1
```

In this restricted session, the default Python 3.11 lacked pytest/dependencies and a
local pip installation stalled. Tests and `start.py` instead used the existing installed
Python 3.14.5 environment at the original checkout, without changing that environment:

```powershell
& 'C:\Users\ExampleUser\Desktop\LocalMind_MVP_01\.venv\Scripts\python.exe' start.py
```

Set `OLLAMA_MODEL=qwen3.5:9b` for the measured configuration. In a prepared environment:

```powershell
python -m pytest -q -p no:cacheprovider
npm.cmd run check:ui
npm.cmd run test:dom
npm.cmd run test:ui
python scripts/smoke_local.py
python scripts/verify_selected_pdf.py --model qwen3.5:9b
python scripts/verify_filename_audio.py --consent --play
python scripts/eval_stt.py recordings.csv --consent --profile balanced --compare
python scripts/eval_stt.py recordings.csv --consent --matrix --include-transcripts --hardware-note 'mic; distance; CPU; GPU; driver; levels'
```

On Windows redirected consoles, set `$env:PYTHONIOENCODING='utf-8'` before scripts
that print Russian. Use `--model-dir` on the WAV script only when explicitly reusing
already installed Piper assets. It reads the declared model/sidecar and never downloads.
Generated WAVs, hashes, waveform metrics, literal prepared text, playback outcomes and
a listener template are in `.test-artifacts/filename-audio/`. Add the listener's own
words to a separate JSON and pass `--listener-feedback`; do not infer feedback from
ASR transcription or waveform metrics. PDF reports are `.test-artifacts/pdf-evidence-*/report.json`.

## Offline demo and troubleshooting

After explicit setup/download of the selected Whisper, Piper and Ollama assets, all
inference uses local files/local Ollama. Full disconnected-network operation was not
retested here; follow README.md and VOICE.md for the offline demonstration. In DEMO
mode the lamp is simulated. Keep raw recognition editable and explicitly reviewed.

For missing model/dependencies, follow VOICE.md/setup_windows.ps1; no API downloads or
cloud fallback occur. GPU profile labels do not prove CUDA execution: inspect `device`,
`compute_type` and `fallback`. Unsupported multilingual decoding reports an error.
If Windows refuses focus, choose the correct window, restore/select it manually and
retry; do not change security policy. If extraction fails, report that the content is
unknown; scanned PDFs need a separate approved OCR workflow. After permission or file
identity changes, search/select again. Preserve the default mute/interruption controls.

The existing 40 explanatory defense answers remain in [DEFENSE_QA.md](DEFENSE_QA.md).
Source recovery is available in `.test-artifacts/baseline-cdfd1d3.zip`; the shared Git
metadata denied rollback-branch creation, so orchestrator branch/checkpoint creation
must still be performed in a permitted owner session. No push/publish/deploy occurred.

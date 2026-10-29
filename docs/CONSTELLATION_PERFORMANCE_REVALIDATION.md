# Constellation performance revalidation — 29 October 2026

Current browser/hardware gate is incomplete. Base checkout: `e4a71c8`.
Changes remain uncommitted because the required browser verification cannot run
in this execution environment. The earlier performance report is historical;
its numbers are not evidence for these changes.

## Evidence-backed changes

The controlled DOM/Canvas submission spy uses fourteen nodes, a deterministic
rAF queue and fake drawing contexts. Against the original renderer, thirty
repeated application/conversation observations followed by one draw caused
28 label rasterizations, 14 text measurements and 28 new Canvas contexts,
and restarted settled physics. The updated renderer adds zero rasterizations,
measurements or contexts for the same observation sequence, preserves the
existing select options and leaves physics settled. These are operation counts,
**not real raster timings, rendered FPS or GPU measurements**.

Reconciliation retains live node objects, dragged coordinates and unchanged
label caches. Permission/detail updates remain visible without waking physics;
renaming one node rebuilds only its two label variants. Topology changes still
wake the bounded solver. Recenter/reset, selection and the 36-node limit remain.

A resolution media query now detects DPR-only monitor/zoom transitions, re-arms
after each change and refreshes on page restore. Window resize also runs with
ResizeObserver available. Existing geometry, 1.5 DPR and 1.6M pixel caps and
adaptive-quality rules remain. Identical appearance settings do not restart
the solver or animation. No colors, blur sprites, starfield design or CSS changed.

`stats({timings:false})` omits sample copying/sorting for benchmark polling;
the default `stats()` and optional overlay still include timings. Tests verify
one animation chain after hide/show, no unchanged-cache reallocation, font
invalidation, lost pointer capture and reset when observations are unchanged.

## Benchmark changes and limits

The runner verifies exact extension-set native zoom and accelerated Canvas /
compositing. It writes configuration and failure metadata even when launch fails.
Inference sampling starts after an actual streamed delta appears and ends at
the final response or the requested duration, excluding model startup and idle
tails. This measures the browser's active output window, not Ollama kernel time;
trace setup follows the first delta and final DOM rendering can occupy the last
display interval. The actual sampled duration and separate startup duration
are retained; a short response is never reported as thirty seconds of inference.
Samples shorter than one second are rejected.

Canvas frame submissions, sampling rAF callbacks and raw compositor/frame-event
counts are separate fields. Raw event counts are **not** presented FPS or proof
of zero dropped frames. Open the trace in DevTools Performance and inspect its
Frames track before judging displayed smoothness. Layout, paint, raster, scripting
and GC event durations are clipped to user-timing sample markers; nested or
cross-thread durations must not be summed as elapsed time. CPU is renderer main
TaskDuration over the matching CDP Timestamp window (also recorded). Timestamped
NVIDIA samples within the window describe **whole-device** utilization, including
Ollama and other desktop activity, rather than Canvas-only GPU cost. Real typing
is attempted while generation is active and included in that workload's CPU cost.

Synthetic reducer tests verify window clipping, frame/callback separation,
inference-tail exclusion and absence of per-frame timing sorts. They do not
establish correctness of live Chromium trace emission in this environment.

## Current verification

- Python: **391 passed, 35 subtests passed**, no skips. The initial expiry test
  race was corrected by joining the request worker before forcing its finished
  timestamp; the existing assertion and backend implementation are unchanged.
- **31 DOM checks passed** (all original 28 retained), plus benchmark reducer /
  sampler checks. These use mocks and controlled clocks where stated.
- Seven UI module syntax checks, benchmark/helper/browser-test syntax checks,
  all 76 local asset references and `git diff --check` pass.
- The documented Windows entry command starts the actual loopback server.
  A real `qwen3:4b` stream produced 54 deltas and final engine `ollama`, with
  zero actions. Backend smoke only; no browser or physical audio claim.
- Playwright discovers **23 scenarios**, retaining all original assertions, but
  exits before running any worker: `spawn EPERM` in `child_process.fork`.
- The 30000 ms native-zoom benchmark exits on Chromium launch with `spawn EPERM`;
  zero cases completed. Direct isolated Chromium launch also exited before a
  DevTools endpoint appeared. A direct launch diagnostic reports Mojo platform
  channel `Access is denied (0x5)` and a failed Crashpad launch; stderr is retained
  in `.test-artifacts/chromium-diagnostic/stderr.log`. The browser connector
  reports its host unavailable.
  No security settings, user browser profiles or permissions were changed.

Environment readback: Windows 10 build 19045 x64; RTX 4070; NVIDIA driver 616.92;
32 GB RAM; AMD Ryzen 9 7950X3D (16 logical CPUs exposed to this process);
Python 3.11.9; Node 24.19.0; Playwright 1.64.1; installed Chromium binary
156.0.8078.4. Chromium acceleration and refresh rate could not be verified here.

| Native zoom requested | Workload | FPS | p95 ms | Renderer CPU | Whole GPU |
|---|---|---|---|---|---|
| 100% | idle | unavailable | unavailable | unavailable | unavailable |
| 100% | actual Ollama + typing | unavailable | unavailable | unavailable | unavailable |
| 125% | idle | unavailable | unavailable | unavailable | unavailable |
| 125% | actual Ollama + typing | unavailable | unavailable | unavailable | unavailable |
| 140% | idle | unavailable | unavailable | unavailable | unavailable |
| 140% | actual Ollama + typing | unavailable | unavailable | unavailable | unavailable |

Actual native zoom, DevTools traces, presented/dropped frames, screenshots,
Windows minimize/monitor transitions, dragging/typing in a live browser, physical
microphone, TTS audibility and GPU/CPU STT remain unverified for this checkout.
The practical 60 FPS target is not established. Do not commit/merge this repair
until the remaining live checks pass in a browser-capable execution session.

## Reproduce

One-command app start, after dependencies/assets are installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_windows.ps1
```

Run checks and the benchmark sequentially against that server:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd run check:ui
npm.cmd run test:dom
node tests/constellation-metrics.test.mjs
npm.cmd run check:assets
npm.cmd run test:ui
$env:CONSTELLATION_BENCH_MS='30000'
$env:CONSTELLATION_BENCH_OUT='.test-artifacts/canvas-builder-current'
node scripts/benchmark_constellation.mjs
git diff --check
```

`npm.cmd` avoids the disabled PowerShell npm wrapper without changing execution
policy. On `EPERM`, retain the failure log and use a browser-capable DevCrew
session; do not substitute mocks or old measurements for the missing matrix.
Raw local failure/configuration evidence is under `.test-artifacts/canvas-builder-current/`;
the backend smoke summary is `.test-artifacts/ollama-builder-smoke.json`.

The existing [offline demo after asset downloads and troubleshooting](../README.md)
and [40 defense questions with explanatory answers](DEFENSE_QA.md) are preserved.
No models were downloaded; dependency packages were installed only in the local
ignored test environment. Cloud inference, backend/API/security policy and
microphone consent/playback implementation are unchanged.

Primary API references used for this repair: [DPR changes and matchMedia](https://developer.mozilla.org/en-US/docs/Web/API/Window/devicePixelRatio),
[DevTools Frames and Performance reference](https://developer.chrome.com/docs/devtools/performance/reference),
[CDP Tracing](https://chromedevtools.github.io/devtools-protocol/tot/Tracing/).

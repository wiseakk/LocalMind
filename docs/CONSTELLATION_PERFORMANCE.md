# Constellation Canvas performance — 28 October 2026

The measured bottleneck was the scheduler: normal idle animation used an 84 ms
timeout (about 12 FPS), and active animation a 34 ms timeout (about 30 FPS).
This prevented smooth animation even when the GPU had spare capacity. Each
frame also reran pairwise physics, rasterized labels and applied per-node blur.
Those costs become more significant when removing the artificial frame limits.

## Measurement method

Windows 10 build 19045, RTX 4070, NVIDIA driver 32.0.16.1692. Full Playwright
Chromium with D3D11 reported hardware-accelerated Canvas and GPU compositing.
The initial headless-shell run selected SwiftShader and was excluded from the
hardware results. The display's measured rAF cadence was approximately 165 Hz.

The benchmark uses a **disposable project-local browser profile** and a minimal
local extension to call `chrome.tabs.setZoom`. `getZoom` verifies exact 1, 1.25
and 1.4 tab zoom. CSS zoom remains 1. At 140%, viewport dimensions change from
1440x1000 to 1028x714 and devicePixelRatio becomes approximately 1.4. These are
native browser zoom measurements, separate from existing CSS-zoom stress tests.
The extension is not installed in the user's regular browser profile.

Fourteen fixture nodes isolate graph size without launching any application or
uploading a file. The drawer is open. Each case samples six seconds after a
1.5-second graph warm-up, with DevTools Performance traces and GPU utilization
sampling enabled. Ollama cases send a real knowledge question through the app's
streaming endpoint to installed `qwen3:4b`, with a 1536-token response budget.
The runner verifies the final engine is `ollama`; nothing is mocked on that path.
Request windows can include model startup and an idle tail when generation ends;
JSON records the number of rendered frames observed in generating mode.

CPU is Chromium renderer-main-thread TaskDuration divided by its matching CDP
Timestamp interval, expressed as percent of one core. It includes streaming,
rendering and instrumentation. GPU percentages are whole-device NVIDIA samples
once per second, including Ollama, browser and other desktop activity. They do
not isolate Canvas GPU time. Memory samples are also retained in the JSON.

DevTools trace categories: `devtools.timeline,blink.user_timing,gpu`. Import any
`*.trace.json` into Chrome DevTools Performance to inspect CPU/raster/compositor
events. Idle traces showed zero Layout/UpdateLayoutTree events: there was no
evidence of a per-frame layout bottleneck. Streaming produces layout/paint work
for the conversation, which remains independent of the Canvas loop. Blur/text
calls were identified directly in the old pipeline; the new regression test
verifies neither is repeated once caches are warm. No claim is made about their
individual share of the old GPU time.

## Implementation

- Normal animation uses requestAnimationFrame without a 30/60 FPS ceiling.
  Drift and pulse use timestamps. Physics runs fixed 60 Hz substeps, at most
  three after a delayed frame, then settles based on velocity or a five-second
  bound. Settled relationships stop running the pairwise solver.
- Decorative starfield and orientation rings are cached. Labels and blur glow
  sprites are rasterized once per geometry/font/quality invalidation. Dynamic
  node coordinates are reused for edges, bodies and labels. No gradients or
  text measurement are rebuilt during steady animation.
- Logical dimensions use the canvas CSS size. Pointer coordinates are converted
  from its rendered rectangle, keeping dragging correct under CSS zoom. Backing
  DPR is capped at 1.5 with the existing 1.6-million-pixel ceiling. Sustained
  drawing cost above 5 ms reduces the cap toward 1; recovery below 2 ms uses a
  longer hysteresis window. An isolated slow frame does not reallocate caches.
- Document visibility, offscreen intersection, closed drawer and page exit cancel
  pending animation. Explicit economy/reduced-motion modes remain on demand
  when quiet. Economy live audio retains its existing lower update rate.
  Normal visible idle animation stays smooth through cheap cached drawing.
- DOM activity announcements update only on state changes. Audio sampling,
  microphone consent, pause/stop/mute, keyboard graph controls and API contracts
  are preserved. Physical microphone/speaker and GPU STT were not exercised.

## Developer overlay and reproduction

The overlay is absent by default. In browser DevTools Console:

```js
localmindScene.setDiagnostics(true);  // FPS, p95 interval, draw time, backing DPR
localmindScene.setDiagnostics(false);
```

It contains no node labels, paths or document data, is excluded from assistive
announcements, and reports suspension/on-demand state rather than stale FPS.

Start the local app with:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_windows.ps1
```

After the existing model/assets are downloaded, the app and benchmark inference
run locally. Existing offline demo, troubleshooting and 40 explanatory defense
answers remain in README.md and docs/DEFENSE_QA.md.

Run benchmarks sequentially, with no Playwright suite or other generation job
in parallel (those can reset app state or compete for GPU resources):

```powershell
$env:CONSTELLATION_BENCH_OUT='.test-artifacts/canvas-native-before'
$env:CONSTELLATION_BASE_REF='4bcbaef'
node scripts/benchmark_constellation.mjs
Remove-Item Env:CONSTELLATION_BASE_REF
$env:CONSTELLATION_BENCH_OUT='.test-artifacts/canvas-native-after'
node scripts/benchmark_constellation.mjs
```

The baseline option serves only the old renderer/interface from Git into the
benchmark tab, without changing the checkout. Traces, hardware metadata, browser
profiles and raw results stay under ignored `.test-artifacts/`. A committed
numeric snapshot is in CONSTELLATION_PERFORMANCE.json. The benchmark requires
the app on loopback port 8765, provisioned Ollama and local Chromium; it does not
download models or change Windows configuration. If `ERR_CONNECTION_REFUSED`
appears, restart the app and rerun the incomplete matrix. Interrupted and diagnostic-only attempts were excluded; the completed
snapshot is the evidence used below.


## Measured results

Baseline renderer: commit `4bcbaef`. Final normal-mode results, with 14 nodes:

| Zoom | Workload | FPS before / after | p95 interval ms before / after | Renderer CPU % before / after | Whole GPU % before / after |
|---|---|---|---|---|---|
| 100% | idle | 11.8 / 165.1 | 91.0 / 6.1 | 1.75 / 4.39 | 1-9 / 3-25 |
| 100% | ollama | 25.2 / 165.0 | 84.8 / 6.1 | 9.77 / 11.63 | 3-94 / 4-94 |
| 125% | idle | 11.8 / 165.1 | 91.0 / 6.1 | 1.81 / 4.44 | 2-4 / 10-23 |
| 125% | ollama | 23.8 / 165.0 | 84.9 / 6.1 | 9.81 / 11.32 | 2-94 / 17-94 |
| 140% | idle | 11.8 / 165.2 | 91.0 / 6.1 | 1.84 / 4.41 | 5-9 / 8-23 |
| 140% | ollama | 25.3 / 165.0 | 84.8 / 6.1 | 11.47 / 11.45 | 10-94 / 28-94 |

Normal idle now draws about 14 times as many frames. Absolute CPU/GPU use rises
with that higher refresh rate; idle main-thread CPU is about 4.4% of one core.
This is a smoothness improvement with cheaper work per delivered frame, rather
than a claim of reduced total utilization. The final rolling mean Canvas draw
cost was 0.05-0.07 ms. Across the three generation windows the runner observed
713/649/682 rendered frames in generating mode and verified final engine ollama.
GPU inference peaks reached 94%, while the Canvas retained about 165 FPS.
Short sampled windows establish the practical 60 FPS target on this configuration;
long-session behavior, other display/driver combinations and physical microphone /
speaker playback remain outside these measurements.

Verification: all 19 original Playwright scenarios retained, plus two Canvas
regressions: **19 passed, 2 expected skips**. **28 DOM checks** and **391 Python
tests + 35 subtests** pass. JS syntax and diff whitespace checks pass. The new
browser checks cover steady cache reuse, opt-in diagnostics, closed-drawer
suspension, actual root position movement under CSS zoom, and draft typing while
a response is pending. Existing DOM/browser checks retain audio and motion coverage.
Independent review findings in CPU measurement, suspended FPS reporting and drag
test strength were corrected. No backend, security policy, API or model change.

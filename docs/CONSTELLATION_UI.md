# LocalMind Constellation — UI milestone, 2026-10-28

Implementation is in the isolated DevCrew checkout based on `localmind-next-wip`
at `36a4a44`. Backend files, permissions, API schemas and model assets were not
changed. No merge, push, deployment or model installation was performed.
**The browser/visual gate is blocked; this milestone is not fully accepted.**

## Before / after

| Before | Current implementation |
| --- | --- |
| Wide green sidebar, large suggestion cards | Compact rail, near-black/off-white, violet and crimson, quiet suggestion rows |
| One conversation column | Conversation beside an interactive live Canvas constellation; mobile has a scrollable graph section |
| Long settings dialog | Keyboard-operated Model / Voice / Appearance / Access tabs |
| System typography and text-symbol controls | Local Cyrillic Onest and selective Unbounded; first-party rounded SVG vocabulary |
| No attachment input | Selection, file paste and composer drop; bounded in-memory preparation, Canvas image preview, explicit preview processing |
| CSS-only motion preference | CSS plus JavaScript reduced-motion/economical modes, visibility suspension, capped renderer |

This table describes the code and DOM behavior. No before/after screenshot or
video was captured: the available browser paths failed before a usable page.

## What the graph means

The center is LocalMind. Other nodes come from the observed application catalog,
configured devices, the current conversation, explicitly selected attachments,
allowed configured TXT/MD sources, and authoritative tool results. Persistent
memory is not implemented. Decorative stars/rings are atmosphere, not entities
or hidden thoughts. Edges mean that LocalMind has the shown entity in this
session/catalog; the inspector describes that relationship.

Pointer/touch dragging, selection, recentering, native keyboard list selection,
Alt + arrows to move a selected node and a separate move button are implemented.
File names are replaced by numbered types until the user explicitly enables
their display in Appearance. No document content or path is used as graph text.

Generation follows request/stream lifetime. Listening amplitude is sampled from
the existing microphone stream. Speaking amplitude is sampled from the actual
local playback element through Web Audio; no synthetic waveform is used.
If Web Audio analysis is unavailable or its context is suspended, ordinary
playback remains available without a fabricated amplitude. Pause, stop, mute,
chunk completion and page exit release analysis nodes/listeners and playback
URLs. Audio samples were exercised with mocks, not a Windows microphone/speaker.
Transcription is an indeterminate pending state, never a fake partial transcript.
Tool nodes light only after server results; the API has no live tool-start event.

Renderer limits: 36 nodes, at most 35 edges, 52 decorative particles, 1.5 maximum
pixel ratio and 1.6 million canvas pixels. Normal rendering now follows display
refresh using requestAnimationFrame; only explicit economical audio interaction
is throttled to about12fps. See CONSTELLATION_PERFORMANCE.md for real Windows /
RTX 4070 measurements at native browser zoom. Economical/reduced modes
remove physics/drift, and economical mode removes glow. Hidden/offscreen canvas
does not render. No WebGL dependency or continuous Markdown rendering was added.

## Attachments and permissions

Allowed formats: PDF, TXT, Markdown, DOCX, CSV, PNG, JPG/JPEG, WEBP. Limits are
8 files, 10MiB per file and40MiB total, checked before file reads. Supplied MIME
must match extension; an empty MIME is accepted for supported extensions.
Raster headers and dimensions are checked before decoding (16 megapixels and
8192px per side). ImageBitmap is decoded into a small Canvas then closed. No
image URL is allocated, so CSP `img-src 'none'` remains intact. Removal/reset
clears retained Files, previews and timers and invalidates late decode work.

Documents are not parsed/indexed by this prototype. **There is no attachment
upload or model-context endpoint.** Ready means prepared in browser memory.
“Превью обработки” explicitly demonstrates indexing/processing UI, with no real
index, progress percentage, model call, external upload or persistence.

Discovery is read-only and automatic. Existing app grants/revocation,
fingerprints, separate PDF folder read/exact-file open grants and configured
retrieval scopes remain authoritative on the server. Arbitrary-folder and
device-group permission selection is described as unavailable prototype scope;
there are no switches that pretend to grant access. DEMO/REAL is always visible
in the header and the lamp suggestion follows the actual server mode.

## Start and offline demonstration

After the existing one-time setup and explicit model downloads, normal startup
is unchanged:

```powershell
.\start_windows.ps1
```

This isolated checkout has no `.venv`. The existing owner interpreter was reused
without installation for actual startup and tests:

```powershell
& 'C:\Users\ExampleUser\Desktop\LocalMind_MVP_01\.venv\Scripts\python.exe' .\start.py
```

Open `http://127.0.0.1:8765`. Existing offline setup, model downloads,
troubleshooting and defense material remain in README.md, docs/VOICE.md,
docs/DEFENSE_QA.md (40 explanatory questions) and docs/DEFENSE_CHEATSHEET.md.

For this UI demonstration, no new model is needed: inspect the constellation,
drag/recenter nodes, select/paste/drop a disposable TXT or image, try “Превью
обработки”, remove it, and exercise Appearance settings. To test the existing
offline dialogue/voice, first provision the existing local assets explicitly;
the UI does not download them. The DEMO lamp can be exercised with action
composition disabled without Ollama. Never use a REAL device as a simulation.

## Actual verification

- Backend baseline and post-change:391 passed,35 subtests passed. One existing
  pytest cache-write ACL warning. Mocks are not real Ollama/HA integration.
- JavaScript syntax: `npm run check:ui` passes for all seven first-party modules.
- DOM:28 behavior checks pass, including existing replay/deduplication, editable
  speech, speech queue/cancellation, XSS/Markdown and the new attachment, graph,
  permissions and reset races. Canvas/audio tests use explicit mocks.
- `npm run check:assets`:76 linked assets resolve locally; both TTF headers and
  original licenses checked. `docs/evidence/constellation/local-assets.json`
  records file sizes and hashes.
- Real loopback startup succeeded; all76 resources returned HTTP200 and bytes
  matching the checkout. `http-assets.json` records that check and the unchanged
  restrictive CSP. This is not a browser rendering/network test.
- `npm ci --cache .npm-cache --no-fund --ignore-scripts` completed; audit reported
  zero vulnerabilities. No dependency changes were needed.
- Independent tester/reviewer exercised async microphone reset, stale STT
  errors, reset/send concurrency, both catalog-grant race orders, paused audio,
  hidden scheduling, safe rendering and truthful DEMO labeling. Found defects
  were fixed and regression checks pass. No unresolved security issue was found
  in this scoped review.
- Real local DEMO stream API succeeded without LLM composition; the original simulated lamp state was restored. See `demo-http.json`. No physical device was controlled.
- No separate build/typecheck/lint configuration exists for this static JS app;
  syntax, DOM, asset checks and `git diff --check` are the applicable checks.

## Blocked browser gate and troubleshooting

`npm run test:ui` collects the browser scenarios but worker startup fails with
`Error: spawn EPERM`. Browser installation via Playwright also fails spawning
its downloader. Official headless Chromium was downloaded to ignored
`.browser-cache/` using Python; it was never added to the application bundle.
An independent headless launch reports `FATAL:mojo...platform_channel.cc:112:
Access is denied (0x5)`. CDP verification times out or reports a closed target.
Both normal and single-process attempts failed. Test browser processes were
stopped; no OS permissions or security configuration were changed.

The connected browser host is unavailable. Native Zen access was rejected by
automatic approval review: `Computer Use was not approved to use Zen`. No Zen
input was sent. None of these failures establishes a rendering defect or a pass.

Screenshots/video, real desktop/mobile rendering, actual100/125/140% browser
zoom, real image decoding under CSP, touch/focus appearance, blocked-external
HTTP browser run, measured animation smoothness and a local-generation browser
performance trace remain **not tested**. Real Windows microphone, physical
audio output, RTX4070/GPU STT and real HA devices also remain **not tested**.

On a host that permits Chromium, with the server running:

```powershell
npm ci --cache .npm-cache --no-fund --ignore-scripts
npx playwright install chromium
npm run test:ui
npm run test:ui -- --headed -g 'real browser zoom'
$env:LOCALMIND_REAL_GENERATION='1'
npm run test:ui -- -g 'optional real Ollama'
```

Browser tests block every non-origin HTTP(S) request before navigation and
assert no attempts. Existing rich-text XSS coverage is retained. Screenshots
are saved under `test-results/` only after real rendering. Mock generation and
optional actual Ollama performance traces are explicitly separate. CSS scale
stress at100/125/140% is labelled CSS scale; it is not true browser zoom.
Chromium browser chrome has standard zoom steps, so manually verify the exact
requested140% in a browser supporting that value. Do not change OS permissions
or weaken host isolation to make these checks run.

Stop at this UI milestone. The next step is browser/hardware verification on a
permitted host; do not merge or call the whole assistant finished based on DOM
tests. No TTS model installation or backend rewrite is part of this change.

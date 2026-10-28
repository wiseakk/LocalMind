# Overhaul delivery evidence — 28 October 2026

The implementation is preserved in the existing checkout based on `6ee4231`.
The full requested acceptance is **not established**: three-model comparison,
measured default selection, real voice and visual-browser gates are incomplete.
No improved conversational accuracy or comparative speed is claimed.

## Changes that are implemented

- Russian token grammar: politeness, punctuation, morphology and modal questions;
  exact catalog targets, whole-request consumption, independent permission checks.
- Image/session/SID process identity, visible/background/unknown states and locked
  inspection-plus-launch. Existing/pending/unknown state suppresses duplicate
  launches independently of request IDs. No process termination was introduced.
- Per-request installed-local model selection, off/on/auto reasoning, bounded
  context (1024–8192), response budget (64–2048) and keep-alive (0–900 seconds).
  Missing/remote models fail explicitly; completed actions are never replayed.
- Actual conversational text deltas with bounded sequenced replay; immutable
  action results are composed separately, fully validated before display/speech.
  Simple acknowledgements use non-thinking requests capped at256 tokens.
- Sanitized offline Markdown/KaTeX, functional pending/listening states, closed
  diagnostics and simple trusted action feedback, simulation label and mute/stop.
- Frozen36-case Russian corpus,6 held-out paraphrases,10 intent cases; retained
  prompts, answers, rubrics, measurements, errors and model-download evidence.

## Verified

- `python -m pytest -q`:297 tests and35 subtests pass; cache ACL warning only.
- `npm.cmd run check:ui`:passes. `npm.cmd run test:dom`:six checks pass, including
  live Markdown deltas, settings snapshots and interrupted-stream replay.
- `npm.cmd audit`:zero vulnerabilities. Final diff whitespace check is recorded
  in STATUS. No separate lint/type checker/build is configured by this project.
- Real `start.py`:loopback startup successful. `scripts/smoke_local.py`:DEMO
  action status2ms, validated commentary3277ms, identical JSON/stream replay,
  safe-close refusal. These are single observations, not performance percentiles.
- `scripts/check_overhaul.py --steam`:actual dialogue first API answer delta
  671.3434000012057ms, final2604.090200000428ms (108events), identical replay,
  follow-up, explicit missing-model error and DEMO commentary.
- Actual Steam catalog permission was temporarily granted and restored. Four
  positive/polite requests, including concurrent distinct IDs, returned
  `inspection_unavailable`; negative/quoted/hypothetical/compound commands
  executed nothing. This verifies safe uncertainty handling, not successful
  visible/background Steam operation. Unit/native simulations cover startup
  races, exit, PID reuse, denied access and changed targets separately.
- Independent adversarial checks found and verified fixes for false factual
  prose, compound aliases, invalid Unicode and unbounded unterminated streams.

## Remaining gates and exact measurement limits

Only qwen3:4b finished evaluation. Paired median cold3747.9755ms versus
warm1426.658ms; Ollama reported100%GPU. CPU fallback was also actually exercised.
These are observations of one model, not evidence of an optimization over the
previous application. Objective screening39/52 is not semantic accuracy; Builder
AI dialogue review27/42 is not an independent human evaluation. Actual answers
still fail RSA/dumpling regressions. All details are in MODEL_COMPARISON.md.

qwen3:8b and qwen3.5:9b asset downloads repeatedly stall/retry and roll back
partial chunk counters. A reconnect was attempted; incomplete asset bytes and
sanitized Ollama stall logs are retained. Our stalled download clients were
stopped; partial assets remain resumable. No winner is selected from unmeasured
candidates. `qwen3:4b` remains the prior compatibility default only.

Playwright cannot spawn its worker (`spawn EPERM`). Connected browser host is
unavailable, and computer use rejected Zen access as unapproved. Consequently
browser-visible first-text, screenshots, zoom100/125/140%, keyboard and actual
reduced-motion visual gates remain unverified. DOM tests do not replace them.
Current checkout reports no ready STT model or Piper voice: microphone, edited
human transcript→action→speech, playback and GPU-STT coexistence remain unverified.
Model response prose is conservatively validated, not formally proven truthful
for every possible natural-language paraphrase. No real HA hardware was touched.

## Start, offline demo and troubleshooting

In this provisioned worktree (no `.venv` here), one command:

```powershell
& 'C:\Users\ExampleUser\Desktop\LocalMind_MVP_01\.venv\Scripts\python.exe' start.py
```

After normal installation use `./start_windows.ps1`. Open http://127.0.0.1:8765.
Offline demo after model/assets download: keep Ollama running, ask a text
question, toggle the clearly labelled DEMO lamp, inspect diagnostics, then review
and permit an installed catalog app. Voice additionally requires the local
STT/Piper assets documented in VOICE.md. Fully disconnected-network operation
was not exercised in this run.

Git staging failed with the exact restriction:
`fatal: Unable to create 'C:/Users/ExampleUser/Desktop/LocalMind_MVP_01/.git/worktrees/devcrew-LocalMind_MVP_01-20261028-161515-388f25de/index.lock': Permission denied`.
No commit was created; all implementation/evidence files remain in this worktree.

If a model is absent or Ollama unavailable, install/start it explicitly and choose
the local model in Settings; there is no cloud fallback. If app inspection is
unavailable, check the app manually in a normal Windows desktop session. If
reasoning exhausts the token budget, increase it in Settings or use fast mode;
reasoning is not an accuracy guarantee. Use `npm.cmd` when PowerShell blocks
`npm.ps1`; do not weaken execution policy. Resume evaluation with the command in
MODEL_COMPARISON.md. Existing40 explanatory defense answers remain in DEFENSE_QA.md.

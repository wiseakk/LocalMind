# LocalMind — инструкции для DevCrew / Codex-агентов

**Read first:** `docs/DEVCREW_MASTER_MISSION.md`, `docs/QUALITY_GATES.md`, `docs/USER_FAILURES.md`, `docs/STT_TEST_SET.csv` and `docs/CONFERENCE_2026_NOTES.md`. These are the binding product requirements for this repository.

You are developing a real, locally hosted voice assistant for a student scientific conference. The user's core request is quality, correctness, understandable code, safe app automation and Russian speech recognition. Optimize for a stable, demoable result rather than maximal features or long reports.

Constraints:
- Preserve a runnable version throughout. Do not replace the working app with untested rewrites.
- Work in small isolated commits/worktrees using the owner's DevCrew orchestrator; Architect → Builder → Tester → Reviewer → Security; Visual QA when available. Git worktree merge only after gates pass.
- Maintain `docs/STATUS.md` and `docs/DECISIONS.md` after EVERY milestone; never say "finished" if Windows microphone or GPU has not actually been tested.
- Test code rather than trusting LLM completions. Keep `python -m pytest -q` green. Mock Ollama/Home Assistant in CI; don't claim mocks are real integration tests.
- Zero arbitrary shell commands, arbitrary OS commands, arbitrary LLM-supplied paths/URLs or destructive actions. Tools are declared, validated, and user-authorized. Never pass raw model output to subprocess, PowerShell, eval or shell.
- Human-confirm high-impact operations; app close must be safe, avoid data loss; no force-killing all windows via `taskkill /IM /F` by default.
- Zero cloud STT/TTS/LLM by default. Models may be downloaded on first setup; distinguish download from inference in reports. No telemetry/audio retention by default.
- Windows 10/11 first, RTX 4070 12 GB + 32 GB RAM target; test CPU fallback. Do not assume all Windows users have CUDA libraries.
- Development with AI is allowed; document what code the student can demonstrate and explain. Do not fabricate benchmarks, transcript accuracy, hardware, partner feedback or test results.
- Work on user-supplied computer only. Do not touch user personal files or system configurations without explicit permission.
- Final output must include a one-command way to start, offline demo (after assets downloaded), troubleshooting, and at least 20 defense questions with explanatory answers.

Entry command for first run is `DEV_CREW_START.txt` (paste to DevCrew Studio). The detailed mission is source of truth.

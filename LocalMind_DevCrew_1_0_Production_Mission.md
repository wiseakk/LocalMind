# DEV CREW — LocalMind 1.0: Product-Quality End-to-End Build

**Repository:** the EXISTING Git repository selected in DevCrew Studio (LocalMind_MVP_01 on Windows). Do not create a parallel project, do not discard user changes, and do not reset to a previous archive.

**Mission:** Turn the currently running LocalMind prototype into a polished, truly local Russian-language AI desktop companion with a clear student-engineering architecture and repeatable tests. The user wants DevCrew to perform engineering, debugging, QA, and UI review end-to-end rather than repeatedly asking them to apply tiny patches. Use Architect → Builder → Tester → Reviewer → Security → Visual QA (if available). Perform safe incremental milestones and keep the application runnable throughout.

## Read this before changing code

Read `AGENTS.md`, `docs/DEVCREW_MASTER_MISSION.md`, `docs/QUALITY_GATES.md`, `docs/USER_FAILURES.md`, `docs/STT_TEST_SET.csv`, the current README, `localmind/agent.py`, `localmind/server.py`, `static/index.html`, `package.json`, `scripts/vendor_ui.mjs`, and the current test suite. Detect files absent in older revisions and adapt instead of failing. Check `git status --short`, `git log -3 --oneline` and the current working tree. Respect the existing security hardening commit `26ee673` if it is in the checkout. Preserve later UI changes, including vendored offline `marked`, `DOMPurify` and `KaTeX` if present.

**Immediate regression to check:** A prior patch once created the invalid import `from fastapi.staticfiles import StaticFiles, JSONResponse`. It must be two separate imports: `StaticFiles` from `fastapi.staticfiles`, `JSONResponse` from `fastapi.responses`. Fix any lingering import errors, run test collection, and confirm app startup before feature work.

## Priority 0: Make LocalMind genuinely conversational AFTER real actions

The user explicitly does NOT want a cosmetic Python/JavaScript template that adds "Готово!" before a rules response. Instead, after a deterministic authorized action (open app, safe close, light toggle, later Home Assistant), pass a structured **trusted tool-result summary** into the local Ollama LLM (no tools exposed in the response-generation call). Let the model formulate a short, natural, contextually appropriate Russian answer **grounded strictly in the outcome**.

Required architecture:

1. STT or typed user input -> explicit review/submit for voice -> centralized intent + permission + target validation -> deterministic action execution -> typed `ActionResult(success, action, resolved_target, observed_state, error, duration, ...)` -> **separate non-tool Ollama response composer** -> UI + optional TTS.
2. The action must be executed **at most once**, even if generation retries/fails. Do not let the LLM generate executable shell/PowerShell commands, arbitrary paths, or repeat calls. Never claim success on failure or that a state has been observed if the adapter only sent a request.
3. UI displays truthful deterministic action status immediately; AI commentary follows asynchronously. On LLM timeout/error, retain correct result and gracefully fall back to a concise safe status. Store a visible technical trace separately from the conversational message.
4. Natural dialogue examples (do not hardcode these as response templates): “Открой блокнот” -> actually launch -> “Блокнот открыт. Можешь диктовать заметку или продолжить работать.”; “Включи лампу” -> toggle simulator -> “Включил настольную лампу. Сейчас она горит.”; on denied or failed action -> natural but truthful explanation with next step. Never claim an application was launched simply because a command was recognized.
5. Keep general educational questions fully conversational ("Что такое RSA?", "Как сварить пельмени?") and never mix them with tool authorizations. Improve accuracy by testing factual answers; do not assume better UX means correctness.
6. Add settings for response length (Brief / Normal / Detailed) and, if practical, a toggle for AI-generated action replies vs deterministic fallback. Track LLM response latency without hiding action execution latency.

## Priority 1: Redesign UI as a quality app, not static HTML

Current UI has useful Markdown/LaTeX but looks dated, with almost no animations. Create a deliberate professional, responsive desktop interface in Russian — smooth restrained motion, high-quality spacing/typography, clear visual hierarchy, action/status chips, modern side panel/settings, dark-mode aesthetic, good phone/tablet layout if time permits.

Must implement **functional** animations and states: new-message entrance, typing/streaming indicator, microphone recording pulse and listening/processing states, gentle transitions on sidebar/cards/buttons, hover/press interactions, status feedback for real actions, error/permission dialogs, loading skeleton or spinner, smooth scroll, optional audio visualizer if backed by real input. Use CSS transforms/opacity over expensive effects. Respect `prefers-reduced-motion`; keep animations fast and purposeful, no blinding neon or infinite bouncy effects.

Maintain safe offline Markdown and mathematics rendering with local assets only. Correctly display fenced code, lists, headings, tables, inline `\(...\)`, display `\[...\]` and `$$...$$` mathematics; consider `$...$` ambiguity thoughtfully. Preserve raw text fallback and protect against XSS (`DOMPurify` / safe rendering). Ensure no scripts or styles load from external CDNs. Use Playwright or another available browser automation to inspect screens and record visual QA where feasible; if unavailable, document exact manual checklist.

The chat should not duplicate the same user utterance as both a "draft" and a sent message; speech transcript review should be an editable draft in the input area until submitted.

## Priority 2: Better Russian speech recognition + fully local voice loop

Replace unconfigurable tiny Whisper behavior with testable profiles (CPU fast, balanced, higher-accuracy/GPU where actually supported), robust WebM decoding, voice activity detection, recording/timeout/error handling, correct Russian language selection, and vocabulary for uncommon names ("пельмени", "Codex", "Obsidian", "Visual Studio Code", "Discord"). Preserve the confirmed PyAV compatibility pin until verified otherwise. User edits uncertain transcripts before actions. Don't use English-only models for Russian.

Add offline Russian TTS with start/stop/mute, sensible voice selection and clear licensing/model setup. Prefer a sustainable local engine such as Piper if available, but evaluate actual compatibility. Clarify that web browser voices may be cloud-backed; do not advertise them as guaranteed offline. If local audio/model assets aren't installed, show setup instructions rather than silently falling back to online services. RTX 4070 12 GB VRAM is shared with Ollama; choose memory-aware defaults and test real GPU vs CPU fallback on the owner's PC rather than inventing performance results.

## Priority 3: Real installed Windows application catalog

Discover installed user apps from Start Menu/Desktop and supported Windows registration locations, with normalized names, aliases, stable IDs, verification and a visual permission picker; support Codex, Obsidian, Discord, VS Code *when actually installed*. Do not claim that an app exists if not detected. Disambiguate "Codex CLI" vs GUI/editor vs website. Use verified safe targets and non-shell APIs. Never execute arbitrary user/model-supplied commands, scripts, URLs, uninstallers or dangerous launchers. Permission decisions belong to user + server, not the LLM. Never force-kill unrelated processes or close Notepad with unsaved content.

## Priority 4: Robust tests, security and reproducible demonstration

Preserve all existing P1 fixes: no global taskkill, no PATH-dependent untrusted process launch, no automatic OS execution from unreviewed STT, no unsecured LAN bind. For voice, the front-end must show an editable draft before submission. For text, explicit sending can be authorization for a precisely parsed non-destructive command; for high-impact/ambiguous actions require an additional confirmation. Audit direct `/api/chat` calls too. No raw LLM tool execution.

Have Tester build deterministic unit/integration tests with Ollama/STT/TTS mocks plus actual optional local smoke tests. Test positive and negative commands; quoted commands, negation, "как открыть", errors, offline mode, timeouts, wrong tool result and repeated clicks; static asset paths, sanitization/XSS, KaTeX rendering, client responsive layout, basic accessibility and `prefers-reduced-motion`. Record real numbers (STT WER/CER, recognition and model latency, peak RAM/VRAM where measurable) only after experiments. No fabricated benchmark or external reviewer endorsements. Separate test-mocked success from real hardware results. Include a ready demo script and at least 20 technical jury questions with clear explanations suitable for a 10th-grader.

## Implementation / QA contract

- M0: inventory and baseline; ensure the existing app and tests run; fix import/version issues; create rollback point. Record in docs.
- M1: typed ActionResult + LLM post-action composer + fast truthful status and fallback. Test no double action and no fictional success.
- M2: new design system, animation states, responsive layout, offline Markdown/KaTeX and sanitization. Visual QA.
- M3: Russian STT profiles, transcript review, local voice output, graceful fallbacks. Quality tests and settings.
- M4: detected-app catalog, aliases, permissions, safe launcher and relevant UI.
- M5: end-to-end tests, docs, performance experiment tooling, offline smoke demo, release notes and presentation/defense walkthrough.

After EACH milestone: implement -> run test suite -> fix regressions -> have Tester/Reviewer/Security review -> record in `docs/STATUS.md` and `docs/DECISIONS.md` -> commit a coherent working snapshot, if permissions permit. Use worktrees as configured, avoid modifying the base tree directly if DevCrew policy forbids it. Do not auto-merge without owner approval.

If an unavailable mic/GPU or real smart-home device prevents *hardware verification*, continue implementing and testing independent tasks, report that specific verification as pending, and provide one concise manual smoke script. Do NOT use inaccessible hardware as a reason to skip unrelated deliverables. If there is an actual P0/P1 safety defect, prioritize fixing it before proceeding, not hiding it. If the Architect in this DevCrew policy is read-only and blocks because a vulnerability exists, provide a concrete patch-ready blocker report; a coding agent must then remove the defect before the next full run.

**Acceptance is NOT** a polished README, a collection of hardcoded "Готово" strings, green mocks only, or screenshots of an untested interface. **Acceptance requires** a runnable application; deterministic secure actions; a genuine separate Ollama-based natural-language reply using the observed result; offline-safe rich chat; thoughtful animated UI; tested STT flow; documented TTS/catalog availability; meaningful tests; and a clear statement of still-unverified integrations.

Final report must state: changed files, current commit(s), precise install/start commands, exact test output, demo steps, security findings, what works locally vs mocks, remaining known issues and instructions for one clean acceptance run. Avoid repeatedly soliciting human guidance for ordinary errors: investigate and self-repair within repo/sandbox limits. Do not claim that user-visible production features are finished when only simulated.

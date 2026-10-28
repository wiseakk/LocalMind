# M1 — grounded responses and request lifecycle

Implemented on 2026-10-28 in the existing checkout. This report records code and mocked verification, not a real Ollama, microphone, GPU, application-window or Home Assistant integration claim.

## Implemented behavior

`localmind/results.py` defines immutable `ActionResult`: success, action, resolved target, execution status, observed state, safe error, REAL/DEMO mode, duration and deterministic status text. The DEMO lamp has an observed simulated state. Windows process creation and Home Assistant HTTP acceptance have no observed window/device state. Closing applications still refuses safely.

`agent.prepare_reply(...)` performs authorization, strict intent parsing and one deterministic dispatch. Its `PreparedReply.initial` is JSON safe and contains the truthful status before generation begins. `agent.complete_reply(prepared)` has no execution branch. `reply(...)` wraps those phases for compatibility. Legacy `answer`, `engine`, `actions`, `latency_ms` remain; `status`, `action_results`, `commentary`, `action_ms` and `llm_ms` expose the distinction between execution and commentary.

The tool-free Ollama composer receives structured result facts and a separately labelled untrusted request. JSON outcome echoes must match the trusted result, including strict Boolean types. Empty/malformed replies, tool calls, contradictory facts, obvious success claims after refusals, unobserved window/device claims and omitted DEMO disclosure fall back to deterministic status. Failure details never include remote response bodies, tokens or raw exception strings. This is a conservative language guard, not a proof of arbitrary model factual correctness; the authoritative status always remains separate.

Response lengths are brief (400 characters), normal (1,200) and detailed (2,600), with bounded model generation. Ollama connections use loopback HTTP only, ignore environment proxy variables and use connect/read timeouts. Structured composer output uses Ollama's `format` JSON schema with exact outcome enums; `think: false` avoids consuming the response budget on thinking. Both parameters were checked against the [official Ollama chat documentation](https://docs.ollama.com/api/chat). Educational dialogue remains tool free. A failed generation never re-enters dispatch.

Catalog aliases are available only for detected targets. Exact full names can resolve a shared short alias; two exact matches are denied. Built-in Notepad/Calculator aliases stay reserved for their separately verified system-directory launcher. Catalog launch permission is enforced again inside the catalog, including direct API-triggered requests.

## Shared request store integration

Create one `RequestStore(capacity=128, workers=4, ttl=300)` and share it between JSON and streaming routes. Call:

```python
entry = store.begin(
    request_id,
    fingerprint,
    lambda: prepare_reply(text, history, actions_authorized, response_length, compose_actions),
    complete_reply,
)
```

The fingerprint must cover all relevant request fields. Both `entry.initial` and `entry.final` are `concurrent.futures.Future`; async routes can use `await asyncio.to_thread(entry.initial.result)` and then the final future. Map `RequestConflict` to HTTP 409 and `RequestBusy` to HTTP 429. Emit the initial status before awaiting commentary. A connection-specific cancellation cannot cancel these shared futures. Background work survives the submitting connection leaving. Unexpected composer defects preserve the trusted initial result as the final fallback.

Concurrent identical IDs share one execution, including after a generation failure. Changed content with the same ID is rejected. The store never evicts executing or unexpired IDs to make room. Capacity and concurrency are both bounded. IDs expire five minutes after completion; this is deliberately in-process idempotency, not crash-persistent exactly-once execution. Clients must never automatically retry after a server restart, or outside the advertised retention window, when the action outcome is unknown. Requests without an ID are independent submissions.

## Actual verification

Provisioned interpreter used because this worktree initially had no `.venv`:

```powershell
& C:\Users\ExampleUser\Desktop\LocalMind_MVP_01\.venv\Scripts\python.exe -m pytest tests/test_responses.py tests/test_apps.py -q -p no:cacheprovider
```

Actual recorded output at this milestone: **48 passed in 1.49s**. A repeat after explicit schema/request-body assertions passed **48 tests in 1.45s**. Earlier legacy-agent plus response verification before the UI script extraction: **33 passed, 35 subtests passed in 0.36s**. The old inline-STT source assertion needed adjustment after the UI moved to `app.js`; this was reported to the integrating Builder. Final full-suite/browser results belong in `docs/STATUS.md` after integration.

Focused tests cover initial result before generation, real tool-free composer inputs, malformed/contradictory responses, truthful denial, timeout without repeated dispatch, preview without execution, process creation without window observation, HA acceptance without observed state, proxy avoidance, concurrent duplicate IDs, changed-content conflict, capacity limits, disconnect cancellation, unexpected composer defects, dynamic alias ambiguity, permissions and built-in alias shadowing. HA, launches and model output are mocked in these tests.

## Actual local Ollama smoke

Read-only `GET http://127.0.0.1:11434/api/tags` succeeded and reported `qwen3:4b`. An actual separate composer call after a DEMO lamp operation succeeded after the initial deterministic result. Measured in that run: action **1 ms**, LLM **1,000 ms**, total **1,001 ms**. Actual generated answer: «В демо-режиме настольная лампа успешно включена. Состояние подтверждено.» This demonstrates local model integration and simulated lamp state, not a physical lamp, GPU usage or STT/TTS integration.

An actual safe-close refusal also went through the separate composer without any close/termination attempt: action/assessment **1,297 ms** (included first catalog discovery), LLM **1,161 ms**, total **2,459 ms**. Its generated reply retained the refusal and manual-close advice. These are individual smoke timings, not a benchmark. An earlier unstructured response attempt fell back truthfully; structured schema generation was added and the successful smoke above was rerun. No model thinking content is surfaced in the UI or saved as an artifact.

## Review repairs

Independent review identified shared-future cancellation as a replay defect and fixed it with non-cancellable execution-owned futures plus a focused regression. A separate regression verifies preserved status after an unexpected composer exception. A catalog-refresh race could remove a target between matching passes; matching now denies a missing target instead of indexing it. Conservative success-verb matching was corrected so the Russian infinitive «закрыть» and noun «закрытие» do not incorrectly reject safe-close explanations. Catalog review identified a stat-before-read size race and console executables being mistaken for GUI applications; its owner added a cumulative hashing limit, PE GUI-subsystem checks and adversarial tests. No unresolved critical issue was established in the reviewed response/deduplication subset. Full integration acceptance and arbitrary model factual quality remain separate checks.

A later adversarial review supplied the contradictory denial commentary «Всё выполнил, окно блокнота больше не работает.» while the JSON facts correctly echoed failure. Failure commentary now requires an explicit Russian refusal/failure anchor and rejects additional completion stems (`выполнил`, `выполнено`, `исполнил`, `сработало`, `успех`). Seven adversarial paraphrases are covered, including a refusal followed by a completion claim. Response tests after this repair: **29 passed in 1.39s**. These lexical checks remain conservative heuristics; they cannot establish the truth of arbitrary model paraphrases. The deterministic action result must remain authoritative in chat and speech, and failed-action speech should use the trusted refusal status so a model cannot announce a fictional success through audio.

## Educational dialogue repair and factual limitation

The integrating Builder's actual smoke found Qwen3 returning visible answer-planning prose and stopping before the useful answer. Educational dialogue now also uses a tool-free JSON schema, with one `answer` string. It decodes that field, never exposes `thinking`, rejects malformed/empty envelopes and obvious self-instruction prefixes, and preserves Markdown/math inside the string. Length limits prefer the last complete sentence, or a word boundary with an ellipsis, instead of cutting blindly inside a word. The prompt requests the actual operation asked for and explicit uncertainty when information is insufficient; no canned topic answers or topic-specific reference cards were added.

Read-only inspection of `/api/show` found this provisioned `qwen3:4b` template always appends an opening think block. For the exact `qwen3` model family, the request adds an empty assistant think prefill without changing user history or installed model files. This follows [Qwen's documented non-thinking assistant-prefill method](https://github.com/QwenLM/Qwen3/blob/main/docs/source/inference/transformers.md); other configured model names do not get the prefill. `think: false` remains set.

Actual direct local-model checks after schema/prefill produced ready RSA explanations without answer-planning prose (one run: **1,629 ms**, no actions). The explanation correctly distinguished public encryption and private decryption keys. A DEMO action composer still succeeded with the prefill (**4,083 ms** LLM in that individual run). These timings are observations, not benchmarks.

**Known factual limitation:** actual `qwen3:4b` cooking replies remained unreliable. A broad pelmeni question produced incorrect preparation steps; even a more explicit frozen-product question mixed correct boiling basics with inaccurate doneness wording. Prompt changes did not establish reliable factual accuracy. The app must not present generated educational answers as verified facts. This remains a model-quality limitation; schema validation proves response structure, not factual truth. Real microphone/GPU/TTS/physical-device checks are still separate.

Focused verification after the educational repair:

```powershell
& C:\Users\ExampleUser\Desktop\LocalMind_MVP_01\.venv\Scripts\python.exe -m pytest tests/test_responses.py tests/test_agent.py -q -p no:cacheprovider
```

Actual output: **60 passed, 35 subtests passed in 1.61s**. These tests cover schema decoding, hidden-thinking separation, malformed envelopes, self-instruction rejection, sentence/word truncation, Qwen-only request-local prefill, and preserved tool-free legacy tests. They do not establish factual correctness for arbitrary questions.

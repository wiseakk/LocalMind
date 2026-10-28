# Russian conversation and Ollama measurements — 28 October 2026

This is actual evidence from this checkout and this Windows computer. The comparison is **incomplete because the two required model downloads repeatedly stalled, including after a bounded reconnect**. The pull clients were stopped; partial assets were preserved. No higher-quality default has yet been selected; `qwen3:4b` is retained only as the existing compatibility default. Its measured failures make it unsuitable for a claim that the requested intelligence overhaul has passed.

## Reproduction and frozen protocol

```powershell
$lmPython = 'C:\Users\ExampleUser\Desktop\LocalMind_MVP_01\.venv\Scripts\python.exe'
& $lmPython scripts/eval_llm.py --pull --tuning --output docs/evidence/llm-2026-10-28.json
# After interrupting a download, retain completed candidates:
& $lmPython scripts/eval_llm.py --pull --tuning --resume --output docs/evidence/llm-2026-10-28.json
```

`--pull` explicitly downloads missing assets through the local Ollama daemon. Downloads require internet; inference calls only loopback with proxy inheritance disabled. The CLI accepts only the four declared candidate names, rejects cloud-tag names before HTTP, and rejects installed tags/show metadata containing `remote_host` or `remote_model` before inference; loopback alone is not treated as proof of local execution. Failed model metadata inspection prevents inference. The evaluator executes no application or device actions. `--limit` is for smoke checks and cannot establish complete quality. Unrelated resident models are never unloaded. Required candidates run sequentially, and each candidate is unloaded before the next one to avoid simultaneous large-model residency. Evidence writes use a same-directory atomic replacement so an interrupted write preserves the prior complete snapshot.

The versioned corpus is [`tests/data/russian_llm_v1.json`](../tests/data/russian_llm_v1.json), SHA-256 `7939db41b216fdb23d268076fc4b9c276be8812d4cf84ad9951612f581308b15`. It was frozen before the comparison: 36 cases equally divided among facts, practical everyday help, contextual follow-ups, mathematics, code and natural dialogue; six additional held-out dialogue paraphrases; ten intent proposals, including positive, negated, quoted, hypothetical and multiple-target forms. All five required regressions are included. Held-out cases were not used to adapt the prompt during this run; they are now public regression cases and are not a future blind test.

Every dialogue answer must satisfy its rubric without a material factual error, invented observation or fabricated memory. Regex checks screen obvious failures, **not semantic accuracy**. The separate [`llm-review-2026-10-28.json`](evidence/llm-review-2026-10-28.json) records Builder AI adjudication of every retained dialogue answer. An independent human review has not occurred. Naturalness uses the frozen 0–2 scale; these ratings are AI judgments, not measured human preferences.

Comparison uses the application-equivalent system prompt snapshot and JSON `{"answer": "..."}` schema, temperature `0.2`, seed `42`, context `4096`, response budget `384`, `think:false`, keep-alive `5m`, streaming. The application response budget can differ; **384-token comparison results cannot substantiate a 768-token production configuration without further checks**. Each request and full answer/error is retained. Installed Qwen3 templates require a recorded closing-think assistant prefill; Qwen3.5 does not receive a Qwen3-specific prefill. The benchmark records both the requested mode and `/api/show` support rather than assuming that `think:false` is honored.

Each category has one paired cold/warm prompt, six pairs per candidate. Cold means unloaded from Ollama, checked with `/api/ps`; it does not mean cleared OS disk cache or first download. Warm immediately follows the same cold prompt, allowing prompt-cache reuse. The complete corpus follows those pairs, one request per case; there are no confidence intervals from these single observations. Performance tuning is retained separately from comparison runs.

## Computer and available results

Windows 10 build 19045, 33,408,708,608 bytes physical RAM, NVIDIA RTX 4070 with 12,282 MiB VRAM, driver 616.92, Ollama 0.40.12. CPU identifies as AMD64 Family 25 Model 97 Stepping 2, AuthenticAMD. WMI marketing-name queries were denied; no CPU model name is invented. RAM snapshots measure the whole system, not isolated model allocation.

| Candidate | Asset/measurement status | Objective screening | Builder AI dialogue review | Exact intent JSON | Naturalness |
|---|---|---:|---:|---:|---:|
| qwen3:4b | Measured, Q4_K_M | 39/52 (75.0%) | 27/42 (64.3%) | 5/10 | 1.36/2 |
| qwen3:8b | Asset unavailable after stalled pulls; not measured | unavailable | unavailable | unavailable | unavailable |
| qwen3.5:9b | Asset unavailable after stalled pulls; not measured | unavailable | unavailable | unavailable | unavailable |

`qwen3:4b` digest is `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`; installed weights 2,497,293,931 bytes. `/api/ps` reports 3,180,247,121 bytes total and the same bytes in VRAM at 4096 context; `ollama ps` reports **100% GPU**. There was no observed partial CPU offload in those comparison samples and no OOM. Whole-GPU memory sampled during the run ranged 2,021–5,238 MiB, utilization 25–99%; whole-system used RAM ranged 14,061,289,472–15,021,162,496 bytes. Other desktop workloads contribute to these totals. Sampler snapshots are retained; they are not per-kernel CUDA traces.

## Exact qwen3:4b latency observations

All times below are milliseconds measured with `perf_counter`; the table reports individual observations, not rounded performance claims. Generated token count and token rate are from final Ollama API metrics. All per-request load/prompt-evaluation nanoseconds and RAM/GPU samples remain in [`llm-2026-10-28.json`](evidence/llm-2026-10-28.json).

| Case | Cold total | Warm total | Cold load | Warm load | Cold generated tokens | Warm generated tokens |
|---|---:|---:|---:|---:|---:|---:|
| RSA | 7340.644 | 4078.112 | 1986.9994 | 1.8902 | 281 | 223 |
| Dumplings | 5475.871 | 3245.636 | 1958.9168 | 2.0001 | 180 | 174 |
| Encryption follow-up | 3531.363 | 1332.732 | 1971.5003 | 1.7013 | 71 | 71 |
| 17 × 23 | 3341.784 | 1176.793 | 1964.4637 | 2.0028 | 62 | 62 |
| Python sum | 3275.559 | 654.078 | 1967.4999 | 1.8956 | 57 | 32 |
| Capabilities | 3964.588 | 1520.584 | 1974.9999 | 1.8402 | 109 | 94 |

Paired median total: cold **3747.9755 ms**, warm **1426.658 ms**. All 42 dialogue comparison requests: median **1648.903 ms**. All 52 comparison requests: median generated rate **53.95025055812539 tokens/s**. Cold and warm output lengths can differ even with a fixed seed, so total-time differences are not purely loading overhead.

First generated **raw JSON content token** median: cold **2214.3135 ms**, warm **34.889 ms**. This includes JSON scaffolding and is **not the first answer character or first browser-visible text**. Those browser measurements are unavailable in the direct Ollama runner and must be collected separately from the actual application. Immediate deterministic execution/status feedback is likewise a different application metric, not a model first-token measurement.

## Quality findings and mode experiments

The RSA answer omitted all required creators and gave an incorrect description of the public key. Its held-out paraphrase supplied correct English names beside invented Russian first names; the regex screen passed this wrong answer. Dumplings became a dough/meat recipe, and the follow-up recommended thawing in water. Other errors included bacteria producing antibodies, calling Python lists immutable, falsely identifying Dostoevsky's first major novel, an incorrect fraction while comparing decimals, and fabricated yesterday conversation history. The capabilities response contained a nonsensical cooking example. These are actual retained outputs; passing unit tests does not resolve them.

Raw plain-text streaming compatibility was tested first and failed: internal self-instructions and `</think>` leaked despite `think:false` and the existing Qwen3 closing prefill. Those interrupted observations are preserved in [`llm-raw-compatibility-2026-10-28.json`](evidence/llm-raw-compatibility-2026-10-28.json), separate from the application-equivalent schema comparison. They must not be mixed into quality percentages.

Separate qwen3:4b tuning for 17 × 23:

| Experiment | Total ms | Outcome |
|---|---:|---|
| Native `think:false`, no prefill, JSON schema | 3331.116 | Correct answer; `/api/show` still advertises only thinking=true |
| `think:true`, 768-token budget | 6862.721 | Correct 391; slower than non-thinking schema request |
| Context 2048, budget128 | 3323.297 | Correct; `ollama ps` reports2.9 GB versus3.2 GB at4096 context |
| CPU fallback,128 tokens | 7544.850 | Correct; immediate unload meant after-request residency unavailable |
| Repeated CPU fallback with residency retained | 7301.159 | Correct; `ollama ps` explicitly reports100% CPU |

The retained CPU run verifies inference without GPU offload; it does not verify microphone/STT CPU fallback. Further separate reasoning=true768token RSA and dumpling attempts produced truncated malformed JSON at **17370.206 ms** and **14470.596 ms**; these are failures, not successes. Extra evidence is in [`llm-extra-tuning-2026-10-28.json`](evidence/llm-extra-tuning-2026-10-28.json). No universal disabling or enabling of thinking is justified by these observations.

Removing the Qwen3 closing-think prefill was also checked separately with the exact frozen prompt/schema/options for RSA and dumplings. Both still failed their rubrics: RSA omitted the creators and supplied a broken modular example, and dumplings became a dough recipe. These retained outputs are in [`llm-native-false-2026-10-28.json`](evidence/llm-native-false-2026-10-28.json). Prefill removal is therefore not supported as a fix for the measured intelligence failures.

## Remaining evidence and selection boundary

Required qwen3:8b and qwen3.5:9b downloads were attempted. At 13:38:19 UTC, qwen3:8b had 171,337,692 / 5,225,374,496 bytes of its weight layer, net 438,837 bytes/s over a 7.62-second sample; qwen3.5:9b had 110,344,069 / 921,704,832 bytes of its current layer, net 740,993 bytes/s over that sample. These are short-window rates, not completion estimates. Repeated server `part stalled; retrying` messages and backwards progress counters show incomplete chunks were retried. A reconnect progressed qwen3:8b to 394,083,708 bytes but reproduced part8/part10 stalls at16:40:13/14 Moscow time, so the bounded retry was stopped. No partial files, installed models, daemon or unrelated workload were deleted or terminated. The [progress snapshot](evidence/download-state-2026-10-28.json), [filtered stall log](evidence/ollama-download-stalls-2026-10-28.txt) and interrupted comparison artifact preserve the blocker; `--resume` retains the completed qwen3:4b comparison.

A complete three-model comparison and measured default selection remain blocked until these assets finish. Optional Gemma was not downloaded. No comparative speed/quality improvement over qwen3:4b is claimed. GPU STT coexistence, actual microphone-to-edited-transcript-to-action-to-Piper speech and browser-visible timing require separate real integration evidence; they are not established by this evaluator. The read-only voice status probe found STT installed but all three model profiles unready; Piper and Denis were unavailable. Do not infer CUDA availability from this computer's successful GPU run for other Windows installations.

Primary API references consulted on 28 October 2026: [chat metrics/stream/keep-alive](https://docs.ollama.com/api/chat), [model-specific thinking controls](https://docs.ollama.com/capabilities/thinking), [resident model and VRAM metadata](https://docs.ollama.com/api/ps), [GPU/CPU offload interpretation and context controls](https://docs.ollama.com/faq), [Qwen3.5 local model family](https://ollama.com/library/qwen3.5). Actual `/api/show`, rather than web descriptions alone, determines installed compatibility.

# LocalMind Next: measured model comparison

The frozen 66-case Russian corpus is `tests/data/russian_llm_v2.json`. It retains
the previous corpus and adds RSA follow-up, verified PC capability reporting,
selected-file permission, save-dialog/focus failures, reference ambiguity,
replacement, forged-history and malicious-title cases. These are benchmark
fixtures only: the application never imports questions or reference answers.
Structured tool facts in this comparison are fixtures, not actual Windows tests.

Real local inference on 2026-10-28 used Ollama 0.40.12, seed42, temperature0.2,
4096 context and384 output tokens. Candidates ran sequentially with no unrelated
resident model unloaded. Both installed models completed66 comparison cases and
nine cold/warm pairs (one representative per category). Cold means explicitly
unloaded from Ollama; filesystem caches were not cleared. Warm paired prompts
benefit from prompt caching and are not the latency of arbitrary new requests.
There were zero inference/transport failures among those168 requests.

| Observed metric | qwen3:4b Q4_K_M | qwen3.5:9b Q4_K_M |
|---|---:|---:|
| Strict rubric passes /66, AI-assisted self-review |33 |45 |
| Regex/schema screening passes /66 |51 |57 |
| Comparison raw first token p50/p95, ms, n66 |36.184 /52.297 |158.540 /213.386 |
| Cold raw first token p50/p95, ms, n9 |2101.895 /2133.373 |3810.042 /3876.406 |
| Paired warm raw first token p50/p95, ms, n9 |27.299 /30.113 |43.080 /67.474 |
| Paired warm total p50/p95, ms, n9 |637.044 /1865.431 |722.837 /1565.382 |
| Observed Ollama size_vram after final warm sample, bytes |3,180,247,121 |5,606,337,412 |

These rubric rates include factual correctness, following the actual request and
safe truthful status, not just factual accuracy. Every answer was read and bound
by SHA256 in `docs/evidence/next-llm-review-2026-10-28.json`. This is explicitly
Codex Builder self-review, **not independent human evaluation**. All raw requests,
answers, timings, hardware samples and metadata remain in
`docs/evidence/next-llm-2026-10-28.json`. Human review may disagree and can replace
the ledger with independently justified decisions. Regex false positives include
invented facts; false negatives include a correct short name “Рон Ривест”.

The9B candidate is better on these fixtures, but both fail core regressions.
For example,4B invents several RSA developers and claims a close without a
verified window;9B invents “Адриан Шамир” in the RSA follow-up and mishandles
window ambiguity. Neither is promoted to a verified production profile. The
existing fast default stays provisional;9B remains an optional quality candidate
through installed-model selection. The runner emits `fast:null, quality:null`
when core regressions fail or review/resource/timing evidence is incomplete.
qwen3.5:4b and qwen3:8b were absent; no download was started in this run.

## Reproduction and review

```powershell
.\.venv\Scripts\python.exe scripts/eval_llm.py --repetitions 3 --output docs/evidence/my-comparison.json
# Optional explicit asset download, never inference in the cloud:
.\.venv\Scripts\python.exe scripts/eval_llm.py --pull --models qwen3.5:4b qwen3:8b --output docs/evidence/new-candidates.json
.\.venv\Scripts\python.exe scripts/eval_llm.py --review-only --reviews docs/evidence/next-llm-review-2026-10-28.json --output docs/evidence/next-llm-2026-10-28.json
```

A semantic ledger is keyed by model, with `method` (`human` or `ai-assisted`),
`reviewer`, and an `answers` list. Each decision requires `case_id`, exact
`answer_sha256`, three booleans (`factual_correct`, `addresses_request`,
`safe_and_truthful`), `naturalness`0..2 and an explanatory `reason`.
Partial review has no pass rate. Smoke subsets cannot select profiles. Profile
recommendations require complete exact-text review, passing core cases, at least
three warm timing samples and measured VRAM allocation. Fast candidates must
also meet the documented85% strict-rubric threshold. Selection writes evidence,
never silently changes application configuration.

## Voice and response instrumentation

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_next.py --kind dialogue --n 5
.\.venv\Scripts\python.exe scripts/benchmark_next.py --kind voice --n 5 --retain-audio
# Direct supervised worker comparison when HTTP startup is unavailable:
.\.venv\Scripts\python.exe scripts/benchmark_next.py --kind voice --direct-voice --n 5
```

The voice runner compares the same Russian/English/numeric text across Piper,
Silero v5.6 and Chatterbox V3 adapters without downloading assets. It records WAV
duration, HTTP synthesis time, RTF, first HTTP bytes, RAM/GPU snapshots, failures
and p50/p95. Audio retention is explicit. An unavailable voice stays a failed
attempt, never a zero-time success. The response runner records first admitted
HTTP delta and final result; it does not act on apps/files. Light testing is a
separate `--kind light`; REAL actuation requires `--allow-real`.

First browser paint, actual audible latency and total spoken response time stay
null in CLI reports. Browser play-promise timing indicates playback started,
not sound measured at speakers. Human listening and acoustic/hardware tests are
still required for intelligibility, naturalness, pronunciation, interruption and
12GB shared LLM/TTS limits. Snapshot whole-system RAM is not per-model allocation;
Ollama size_vram is allocation, not GPU utilization. No model+high-quality-voice
VRAM coexistence or CPU fallback benchmark was performed by this comparison.

Actual direct-worker voice measurements are retained in
`docs/evidence/next-voice-2026-10-28.json`. Identical sample text was synthesized
five times on CPU Piper: first-call synthesis3497.918ms; four observed warm calls
284.817–307.711ms, p50290.397ms and p95307.711ms. Generated WAV duration was
17.229–17.531seconds. Warm RTF p50 was0.016642, p950.017860. Resource probes run
outside measured synthesis. Silero and Chatterbox each failed five times because
their local environments/assets are missing; these failures remain in the
denominator. No audio was played or retained. Listening quality and audible
latencies remain unmeasured; these synthesis timings alone do not prove scenarioD.

## Optional approved local references

`localmind/retrieval.py` supplies a bounded lexical retriever, disabled by default.
The owner edits `config/retrieval_sources.json` with at most16 exact UTF-8 `.txt`
or `.md` sources, for example:

```json
{"sources":[{"id":"crypto-notes","label":"Мои проверенные конспекты","path":"C:/LocalMindSources/cryptography.md"}]}
```

Configuration declares candidates; a separate UI/API permission must approve an
exact source fingerprint before its contents are read for retrieval. Metadata
listing alone reads no contents. Grants are session-only and bind identity and
SHA256 bytes; replacement or editing revokes access. Network paths, links,
reparse points, binary data and files over256KB are refused. There is no recursive
scan. Search returns at most five1800-character passages with exact source IDs,
filenames, line ranges, content hashes and modification timestamps. Windows
read locks hold path ancestors and prevent source write/replacement while read.

Only explicitly enabled conversations should include returned excerpts, marked
as untrusted reference data. Retrieved instructions cannot authorize an action,
choose an executable path or grant another source. Citations establish where a
claim came from, not that its author is correct. Without an approved matching
source, the assistant must acknowledge uncertainty rather than invent citations.
Unit tests exercise missing permission, forged fingerprint, replacement with
restored timestamp, revocation, malicious source text, symlink rejection and
bounded source selection. Browser permission and model provenance integration
must be verified separately by the main Builder.

API behavior was checked against primary documentation: [Ollama chat API](https://docs.ollama.com/api/chat)
documents NDJSON streaming, structured format and nanosecond duration counters;
[qwen3.5:4b model page](https://ollama.com/library/qwen3.5:4b) confirms the candidate
identity. Measurements, rather than upstream marketing benchmarks, drive local
recommendations.

# V4-4A Production Context Preparation

V4-4A adds the pre-LLM context path to the production Python sidecar. A chat
generation snapshots persisted history and reads the existing Memory, Persona,
Knowledge, and optional RAG sources once, then passes the resulting system
context to the existing `modules.chat.stream_chat()` boundary. Conversation
history remains structured messages; it is not copied into the system prompt,
and the current user message is appended exactly once by the chat boundary.

The adapter reuses `build_memory_retrieval_config`, `retrieve_memories`,
`KnowledgeStore.retrieve`, `PersonaStore.build_context`,
`run_configured_rag_pipeline`, `format_memory_context`,
`format_knowledge_context`, and `ContextBuilder`. RAG follows
`rag.pipeline_enabled`; disabled RAG reports `rag_ms: null` and does not
execute the underlying pipeline runner. Context preparation runs through `asyncio.to_thread`,
with cancellation checks at every source and assembly boundary. A cancelled
context never enters Ollama.

Context sources are opened read-only in this path. The optional `read_only`
flags prevent the legacy Memory normalization write-back, Persona load
timestamp write-back, and Knowledge metadata normalization write-back. No
memory extraction, candidate generation, title generation, summary, or
Conversation Intelligence is scheduled.

`chat.completed.payload.diagnostics` has an additive optional context extension:
stage timings (`context_total_ms`, `memory_ms`, `persona_ms`, `knowledge_ms`,
`rag_ms`, `prompt_assembly_ms`), source enablement flags, and item counts only.
Source contents, prompts, responses, paths, credentials, and identifiers are
never placed in IPC diagnostics.

The Stable changes are limited to explicit read-only store construction and
lazy embedding-settings resolution so the headless adapter does not create or
mutate user data during import or retrieval. The V4-3C persistence policy is
unchanged: only completed turns are saved.

## Production pipeline audit

The audited legacy entry is `ChatPage.send_prompt()` → session snapshot →
`main.py::build_chat_runtime_callbacks.prepare_chat_prompt_context()` →
`build_memory_context()` → `ChatSession.set_system_context()` → `stream_chat()`.
The nested UI callback is not imported into the sidecar. The adapter calls its
actual production dependencies, and a synthetic parity test compiles only the
audited function declarations from `main.py` to compare the resulting prompt.

| Source | Actual read path and settings | Side effects excluded from v4 |
| --- | --- | --- |
| Memory | `MemoryStore.list_memories` → `build_memory_retrieval_config` → `retrieve_memories`; record enabled/state and configured limits/thresholds; relevance/confidence/importance/freshness ranking | Directory creation, normalized-record write-back and recovered-backup write-back |
| Persona | `persona.enabled` (default true), `PersonaStore.load` each generation, then `build_context`; missing/corrupt input keeps production DEFAULT_PERSONA | Creating a default file, load timestamp save, normalization save |
| Knowledge | `knowledge.enabled` (default true), `knowledge.max_results`; `KnowledgeStore.retrieve`: existing vector index first, then existing keyword fallback | Directory/metadata creation and normalized metadata save; no reindex, no document embeddings generated |
| RAG | `rag.pipeline_enabled` (current shipped default true), `run_configured_rag_pipeline`; existing dedup/rank/optimization/configured budgets | When disabled the whole wrapper is skipped, including unused config/policy preparation; raw source formatting remains identical |

There is **no global memory.enabled setting** in the audited production path.
`memory_enabled=true` means the production retrieval stage exists; disabled
records still obey production filtering. The real setting is
`memory.max_injection` (default 5, minimum 1), not a global disabling switch.
This is not a new always-on v4 source switch. Capability availability does not enable RAG.

Knowledge uses the production `embedding_model` and `ollama.host`, not a new
resolved-model preference. Embedding provider construction is lazy/no request;
query embedding is requested only if an existing vector index can be searched.
Missing/invalid index or embedding error uses keyword fallback. No startup
rebuild, index write, model selection or new embedding configuration is added.

RAG reuses `build_rag_runtime_config`, `run_rag_pipeline_with_fallback`, the
existing deduplication/ranking stages, and `ContextOptimizer`. Default context
budget is 4000, reserved output 0; configured adaptive allocation is preserved.
Optimizer estimates tokens with ceil(chars / 4), trims sections to allocation,
and preserves section priorities. This is the production RAG context budget,
not a new cap on the full history. `ContextBuilder`'s 6000-token default is a
warning threshold, not a second truncator. Raw source formatters retain their
existing per-item limits. No rank weights, thresholds or algorithms changed.

## Prompt and persistence boundaries

The model system text joins the first four production sections in order:
System Context → Persona → Memory → Knowledge. Existing structured history
follows; `stream_chat` appends the new user turn exactly once. Identical text in
an older user turn is retained, never deduplicated by content equality.

When no source contributes context and Persona is disabled, the adapter returns
no system override and preserves V4-3C History Chat behavior. Enabled but missing
Persona is *not* treated as disabled: production's default persona is preserved.

Retrieved system context is generation-local and never saved into conversation
DTOs. Completed persistence retains the original historical system and appends
only the new user/assistant turn. This prevents a later `conversation.get` from
exposing retrieved source text. Existing completed-only save/cancel race policy
is unchanged. No extraction, candidate, title, summary, signal or Conversation
Intelligence entry is called. Non-atomic ConversationManager.save remains debt.

## Ownership, cancellation and diagnostics

Ownership and the request-local stop event exist before `chat.accepted` yields.
History, conversation/generation IDs, user turn, immutable settings reference
and assembled context are bound to a frozen per-generation snapshot. Its
contents are hidden from repr; scalar diagnostics use an immutable mapping.
No store is accessed per token. This is a read snapshot, not cross-file MVCC.

Context runs in a blocking worker, not the WebSocket loop. Memory, Persona,
Knowledge, RAG and assembly each check cancellation before and after the stage.
Stop during a synchronous source waits for that call to return, but skips every
later stage and Ollama. An existing query-embedding call can last up to the
production HTTP timeout (60 s); this stage does not rewrite that client.
Even asyncio task cancellation shields and joins the actual context worker
before terminal/reuse. Explicit cancel wins later provider errors. N+1 cannot
start until N's worker is gone. Health and cancel IPC remain responsive.

Timings reuse `PreLLMLatencyDiagnostics` with `perf_counter` for sub-ms Windows
resolution: memory/persona/knowledge/rag names are unchanged;
`context_builder_total_ms` maps to `prompt_assembly_ms`. Disabled stages have
enabled=false and null (or absent optional wire) duration, not fake zero time.
Failures/cancellation preserve partial timings. IPC v1 gets only optional scalar
fields, validated by schema, Python and Rust; no new RPC or content payload.

Unexpected source exceptions produce safe INTERNAL_ERROR with a bounded stage
name; the sidecar remains alive. Store-specific fallback remains production:
Memory recovery/empty corrupt result, default Persona, Knowledge keyword,
and RAG raw-source fallback. RAG fallback marks `context_error_stage=rag` but
can complete the turn. No exception body or retrieved text enters diagnostics.

## Stable changes and headless safety

Only four stable modules changed: Memory/Persona/Knowledge gain optional
read-oriented construction (defaults preserve legacy writes); Knowledge accepts
an optional embedding provider; embedding settings become lazy and injectable.
These flags suppress implicit writes on reads, not a permission sandbox for
arbitrary mutation methods. The sidecar exposes no mutation API.
`main.py`, ChatPage, `modules/chat.py`, Voice, TTS and playback are unchanged.
No Tk/widgets/main or eager global Settings singleton is imported by the context
path. Existing source-declaration settings/chat adapters remain separate debt.

## Verification commands

From the repository root, use the project's Python environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests --ignore=tests/output prototype/aurora-v4 -p no:cacheprovider --basetemp tests/output/v4-4a-validation
.\.venv\Scripts\python.exe prototype/aurora-v4/sidecar/smoke_production_context.py --runs 3 --cancel
```

The headless smoke reads actual sources, writes only disposable conversations,
compares complete source inventories/hash/mtime (including candidates and index),
and labels its timing `first_sidecar_delta_ms` — not frontend latency.
The desktop observer's `--isolate-context` copies the current real settings and
context into a disposable, non-repository directory (no real conversations),
then checks both original and snapshot sources for writes. It reads existing
WebView performance marks; Send/Stop/Close are genuine desktop actions. It does
not submit prompts through CDP or manufacture frontend marks.

No content from real stores is committed to fixtures or reports. Tests use
synthetic sources. The Windows pytest cache has an existing ACL problem, so
validation disables the cache and places fresh temp work under ignored output.

## Implementation acceptance record (2026-09-15, before Git closure)

Passed: context-specific tests 16; sidecar/contracts 89; complete source plus
prototype suite **1017 passed, 3 skipped** (83.95 s); Rust **16 passed, 1 ignored**
(the opt-in read-only real smoke); frontend 14 passed; TypeScript/Vite and Tauri
release build; compileall of 252 source Python files; default settings JSON,
25 contract examples and `git diff --check`.

One earlier full-suite run concurrent with release compilation saw the existing
mock cancel test receive completion before cancel acknowledgement (1016 passed,
1 failed, 3 skipped). That exact test passed isolated (0.23 s); the subsequent
complete run without parallel compilation passed. No scheduler-test or logging
technical debt code was modified to conceal it.

Real headless smoke: READY, existing qwen3.5:9b, current settings enable Persona,
Knowledge and RAG; Memory uses production record filtering. Matched Memory,
Knowledge and RAG counts were zero with these synthetic prompts. Real Persona
was prepared without recording its text. Three completed turns persisted in an
isolated conversation; streaming cancel returned cancelled, worker exited,
response cleared, and no cancelled turn was saved. Full original source
inventory/hash/mtime (settings, memory/candidates, persona, knowledge/index)
was unchanged. No title/intelligence or settings mutation was triggered.

Warm ×3, milliseconds (headless: **sidecar delta**, not frontend):

| Run | Context | Memory | Persona | Knowledge | RAG | Assembly | Ollama first model/content | Sidecar first delta | Load |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2.750 | 1.896 | 0.272 | 0.263 | 0.196 | 0.037 | 219 | 250 | 1.190 |
| 2 | 0.895 | 0.197 | 0.173 | 0.220 | 0.194 | 0.034 | 156 | 204 | 1.809 |
| 3 | 0.847 | 0.188 | 0.159 | 0.197 | 0.200 | 0.032 | 171 | 218 | 1.726 |

Thinking policy remains off; reasoning_chars=0 in these runs. No reasoning
body is observed/logged. Separate cold run after restarting the existing Ollama
service: context 2.728 ms, model load 7681.578 ms, first sidecar delta 7906 ms.
This is model loading, not context latency; no SLA or model optimization implied.

Resource observation (desktop READY, before UI generation): Rust 35.82 MiB,
WebView2 processes 396.16 MiB, Python sidecar 33.47 MiB; warm Ollama process
tree 942.19 MiB. `/api/ps` reports model size_vram=5,490,081,790 bytes (~5.11 GiB).
These are a point-in-time observation, not peak performance measurements.

**Unverified desktop acceptance:** the new release desktop was launched with isolated real
context snapshots and its read-only performance observer became ready, but Windows
Computer Use twice reported `failed to activate captured window`. No real
desktop Send/Stop or first-frontend-delta result is claimed yet; normal desktop
exit/resource cleanup for that smoke was not recorded. The closure audit found
zero runs and no completed exit/cleanup fields in the desktop observer record.
This record does not prove manual Send/Stop or first-visible latency.

At that point Git was on `refactor/aurora-v4` at
`d5e9778c03bde823a7008b184825c41d861a2b3b`, with this stage uncommitted.
The subsequent explicit V4-4A Git Closure request authorizes committing/pushing
after renewed code audit and validation, while preserving this desktop evidence
limitation. It does not convert missing manual acceptance into a passed result.
No work on V4-4B has begun.

## Git closure validation (2026-09-15)

Closure baseline: `d5e9778c03bde823a7008b184825c41d861a2b3b`, tracking
`origin/refactor/aurora-v4` without divergence. Only the 19 V4-4A source, test,
schema and documentation files are staged; no logs, model output, user data,
screenshots, caches or build artifacts are part of the commit.

Fresh closure runs, not copied from the earlier implementation result:

| Validation | Result |
| --- | --- |
| Context tests | 16 passed (5.31 s) |
| Production sidecar + IPC contracts | 89 passed (33.20 s) |
| Chat / Conversation / Cancel / pre-LLM regression | 57 passed (0.67 s) |
| Complete source + prototype pytest | 1017 passed, 3 skipped (85.02 s) |
| Rust | 16 passed, 1 ignored (opt-in real smoke) |
| Frontend | 14 passed |
| TypeScript / Vite / Tauri release | passed; release build 1m 39s |
| Python compileall | 249 previously tracked + 3 new source files passed |
| Default settings / IPC schema JSON | valid |
| IPC contract examples | 25 passed |
| Whitespace / patch validation | git diff --check passed |

No regression fix or runtime feature was introduced during closure. The only
closure edit is this documentation update, including correction of the Memory
setting name. The fresh complete test run had no failures; the earlier timing
failure remains documented above. Existing Rust unused-method/linker warnings
remain unchanged.

The change is one logical stage: `feat(v4): integrate production chat context`.
Post-turn intelligence, title generation and memory extraction/write remain
disabled. V4-4A is the code baseline for a separately authorized V4-4B; manual
desktop UX/first-visible timing remains unverified and must not be represented
as a passed V4-4A desktop acceptance.

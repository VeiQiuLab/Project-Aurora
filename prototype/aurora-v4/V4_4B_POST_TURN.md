# V4-4B — Post-Turn Intelligence

Scope: headless scheduling and production post-turn reuse. No Voice, Settings UI,
audio, Live2D, model optimization, RAG change or visual redesign.

## Production Post-Turn Pipeline Map (audited source)

| Stable boundary | Actual behavior | Model slot | Writes |
| --- | --- | --- | --- |
| `modules/chat.py:stream_chat` successful nonempty assistant | Append assistant, then `MemoryStore.queue_candidates(session.snapshot(), source="chat")` before returning to caller; cancelled partial assistant excluded | No | Pending candidates only |
| `widgets/pages/chat_page.py:save_conversation` (also ChatWindow) | Save conversation first, refresh list, then schedule intelligence | No | Conversation JSON |
| `modules/conversation.py:schedule_conversation_intelligence` | Daemon runs deterministic analysis; first-turn title waits idle, then saves analysis/title and calls signal-to-candidate adapter | Title only | Conversation metadata/title; candidate marker if signals exist |
| `analyze_conversation` | Summary from first three user messages (fallback assistant), topics, important events, rule title; current `memory_signals=[]` | No | None until caller persists |
| `generate_title_summary` | Same first user/assistant prompt, Chinese 2–8 characters, reject over 10; LLM then rule/default fallback | **Yes, only current model-backed post-turn task** | None until caller persists |
| Memory extraction/intelligence/relation scoring | Existing deterministic rules and dedup; `queue_candidates`, not `save_candidates`/approval | No | `memory_candidates.json`, backup |
| `_trigger_conversation_memory` | Minimum count 2, stale count and fingerprint guards; empty signals skip before store access | No | Pending candidates and trigger marker only for nonempty signals |

Stable first-title condition: no existing conversation ID at save, exactly one
user and one assistant. Stable debounce is `TITLE_GENERATION_IDLE_SECONDS=4.0`,
using `_turn_lock.locked` and `_turn_counter`; a changed counter or active turn
waits for idle and restarts the entire delay. There is another launch guard.
`ChatPage.destroy()` sets `_title_generation_cancel_event`; pending daemon work
stops, but an already-entered HTTP call is not preempted. Later saves do not title
again; metadata manual/title-change guards and Memory fingerprint/similarity
guards supplement scheduling. Summary analysis runs on normal saves, not via LLM.

No automatic forgetting/deletion was found in this completed-turn chain. The
store has explicit delete/archive/merge/approve/update methods; V4 never invokes
them. `save_candidates` can create confirmed records but is NOT the queue path.
No formerly-disabled signal extraction or new analysis is enabled.

## V4 architecture and ordering

`chat.start` ownership -> `foreground_started` before accepted await -> immutable
generation-start context -> production streaming/cancel -> completed persistence
-> terminal event -> enqueue copied completed turn -> `foreground_finished` ->
full 4-second idle gate -> candidate queue -> deterministic intelligence -> title
if eligible -> persisted metadata -> `conversation.changed`.

V4 intentionally moves the legacy stream function's optional candidate hook out
of the request path. `DirectChatAdapter` still sets `collect_memory_candidates=False`;
the coordinator calls the same production algorithm after successful persistence.
No job for cancelled/failed/backend_lost/rejected or an unpersisted conversation.
The coordinator is not a business-algorithm fork and does not use Tk callbacks.

One condition variable, one daemon worker, one deque and one idle gate. CPU/IO
work shares that gate for simple ordering; model calls never run concurrently.
Foreground starts invalidate the idle epoch and wake the worker. Finishing the
matching owner sets a new idle timestamp; stale finishes cannot release N+1.
The final guard runs inside the actual title callback immediately before calling
`chat_with_messages`. If it defers, the helper's normal exception-to-fallback
behavior is explicitly distinguished so the attempt is not consumed. CPU work
is not repeated when the title resumes. No stacked per-task 4/8/12-second timers.
Scheduler locks are not held across CPU, filesystem or model work.

Title policy remains Production: same model, same prompt/validation/fallback,
`think=false`, `num_predict=32`, timeout 20 seconds, current keep_alive (30m in
the real environment). Pending first-turn title survives subsequent completed
turns; a real/manual title suppresses it, including after process restart.
Title attempts are once per conversation per coordinator instance, no retries.

## Ownership, persistence, failure and shutdown

- Idempotency: `(conversation_id, generation_id)` is the immutable turn identity.
  Seen identities survive completion/failure within the instance; duplicate
  notification cannot repeat extraction. Candidate content dedup is additionally
  provided by Production, not used as a substitute for generation identity.
- No persistent jobs, history scan or crash compensation. Pending jobs/seen IDs
  belong to this sidecar instance only. Restart starts empty. The in-memory seen
  ledger and conversation locks grow with that instance's workload and disappear
  on exit.
- Per-conversation reentrant transactions cover foreground read/save and
  background read/metadata/title writes, including list/get reads. Latest
  messages are preserved; stale deterministic analyses do not overwrite newer
  conversation analysis. `ConversationManager.save()` remains non-atomic debt.
- Context and post-turn use **the same** MemoryStore instance. Candidate writes
  retain Production backup/fsync/atomic replace. A reproduced Windows read-vs-
  replace sharing failure required the minimal Stable fix: reads use the existing
  writer lock as well. No additional store or permission-policy change.
- Pending candidates do not enter confirmed retrieval. The current snapshot
  remains immutable; only a later legally confirmed memory can affect a later
  generation. There is no autoapproval because a V4 confirmation page is absent.
- Title/Memory/intelligence failures are separate safe diagnostics; a completed
  persisted chat never becomes failed. Offline title uses Production fallback,
  with one bounded attempt, no infinite retry. Exceptions are logged by type,
  not content; internal payloads do not cross IPC.
- Shutdown closes scheduling, clears pending work, suppresses future publication,
  wakes idle worker and joins for at most 250ms. Running local IO is best-effort;
  already-started non-streaming urllib before headers cannot reliably be aborted.
  The background worker is daemonized (not the asyncio executor), so it cannot
  keep the Python process alive. Late HTTP completion after close cannot save a
  title or emit metadata. Existing Rust process/job ownership remains unchanged.
- Once a model call has entered HTTP there is a narrow unavoidable contention
  window. This is **not** claimed fully preemptible; debounce, final guard,
  reasoning-off and 32-token cap are the defenses.

## IPC and UI

Backward-compatible v1 `conversation.changed`, no command: safe conversation
metadata DTO only. Schema, example, Python validator, Rust validator/gateway,
frontend type and sidebar handling updated. Existing Rust connection epoch
validation rejects old-instance traffic. Selected conversation/messages are not
changed; unselected title refresh is supported. Unknown metadata identity invokes
the existing list RPC. No summary, signals, Memory body or prompt is transmitted.
No CSS/layout/font/composer/titlebar/black-white glass changes.

## Real Ollama verification (2026-09-15, isolated roots)

Command: `.venv/Scripts/python.exe prototype/aurora-v4/sidecar/smoke_post_turn.py
--output tests/output/v44b-real-post-turn.json` (one command line).

Real settings/policy, real qwen3.5:9b; copied Persona and isolated conversations
and Memory. Original config/context fingerprint and all existing conversation
bytes unchanged. No user Memory/title altered. No model tuning or unloading.

Initial real run:

| Case | Result |
| --- | --- |
| A: turn 2 one second after completed turn 1 | Deferred background, first model/content 140ms; first sidecar delta 187ms |
| B: idle | Title starts after 4015ms; request 360ms; real title and metadata events persisted/emitted |
| Warm 1 | pre-LLM 0.582ms, load 1.018ms, prompt eval 141.679ms, first model/content 203ms, first sidecar 235ms |
| Warm 2 | pre-LLM 0.591ms, load 1.106ms, prompt eval 137.671ms, first model/content 140ms, first sidecar 187ms |
| Warm 3 | pre-LLM 0.739ms, load 1.266ms, prompt eval 135.711ms, first model/content 172ms, first sidecar 203ms |
| C: foreground at actual background call boundary | First model/content and sidecar delta 547ms; concurrent title request 390ms |
| D: another 5.2 seconds idle | No extra title or extraction |
| E: Memory | One pending candidate, zero confirmed memories, zero destructive calls; next context sees zero unconfirmed items |
| Cancel | Real first-delta cancel; no persisted cancelled conversation or post-turn identity |

All foreground and both background title requests reported reasoning_chars=0.
Model residency remained qwen3.5:9b, VRAM 5,490,081,790 bytes throughout. Whole-system
RAM used before/during/after: 16,601,583,616 / 16,931,508,224 / 16,635,170,816 bytes.
These are observations, not attributable process-only measurements or an SLA.
No unexplained warm 5s+ stall; background worker exited after smoke.

**First frontend delta and manual Windows Send/Stop/first-character experience:
NOT YET VERIFIED.** Python send timing is not frontend timing. Automated DTO/UI
store tests do not replace manual desktop acceptance.

## Validation and limitations

Final-code real rerun (`tests/output/v44b-real-post-turn-final.json`) also passed
A/B/C/D/E and real cancel. Turn 2 during debounce: first model/content 172ms,
first sidecar delta 188ms. Final warm timings:

| Run | pre-LLM ms | load ms | prompt eval ms | first model/content ms | first sidecar delta ms |
| --- | --- | --- | --- | --- | --- |
| 1 | 0.658 | 1.396 | 136.276 | 187 | 219 |
| 2 | 0.627 | 1.084 | 136.782 | 156 | 187 |
| 3 | 0.613 | 1.110 | 139.295 | 156 | 172 |

Titles started at 4016/4000ms idle and took 391/250ms, reasoning_chars=0.
The narrow race produced 375ms model/content, 406ms sidecar delta. Destructive
methods were instrumented to fail on any call: zero calls, one pending candidate,
zero confirmed memories, no duplicate work. Model VRAM unchanged. Final whole-system
RAM before/during/after: 16,906,608,640 / 17,076,207,616 / 16,928,464,896 bytes.
Original data/conversations unchanged; post-turn worker exited. Reports contain
only counters/timings and remain ignored local evidence, not committed user data.

Final validation:

- Coordinator/post-turn targeted: **22 passed**.
- Full source plus prototype: **1040 passed, 3 skipped**, 87.42 seconds. Includes
  all **112 V4 sidecar/contract tests**, Conversation/Chat/Context/Memory/Intelligence,
  cancellation and Voice regressions. Earlier full pass: 1038 passed, 3 skipped
  before adding the two schedule-failure/terminal-order tests.
- Rust: **16 passed, 1 ignored** (explicit opt-in real read-only test).
- Frontend: **15 passed**. TypeScript/Vite and Tauri optimized release succeeded.
- compileall: **255 Python files**. Default settings JSON and IPC schema/examples
  valid (**26 canonical examples**); `git diff --check` passed.
- Stable changes only: optional scalar non-streaming diagnostics in `modules/chat.py`
  (4 added lines), existing Memory read/write lock sharing in `modules/memory.py`
  (6 added lines). No changes to Tk scheduler, prompt, policy, inference or UI.

Initial
test-authoring errors (fixture path and contract example placement) were corrected.
A new concurrent read/write stress test exposed the Windows sharing violation;
the minimal shared-read-lock fix passed its rerun. Neither was treated as a pass
or dismissed as flaky. Existing Rust unused-method/linker warnings are unrelated.

Acceptable limitations: non-preemptible entered urllib call; best-effort jobs with
no restart recovery; Memory confirmation UI absent (candidates remain pending);
existing non-atomic conversation saves; headless timing only. No unrelated logging
traceback fix. Next-stage choices remain Settings, Voice UI/existing backend,
Rust Audio/B-3 or Live2D; none is started by this stage.

## Closure classification

- Passed: implementation, isolation, ownership/failure tests, full regression,
  real background contention checks, release build.
- Acceptable issues: the explicitly listed non-preemptible/best-effort/confirmation
  UI and existing persistence limitations. No unrelated logging traceback observed.
- Code/real-smoke blockers: none after final validation.
- Pending: **MANUAL GUI NOT YET VERIFIED** and actual frontend-delta timing.
  This remains a separate user acceptance task, not a claimed pass.

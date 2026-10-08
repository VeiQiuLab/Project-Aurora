# Stage V4-8C — Memory Governance & User-Controlled Operations

Status: **PASS** for implementation, directly related regressions and isolated
Windows Native Desktop acceptance. Starting HEAD:
`d9c14e920ac466afc3173078f411d53b0b72acbc`, branch `refactor/aurora-v4`.
Git closure and final full commit SHA are recorded in
`tests/output/v48c/v48c-final-report.md` and the accompanying Git gate evidence.

## User-controlled operations

Settings → Memory retains the V4-8B Saved/Pending inspection UI. Pending details
now expose Approve and Reject. Saved details expose Edit/Save/Cancel and Delete.
Delete first shows the exact object ID, content preview, irreversibility warning
and Cancel. Only the second explicit confirmation sends a deletion request.
Closing Settings cancels the confirmation. Cancel/editing alone never writes.
Legacy records without a supported stable ID remain viewable only.

The UI guards duplicate submission, shows progress/result/errors and refreshes
both lists after completion. Failed edits retain the draft. Retry sends the same
immutable operation ID/payload with a fresh transport request ID. Conflicts
require rereading the latest object; old snapshots cannot overwrite it. Late or
mismatched responses cannot acknowledge a different operation.

## Gateway and ownership

`memory.write.request/response` and Tauri `memory_write` extend the existing
authenticated Rust/Python gateway. Requests contain exactly `operation_id`,
`action`, `id`, `expected_version`, `content`, and `confirmed`. Actions are
approve/reject/edit/delete; no paths, batch operations or clear-store command.
Rust and Python independently enforce bounded IDs, a 64-character SHA-256
version, valid nonblank edit content (up to 32,768 Unicode characters), and
explicit deletion confirmation. The response contains only operation identity,
completion status and the associated saved ID. Error diagnostics contain codes,
not memory bodies, private paths or authentication tokens.

Python remains the sole Memory owner. `MemoryStore.govern()` reuses existing
candidate approval/rejection and saved update/delete semantics. Rejection
persists `rejected`, removes the candidate from Pending, and does not delete a
saved memory. Frontend never opens Store files or connects to private IPC.

## Resolution of the three authorized consistency defects

1. **Approval consistency:** the existing saved/candidate JSON schemas stay
   unchanged. Mutations stage exact after-images, then persist an allowlisted,
   checksummed redo intent in `memory_operation_intent.json` before replacing
   any Store file. Saved records, candidate status and the operation receipt
   roll forward as one coordinated operation. Backups are updated to the
   completed after-images before the completion marker. Failure before durable
   intent leaves primary data unchanged; failure after intent is recovered
   before another cooperating reader/writer can observe state. Failed recovery
   blocks access. Replay never re-executes approval or creates a second UUID.
2. **Concurrent edit:** complete read-modify-write operations use the same
   directory-keyed reentrant lock and OS lock across Store instances/processes.
   Windows uses a named mutex and handles abandoned ownership; POSIX uses
   `flock`. Each edit rereads current raw records, validates the exact target and
   compares its full-record fingerprint. Other records and legacy fields are
   preserved. The existing `updated_time` field advances monotonically at
   microsecond precision, including edits that return to earlier content, so
   a stale version cannot become valid through an ABA content change.
3. **Concurrent delete:** deletion acquires the same operation lock, rereads the
   current file and requires exactly one matching ID and the expected version.
   It preserves all other current records. Edit/delete conflicts safely reject
   the stale operation. Identical operation retries replay a persisted receipt;
   reusing an operation ID with different arguments is rejected.

`memory_operations.json` stores minimal operation receipts and request digests,
without memory bodies. Receipt and mutation share the redo intent. Reads with
no outstanding intent remain side-effect free and do not create absent Store
directories. Outstanding explicit writes must finish recovery before reads.

## Verification

- Python/v4 related regression: **333 PASS**. Includes Memory retrieval,
  context assembly, candidate generation, post-turn, conversation persistence,
  direct chat, Settings and real authenticated governance IPC.
- Store governance suite: **36 PASS**, included above. Isolated fixtures cover
  failure before intent, every approval commit boundary, concurrent writes,
  duplicate requests, actual child-process termination, restart recovery,
  fail-closed corrupted intent, exact IDs, unrelated records and ABA versions.
- Rust Desktop: **71 PASS**, two pre-existing opt-in tests ignored.
- Frontend unit tests: **42 PASS**; controlled-IPC governance UI: **7 PASS**;
  V4-8A workflow UI regression: **PASS**.
- Contract examples: **26 PASS**. Final Release `--no-bundle` build: **PASS**.
- Real Windows Native input on isolated fixtures: Pending/detail, Approve,
  Reject, Edit/Save, Delete/Cancel, explicit confirmed Delete, Settings reopen
  and persisted exact-target readback: **PASS**. The destructive native action
  received the user's action-time consent for `v48c-fixture-memory` only.
- Real Release gateway checks: concurrent edit conflict, failed write with
  retained draft, identical-operation retry, restart persistence, hide/show
  draft/conversation/runtime continuity, local chat and Local Melo/Rust Audio
  with Memory open, Avatar ready/visible and return to mouth=0: **PASS**.
  Two normal exits: zero owned process remnants.
- Final rebuilt Release native accessibility observation confirms the new
  user-control explanation and absence of the obsolete read-only sentence.
  Native inputs, accessibility observations, controlled-IPC tests and Release
  automation are separate evidence; none substitutes for human voice listening.
- Real user Memory and all 12 historical untracked hashes remain unchanged;
  WIP Glass is untouched. No project files were deleted.

Evidence is under `tests/output/v48c/`, including the final regression logs,
`runtime-jO7oaf/native-smoke.json`, `runtime-jO7oaf/report.json`, native
accessibility captures, protection inventory and final Git gates. An obsolete
pre-inspection capability test was corrected to expect existing `memory=true`;
production capability behavior was not changed.

## Limits and exclusions

The guarantee covers cooperating MemoryStore clients; external manual file
editors do not participate in its lock. Windows mutex coordination is within
the Desktop login session. Process interruption/restart was tested; sudden
power loss, filesystem failure and tampering are not claimed as proven.
Unrecoverable intent blocks reads/writes rather than guessing or deleting it.
Operational receipts are retained for idempotency; automatic receipt pruning,
memory compression and storage/schema redesign are excluded.

No auto-approve/reject/delete, batch deletion, LLM-controlled edits, new Memory
Store, Persona/RAG redesign, Voice/LLM/Live2D changes, Glass work or packaging.
Approved edits/deletes affect future Context assembly; historical turns are
not regenerated or rewritten.

Still unresolved: **Voice Full Manual Matrix NOT COMPLETED**, **G01 percentage
pronunciation Major**, **LEGAL REVIEW RECOMMENDED** (including ORT MPL-2.0
obligations), and **Packaging / First-run NOT COMPLETED**. V4-8C does not resolve
these items and does not authorize V4-8D.

# Stage V4-8B — Memory Visibility & Candidate Inspection

Status: **PASS**. Starting HEAD: `c56b5756c2724c84fd282d3eb823c45f58212743`.
Branch: `refactor/aurora-v4`. Implementation, directly related regressions,
Release build and real Windows Desktop UI smoke passed. No V4-8C work.

## Implemented scope

- Python `MemoryStore.inspect_records()` reads the same existing memory and
  candidate files and shares the existing reader/writer lock. It neither calls
  normalization nor writes/restores files. It reports missing/primary/backup;
  unusable storage fails explicitly instead of appearing empty.
- Production Sidecar uses `composition.context.memory`, with a bounded
  allowlisted projection. Saved records include disabled/archived/superseded
  records with their real metadata; candidates include pending records only.
  Legacy absent fields remain absent. Existing implicit-pending legacy records
  are labelled as lacking a persisted status.
- Authenticated `memory.read.request/response` and Rust `memory_read` provide
  four read operations: Saved list/detail and Pending list/detail. Rust validates
  the DTO and forwards correlated frontend events. Request IDs and connection
  epochs preserve the existing gateway boundary. No frontend filesystem or DB
  access. Production capability `memory=true` means inspection only.
- Settings → **记忆 / Memory** expands two independent sections. Loading, Empty,
  Ready and Error are visible, with retry/refresh, pagination and full detail.
  Candidate copy explicitly distinguishes it from saved memory. Text/metadata
  use textContent, so stored text is never interpreted as HTML.
- Close/disconnect invalidate requests and clear inspected content. Late list,
  detail, wrong-collection and wrong-record responses cannot replace the current
  view. Settings close returns to the existing chat and preserves its draft.

Excluded: approve/reject/edit/delete, auto-approve/delete/merge, compression,
schema or storage redesign, Persona changes, unrelated runtime or UI redesign,
new voice providers, packaging and later stages. No new runtime dependency.

## Validation

| Gate | Result |
| --- | --- |
| New Python Memory inspection tests | 14 PASS |
| Related Python Context/Post-Turn/Settings/Memory regressions | 101 PASS |
| v4 Chat/Conversation/Voice regressions | 38 PASS |
| IPC contract regression | 27 PASS |
| Unique Python/v4 tests, final applicable results | **180 PASS** |
| Frontend unit tests | **41 PASS** |
| Memory UI scenarios with controlled IPC | **10 PASS** |
| V4-8A controlled workflow regression | PASS |
| Rust Desktop | **70 PASS**, 2 existing opt-in ignored |
| `pnpm build` and Release `pnpm tauri build --no-bundle` | PASS |
| Real Release + Rust + authenticated Python + existing Store | PASS |
| Real native Windows UI input/screenshot/accessibility smoke | PASS |
| Normal exit, owned process identities | 0 remaining |

Applicable results combine the original 114-test related Python run (13 initial
inspection tests plus 101 regressions), the 38 passing v4 regressions, and final
inspection/contract recheck (14 + 27). Counts are deduplicated, not a claimed new
full historical-suite run. The final recheck tightened rejection of numeric read
handles; it preserves the string-ID paths exercised by the Desktop smoke.

The Release smoke used an isolated user-data/WebView profile and non-personal
fixtures in the existing schema. Both real API lists/details were exercised;
only the isolated fixture was changed to test empty/error/retry. Real user memory
was not modified. Saved/candidate hashes match before inspection, after the
ordinary chat turn and after native UI interactions. One local LLM turn completed
with Local Melo/Rust Audio playback while the Memory page was open; Avatar
remained ready/visible and returned to idle/mouth=0. Settings close/reopen and
Show/Hide preserved conversation/draft and critical runtime identities.

Native smoke used Windows input on the Release window to open Saved and Pending
details, scroll, return to chat and reopen Settings. It is agent-observed native
smoke, **not a claimed new human acceptance or Voice listening matrix**.

Detailed local evidence: `tests/output/v48b/v48b-final-report.md`, test logs,
`runtime-umVQb2/report.json`, `native-smoke.json` and `native-details.txt`.

## Limits and retained open items

- Snapshot inspection, explicit refresh; no candidate-change subscription,
  search/export, approval or editing. Lists are paged at 20, with 160-character
  previews; detail supports 32,768 characters and 16 KiB projected metadata.
  Oversized detail is an explicit error, not silent truncation.
- Read handles are fingerprints, not new stored IDs. A changed record requires
  list refresh. Legacy missing fields are not synthesized or migrated. Backup
  reads are clearly labelled and do not repair primary storage.
- **Voice full manual matrix NOT COMPLETED**; **G01 percentage reading Major**
  remains. No 65-synthesis voice soak or full manual matrix rerun.
- **LEGAL REVIEW RECOMMENDED**; existing ORT/MPL-2.0 obligations remain. No legal
  clearance claimed. No new architecture/runtime/license blocker observed.
- **Packaging / First-run NOT COMPLETED**. Single speaker, no cloning, limited
  lexicon/special-symbol coverage and ONNX internal cancellation limits remain.
- WIP Glass and all 12 historical untracked files are protected. Stage closure
  records the final commit, remote equality and hashes in the local final report.

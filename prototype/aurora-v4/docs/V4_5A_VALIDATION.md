# V4-5A — Validation and delivery report

Branch: `refactor/aurora-v4`. Starting HEAD:
`dcd26fb22f3d2140a2baa110f338069c56b33db7`.
The delivery commit hash and verified local/remote HEAD are reported in the final
handoff (a document cannot contain the hash of its own commit).
The headless extraction and adapter migration are one cohesive commit: splitting
them would leave the old checked-source adapter incompatible at the intermediate
checkpoint. No amend, force push or history rewrite.

## Final evidence

| Check | Result |
|---|---|
| Full source pytest, isolated data root | **976 passed, 3 skipped** |
| V4 sidecar/contracts | **137 passed** |
| Final Settings + V4 rerun | **185 passed** (48 service + 137 V4) |
| Rust, including real offline sidecar settings routing/restart/backend_lost | **18 passed, 1 ignored** (opt-in real Ollama smoke) |
| Frontend transport/state regressions | **17 passed** |
| TypeScript / Vite | Passed |
| Tauri release | **Passed**, final source build 1m 48s; aurora-v4-desktop.exe produced |
| compileall | **260 Python files**; tracked plus new source files |
| Draft 2020-12 schema + executable validators | **36 examples passed** |
| default_settings.json | Valid JSON; working Git blob equals baseline; no key/default/format diff |
| git diff --check | Passed |
| Actual AppData settings read | loaded; 23 descriptors; revision 0; hash and mtime unchanged |
| Actual read-only smoke side effects | 0 writes, 0 network requests, legacy singleton uninitialized |
| Manual Settings GUI / Chat Send–Stop / first-visible | **NOT YET VERIFIED** |

All automated writes used fixture config roots. The whole source suite was run
with an isolated AURORA_USER_DATA_DIR, not the real AppData root. Only the explicit
read-only smoke used the real path resolved by app_paths; it prints no path/raw
config/secret/reasoning. Its policy observations remain off / 30m.

Final Settings/V4 rerun: 185 passed in 53.33s.
Final source rerun: 976 passed, 3 skipped in 52.92s.
These are separate fresh Python processes; the V4 result is not described as a
single-process combined-suite pass. The 48 service tests are included in both
the source suite and the Settings/V4 focused run.

## First failures are retained, not hidden

1. Initial V4 focused run: 4 failed, 63 passed. Old tests asserted that the
   settings module could not be imported at all / depended on the removed AST
   boundary. One injected stream stub was bypassed by per-call API rebuilding.
   Updated import assertions to test no writes/UI/threads/network/singleton;
   retained the injected API and passed the snapshot explicitly.
2. First full combined run: 23 failed, 1085 passed, 3 skipped. Root cause was
   legacy lazy-proxy method assignment delegation: monkeypatch saved a bound
   proxy get and installed a delegating get on its inner owner, causing recursion
   and cascading transport failures. Fixed method override vs data-property
   assignment distinction; added a direct regression. This was a code bug, not
   classified as flaky.
3. Initial schema coverage test assumed every definition used allOf; settings
   uses a closed direct object schema. Extended the coverage check without
   weakening the message/schema set equality assertion.
4. A new Rust test initially omitted the json macro import; fixed before the
   passing Rust run.
5. Later combined run: 1 failed, 1108 passed, 3 skipped. Existing
   RpcTests.test_created_identity_accepts_first_turn_then_materializes saw a
   missing conversation, alongside a Tk Variable finalizer warning
   (“main thread is not in main loop”). The individual rerun passed
   (1 passed); fresh-process full source and V4 suites passed. The warning
   suggests mixed Tk/worker process timing but is **not established as the
   cause**. No unrelated Tk/Conversation rewrite or timeout relaxation was made.

## Coverage / semantics

- Import/read safety; legacy explicit load/migration and singleton get/set/data
  compatibility; descriptor allowlist; invalid existing host redaction.
- Types/enums/ranges/NaN/host authority/model capability; unknown/secret/read-only
  keys rejected; mixed invalid patch leaves disk and snapshot unchanged.
- No-op: unchanged revision, hash/mtime, no notification. Atomic persistence
  injects temp creation failure, mid-write failure, fsync failure, replace failure,
  and unserializable data. Original config remains readable, temp files cleaned.
- Stale revision, external edit, explicit reload, two concurrent updates,
  shutdown waiting for a file transaction, restart/reload round-trip.
- Generation N frozen during context and blocking HTTP; N+1 receives new
  thinking/keep_alive/RAG/Persona plus host/model. No per-token settings reread.
- Title debounce + running title retain originating model/settings; foreground
  guard still prevents title starts while foreground is active.
- Actual authenticated loopback Python sidecar: get/patch/changed/no-op/errors,
  secret redaction, child shutdown/restart. Fixture model server sees only tags
  for settings validation; no real model was loaded or generated by settings tests.
- Rust real offline sidecar: route commands, save while Ollama unavailable,
  restart reads policy, disconnected commands fail, old epoch event rejected.
- Frontend: change invalidation, out-of-order revision rejection, conflict and
  backend lost reset. No UI, local defaults copy, disk access or autosave.
- Explicitly clearing a migrated chat_model removes only retired model aliases,
  preventing resurrection on reload while preserving other raw/secret fields.

## Requested 41-point closeout index

| # | Item | Result / location |
|---|---|---|
| 1 | branch / HEAD | refactor/aurora-v4; final hash in handoff |
| 2 | commit hashes | One cohesive V4-5A commit, hash in handoff |
| 3 | push | Normal push requested; actual result and remote HEAD verified in handoff |
| 4 | Production Settings Audit | V4_5A_SETTINGS_AUDIT.md, all 95 defaults + dynamic/retired keys |
| 5 | Ownership Matrix | Same audit, AI/desktop/presentation/secret ownership |
| 6 | Stable changes | settings.py headless lazy boundary; settings_service.py; optional settings injection in chat.py; explicit legacy startup initialize |
| 7 | checked-source adapter | Removed Settings/Chat AST execution; compatibility façade uses real service |
| 8 | headless boundary | SettingsService / immutable SettingsSnapshot / SettingsError |
| 9 | import writes | No config write/migration/thread/network/Tk merely on import |
| 10 | root | Existing app_paths.CONFIG_FILE, no second V4 JSON |
| 11 | descriptor | 23 allowlisted descriptors, 20 mutable / 3 read-only |
| 12 | secrets | qq.access_token excluded; no secret update API or raw dump |
| 13 | RPC | get, update, changed on authenticated IPC v1 |
| 14 | validation | Strict types, finite bounds, enum, host/model format, existing policy parsers |
| 15 | atomic logical patch | Entire patch validated before IO/publication |
| 16 | no-op | No write/revision/event/probe |
| 17 | revision | In-memory expected_revision; conflict on stale/external edits; reset cache on restart |
| 18 | persistence | Same-dir temp + flush/fsync + replace + prepared snapshot publication |
| 19 | failure safety | Failure injections preserve original file/revision/snapshot |
| 20 | runtime apply | All current mutable keys next-request; no invented restart setting |
| 21 | generation | One settings snapshot before first await; N untouched, N+1 refreshed |
| 22 | post-turn | Originating generation model/settings retained through debounce/running |
| 23 | model | Format/capability only; missing model allowed; no pull/load; manual pin explicit |
| 24 | host | http(s) authority only, no credentials/path/query/fragment, valid port |
| 25 | thinking | Existing off/on/default parser; default off unchanged |
| 26 | keep_alive | Existing duration parser; default 30m unchanged |
| 27 | RAG/context | Next context sees changed settings; algorithms unchanged |
| 28 | cache | Atomic authoritative snapshot replacement; no per-token disk IO |
| 29 | external edit | Conflict check; explicit load or restart, no watcher |
| 30 | simultaneous Tk/V4 | Best-effort fingerprint, no cross-process lock; TOCTOU documented |
| 31 | changed | Keys/revision/restart keys only, after successful nonempty update |
| 32 | health | Next health.request or foreground preflight; settings update never waits on Ollama |
| 33 | Voice | Python legacy owner; V4 voice.ipc/streaming_pcm/cosyvoice_local remain false |
| 34 | Desktop | Low GPU frontend memory + Rust effect; window native/static config, no AI JSON writes |
| 35 | targeted tests | Service, real fixture IPC, snapshot/concurrency and transport/state tests |
| 36 | full regression | Full source plus fresh-process V4, Rust, frontend, release, compile/schema |
| 37 | defaults | No diff; defaults and policy parsers unchanged |
| 38 | contract | IPC_V1.md, schema/examples/validator, Python/Rust/TS synchronized; still v1 |
| 39 | status | Final handoff reports post-commit worktree |
| 40 | local / remote HEAD | Final handoff reports post-push comparison |
| 41 | Manual GUI | NOT YET VERIFIED, no Settings page built |

## Classification / next boundary

**Passed:** headless authoritative settings owner, safe read/update/persistence,
request snapshots, notification, contract/state tests, full regressions listed above.

**Acceptable limitations:** no cross-process lock; last check-to-replace race with
old Tk; old direct save primitive unchanged; health can remain stale until next
probe; revision is not durable across restart; auto embedding resolver remains
unmigrated/read-only; no-op comparison uses normalized submitted values against the
stored snapshot. RESTART_REQUIRED is reserved but no mutable key needs it.
Existing dead-code/linker informational warnings remain. Combined-process Tk
warning/flaky observation is recorded above, not silently reclassified as PASS.

**Blockers:** none in implementation or final automated/build validation.
Actual Git delivery status is verified and reported in the final handoff.

**Not yet verified:** Manual GUI (Settings and Chat Send/Stop/first-visible);
real writes to user AppData intentionally not attempted.

Eligible to plan **V4-5B — Settings UI Migration** after this checkpoint.
This delivery does not start V4-5B.

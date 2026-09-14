# V4-3C — Conversation Persistence & History

## Scope

V4-3C adds the smallest production conversation boundary to the v4 prototype.
Python is the sole owner of the existing Aurora JSON store; Rust only routes
IPC and the TypeScript store is presentation state. Memory, Persona, Knowledge,
RAG, Conversation Intelligence, automatic titles, Voice and TTS remain out of
this path.

## Persistence audit

`modules.conversation.ConversationManager` is headless-safe to import: its
module import performs no I/O. Its constructor creates the configured directory
but does not load or rewrite conversation files. `list_conversations()` and
`load()` are read-only. `save()` writes the existing JSON schema directly and
does not call title generation, Conversation Intelligence, or Memory; the
legacy UI separately schedules those features, and the v4 adapter never calls
that scheduler. The existing write primitive is not temp-file/replace atomic;
that pre-existing integrity risk is recorded as technical debt and no migration
or bulk rewrite is performed here.

The adapter resolves `%APPDATA%\\Aurora\\conversations` through
`modules.app_paths.CONVERSATIONS_DIR` (or an explicit disposable test root).
Only completed turns call `save_completed()`. Cancelled, failed, and
`backend_lost` generations do not save either the user message or partial
assistant output. A new identity is ephemeral until its first completed turn.

## IPC and UI behavior

`conversation.list` returns metadata only and preserves the existing updated-at
descending ordering. `conversation.get` is lazy and returns one safe DTO with
ordered system/user/assistant messages. Unknown roles are ignored at this
boundary. `conversation.create` allocates an opaque ID without creating an
empty file; a first completed turn materializes it. Missing IDs return
`NOT_FOUND`; IDs are restricted to `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`.

Production startup loads the list but opens no message bodies. Selecting an
item requests only that item's detail. The prototype blocks conversation
selection and creation while a generation is active; this avoids an implicit
cross-conversation cancel and keeps the single active-generation ownership
model explicit. Each chat request carries its conversation ID, so completion
cannot write to whichever conversation happens to be selected later.

## Evidence

- Existing AppData read-only check: 4 conversations; listing and one detail
  load changed no existing file hash or mtime (list 10.552 ms, get 0.169 ms).
- Isolated Python persistence/RPC tests exercise list/get/create/materialize,
  history ordering, malformed-file isolation, missing/traversal IDs,
  completed-turn history, cancel/failure no-save policy, and real WebSocket
  RPC routing.
- An isolated real Ollama two-turn smoke used `qwen3.5:9b`; the sidecar was
  restarted between turns, the second answer confirmed the persisted first
  turn history, and the final store contained five ordered messages. The
  temporary store was removed with its temporary directory (save fixture:
  8.895 ms).
- Isolated real-model cancel and backend-kill smokes left no conversation file
  for the interrupted turn; a fresh sidecar listed zero files and shut down
  cleanly. The built Windows desktop also passed normal and forced-close
  lifecycle checks with no orphan Python child.

## Regression status

Python sidecar/contracts, Rust gateway tests, and frontend tests/builds pass;
the full repository suite and compile checks are run at final handoff. No
Stable production file is modified by V4-3C.

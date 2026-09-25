# Aurora IPC v1

## V4-4B optional metadata notification

`conversation.changed` is a sidecar-originated, authenticated, backward-compatible
v1 event. Payload: `{ "conversation": ConversationMetadata }`, with the same six
safe fields as `conversation.create.response`. It has **no** request_id, session_id,
generation_id or seq. It never carries messages, summary, signals or Memory bodies.
Python emits after persisted background metadata updates; Rust validates the DTO
and active connection epoch before forwarding `conversation_changed`. The frontend
updates the sidebar record even when it is not selected; an unknown record triggers
the existing list request. It does not replace message history or active generation.
No new command, task queue RPC, capability or protocol version is introduced.
Notifications are best-effort; list/get remain the persistent source of truth.

This is the normative contract between the Rust Desktop Core and Python AI
Sidecar. The transport is an authenticated WebSocket bound only to loopback.
JSON text frames use the schema in `ipc-v1.schema.json`.

## Version and bootstrap

The protocol identifier is `aurora-ipc`; this document defines version `1`.
Python binds `127.0.0.1:0` and writes one machine-readable `bootstrap.ready`
JSON line to stdout. Logs use stderr. The ready object advertises every
supported version, so Rust can detect an empty intersection before connecting.

The WebSocket upgrade carries the per-launch token as an `Authorization:
Bearer` header. The first JSON message is `hello`, followed by exactly one
`hello_ack`. `hello_ack.payload.selected_version` must be present in both peers'
lists and equal the envelope version. Otherwise the connection closes with
`PROTOCOL_VERSION_MISMATCH`; there is no silent fallback.

## Envelope

```json
{
  "protocol": "aurora-ipc",
  "version": 1,
  "type": "chat.delta",
  "request_id": "req-chat-001",
  "session_id": "runtime-session-001",
  "generation_id": "generation-001",
  "seq": 0,
  "payload": {"delta": "Hello"}
}
```

Every WebSocket JSON frame requires `protocol`, `version`, `type`, and
`payload`. Other fields are required, optional, or forbidden by message type:

| Type | request_id | session_id | generation_id | seq |
| --- | --- | --- | --- | --- |
| `hello`, `hello_ack` | required | forbidden | forbidden | forbidden |
| `health.request`, `health.response` | required | forbidden | forbidden | forbidden |
| `shutdown.request`, `shutdown.ack` | required | forbidden | forbidden | forbidden |
| `chat.request`, `chat.accepted`, `chat.completed` | required | required | required | forbidden |
| `chat.delta` | required | required | required | required |
| `chat.cancel.request`, `chat.cancel.ack` | required | required | required | forbidden |
| `conversation.*` | required | forbidden | forbidden | forbidden |
| `state.changed` | forbidden | forbidden | forbidden | forbidden |
| `backend.warning` | optional | optional | optional | forbidden |
| `error` | optional | optional | optional | forbidden |

Unknown top-level or payload properties are rejected in v1, except unknown
capability keys, which are forward-compatible metadata.

## Identifier semantics

- `request_id` uniquely identifies one IPC command. A cancel command gets its
  own ID and names the original chat command in `payload.target_request_id`.
- `session_id` is the opaque runtime interaction owner. Stable Aurora currently
  creates a fresh voice/session owner independently of persisted conversations;
  v4 preserves that ownership role.
- `generation_id` uniquely identifies one assistant generation within a
  session. It is the stale-result/cancellation boundary and must not be reused
  after completion, cancellation, failure, disconnect, or restart.
- `conversation_id` identifies Python-owned persisted conversation data. It is
  inside `chat.request.payload` and may be `null` for a new unsaved
  conversation. It is never substituted for a session or generation ID.

Example: command `req-chat-001` starts `generation-001` in
`runtime-session-001` for persisted `conversation-demo-001`. A later cancel
command `req-cancel-001` targets `req-chat-001` and `generation-001`.

IDs are opaque non-empty strings. Neither side parses meaning from their text.

## Core message flow

The v1 callable surface is `health.request`, `chat.request`,
`chat.cancel.request`, and optional graceful `shutdown.request`.

```text
chat.request
  -> chat.accepted
  -> chat.delta (seq 0)
  -> chat.delta (seq 1)
  -> ...
  -> chat.completed (one terminal state)
```

`chat.request.payload.input` is the user input required for execution. Wire
payload and logging policy are distinct: neither Rust nor Python diagnostics
repeat that text. `chat.delta.payload.delta` contains visible assistant content
only. Reasoning text is neither emitted nor retained by this contract.

`chat.accepted` means Python registered ownership; it does not mean generation
completed successfully. A rejected request receives an `error` and, if it was
already accepted, one `chat.completed` with `terminal_state: rejected`.

### V4-3C conversation persistence extension

Production Python is the sole owner of the existing Aurora conversation store
resolved through `modules.app_paths`. `conversation.list.request` returns
metadata only; `conversation.get.request` lazily returns one validated history;
and `conversation.create.request` allocates an opaque identity without writing
an empty file. A completed `chat.request` writes the full user/assistant turn
through the same Python boundary. Cancelled, failed, and `backend_lost` turns
never persist a partial assistant response. Mock mode keeps its in-memory
presentation seed and does not expose these production RPCs.

Conversation payloads contain only `conversation_id`, title/timestamps, model,
message count, and (for `get`) ordered `{role, content}` messages. System,
user, and assistant roles are accepted; unsupported roles are ignored at the
history boundary. IDs are opaque and path-like values are rejected. Listing or
loading never rewrites existing JSON, and malformed files are isolated.

## Ordering

`seq` starts at `0` for each chat generation and increments by exactly one for
every `chat.delta`. WebSocket ordering does not replace ownership validation.
Rust checks connection instance, request, session, generation, terminal state,
and expected sequence before forwarding a delta.

A duplicate, reverse, or gap sequence is a protocol violation: log a safe
warning, drop the invalid event, and do not concatenate guessed or reordered
content. A delta after terminal state is stale and is also dropped. Depending on
severity, Rust may disconnect the faulty sidecar rather than continue a stream
whose integrity cannot be established.

## Cancellation and terminal race

```text
chat.cancel.request (new request_id, target_request_id, generation_id)
  -> chat.cancel.ack outcome=cancel_requested
  -> chat.completed terminal_state=cancelled
```

`cancel_requested` only acknowledges that Python accepted the cancellation
request. It is not proof the transport and workers have stopped. The canonical
terminal event is `chat.completed`. `chat.cancel.ack` outcomes are:

- `cancel_requested`: cancellation has begun; terminal event will follow.
- `cancelled`: the target is already terminal as cancelled.
- `already_completed`: another non-cancel terminal state already won.
- `not_found`: no matching owned request/generation exists.

Python marks the generation cancelled before aborting a transport, suppresses
late results, and preserves explicit-cancel priority over socket-close side
effects. Completion and cancellation race through one atomic terminal
transition. Exactly one of `completed`, `cancelled`, `failed`, `backend_lost`,
or `rejected` wins. A generation can never become completed and later
cancelled.

## Errors and terminal states

All accepted long-running requests produce exactly one `chat.completed` with a
terminal state:

- `completed`
- `cancelled`
- `failed`
- `backend_lost`
- `rejected`

After terminal state, all same-generation deltas and terminal events are stale
or protocol violations and are never applied. `error` carries safe detail using
the taxonomy in `ERROR_CODES.md`; it does not overwrite a winning terminal
state.

If the connection dies, Python cannot send a final frame. Rust atomically
synthesizes `backend_lost` for each active registry entry, invalidates every old
generation, and transitions the backend state to `DISCONNECTED`.

## Health and capabilities

`hello_ack` and `health.response` include the sidecar state, opaque
`sidecar_instance_id`, capability object, and concrete negotiated limits. The
meaning of each capability is frozen in `CAPABILITIES.md`. Health is not ready
merely because a process exists: handshake, limits and the selected backend
mode's required capabilities must succeed. Mock requires chat streaming/cancel;
V4-3B production additionally enables direct chat streaming/cancel. Neither
READY nor implementation inventory enables an unrelated RPC.

### V4-3A optional production health diagnostics

`health.response.payload.diagnostics` may contain the strictly typed
`productionDiagnostics` schema: backend mode/readiness, read-only settings
status, the existing Ollama policy diagnostics, and Ollama reachability,
sanitized HTTP origin, configured model/install availability, bounded probe
duration and a fixed error code. See `ipc-v1.production.examples.json`.
No IPC port/PID/token, file paths, settings contents or provider response bodies
belong in this object. Rust validates and maps it to a separate frontend DTO;
it does not forward a raw health envelope or capabilities object.

READY means composition constructed, settings loaded and configured model
present in a valid tags response. DEGRADED means composition/IPC still work but
settings use in-memory defaults, Ollama is unavailable, or the configured model
is missing/unset. No GPU inference readiness is implied. DISCONNECTED remains
Rust's actual process/transport loss. A health request re-probes; no background
poller or model auto-start is installed.

### V4-3B direct chat extension

V4-3B enables `chat_streaming` and `chat_cancel` for the production sidecar.
The sidecar constructs a one-message direct request and reuses Stable
`modules.chat.stream_chat()`; it does not invoke Memory, Persona, Knowledge,
RAG, persistence, or title generation. The blocking HTTP stream runs outside
the asyncio loop and forwards visible deltas through a bounded queue. Only one
generation is active per connection; a second request is rejected until the
first reaches its terminal state.

`chat.accepted.payload.ipc_received_unix_ms` and
`chat.delta.payload.python_sent_unix_ms` are optional non-negative wall-clock
observations. `chat.completed.payload.diagnostics`, when present, is the
strictly typed `chatDiagnostics` object in the schema. It contains durations,
counts, policy values, and worker/response lifecycle booleans only. Reasoning,
user text, assistant text, credentials, ports, PIDs, and paths are excluded.
Wall-clock bridge values are estimates; monotonic production timings remain
the authoritative durations.

Compatibility: this is an additive *optional* v1 field, with unchanged existing
message meanings, required fields and legacy examples. Updated validators accept
old messages without it. However, older strict v1 validators reject unknown
payload fields: an old gateway is NOT compatible with new production diagnostics.
Deploy this prototype gateway and sidecar together. Mock omits the extension and
stays wire-compatible. The V4-3B extension follows the same compatibility rule:
older strict validators reject unknown optional chat fields, so the matching
Rust/Python prototype pair must be deployed together. This is not a claim of
arbitrary old-client forward compatibility.

`state.changed` is an unsolicited lifecycle notification. Rust remains the
authoritative desktop state machine and validates the transition before
exposing it to the frontend.

## Security and payload policy

- Bind only `127.0.0.1`, never `0.0.0.0` or a LAN interface.
- Use a cryptographically strong, per-launch token; rotate it on restart.
- Never expose credentials, sidecar endpoint, or PID to the WebView.
- Keep the token out of argv, URLs, persistence, diagnostics, and errors.
- Reject failed authentication at upgrade time.
- Enforce the negotiated JSON/chat/event/binary byte limits before allocation
  or dispatch. Exact defaults are benchmarked in V4-2.
- Reject malformed JSON, unknown message types, extra fields, invalid IDs, and
  unsupported versions with a bounded safe error or connection close.
- Apply a minimal Tauri CSP/capability set; frontend code cannot open arbitrary
  localhost connections.

## Reserved Voice/PCM extension

V4-1 originally reserved Voice; V4-6B adds metadata-only status/stop below,
but still implements no binary audio transport. Future PCM
negotiation will introduce JSON metadata containing `generation_id`,
`stream_id`, `sample_rate`, `channels`, and `sample_format`, followed by binary
frames that carry a bounded header able to associate bytes with `stream_id`.
Terminal messages will distinguish `audio.end`, `audio.error`, and
`audio.cancelled`.

PCM is never base64-encoded into JSON. The future producer and Rust audio buffer
must both be bounded; backpressure must cross the sidecar boundary. Cancellation
discards buffered data for stale generations, and stale PCM never plays. V4-1
does not define a credit protocol or implement these reserved message types.

## Examples

### V4-5A Settings extension (still v1)

Authenticated request/response pairs carry request_id only, no generation/session/seq.
`settings.get.request` has an empty payload. `settings.get.response` returns
`revision`, `status`, and the explicit allowlisted `descriptors` (safe values/defaults,
type, mutable/apply/restart metadata, bounds/options/label/value_valid). It is not raw JSON.

`settings.update.request` requires `expected_revision` (nonnegative safe integer)
and a bounded `patch` object of flat dotted keys to scalar values.
Python validates every key/value before any persistence. A response contains only
`revision`, `changed_keys`, `restart_required_keys`.
Only nonempty successful changes emit `settings.changed` with this same payload,
without request/session/generation/seq. No-op produces a response but no event or file IO.
Concurrent updates are serialized; stale revisions/external edits produce CONFLICT.
Revision is process-local; gateway epoch invalidation and frontend cache reset require
a fresh get after backend loss/restart before editing. This is not a durable revision token.

Rust commands `settings_get` / `settings_update` route through the authenticated
transport. Typed frontend events are `settings_snapshot`, `settings_updated`,
`settings_changed`, `settings_error`; no Settings UI is added.
Secrets, unknown keys, and raw paths are not exposed. All current mutable descriptors
apply to the next request; restart_required_keys is empty. Embedding mode and resolved
model metadata are read-only (no automatic resolver is introduced).
See `ipc-v1.settings.examples.json`, `settings_contract.py`,
and [the complete ownership/runtime audit](../docs/V4_5A_SETTINGS_AUDIT.md).

`ipc-v1.examples.json` contains a bootstrap/handshake, health/capability reply,
three ordered deltas and completion, cancellation with cancelled terminal,
backend failure, and a Rust-synthesized backend-lost terminal. All text and IDs
are synthetic.

### V4-6B completed-turn Voice extension (still v1)

Production advertises `voice.ipc=true`; `streaming_pcm` and `cosyvoice_local`
remain false. Python calls the existing TTSRouter after a successful Chat
terminal, and owns file-backed playback. No audio or TTS text crosses this IPC.

- `voice.get.request`: `{}`; reply `voice.get.response` with the snapshot below.
- `voice.stop.request`: `{ "target_generation_id": "existing-chat-generation" }`;
  reply `voice.stop.response` with the authoritative snapshot.
- `voice.changed`: unsolicited snapshot event, without request_id.

Requests/responses carry request_id, but no envelope session/generation/seq.
Snapshot fields (no additional fields permitted):

| Field | Values |
| --- | --- |
| revision | Nonnegative safe integer, process-local |
| state | idle / preparing / speaking / stopping / error |
| enabled | Boolean, voice and playback settings both enabled |
| provider | empty / edge_tts / remote_cosyvoice / fake |
| generation_id | Existing Chat generation ID or null |
| error_code | Empty except in error state |

Safe error codes: VOICE_UNAVAILABLE, SYNTHESIS_FAILED, PLAYBACK_FAILED,
VOICE_TIMEOUT, INVALID_VOICE_SETTINGS. Raw provider exceptions, endpoint,
audio paths, worker identity and secrets are never forwarded.
Rust drops old transport epochs and non-increasing revisions; frontend also
drops stale revisions and resets on disconnect. Reconnect requests a fresh
snapshot. Stop targets the current generation; stale stops are harmless.
Voice Stop does not change Chat's terminal/history. Chat cancel suppresses
that generation's future Voice scheduling. This is not a PCM framing protocol.

Five descriptors use the existing settings authority and patch transaction:
`voice.enabled`, `voice.playback.enabled`, `voice.tts.provider`,
`voice.tts.voice`, `voice.tts.timeout_seconds`. Voice changes stop current speech
and take effect next turn. Remote endpoint remains backend-private.

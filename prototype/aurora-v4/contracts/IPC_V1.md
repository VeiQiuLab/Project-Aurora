# Aurora IPC v1

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
merely because a process exists: handshake and required chat capabilities must
succeed.

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

V1 implements no voice command or binary audio transport. Future voice
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

`ipc-v1.examples.json` contains a bootstrap/handshake, health/capability reply,
three ordered deltas and completion, cancellation with cancelled terminal,
backend failure, and a Rust-synthesized backend-lost terminal. All text and IDs
are synthetic.

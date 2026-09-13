# Aurora v4 process architecture

## Process boundary

```text
Web UI
  | Tauri commands and typed Channels
  v
Rust Desktop Core
  | authenticated loopback WebSocket
  v
Python AI Sidecar
```

The Rust Desktop Core is the only gateway. The WebView never receives the
Python port, token, PID, or filesystem paths and never opens a sidecar socket.
The sidecar never addresses the WebView. Rust validates, normalizes, checks
request/generation ownership, and only then emits typed frontend events. It is
not a transparent proxy.

The stable Tkinter application remains unchanged while this prototype is
developed.

## Responsibilities

Rust owns desktop lifecycle, window and native integration, AppData roots,
sidecar process supervision, the IPC connection, backend state, request
registry, cancellation routing, and frontend event routing.

Python owns AI execution: Ollama/LLM providers, context construction, Memory,
Persona, Knowledge/RAG, Conversation Intelligence, the TTS provider/router,
speech segmentation/generation semantics, and AI diagnostics. Conversation
persistence remains exclusively Python-owned during migration.

An AI request deliberately has split responsibilities: Rust owns the external
request registry and frontend routing; Python owns execution and its terminal
result. The protocol is the synchronization boundary. This is not dual
ownership of storage.

## Ownership matrix

| Resource | Owner / source of truth | Readers | Writers |
| --- | --- | --- | --- |
| Window lifecycle and native integration | Rust | frontend | Rust |
| Python process and IPC credentials | Rust | Rust only | Rust |
| Sidecar listener | Python child, supervised by Rust | Rust | Python |
| IPC request registry | Rust | Rust/frontend projection | Rust |
| AI request execution | Python | Rust through validated events | Python |
| Generation terminal state | Python while connected; Rust may terminalize as `backend_lost` after disconnect | Rust/frontend | Python or disconnect handler, exactly once |
| Conversation persistence | Python | Python through gateway APIs | Python only |
| Memory/Knowledge stores | Python | Python through gateway APIs | Python only |
| Desktop settings | Rust (future migration) | frontend/Rust | Rust |
| AI settings | Python initially | frontend through Rust | Python only |
| Audio device | Python in the first v4 migration | Rust candidate later | Python initially |
| Ollama process | existing Python/legacy manager initially | Python | Python |
| Aurora Voice Node | independent service | Python TTS provider | Voice Node |

Rust and Python must never both write the current conversation JSON or treat
the same persisted setting as authoritative.

## Settings boundary

Desktop settings (window position/size, theme, glass effects, low-GPU mode,
tray, startup) are Rust-owned after migration. AI settings (model, Ollama host,
thinking mode, keep-alive, Memory/RAG, TTS provider, Voice Node endpoint) remain
Python-owned initially. The frontend accesses both only through Rust commands;
it does not read `settings.json` directly. V4-1 performs no settings migration.

## Sidecar lifecycle

The Rust state machine is:

```text
STOPPED -> STARTING -> HANDSHAKING -> READY
              |             |          |
              +-----------> DISCONNECTED <---+
                                             |
DISCONNECTED -> RESTARTING -> HANDSHAKING ----+
READY/DEGRADED/DISCONNECTED -> STOPPING -> STOPPED
READY <-> DEGRADED
```

- `STOPPED`: no child and no connection.
- `STARTING`: child created; bootstrap line not yet accepted.
- `HANDSHAKING`: valid bootstrap received; authenticated WebSocket and version
  negotiation are not complete.
- `READY`: handshake succeeded and required v1 capabilities are available.
- `DEGRADED`: connection is alive but one or more non-core capabilities are
  unavailable.
- `DISCONNECTED`: startup failed, child exited, socket closed unexpectedly, or
  protocol integrity was lost.
- `RESTARTING`: an explicit user-requested restart is creating a fresh child.
- `STOPPING`: graceful shutdown or forced process termination is in progress.

V4 prototypes do not restart forever. A user may request `Restart Backend`.
Later releases may add a small bounded backoff policy, but it must never revive
old request or generation ownership.

## Crash and reconnect semantics

If the Python process exits or the WebSocket is lost, Rust stays alive,
transitions to `DISCONNECTED`, and atomically completes every active registry
entry as `backend_lost`. The UI remains usable and shows a safe `Backend
disconnected` state.

A restarted sidecar has a new process, token, connection, and
`sidecar_instance_id`. All pre-crash generations are permanently stale. A
persisted conversation may be reopened, but no old stream is resumed and no
late event from an old connection is accepted.

## Diagnostics and privacy

Python retains AI, Ollama latency, Memory/RAG, and voice-provider diagnostics.
Rust adds sidecar lifecycle, IPC latency, disconnect, frontend-command latency,
and later audio/device diagnostics.

IPC diagnostics may record message type, shortened request/generation IDs,
duration, status, byte size, sequence number, and safe error code. They must
not record the session token, full user or assistant text, prompts, memories,
knowledge content, reasoning text, or Python tracebacks. Detailed tracebacks go
only to the backend log on stderr.

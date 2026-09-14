# V4-3B real chat pipeline

V4-3B connects the already supervised desktop prototype to the existing
headless-safe `modules.chat.stream_chat()` boundary. It is deliberately a
direct chat experiment: one user message becomes one Ollama request, with no
Memory, Persona, Knowledge, RAG, persistence, title generation, Voice, or TTS.

## Runtime shape

```text
Aurora WebView
  -> typed Tauri command/channel
Rust Desktop Core
  -> authenticated loopback WebSocket (IPC v1)
Python Production Sidecar
  -> DirectChatAdapter
modules.chat.stream_chat()
  -> Ollama /api/chat NDJSON
```

Rust owns the request registry, generation identity, sequence validation,
frontend routing, and sidecar lifecycle. Python owns the blocking production
chat call and its request-local cancellation handle. `ChatExecution` runs that
blocking call in a worker thread and forwards visible deltas through a bounded
async queue (16 events); backpressure therefore stops unbounded token buildup.

Only one generation is active per sidecar connection. A new request while one
is active is accepted and immediately terminalized as `rejected` with
`BACKEND_NOT_READY`; it never starts a second Ollama request. A request ID or
generation ID replay is ignored. After a terminal event the owner is removed;
the bounded one-generation tombstone only lets a repeated cancel receive a
deterministic acknowledgement.

## Headless import audit

The adapter loads the source declaration for `modules.chat` with a fail-closed
AST guard. It compiles the actual module source in an isolated namespace and
requires the expected `stream_chat`, `ChatSession`, `OllamaRequestPolicy`, and
`StreamingRequestHandle` shapes. It does not import `main`, Tk widgets,
`ChatPage`, or context stores. Importing the adapter creates no UI, thread,
network connection, directory, or settings write. Context preparation returns
an empty snapshot and adds exactly the current user message.

The adapter calls the real `stream_chat()` implementation; it does not copy an
Ollama client, NDJSON parser, think resolver, keep-alive resolver, or transport
abort implementation. The only stable production change is the optional,
backwards-compatible `collect_memory_candidates` keyword. Direct chat passes
`False`, so a direct response cannot enqueue a Memory candidate; the default
remains `True` for existing callers.

## Policy and privacy

Model, host, thinking mode, and keep-alive are resolved through the existing
read-only settings snapshot and `OllamaRequestPolicy`. The current production
snapshot resolves to model `qwen3.5:9b`, `think=false`, and `keep_alive=30m`,
but none of these values is hard-coded in the adapter. Reasoning text is
counted for diagnostics and never emitted, persisted, or logged. Logs contain
short IDs, counts, durations, status, and safe error codes only; prompts and
assistant bodies are not logged.

## Cancellation and failure ownership

The cancel command sets the generation's cancellation truth before touching the
socket. `StreamingRequestHandle.cancel()` closes the request-local response,
which wakes a blocked `urllib` read. The Python worker exits before the single
terminal event is sent. If socket shutdown produces `IncompleteRead`, reset,
or bad-file-descriptor errors after an explicit cancel, they are cancellation
side effects and cannot replace `cancelled`. Non-cancel transport errors map to
`failed`; unavailable Ollama and a missing configured model map to
`PROVIDER_UNAVAILABLE` and `MODEL_UNAVAILABLE` respectively. A cancelled
partial assistant is not committed to `ChatSession` or Memory.

If the sidecar disappears, Rust invalidates every active owner and synthesizes
one `backend_lost` terminal. Restart rotates the process, token, connection,
and sidecar instance ID; stale events from the old connection cannot enter the
new generation. Desktop close sends the normal shutdown request and the
existing Windows Job Object reaps the owned sidecar. Ollama is an independent
user service and is not killed by desktop close.

## IPC additions

IPC v1 remains the protocol version. Chat events add optional wall-clock
observations (`ipc_received_unix_ms`, `python_sent_unix_ms`) and an optional,
strictly typed `chatDiagnostics` object on `chat.completed`. All additions are
optional for old message producers, but older strict validators reject unknown
fields; this prototype's Rust and Python peers must therefore be deployed as a
pair. The existing voice/PCM reservation remains unchanged.

## Known boundaries

`urllib.request` cannot abort the narrow interval before `urlopen()` exposes
response headers. Once a response exists, cancellation closes it directly;
the implementation does not replace the HTTP client for that edge. Cross-
process wall-clock timings are estimates and may differ by sub-millisecond
clock skew; monotonic production timings are the authoritative durations.
This stage measures direct-chat latency only and does not represent full Aurora
context-chat latency. Resource measurements are observational; no model,
quantization, context, or Ollama setting is changed by the smoke tool.

## Validation entry points

The opt-in observer starts a production desktop with a temporary WebView2
profile and read-only CDP performance collection. The user performs Send,
Stop, Crash, Restart, and Close in the visible window; the observer never
generates a request or changes settings:

```powershell
.\.venv\Scripts\python.exe prototype\aurora-v4\sidecar\smoke_real_chat_desktop.py `
  --desktop-exe prototype\aurora-v4\desktop\src-tauri\target\release\aurora-v4-desktop.exe `
  --report $env:TEMP\aurora-v43b-real-chat.json
```

The report records text-free performance marks, sanitized sidecar stderr,
model availability from `/api/ps`, desktop exit status, settings hash before
and after, and any Python PIDs seen during the run. It marks forced cleanup
explicitly; a normal close must have exit code `0`, no forced cleanup, and no
orphan sidecar PID.

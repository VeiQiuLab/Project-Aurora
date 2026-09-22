# Python sidecar lifecycle contract

V4-6A adds a V4-only BuiltInLlamaProvider selected by Rust's private environment
handoff. Runtime/process/auth remain Rust-owned; production Settings, context,
conversation and post-turn owners are preserved. Stable's Ollama default is
unchanged. See [Local runtime architecture](../docs/V4_6A_LOCAL_RUNTIME.md).
The descriptions below record earlier stages rather than today's desktop default.

V4-5A replaces the checked-source Settings/Chat bridge with direct headless-safe
production imports and request-local immutable settings snapshots. AI settings
remain Python-owned in the existing app_paths.CONFIG_FILE; no second V4 file.
Read/patch/change notifications use authenticated IPC v1. See
[Settings ownership/runtime audit](../docs/V4_5A_SETTINGS_AUDIT.md).
The real-config smoke is read-only:
`python -B prototype/aurora-v4/sidecar/smoke_settings_readonly.py`.
It prints safe scalar results only; all update tests use isolated settings roots.
No Settings page is included. Manual GUI remains **NOT YET VERIFIED**.

V4-3C adds Python-owned conversation list/get/create and completed-turn
persistence on top of the V4-3B direct-chat RPC. History is loaded lazily from
the existing `modules.app_paths` conversation directory; cancelled, failed,
and disconnected generations never write partial assistant content. The
legacy title, intelligence, and memory schedulers are not called.

V4-3B adds an opt-in direct-chat RPC on top of the V4-3A production
composition. It reuses the headless-safe Stable `modules.chat.stream_chat()`
boundary and runs its blocking Ollama stream in a worker thread. It does not
enable persistence, context systems, voice, or PCM IPC. See
[V4_3B_REAL_CHAT.md](../V4_3B_REAL_CHAT.md) and
[V4_3B_VALIDATION.md](../V4_3B_VALIDATION.md) for the boundary and evidence;
the additive conversation message contract is documented in
`../contracts/IPC_V1.md`.
Default is mock; `AURORA_V4_BACKEND=production` selects production.

V4-1 defined this lifecycle without an implementation. V4-2 adds an isolated
mock under `mock_sidecar/`, pinned to `websockets==17.1` in a prototype-local
virtual environment. It emits only fixed synthetic tokens and imports none of
Stable Aurora's AI, persistence, settings, or voice modules.

## Bootstrap

1. Rust generates a cryptographically strong token for this desktop launch.
2. Rust starts one Python child with the token and supported protocol versions
   in inherited environment variables. The token is never a command-line
   argument.
3. Python binds `127.0.0.1` on port `0`, allowing the operating system to choose
   a free dynamic port.
4. Python writes exactly one UTF-8 JSON line matching `bootstrap.ready` to
   stdout, flushes it, and never writes ordinary logs to stdout.
5. Rust reads that bounded line, validates protocol/version/PID/port, then opens
   the loopback WebSocket with `Authorization: Bearer <session-token>`.
6. Rust and Python exchange `hello` and `hello_ack`. Rust enters `READY` only
   after the selected version and required capabilities are accepted.

Recommended inherited variables (names are part of the bootstrap contract):

- `AURORA_IPC_TOKEN`: high-entropy, per-launch bearer secret.
- `AURORA_IPC_PROTOCOL`: `aurora-ipc`.
- `AURORA_IPC_SUPPORTED_VERSIONS`: comma-separated versions, initially `1`.

The bootstrap line contains the selected port, PID, supported versions, and a
fresh opaque `sidecar_instance_id`; it never contains or echoes the token.

On this Windows Python distribution, a virtual-environment `python.exe` is a
launcher that starts the base interpreter as a child process. Rust reads the
selected venv's `pyvenv.cfg`, starts that base interpreter directly, and adds
its `site-packages` plus explicit source paths to `PYTHONPATH`. Production uses
the repo venv, mock the prototype venv. The bootstrap PID
therefore matches the process Rust supervises. Rust assigns that process to a
kill-on-close Job Object, which also contains any descendants.

Python choosing port `0` avoids the time-of-check/time-of-use race created when
Rust reserves a port, releases it, and asks the child to bind it. Rust still
owns the child lifecycle; Python owns only its listener. The small extra cost
is parsing the bootstrap line, which is required for version discovery anyway.

## Output and shutdown

Normal logs and tracebacks are UTF-8 on stderr. The desktop drains stderr so the
child cannot block on a full pipe and applies its existing log rotation/privacy
policy. stdout is a bootstrap-only machine channel.

Rust first sends `shutdown.request`. Python stops accepting new work, cancels
active work, responds with `shutdown.ack`, closes the WebSocket/listener, and
exits. After a bounded grace period Rust terminates the owned child. Exact
timeouts are implementation values to benchmark in V4-2, not invented here.

If bootstrap is malformed, too large, times out, reports no common version, or
the child exits, Rust enters `DISCONNECTED` and surfaces a safe diagnostic.

## Authentication boundary

The listener is loopback-only and rejects an HTTP upgrade without an exact
bearer token before accepting protocol messages. Credentials are never placed
in a URL/query string, log, persistent settings, conversation data, or frontend
event. A fresh restart rotates both token and `sidecar_instance_id`.

This protects against accidental or unrelated localhost clients. It is not a
defence against a process already running as the same compromised OS user.

## Prototype setup and tests

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The server isn't intended to be started by hand. Rust supplies its bootstrap
environment, supervises it, and places it in a kill-on-close Windows Job Object
so an abnormal desktop exit cannot orphan the Python child.

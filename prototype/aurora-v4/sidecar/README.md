# Python sidecar lifecycle contract

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
prototype venv's `pyvenv.cfg`, starts that base interpreter directly, and adds
only the prototype venv's `site-packages` to `PYTHONPATH`. The bootstrap PID
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

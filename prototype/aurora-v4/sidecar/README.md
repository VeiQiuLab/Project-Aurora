# Python Production Sidecar — 当前入口与生命周期契约

正常 V4 EXE 默认使用 Production Sidecar，由 Rust 监督；mock 仅为显式隔离测试。
Python 复用根 `modules/` 的 AI/Settings/Memory，使用根 `.venv` 完整依赖，不导入 Tk 桌面。
已有对话持久化、Context/Persona/Knowledge/RAG/Post-Turn、Memory 查看/治理、Voice 和 QQ 适配。
设置界面已经实现；历史 V4-3A/3B 的「默认 mock、无持久化/Context/UI」不再代表当前状态。

模型由 Rust LocalModelSupervisor 管理 Qwen3.5-4B / llama.cpp Vulkan，Python 调用私有 provider。
本地 Voice 由 Rust LocalVoiceSupervisor 管理 sherpa/Melo Host，Python 保留 TTS semantics；
完整 WAV 经 Rust Audio 播放，voice.streaming_pcm=false。远端 Voice 仅 Compatibility / Legacy。
QQ 复用同一个 Sidecar/模型，独立 archive 与外部上下文不读写主人私人 Memory。

V4-8F **HOLD**。当前架构、准备与证据见
[根 README](../../../README.md)、[架构](../../../docs/ARCHITECTURE.md)、
[V4-8F](../../../docs/v48f-controlled-qq.md)。
下面保留 bootstrap/lifecycle 契约说明；历史 Windows/mock 环境描述按各阶段证据阅读。

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
timeouts are defined by the current Rust implementation; changing them requires
lifecycle and cleanup validation rather than relying on the historical V4-2 plan.

If bootstrap is malformed, too large, times out, reports no common version, or
the child exits, Rust enters `DISCONNECTED` and surfaces a safe diagnostic.

## Authentication boundary

The listener is loopback-only and rejects an HTTP upgrade without an exact
bearer token before accepting protocol messages. Credentials are never placed
in a URL/query string, log, persistent settings, conversation data, or frontend
event. A fresh restart rotates both token and `sidecar_instance_id`.

This protects against accidental or unrelated localhost clients. It is not a
defence against a process already running as the same compromised OS user.

## Historical mock environment setup and tests

The following is the earlier isolated mock setup from this directory, not the
normal production AI dependency installation. For production, use the root
virtual environment and instructions in the repository README.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The server isn't intended to be started by hand. Rust supplies its bootstrap
environment, supervises it, and places it in a kill-on-close Windows Job Object
so an abnormal desktop exit cannot orphan the Python child.

## V4-6B optional Voice

Production now integrates the existing Python TTSRouter after successful Chat
completion. Voice settings still use the single project SettingsManager.
The optional Edge dependency is declared in the root `requirements.txt`.
Tk/pygame and historical microphone/package extras are now isolated in
`legacy/requirements.txt`; the older Voice lockfile is retained for those tools.
Missing dependencies report a Voice-only error, not Chat failure.
See [V4-6B ownership, lifecycle and validation](../docs/V4_6B_VOICE.md).

B-3 replaces only v4 production's pygame execution with private Rust playback.
`AURORA_AUDIO_ROOT` is supplied by the supervisor, not personal settings.
No bridge/root means Voice-only failure, never automatic pygame fallback.
Legacy pygame remains supported outside v4 production. See
[B-3 details](../docs/B3_RUST_AUDIO.md).

## Current local Voice route

V4-7B.3B integrated LocalSherpaMeloProvider with the Rust-supervised native host.
The earlier Edge/B-3 notes above describe the route at those stages, not the
complete current provider list. See [Offline Local Voice integration](../docs/OFFLINE_LOCAL_VOICE_INTEGRATION.md).
Existing provider selection is preserved; Local has no implicit network fallback.
Voice Full Manual Matrix remains incomplete, G01 percentage pronunciation is Major,
and LEGAL REVIEW RECOMMENDED includes ORT/MPL-2.0 obligations.

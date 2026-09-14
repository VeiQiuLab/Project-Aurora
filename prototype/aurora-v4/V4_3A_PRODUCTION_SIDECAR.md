# V4-3A — Production Python Sidecar Composition

Read-only headless composition, AI settings, GET-only Ollama health, capability
inventory and lifecycle. No real chat, persistence, voice IPC, PCM or V4-3B.
Accepted UI geometry/CSS remain unchanged; diagnostics live in the existing
developer menu only. `AURORA_V4_BACKEND=mock|production`, default **mock**.

## Composition and import audit

Rust BackendManager → production_sidecar/server.py → ProductionComposition owns
ReadOnlySettings, the actual OllamaRequestPolicy, an OllamaHealth service, a
refresh lock and close state. The production server reuses tested v1 transport
from MockSidecar through small state/health hooks, overriding both chat commands
to reject. No mock generator runs in production.

| Module | Import-time finding | Decision |
| --- | --- | --- |
| app_paths | Path computation/default-file stat; no mkdir, write, worker or Tk | Safe direct import; never call ensure_user_data_directories |
| ollama_request_policy | Pure stdlib declarations | Safe direct reuse, no copied resolver/defaults |
| settings | Eager settings=Settings() creates/migrates/saves real config | Needs read-only declaration adapter; no singleton import |
| chat | Transitive eager settings; no generation itself at import | Inventory only in 3A; not imported |
| settings_controller | Transitive eager settings; validation/save controller | Not imported/instantiated |
| logger | Eager logger makes log directory/file/handlers | Not imported; isolated stderr logging |
| service_manager | No eager worker/service; optional psutil, runtime_dependencies | Not instantiated; methods can start/stop services/write logs; use narrow GET adapter |
| runtime_state | No eager worker; first_run/runtime_dependencies transitive; UI root/after coupling at use | Must not compose: refresh can save selection/prepare voice |
| runtime_dependencies | Declarations/imports only; broad probes can persist model metadata | Not composed for health |
| models, i18n, first_run, dependency_actions | Constants/declarations, lazy locale cache; explicit actions only | Audited transitive dependencies; not required here |
| main, widgets, ChatPage, Voice UI, Live2D | GUI/application composition | Must not import |

Audit checked top-level execution, global instances, filesystem/settings I/O,
logger handlers, Tk, workers, subprocesses and main.py coupling. Selected imports
have no UI/main dependency, service startup or background worker. Import-safety
test prohibits writes, subprocesses/network and checks forbidden modules and
thread count. Actual HTTP work uses asyncio's joined executor and context-managed
responses. Existing AuroraLogger StreamHandler uses **stderr**, not stdout; its
eager filesystem ownership is why this stage isolates logging.

## Read-only production Settings bridge

The production Settings module has no injectable read-only constructor and
creates a singleton. The adapter loads its **actual class declaration** from
source, checks the narrowly audited top-level shape (three known imports,
method-only Settings class, terminal singleton assignment), and compiles only
that declaration into a private namespace. It does not patch sys.modules,
copy defaults/migration/policy code or modify stable production.

A subclass overrides load/save/set/update_many: real defaults/getters/migration
methods run in their existing order, in memory only. A parity test compares this
normalization with the actual Settings constructor using disposable files.
Shape drift fails closed with SETTINGS_DECLARATION_CHANGED. This is an explicit
**source-checkout development bridge**, not an arbitrary-code security sandbox
or packaged/frozen loader. Packaging should replace it with a reviewed injectable
settings boundary; do not silently package this source loader unchanged.

Settings come from app_paths.CONFIG_FILE: AURORA_USER_DATA_DIR override, otherwise
APPDATA/Aurora/config/settings.json, retaining the existing production fallback.
No repo/data guess, settings-v4 file, writes or automatic model selection/save.
Missing config uses real defaults without creating directories. Invalid JSON,
non-object or read failure uses in-memory defaults and DEGRADED. Valid old config
migrates in memory only. Existing thinking_mode/keep_alive are resolved by the
actual production policy (defaults off/30m unchanged).

## GET health, state and capabilities

Sidecar uses only GET /api/tags, consistent with existing production health.
No chat/generate/embedding/pull, model warmup, subprocess or Ollama auto-start.
Host must be an HTTP(S) origin, without credentials/query/fragment/path;
redirects/environment proxies are disabled. Reply bounded to 1 MiB, socket
timeout 1 s. Refresh is serialized; no background poller. A slow-drip untrusted
server can extend per-socket timeout; Rust startup timeout/Job Object still bound
startup ownership. This is not a general untrusted-network HTTP client.

Configured model is manual chat_model, or existing resolved_chat_model in Auto
(falling back to chat_model). Compare tags, including implicit :latest. Do not
pick/download another model. Installed is not a GPU/inference-readiness claim.

- READY: constructed composition, loaded settings and configured model in tags.
- DEGRADED: functioning IPC but settings fallback, offline/invalid Ollama reply,
  missing/unset model.
- DISCONNECTED: actual process/IPC loss, owned by Rust.

Top-level chat_streaming/chat_cancel/memory/knowledge/rag are false (not callable).
Optional implementation metadata describes source presence only, not dependency
or inference validation. Edge/Remote voice inventory is based on implementation
files; voice.ipc=false, voice.streaming_pcm=false, cosyvoice_local=false.
Rust gates chat; Python independently rejects both commands with existing
BACKEND_NOT_READY, retryable=false and a V4-3A-specific safe explanation.

Optional health diagnostics use the updated v1 schema/examples/validators.
Updated gateway accepts old messages; old strict validators reject the new
optional field, so gateway/production sidecar deploy together. Mock remains
wire-compatible. Frontend receives a typed allowlist, never the raw envelope,
Python PID, IPC port/token/instance ID, file paths or provider response bodies.

## Interpreter and launch

Existing production source uses main.py and explicit Python selection in build
scripts; no stable launcher is changed. Development needs Python 3.12 and
websockets==17.1 in the repository .venv; only tests/smoke additionally require
requirements-dev.txt. GUI, voice and other AI packages are not imported here.

```powershell
# From repository root; substitute your checkout location normally.
& .\.venv\Scripts\python.exe -m pip install -r prototype/aurora-v4/sidecar/requirements-dev.txt
$env:AURORA_V4_BACKEND = 'production'
& .\prototype\aurora-v4\desktop\src-tauri\target\release\aurora-v4-desktop.exe
```

Rust finds source by executable/cwd ancestors and app_paths/default JSON markers;
optional AURORA_V4_SIDECAR_DIR identifies sidecar root. Explicit PYTHONPATH makes
foreign cwd safe. Windows reads the selected venv's pyvenv.cfg and starts the
**base interpreter directly**, with that venv's site-packages; this avoids a
Windows venv redirector starting a second unsupervised PID. Production uses repo
.venv, mock uses sidecar .venv. UTF-8/no user-site/no bytecode writes are explicit.
Optional AURORA_V4_PYTHON must be an absolute base interpreter already provisioned
with dependencies; bootstrap PID must equal supervised PID. No bare python,
PATH or Windows Store fallback. This is source/venv **dev resolution**, not a
finished packaged interpreter distribution.

## Lifecycle and verification

stdout is one bootstrap JSON line only; logs/tracebacks stderr, no production
logger files. Missing dependencies/import failure never publish fake readiness;
Rust returns a fixed safe summary. Job Object kill-on-close and kill_on_drop own
Python/descendants. Normal IPC shutdown precedes bounded termination. Restart
rotates PID/token/port/instance/epoch. Stale startup/health cannot resurrect an
old epoch. No action owns or stops the user's existing Ollama service.

```powershell
# Offline tests; all settings mutations use temporary paths.
& .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider prototype/aurora-v4/sidecar/tests prototype/aurora-v4/contracts/test_ipc_v1_contract.py
cargo test --manifest-path prototype/aurora-v4/desktop/src-tauri/Cargo.toml

# Opt-in actual read-only Ollama + Rust gateway + built desktop lifecycle/RAM.
& .\.venv\Scripts\python.exe prototype/aurora-v4/sidecar/smoke_production_sidecar.py --desktop-exe prototype/aurora-v4/desktop/src-tauri/target/release/aurora-v4-desktop.exe
```

Real smoke runs gateway crash/restart, desktop normal/forced exit from foreign
cwd, settings hash and GET /api/ps before/after. No generation requests. RAM is
process working-set sum (may double-count shared pages), not private memory.
Startup is process/handshake readiness, not a measured first visual paint.
Results and limitations are recorded in V4_3A_VALIDATION.md.

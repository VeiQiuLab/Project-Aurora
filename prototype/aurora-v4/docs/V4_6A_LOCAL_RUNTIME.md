# V4-6A — Built-in local model runtime

## Scope and ownership

V4 production now defaults to `builtin_local`. Stable/Tkinter still uses its
unchanged Ollama transport. No Voice, PCM, Liquid Glass, layout or model-manager
work is included. The experimental Glass branch is untouched.

```text
Tauri frontend --typed IPC--> Rust BackendManager
                               |-- LocalModelSupervisor --Job Object--> llama-server
                               |                          127.0.0.1:ephemeral
                               |-- Python production sidecar --private HTTP/SSE--^
```

Rust alone owns runtime discovery, the process, random API key, dynamic port,
startup epoch and shutdown. Python receives the endpoint/key/model alias only
through its inherited environment. The frontend DTO contains only a logical
model name, provider/backend, readiness booleans, fixed error code and probe
duration. It cannot serialize the model path, runtime PID, endpoint or key.

The runtime loads eagerly on a background async startup task, before Python's
bootstrap. The window appears first and remains interactive. Spawn is NOT READY:
Rust requires `/health` to return `status=ok` AND authenticated `/v1/models` to
contain the launched alias. Loading is bounded to 120 seconds. A model failure
still starts Python so Settings/history remain usable; sending is disabled.
The separate supervisor entry point leaves lazy startup possible later, without
implementing a second lifecycle or a lazy-load feature in this stage.

Runtime states are STOPPED → STARTING → LOADING_MODEL → READY. Load/spawn/exit
failures enter FAILED; the desktop/backend becomes DEGRADED when model service
is unavailable. DEGRADED is reserved in the runtime state vocabulary for future
nonfatal runtime health. Shutdown moves through STOPPING to STOPPED. Each epoch
guards late startup and cleanup. Only one owned model process is permitted.
Each desktop start additionally carries its own permanently cancellable owner,
checked under the supervisor lock before accepting startup and spawning. A
shutdown that wins before the old task starts therefore cannot resurrect a model
or let stale cleanup touch the next instance.

Windows uses the existing kill-on-job-close Job Object implementation, one job
per supervised child. Normal close, runtime failure, failed Python startup and
forced desktop termination clean owned processes only. Existing developer
`restart_backend` stops BOTH old children before creating fresh processes,
endpoint and keys. There is no automatic crash retry loop. A 500 ms monitor
detects model exit and terminalizes active generations; Python/Desktop survive.

## Pinned runtime and model discovery

Run once from the repository root, with Aurora closed:

```powershell
& .\prototype\aurora-v4\runtime\bootstrap.ps1
```

`runtime/manifest.json` pins the official upstream Windows x64 Vulkan archive:

- llama.cpp b10964, reported `0.4.1-dev`, commit
  `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`.
- [Official release](https://github.com/ggml-org/llama.cpp/releases/tag/b10964).
- SHA-256: `1ee3ad952f4ba71f438bd6d7bebef19e1c7af04adcaa35d08b4ddabb27d4c642`.
- MIT license, with the archive's separate LLVM OpenMP license retained.
- Default installation: `%LOCALAPPDATA%\Aurora\runtime\llama-b10964-vulkan`.
- Bootstrap verifies the archive before extraction and refuses an in-use runtime.
  No model is downloaded or accessed by bootstrap. Binaries/archive stay outside Git.

Model resolution uses `AURORA_LOCAL_MODEL_PATH` when explicitly supplied.
Otherwise it reads `%USERPROFILE%\.lmstudio\settings.json` → `downloadsFolder`,
falling back to `%USERPROFILE%\.lmstudio\models`. Discovery is restricted to that
root: depth ≤ 4, total ≤ 4096 entries, symlink entries ignored, drive roots
rejected. `mmproj*.gguf` is excluded. Exactly one model is required; ambiguity
fails closed and asks for explicit selection. An absolute path, GGUF extension,
24-byte header and version 3 are validated before spawn; inference compatibility
is validated by the real upstream loader/readiness, not a filename heuristic.

Optional development overrides (absolute paths, never required in the UI):

```powershell
$env:AURORA_LLAMA_SERVER = '<absolute path to official llama-server.exe>'
$env:AURORA_LOCAL_MODEL_PATH = '<absolute path to existing GGUF>'
```

`ExternalExisting` is the current source policy. A future Aurora-managed model
directory is not implemented. This stage never moves, copies, rewrites or
renames the LM Studio model; LM Studio itself is not invoked.

The verified file is `Qwen3.5-4B-Q4_K_M.gguf`, under
`lmstudio-community/Qwen3.5-4B-GGUF` in that discovered directory:

| Property | Actual metadata |
| --- | --- |
| GGUF / architecture | v3 / `qwen35` |
| Logical name | Qwen_Qwen3.5 4B |
| Quantization / file type | Q4_K_M / 15, quantization version 2 |
| File size | 2,707,513,696 bytes |
| Tensors / metadata fields | 426 / 34 |
| Blocks / embedding / FFN | 32 / 2560 / 9216 |
| Attention heads / KV heads | 16 / 4; hybrid recurrent/attention model |
| Declared context | 262144; NOT the configured runtime context |
| Tokenizer | gpt2, pre-tokenizer qwen35; 248320 tokens; 247587 merges |
| EOS / pad / BOS policy | 248046 / 248044 / add_bos=false |
| Chat template | Embedded Jinja template; supports `enable_thinking=false` |

The separate `mmproj-Qwen3.5-4B-BF16.gguf` is not used for text chat. Model size
and nanosecond modification timestamp were recorded before initial work. Real
smokes recheck size/mtime and verify exclusive read access after shutdown.

## Runtime parameters and limits

Current parameters: loopback host, dynamic port, context **4096**, parallel **1**,
`--device Vulkan0 --gpu-layers auto --fit on --reasoning off --no-webui`.
The binary directory is the working directory for its accompanying DLLs.
No CUDA/ROCm installation, driver, registry, pagefile or system setting changes.
Fit/offload is upstream's automatic policy, not hardcoded all-layer placement.
Unsupported Vulkan/model/OOM/bind/template failures remain safe unavailable
states; no silent provider or quantization substitution is implemented.

Two UUIDv4 values supply the per-launch high-entropy bearer key, passed to
upstream through `LLAMA_API_KEY`, not the command line. Upstream `/health` is
public even with auth; model/API endpoints require the key. Loopback/auth do not
protect against another process already running with the same user's privileges.
The small bind-release-spawn dynamic-port race is handled as a startup failure.

Both runtime output pipes are drained with a bounded 16 KiB record. Raw output
can contain paths/templates/prompts, so it is deliberately NOT persisted or
forwarded. Only fixed error categories and allowlisted numeric memory/offload
metrics are logged. Verbosity 4 is needed by this upstream revision for loader
metrics. This privacy restriction takes precedence over retaining full stderr.

## Minimal provider boundary

The existing DirectChatAdapter still supplies ChatSession, request-local
StreamingRequestHandle and the production immutable settings/context pipeline.
In built-in mode only `stream_chat` and `chat_with_messages` are replaced with
the V4-only BuiltInLlamaProvider. `modules/chat.py` and the Stable default are
unchanged. Explicit `AURORA_V4_CHAT_PROVIDER=ollama` selects the legacy path;
`AURORA_V4_BACKEND=mock` remains the UI fixture without loading a model.

Wire contract is pinned to the actual upstream
[server API](https://github.com/ggml-org/llama.cpp/blob/b29c606e28a01b1bc8c1351026a0fa6e616bf6c4/tools/server/README.md):
`POST /v1/chat/completions`, messages, `stream=true`, `max_tokens`, temperature,
`stream_options.include_usage=true`, and
`chat_template_kwargs.enable_thinking=false`. The embedded template is retained;
no hardcoded ChatML/Qwen template. No `think`, `keep_alive`, `options` or
`num_predict` Ollama fields are sent. Default output cap is 1024 tokens; titles
translate the existing 32-token policy into `max_tokens=32`.

SSE processing emits content incrementally, counts but never logs reasoning,
records upstream usage/timings, and requires a successful finish reason plus
`[DONE]`. Invalid/incomplete streams and HTTP/transport failures remain failures.
The existing gateway generation/sequence/terminal guards remain in force.

Cancellation retains stop_event as truth and closes only the request's response.
A duplicated socket plus cancellable RawIO HTTP reader allows Windows blocked
reads (including response headers) to notice cancellation every 20 ms; the normal
HTTP parser still handles framing. Actual TCP connect is bounded to 5 seconds
but cannot be aborted before a socket is registered. The watcher is joined,
response references clear, and cancellation-induced socket errors cannot replace
cancelled with failed. Cancel/failure restores the ChatSession snapshot and does
not persist a partial assistant. No global connection pool is shared.

Memory, Persona, Knowledge, optional RAG and history still enter the same
production context builder. The existing retrieval fallback operates when an
optional external embedding service is absent; no embedding model replacement
or RAG tuning is added. Title generation uses this same local provider and the
existing debounce/final guard. Foreground start aborts an in-flight built-in title
request; stale title output is discarded/deferred, not published as a fallback.

Settings remains Python-owned. Existing Ollama controls are retained for legacy
compatibility and labelled not applicable in built-in mode; the only new visible
information is local model identity/Vulkan/readiness. Model path/backend/provider
selection are internal development configuration, not a second settings file.
Built-in READY does not depend on Ollama health; legacy diagnostic values are
explicitly unavailable/default/null rather than pretending to describe llama.cpp.

Two pre-existing blockers exposed by real persistent chat needed minimal fixes:
Tauri calls now use camelCase `conversationId`; metadata-list refresh preserves
the active conversation and its loaded messages. Without these, turns lacked
persistence/identity or the next send silently had no selected conversation.
Neither fix changes the layout or design.

## Validation commands

```powershell
# Repository root; unit tests never load real model weights.
.\.venv\Scripts\python.exe -m pytest prototype/aurora-v4/sidecar/tests prototype/aurora-v4/contracts -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/output -q -p no:cacheprovider

Set-Location prototype/aurora-v4/desktop
pnpm test
pnpm build
cargo test --manifest-path src-tauri/Cargo.toml --lib
pnpm tauri build --no-bundle
# Playwright/sharp must be available through NODE_PATH or an external dev install.
node tests/local_runtime.mjs
node tests/local_runtime.mjs --kill-desktop
node tests/release_webview.mjs
pnpm test:ui
pnpm test:geometry
```

Real runtime smoke uses synthetic data in ignored `tests/output/v46a-local`,
refuses pre-existing LM Studio/Ollama/runtime/Aurora processes, starts the actual
Release/WebView2 executable, and uses only its observed child PIDs for crash
testing. It checks streaming, Stop/recovery, history, context, persistence/reload,
local title, duplicate instance, runtime crash/restart, and close during generation.
The `--kill-desktop` variant exercises Windows process termination/Job Object
cleanup. Reports omit prompt/response/reasoning and secrets; artifacts are not
committed. These are automated real-WebView2 checks, not manual IME/visual QA.

Installer distribution, model downloads, alternative GPUs/models, lazy loading,
long-context tuning and Voice integration remain outside V4-6A.

Results and explicit verification limits: [V4-6A validation](V4_6A_VALIDATION.md).

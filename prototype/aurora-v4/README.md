# Project Aurora v4 prototype

This directory isolates Aurora v4 architecture work from the stable Tkinter
application. Nothing here is imported by the production entry point.

Stage V4-1 froze the first desktop-to-sidecar contract:

- `ARCHITECTURE.md` defines the process and ownership boundaries.
- `contracts/IPC_V1.md` is the normative wire-protocol document.
- `contracts/ipc-v1.schema.json` is the machine-readable JSON contract.
- `contracts/ERROR_CODES.md` and `contracts/CAPABILITIES.md` define the stable
  error and feature vocabularies.
- `contracts/ipc-v1.examples.json` contains synthetic, privacy-safe examples.
- `contracts/validate_contracts.py` and `test_ipc_v1_contract.py` provide
  dependency-free contract checks. They are specification tests, not a
  production sidecar implementation.
- `sidecar/README.md` freezes the Python sidecar bootstrap and lifecycle rules.

Stage V4-2 implements the isolated prototype against that contract:

- `desktop/` contains one Tauri 2 window, a native TypeScript/Vite frontend,
  the Rust IPC gateway, request registry, and supervised sidecar lifecycle.
- `sidecar/mock_sidecar/` contains a synthetic asyncio WebSocket backend. It
  does not import Stable Aurora or connect to Ollama, persistence, or voice.
- `V4_2_VALIDATION.md` records the Windows prototype evidence and explicit
  verification boundary.

Stage V4-3B adds the opt-in production direct-chat path. See
`V4_3B_REAL_CHAT.md` for the adapter and ownership boundary and
`V4_3B_VALIDATION.md` for the automated and Windows evidence. The default
backend remains mock; production is selected only with
`AURORA_V4_BACKEND=production`. V4-3B does not add persistence, context
systems, voice, or UI settings.

Stage V4-3C adds Python-owned conversation list/get/create and completed-turn
persistence while preserving the existing `%APPDATA%\\Aurora\\conversations`
store. See `V4_3C_VALIDATION.md`; the default backend and Stable entry point
remain unchanged.

Stage V4-4A adds read-only production Memory, Persona, Knowledge, and optional
RAG context preparation before the existing streaming chat boundary. See
`V4_4A_CONTEXT.md`; no post-turn intelligence, voice, or UI changes are made.

## Validation

From the repository root:

```powershell
.\.venv\Scripts\python.exe prototype\aurora-v4\contracts\validate_contracts.py
.\.venv\Scripts\python.exe -m pytest prototype\aurora-v4\contracts\test_ipc_v1_contract.py -q
```

The prototype's production adapter is opt-in and leaves the Stable entry point
unchanged. Voice/PCM IPC remains disabled.

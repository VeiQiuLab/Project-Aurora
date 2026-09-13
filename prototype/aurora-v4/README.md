# Project Aurora v4 prototype

This directory isolates Aurora v4 architecture work from the stable Tkinter
application. Nothing here is imported by the production entry point.

Stage V4-1 freezes the first desktop-to-sidecar contract before a Tauri
application exists:

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

## Validation

From the repository root:

```powershell
.\.venv\Scripts\python.exe prototype\aurora-v4\contracts\validate_contracts.py
.\.venv\Scripts\python.exe -m pytest prototype\aurora-v4\contracts\test_ipc_v1_contract.py -q
```

V4-1 deliberately contains no Tauri scaffold, WebSocket server, production
Python adapter, voice transport, or Rust code.

## Minimum prerequisites for V4-2

1. Install and verify the stable Rust MSVC toolchain (`rustc` and `cargo`) on
   Windows; V4-1 intentionally does not install it.
2. Select and pin the Tauri 2 toolchain versions, then verify one clean Windows
   development build before adding application behavior.
3. Select a maintained Python WebSocket server dependency and pin it only after
   a loopback/authentication/cancellation spike succeeds.
4. Benchmark and freeze concrete bootstrap, handshake, shutdown, and payload
   limits/timeouts currently marked TBD.
5. Generate or implement schema validation for Rust/Python/TypeScript and run
   the shared examples against every implementation.
6. Build the smallest mock sidecar test for handshake, ordered mock deltas,
   cancellation, protocol mismatch, and crash. Do not connect production AI or
   voice code in that prototype.
7. Start with a minimal Tauri CSP and capability manifest that cannot expose the
   sidecar endpoint or credentials to the WebView.

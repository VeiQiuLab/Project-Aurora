# Project Aurora

Aurora is a local-first AI companion for Windows. **Aurora v4 / Tauri Desktop is
the only official Desktop entrypoint.** The directory name `prototype/aurora-v4`
is retained for path compatibility; it does not mean Tk is still the product UI.

## Run from this checkout

Use Windows, Python 3.12, Node/pnpm, Rust and Visual Studio C++ build tools.
Python does not need Tcl/Tk for v4.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
pnpm --dir prototype/aurora-v4/desktop install --frozen-lockfile
.\build_exe.ps1
.\.venv\Scripts\python.exe main.py --check
.\.venv\Scripts\python.exe main.py
```

`main.py` starts only `aurora-v4-desktop.exe`. Missing/failed v4 builds produce
an error, never Tk fallback. `AURORA_DESKTOP_EXE` may explicitly select an
absolute path to the v4 EXE. You can also launch that EXE directly or create a
Windows shortcut to it. No existing user shortcuts are changed automatically.

Build and runtime installation are separate. Configure the existing local GGUF
and Aurora-owned Vulkan llama-server as described in
[Built-in runtime](prototype/aurora-v4/docs/V4_6A_LOCAL_RUNTIME.md).
There is no automatic model download. Ollama and LM Studio are not required;
Ollama remains an explicitly selected compatibility provider, not a fallback.

## Product boundaries

- Tauri/Rust owns Desktop, supervised processes, IPC and Rust Audio playback.
- Python owns chat, conversation persistence, context, Memory, Persona,
  Knowledge/RAG, post-turn intelligence and the single settings authority.
- Optional Voice uses existing TTS routing (Edge / Remote CosyVoice) and Rust
  Audio. Edge TTS requires network access. v4 does not initialize pygame or Tk.
- Optional [Native Live2D](prototype/aurora-v4/docs/LIVE2D_NATIVE_RUNTIME.md)
  uses external read-only SDK/model configuration. Missing optional capabilities
  do not prevent text chat. SDK/model redistribution is not implied.

Shared AI modules are retained. The retirement does not claim new UI for every
historical Memory/Knowledge editing operation, microphone feature or legacy tool.

## Data and packaging

Production data remains in `%APPDATA%/Aurora` (or the existing explicit
`AURORA_USER_DATA_DIR`). No settings, conversations or assets are migrated or
deleted by retirement. Rust does not become a second persistence owner.

`build_exe.ps1` builds the v4 Release EXE with `--no-bundle`. It is a developer
checkout build, **not a new self-contained installer**: Python, sidecar sources,
local runtime and model discovery retain their existing requirements. The old
portable/Inno/PyInstaller recipes are blocked unless explicitly selected as
legacy. Historical v3 installers are not v4 distributions.

## Development and legacy

- [Desktop development](prototype/aurora-v4/desktop/README.md)
- [Tkinter retirement audit and boundaries](docs/TKINTER_RETIREMENT.md)
- [Explicit legacy compatibility](legacy/README.md)
- [Release checklist](RELEASE_CHECKLIST.md)

Do not commit personal settings, conversations, model/SDK binaries, audio or logs.

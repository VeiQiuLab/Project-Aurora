# Aurora v4 Tauri desktop prototype

This is an isolated Windows/Tauri 2 prototype. It does not import or replace
the stable Tkinter application.

The frontend uses native TypeScript and CSS with Vite. The visual base is
black/grayscale, not window-wide glass. V4-5B unifies Chat, Settings, the overlay
composer and menus. Aurora Liquid Glass uses local SVG lensing and CSS blur;
Low GPU switches to opaque, unfiltered surfaces. Appearance is stored locally
by the desktop, separately from Python AI settings. See the implementation,
test evidence and pending manual acceptance in
[V4-5B Unified UI](../docs/V4_5B_UNIFIED_UI.md).

The frontend never opens the sidecar WebSocket. Tauri commands enter a Rust
request registry, and validated events return over a typed Tauri Channel. The
Rust process owns the per-launch token, dynamic loopback endpoint, Python PID,
and Windows Job Object.

## Commands

```powershell
Set-Location ..\sidecar
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Set-Location ..\desktop
pnpm install --frozen-lockfile
pnpm test
pnpm build
pnpm tauri dev
pnpm tauri build
```

The dependency versions are pinned in `package.json`, `pnpm-lock.yaml`,
`Cargo.toml`, `Cargo.lock`, and `sidecar/requirements.txt`.
The desktop now defaults to the existing production sidecar adapter so Settings
and stored conversations are available on a normal EXE launch. Set
`AURORA_V4_BACKEND=mock` explicitly for the isolated UI demo. Model unavailability
does not prevent opening Settings; generation is disabled until actual model
health is available. V4-6A eagerly starts Aurora's own pinned Vulkan llama-server
and reads the existing 4B GGUF without running LM Studio or Ollama. Runtime
installation is explicit, through `../runtime/bootstrap.ps1`; no model is
downloaded. See [Built-in runtime](../docs/V4_6A_LOCAL_RUNTIME.md) for discovery,
private configuration, lifecycle, validation and limitations. Use
`AURORA_V4_CHAT_PROVIDER=ollama` explicitly for the legacy service path.
Voice transport is not connected to the v4 desktop.

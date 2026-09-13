# Aurora v4 Tauri desktop prototype

This is an isolated Windows/Tauri 2 prototype. It does not import or replace
the stable Tkinter application.

The frontend uses native TypeScript and CSS with Vite. Aurora Frost is the
window-wide visual base; backdrop blur is limited to the composer Glass
surface. The manual Low GPU toggle removes blur, noise, deep shadows, and
nonessential motion.

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
`Cargo.toml`, `Cargo.lock`, and `sidecar/requirements.txt`. No real Ollama,
conversation storage, Memory/RAG, or voice code is used here.

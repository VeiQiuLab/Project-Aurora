# Aurora v4 Tauri desktop prototype

This is an isolated Windows/Tauri 2 prototype. It does not import or replace
the stable Tkinter application.

The frontend uses native TypeScript and CSS with Vite. Aurora Frost is the
window-wide visual base; backdrop blur is limited to the composer Glass
surface. The manual Low GPU toggle removes blur, noise, deep shadows, and
nonessential motion.

## Commands

```powershell
pnpm install --frozen-lockfile
pnpm build
pnpm tauri dev
pnpm tauri build
```

The second V4-2 commit adds the mock Python sidecar and Rust gateway. No real
Ollama, conversation storage, Memory/RAG, or voice code is used here.

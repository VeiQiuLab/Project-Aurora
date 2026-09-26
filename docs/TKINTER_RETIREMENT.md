# Tkinter Retirement — dependency audit and implementation

Baseline: `refactor/aurora-v4`, `4167585a414c98a05b652aa03a44011ccc454480`.
Gate 0: local and origin matched, clean worktree. WIP Glass remained
`adeee5aa4949a47e62ba9f7a2cb708f50a361970`.

## Audit method and decisions

Read tracked entrypoints, all Python Tk/CTk/Toplevel/mainloop/ttk/dialog imports,
UI references, requirements, PyInstaller/Inno/PowerShell builds, README/context/
architecture/release guidance, and production sidecar imports. Cross-checked
source-parsing tests before moving the old main. No user shortcuts, installed
applications, settings, conversations or SDK/model assets were altered.

| Category | Inventory / decision |
| --- | --- |
| A DELETE CANDIDATE | Former default Tk entrypoint behavior and unconditional Tk package route: retired/replaced. Pure widgets are potential future deletion candidates, **not approved for deletion now** because explicit legacy UI and regression tests still reference them. |
| B KEEP SHARED | `modules/chat.py`, chat session/cancellation/latency/policy, conversation and intelligence/title modules, memory stores/retrieval/candidates, persona, knowledge/retrieval/embedding, RAG/context/post-turn support, settings/service/controller semantics, app_paths, diagnostics, TTSRouter/Edge/Remote providers, Voice contracts and audio interfaces. Preserve all shared tests. |
| C MIGRATE FIRST | Former `main.py` context callbacks and `widgets/pages/chat_page.py` orchestration combine UI/business behavior. v4 already uses independent headless production context/chat/post_turn adapters over shared modules; legacy AST prompt-parity tests verify equivalence. No additional extraction needed for retirement. Keep the old callbacks as a parity/compatibility reference, not a production import. Future full UI deletion would require reviewing remaining user-editing workflows separately. |
| D LEGACY ISOLATED | `legacy/tk_desktop.py` (formerly main.py); all `widgets/`; `modules/ui_theme.py`, Tk-facing runtime_state/service_manager/single_instance/shutdown manager and old setup/health/controller callers; explicit Tk packaging recipes, old voice distribution tools and historical UI tests. No bulk deletion. |

Some support modules in D also have standalone diagnostics/tests; classification
does not license deleting them or changing their public interfaces.

### Tk UI inventory retained

`widgets/app_shell.py`, `chat_window.py`, `conversation_browser.py`,
`first_run_wizard.py`, `health_window.py`, `knowledge_window.py`,
`memory_window.py`, `models_window.py`, `persona_window.py`, `settings_window.py`,
`voice_setup_wizard.py`, `runtime_details.py`, `section.py`, `ui_components.py`;
`widgets/pages/{chat,home,learning_center,library,memory,persona,settings}_page.py`;
`widgets/components/{chat_panel,dependency_center,knowledge_panel,memory_panel,
persona_panel,workspace_empty_state,workspace_header,workspace_status}.py`.
`modules/ui_theme.py` retains a lazy `tkinter.font` import, used only with a Tk
root. The production sidecar has no import of that UI module.

## Answers to the required audit questions

1. **Before:** root main.py directly initialized Tk/AppShell. **After:** root
   main.py is a standard-library launcher for only the v4 Release EXE.
2. No default script starts Tk now. Compatibility requires
   `python -m legacy.tk_desktop`; old package scripts require `-Legacy`.
3. Root README, context, architecture, release and developer docs now identify
   v4. Earlier stage/release documents are historical. No tracked Windows `.lnk`
   launch artifact exists; installed/user-created shortcuts are not rewritten.
   Inno compatibility shortcuts are labeled Legacy and use a separate product ID.
4. v4 production has no Tk import/initialization; this was already true before
   retirement. Added subprocess tests reject even attempted GUI imports.
5. No v4 import of widgets or the legacy entrypoint. The sidecar's old prompt
   parity test reads declarations with AST; it does not execute a GUI import.
6. `modules/ui_theme.py` is the only actual Tk import in modules (lazy font
   discovery); it is legacy-only. `runtime_state.py` mentions Tk scheduling,
   but has no Tk import. Do not mistake terminology for dependency.
7. Conversation/Memory/Persona/Knowledge/RAG stores are headless and retained.
   v4 context and post-turn adapters already isolate them from Tk orchestration.
8. The old mutable Settings/controller writer remains for compatibility, but
   its process now selects a separate data namespace before all store imports.
   v4 SettingsService still owns validated patch, revision/conflict and atomic
   persistence; no new authority or production writer was added.
9. v4 constructs the existing TTS router without Tk. Rust playback is explicitly
   injected; no bridge means Voice error, never pygame fallback.
10. Ollama is **not solely Tk-only**: modules/chat cancellation/provider support,
    optional embeddings, historical smoke scripts and explicit v4 provider
    selection still use it. Keep these paths. Default v4 chat remains built-in
    Vulkan; no Ollama installation/start or model change was made.
11. pygame is not a v4 dependency, but still serves explicit legacy/standalone
    `RealPlaybackController` tools. Its import is lazy. Keep it in legacy extras,
    not the v4 requirements. Sounddevice streaming/microphone tools also remain
    outside the v4 physical audio path; do not rewrite their implementation.
12. `tests/test_runtime_snapshot_ui.py` creates a real CTk root. Other UI contract
    tests import widgets or use fakes/unbound methods: product_ui_closeout,
    dependency_center_contract, runtime_snapshot, voice_distribution,
    chat_turn_gate, background_title_contention, pre_llm_latency_diagnostics,
    memory_panel_candidate_contract. Retain these as legacy regression coverage.
13. All shared chat, store, RAG, settings, title, Voice/provider, segmentation,
    cancellation, protocol and runtime tests remain. Only four legacy source
    reference tests and the locale scanner follow the moved entrypoint.
14. Root build_exe.ps1 now defaults to Tauri `--no-bundle`. Portable/Inno scripts
    reject invocation without -Legacy; the PyInstaller spec also requires an
    explicit legacy environment gate. Old release recipes no longer package the
    new root launcher as if it were a Tk app.
    A fresh legacy build marker plus matching EXE hash is required by portable/
    installer scripts, rejecting old dist artifacts that lack data isolation.
15. No hidden `v4 failure -> Tk` fallback existed in Rust, and none was added.
    Missing/invalid EXE or spawn failure in the new launcher returns an error.

## Data and ownership

Production remains `%APPDATA%/Aurora` or the existing explicit production root.
Legacy uses `%APPDATA%/Aurora-Legacy`; production overrides are not reused.
Resolved ancestor/equality collisions are rejected, including existing junctions.
Activation after shared app_paths has been imported is rejected rather than
silently retaining already-bound production constants. No data is copied.
The source launch is explicit `-m legacy.tk_desktop`, not an importable API.

Retirement does not modify settings authority, ConversationManager formats,
settings defaults, runtime/provider protocols, Voice orchestration, Rust Audio,
Live2D Native Host/adapter/SDK/D3D11/settings, or WIP Glass. The only new runtime
code is the stdlib desktop launcher and the early legacy data isolation gate.

## Dependencies and release boundary

Root requirements: sidecar websockets, psutil, Edge TTS. Legacy extras retain
CustomTkinter, PyInstaller, pygame, Faster-Whisper, sounddevice, websocket-client.
No installed package was uninstalled; tkinter is part of Python/Tcl/Tk, not a
pip package to remove. The full historical suite requires legacy extras.

The v4 build remains a checkout Release: the EXE discovers Python/sidecar and
local model runtime using existing mechanisms. A new standalone installer is
**not implemented or claimed**. Old PyInstaller/Inno/Full Voice recipes retain
their license/privacy/integrity gates for deliberate compatibility use only.
No installer was built, installed, or used to replace a user's shortcuts.

## Validation

2026-09-26, final working-tree validation:

- Retirement-specific tests: **16 passed** (including actual PowerShell rejection
  of implicit legacy packaging and missing/stale/matching artifact markers).
- Retirement + legacy source/parity/package focused regression: **105 passed**.
- All source tests: **1005 passed, 3 skipped**; no old UI/shared test was deleted.
- v4 sidecar + contracts: **185 passed**.
- Rust Desktop: **53 passed, 1 ignored** (existing opt-in Ollama test).
- Frontend: **34 passed**.
- compileall: **277 Python files**. Default settings JSON and git diff --check
  passed. Root main.py --check resolves the current v4 Release executable.
- Default build_exe.ps1 successfully built Tauri Release, not PyInstaller/Tk.
  Existing unused Rust code warnings remain; no new build error.
- Original Tk implementation after its new isolation preamble matches the old
  main.py text exactly. No shared AI/Voice/audio/Live2D implementation changed.
- Real Release `tests/live2d_runtime.mjs --lifecycle-only`: **passed** with
  disposable settings/history, built-in 4B Vulkan READY, real streaming Chat,
  Edge TTS -> Rust/rodio physical output, Voice stop, Live2D states/hide/crash
  isolation, remote-unavailable isolation, close during playback, relaunch and
  persisted settings. `remainingOwnedProcesses=[]`; no forced sidecar shutdown.
  Ollama and LM Studio were not running. Evidence remains ignored under
  `tests/output/live2d-desktop-lifecycle` (report.json and stderr.log).

Synthetic tests are not manual visual/audio acceptance. Subjective visuals and
listening quality: **NOT MANUALLY VERIFIED**.
Remote Voice Node real playback: **NOT TESTED IN THIS STAGE**.

Changes are intentionally left uncommitted for this stage handoff; no new commit
or push was requested in the retirement attachment. HEAD remains the baseline.
The full installer/legacy package was not rebuilt or installed; only the actual
v4 Release build and isolated package-entrypoint/marker tests ran.

No UI redesign, new Voice provider, local model optimization, SDK update,
tracking/lip-sync, full legacy deletion or new settings framework is in scope.

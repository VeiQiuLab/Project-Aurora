# V4-5B — Unified UI Functional Baseline

## Status / design intent

The functional UI baseline and scoped automated verification are complete.
This closure records a stable engineering baseline, **not final Liquid Glass
or full visual-design acceptance**. Aurora Liquid Glass is inspired by Apple
optical/material principles, not an exact implementation of Apple's system
material. Black/grayscale, quiet spacing, normal foreground text and local
floating controls are retained; there is no whole-page shader, rainbow tint,
light-show or autoplay animation. Chat, Sidebar, Composer, Settings, titlebar
and menus share the same typography, radii, control scale and contrast hierarchy.

Branch: `refactor/aurora-v4`. Starting HEAD before baseline closure:
`2df3925112d8cdc7238744cbed536f41bf5e89e8`.
Inherited V4-5A.5 changes were retained. No production Python,
Voice, model runtime, inference, memory retrieval or IPC protocol was changed.

## Glass renderer architecture / fallback chain

`AuroraGlassMaterial` owns a shared material profile and per-surface SVG filter.
A rounded-box signed-distance normal produces an RG displacement texture.
`feImage` + `feDisplacementMap(SourceGraphic)` refracts the actual backdrop;
CSS then applies blur, brightness, contrast and saturation. Normal text/input
is not filtered or redrawn. Composer, developer popover, preview lens and
Settings save footer share this renderer. Chat messages remain normal DOM.

Canvas 2D generates only the small displacement map on geometry changes
(ResizeObserver), capped at 1024 × 512. It does not capture/repaint the chat.
Pointer movement updates two CSS highlight coordinates; no idle render loop,
scroll-driven texture regeneration, WebGL/WebGPU dependency or duplicated text.
The masked 1 px radial highlight moves around the rim and strengthens subtly
on hover/focus. Reduced motion stops moving specular response and transitions.

Chosen route: **CSS + SVG**, because the current real Release WebView2 rendered
the displacement correctly. With all other properties fixed, switching the
Composer displacement scale to zero changed 49,098 color channels in the
native screenshot. The browser preview comparison changed 11,890 pixels.
These comparisons establish a rendered optical difference, not an artistic
approval or a measurement of Apple's exact material.

Fallback: SVG lens + CSS blur → CSS frost when SVG/map is unavailable → simple
opaque surface when blur is unavailable or Low GPU is enabled. Missing Canvas
2D context, map exceptions and SVG image errors degrade without removing the
interactive foreground. CSS.supports is a capability check, not proof for all
future WebView2 versions; this installed WebView2 was separately pixel-tested.
No WebGL context exists to lose. Low GPU also disables native Mica through the
existing command. Returning from Low GPU restores the selected intensity.

## Material profiles

| Profile | Slider | Tint alpha | Blur px | SVG displacement scale | Brightness |
| --- | ---: | ---: | ---: | ---: | ---: |
| Clear | 0 | .08 | 1.5 | 13 | 1 |
| Mid | 50 | .24 | 11.56 | 7.495 | .935 |
| Frost | 100 | .40 | 32 | 4 | .87 |

Continuous curves use smoothstep for tint/brightness and a power curve for
blur. Clear emphasizes lensing; Frost emphasizes privacy/softness. Foreground
text remains unfiltered with a small shadow; focus adds .08 tint for legibility.
Actual normal displacement is less than the SVG scale because the vector map
is bounded and tapers to neutral within the surface. No full-surface zoom.

## Layout, interaction and ownership

- Composer is an absolute overlay, 28 px from the conversation bottom. The
  message viewport extends underneath. ResizeObserver reserves
  `ceil(composer height) + 28 + 16` px so the final message can scroll above it.
- Sidebar keeps its accepted quiet proportions, conversation selection and
  new-chat path. Settings sits at its lower edge; Low GPU remains a shortcut.
- Chat input, IME guard, send/cancel and conversation owner remain unchanged
  except for truthful model-health gating. Developer controls stay in a menu.
- Settings is one continuous scroll surface, not stacked dashboard cards.
  Footer floats locally; Escape/return restores Chat, navigation keeps drafts.
- Appearance belongs to the desktop origin's localStorage under
  `aurora.desktop.appearance.v1`: version, intensity, lowGpu. Default 50/off,
  corrupt values fall back safely. Slider input previews; change persists.
  Storage failure reports session-only application. It never patches Python
  config, invokes AI settings save, or resets the selected material on Low GPU.

## Settings architecture

The completed V4-5A descriptors remain authoritative: 23 rows, 20 editable and
3 read-only. The frontend supplies Chinese labels/grouping, not a second
settings schema/default set. Types, options, min/max, mutability, invalid-value
status and apply/restart semantics come from the service.

Explicit Save sends only dirty keys through the existing Tauri command with
`expectedRevision`; no frontend filesystem access, direct WebSocket or new
IPC event. Success refreshes the authoritative snapshot. Revision conflict
preserves drafts and requires explicit reload. Network/backend loss disables
AI controls but leaves appearance usable. Busy controls and a 10-second timeout
bound waiting. Invalid input blocks submit; late older revisions are ignored.

Desktop startup now defaults to the **existing production adapter**, rather
than the mock demo; explicit `AURORA_V4_BACKEND=mock` remains supported. This is
a prototype Rust launch-default change only, not a production Python behavior
change. It makes real Settings/conversations accessible from the normal EXE.

Health correction found in real Release: `chat_enabled` indicates protocol
capability, not model availability. UI connection state and Send now additionally
use actual reachable/model_available diagnostics. DEGRADED + capability=true
must not claim a live model. Offline mode keeps browsing/editing/Settings usable.

## Current model and Voice facts

User-reported environment: Ollama removed/unavailable; current model **4B**,
files managed by **LM Studio**. Future route: Aurora Built-in Local Model
Runtime. This stage did not install/start Ollama, run generation, restore 9B,
download/move/copy models, or connect a new runtime. Tests use isolated offline
configuration, not the user's real model data.

Voice presentation is factual and read-only: Edge TTS and Remote CosyVoice
core implemented, but v4 `voice.ipc=false`, `voice.streaming_pcm=false`;
Local CosyVoice not implemented (`cosyvoice_local=false`). No misleading enable
switch or claim that desktop voice is ready.

## Desktop shell / single-instance

Official Tauri 2 plugin `tauri-plugin-single-instance = 2.4.5`, pinned in Cargo.
It is the first plugin, before setup/sidecar startup. Secondary launches exit;
callback restores if minimized, shows and focuses main. Maximized state is
retained. No bespoke lockfile, extra server or second Python startup.

Real Release test PID 6124 kept Python PID 21580 through normal, minimized and
maximized second launches. All secondary processes exited 0. Minimized was
restored; maximized stayed maximized. Focus was observed in each case; the
normal-case later snapshot was false (foreground changed during automation).
A separate background test explicitly activated an existing Explorer window:
Aurora focus=false → second launch → focus=true after 300 ms, second exit=0.
No hidden-to-tray path exists in this application, so tray recovery is not claimed.

Titlebar uses the existing Tauri startDragging API with the narrow main-window
`allow-start-dragging` capability. It excludes interactive descendants and
stops duplicate document routing. Double-click uses the existing maximize
command. Real native double-click maximize and restore were observed.

**Drag evidence limitation:** computer-use drag injection moved the whole
pointer path within ~0.6 ms after mousedown, ahead of the asynchronous native
drag handoff; one trial moved 3 px, others did not establish full movement.
No drag rejection was captured. Full ordinary mouse dragging and drag-down
from maximized state are therefore **not claimed passed**; retain them in
the user's Release acceptance, rather than adding an unverified platform hack.

## Performance observation (real Release / real WebView2)

Screen 2560 × 1440; maximized content 2560 × 1392; devicePixelRatio=1.
100 local synthetic messages, 90 requestAnimationFrame samples per mode while
scrolling. No network/model generation. Values are a short single-process
observation, not a comparative benchmark or proof under inference load.

| Mode | WebView working set MiB | Dedicated GPU MiB | Shared GPU MiB | Median / p95 frame ms |
| --- | ---: | ---: | ---: | --- |
| Clear | 426.8 | 214.5 | 12.7 | 5.6 / 5.6 |
| Mid | 435.2 | 201.2 | 13.7 | 5.6 / 5.7 |
| Frost | 436.1 | 187.5 | 13.7 | 5.6 / 5.7 |
| Low GPU | 437.8 | 193.2 | 13.7 | 5.6 / 5.6 |

Six WebView subprocesses, one Aurora and one Python throughout. Counters sum
the associated WebView process GPU-memory samples, not GPU utilization.
Working set can retain caches across modes, so Low GPU is not claimed to free
all cached memory. No long stalls were observed in this brief sample.
Normal native close completed. Raw JSON/logs/screenshots are ignored artifacts
under `tests/output/v45b-release/`.

A later isolated Computer Use inspection window (PID 16252) was retained at
handoff because concurrent user input prevented safe automated closing. This
is not an orphan from the completed test run. Its settings/WebView data are
sandboxed and its child-only CDP debugging is active; close it before launching
the EXE normally for real user settings. No forced termination was performed.

## Automated tests / Release

- Frontend unit tests: **29 passed** (conversation/input/ownership/settings,
  titlebar/material/appearance/descriptor conversion/offline presentation).
- Actual DOM geometry/interaction: **20 groups passed**, 720×520, 1180×760,
  1920×1080, 2560×1440, simulated device scale 100/125/150/200%.
- Unified UI browser test passed: 23 descriptors/3 readonly, save/revision
  conflict/draft preservation/invalid input/backend loss, appearance persistence,
  keyboard slider, reduced motion, optical difference and fallback. Settings
  layout also checked at all four viewport sizes. Injected SVG error deliberately
  triggers Vite's generic error logger; page-error assertion remains empty.
- Rust `cargo test --locked`: **18 passed, 1 ignored** (existing ignored test).
- Python Settings service + Settings IPC + contract suite: **101 passed**.
- TypeScript/Vite and latest `pnpm tauri build --no-bundle`: passed.
- `git diff --check`: passed; final changes remain scoped to prototype desktop
  and its documentation.
- Real Release/WebView2 test: Settings save/reload, offline UI, single-instance,
  optical difference, four-mode samples and normal close passed, subject to the
  focus/drag evidence distinctions above. Existing Rust warnings are not errors.
- This UI-only stage did not rerun the entire stable-production source suite.
  Native Chinese IME candidate acceptance and real OS DPI changes remain manual;
  simulated composition events/DPI tests are not represented as those results.

Reproduce from `prototype/aurora-v4/desktop` with Playwright/Sharp available via
NODE_PATH (test tooling only, not packaged runtime dependencies):

```powershell
pnpm test
pnpm test:geometry
pnpm test:ui
cargo test --locked --manifest-path src-tauri/Cargo.toml
pnpm tauri build --no-bundle
node tests/release_webview.mjs
```

Native test refuses an already-running Aurora, uses isolated app/WebView data,
and enables CDP only in its child environment. It changes only sandbox Settings.
It never alters execution policy or terminates a user-owned instance. A test
process is closed normally; forced cleanup is explicitly marked if needed.

Latest EXE:
`C:\Users\X\Documents\ChatGPT\本地AI再创\Project-Aurora-baseline-20260902-010344\prototype\aurora-v4\desktop\src-tauri\target\release\aurora-v4-desktop.exe`

Build file time: 2026-09-22 08:40:31 +08:00; size 6,702,080 bytes.
SHA256: `871369250694C8BA7EAEC2EEA55FD973484C46FEEEE5C7DB9CF9D66AB5F77A6C`.
Subsequent changes are test/docs only, not packaged application code.

## Baseline files / scope

Under `prototype/aurora-v4/desktop/`:

- Existing: `README.md`, `index.html`, `package.json`, `src/main.ts`,
  `src/presentation_policy.ts`, `src/presentation_policy.test.mjs`, `src/styles.css`.
- Existing native: `src-tauri/Cargo.toml`, `src-tauri/Cargo.lock`,
  `src-tauri/src/lib.rs`, `src-tauri/src/sidecar.rs`,
  `src-tauri/capabilities/default.json`, `src-tauri/gen/schemas/capabilities.json`.
- New: `src/appearance.ts`, `src/desktop_shell.ts`, `src/desktop_shell.test.mjs`,
  `src/glass_material.ts`, `src/settings_panel.ts`, `src/unified_ui.test.mjs`.
- New tests: `tests/shell_geometry.mjs`, `tests/unified_ui.mjs`,
  `tests/release_webview.mjs`, `tests/resource_snapshot.ps1`.
- Docs: `../docs/V4_5A5_DESKTOP_SHELL.md` (historical inherited record) and
  `../docs/V4_5B_UNIFIED_UI.md` (current report).

Cargo lock changes belong to the official single-instance plugin dependency
tree (including other-platform support). No JS production dependency was added.
No model/runtime files or next-stage implementation are part of this baseline.

## Acceptance status / 28-item handoff index

Items 1–2, 27: Git/scope/file list above. Items 3–10: renderer/material/slider/
fallback above. Items 11–15: layout/Settings/ownership above. Items 16–17:
Voice and model availability above. Items 18–22: native shell, single-instance,
focus, resize/DPI and accessibility/IME evidence above. Items 23–26:
performance/tests/build/exact EXE above.

| Acceptance | Status |
|---|---|
| Functional UI baseline | PASS |
| Automated validation | PASS |
| Single Instance | PASS |
| Settings integration | PASS |
| Liquid Glass final visual acceptance | NOT FINAL |
| Full visual design acceptance | NOT FINAL |
| Ordinary manual mouse drag | NOT CLAIMED PASS |
| Native Chinese IME | NOT CLAIMED PASS |
| Real Windows DPI changes | NOT CLAIMED PASS |

The remaining manual items are intentionally not promoted from automated or
partial native evidence. They do not block the functional baseline closure.
Do not start the built-in model runtime as part of this stage.

References: [Apple optical/material principles](https://developer.apple.com/videos/play/wwdc2025/219/),
[official Tauri single-instance](https://v2.tauri.app/plugin/single-instance/),
[WebView2 debug environment](https://learn.microsoft.com/en-us/microsoft-edge/webview2/how-to/debug-visual-studio-code).

# V4-5A.5 — Desktop Shell Correction & Glass Baseline

Historical stage record. The same uncommitted work was subsequently expanded by
the user into [V4-5B Unified UI](V4_5B_UNIFIED_UI.md). Statements below about no
V4-5B work, runtime-only appearance and the old material are historical, not the
current Release behavior. Use the V4-5B report for current acceptance status.

## Scope and Git gate

- Branch: `refactor/aurora-v4`.
- Starting HEAD and fetched `origin/refactor/aurora-v4`: `2df3925112d8cdc7238744cbed536f41bf5e89e8`.
- Starting worktree clean. First fetch failed with an SSL handshake error; normal retry succeeded.
- Desktop frontend/capability/tests and this documentation only. Production Python,
  Settings backend, IPC semantics, chat processing and all Voice modules untouched.
- No commit/push. No V4-5B. No appearance persistence or new config file.

## Window drag: evidence, cause, correction

The old DOM already contained `data-tauri-drag-region` on the brand and its span.
CSS gave that region the remaining titlebar width; caption controls were separate.
The actual blocker was the capability: only `core:default` was granted.
The installed Tauri 2.11.5 `core:window:default` includes read operations and
`allow-internal-toggle-maximize`, but **not `allow-start-dragging`**.
The installed injected `src/window/scripts/drag.js` invokes
`plugin:window|start_dragging` for a left mousedown. Existing caption buttons
used the application's Rust `window_action` instead, explaining why those could
work while dragging did not. This is a source/ACL diagnosis, not a captured
historical runtime error log.

Correction:

1. Grant only `core:window:allow-start-dragging`, scoped to the existing main window.
2. Explicit titlebar-local mousedown route calls the installed Tauri 2 JS API
   `getCurrentWindow().startDragging()` once on left-button single down.
3. Stop propagation to Tauri's document listener to prevent a duplicate native
   call. Markup remains as a declarative drag-region fallback.
4. Second down (`detail === 2`) uses existing `window_action(toggle_maximize)`.
5. Interactive controls, their SVG descendants, editable/tabbable elements and
   explicit `data-tauri-drag-region="false"` regions cannot initiate this route.
   Developer menu is outside the titlebar. Error is logged instead of silently
   swallowed; no backend calls or new Rust window command were added.

44px titlebar, 44×40 caption targets and centered 16×16 SVGs retained. OS drag
behavior from maximized/restored states still needs the user's Release test.
Reference: [Tauri 2 window customization](https://v2.tauri.app/learn/window-customization/).

## Glass and layout

Old messages and composer occupied separate grid rows. Blur sampled only the
empty black background below the list; 82% black tint further hid any difference.
No single opacity tweak could repair that content-layer problem.

New structure:

```text
chat-pane (header + remaining space)
  conversation-viewport (relative, remaining space)
    message-viewport (100% height, scrolls to the viewport bottom)
      messages (bottom padding reserved for the overlay)
    composer-wrap (absolute, bottom 28px, z-index 1)
      composer (the one glass surface)
```

The composer wrapper is transparent and pointer-events:none; only the composer
accepts input. Gutters remain scrollable. No opaque overlay/pseudo-element or
intermediate backdrop root masks the messages. Text remains normal (no
`filter: blur`); the composer applies **backdrop-filter** and the prefixed
`-webkit-backdrop-filter`. A translucent grayscale tint and subtle border/inner
highlight are painted over the filtered backdrop. Desktop wallpaper transparency
is not claimed: the application shell intentionally stays black.

ResizeObserver measures the actual composer border-box, including multi-line
input and wrapping/resize. Message bottom clearance is `ceil(height) + 28 + 16`
CSS px. It retains bottom anchoring when already at bottom; reading history is
not forced back to bottom. At 58px minimum height, clearance is 102px. A 154px
expanded composer gets 198px. The last message can finish 16px above the composer.

### One runtime-only material value

| Intensity | Blur | Surface alpha | Brightness | Contrast | Saturation | Edge alpha |
|---|---:|---:|---:|---:|---:|---:|
| 0 / clear | 4px | .10 | 1.00 | 1.00 | 1.00 | .12 |
| 50 | 20px | .26 | .91 | .95 | .94 | .16 |
| 100 / frost | 36px | .42 | .82 | .90 | .88 | .20 |

Continuous linear mapping, rounded intensity clamped to 0..100. Zero is still
glass, not off. No shaders, chromatic effects, full-screen blur or animations.
Only the composer and developer popover receive this material. Defaults to 50
each launch. No localStorage, JSON writes, or production settings updates.

Developer menu has a grayscale native range input labelled `玻璃质感` with
`通透` / `毛玻璃` endpoints, native Arrow/Home/End control, visible focus ring,
aria min/max/now/valuetext and descriptive status. Low GPU disables the slider,
shows simplified-mode text, sets both backdrop filters to `none`, uses opaque
`#171717`, and removes shadow. Existing native Mica downgrade call is retained;
Mica is not relied on for composer glass. Turning Low GPU off restores the
previous intensity. No duplicate Glass/Frost switch and no Settings page.

## Automated evidence

- Frontend unit tests: **24 passed** (7 new shell/material/ACL tests).
- Geometry/interaction: **16 groups passed**, real frontend DOM in headless Edge
  with only the Tauri boundary mocked; no backend or model requests.
  1180×760, minimum 720×520 and 1920×1080 at deviceScaleFactor 1/1.25/1.5/2.
  Checks titlebar/caption/SVG dimensions, centering/no horizontal overflow,
  full-height scroller, absolute overlay z-order, last-message clearance,
  actual message/composer rectangle intersection while scrolling, native slider
  keyboard/ARIA, Low GPU blur off/restore, drag invoke routing, double click,
  caption exclusion, new conversation/switch, textarea growth, composition
  suppression, Send/Stop routing and absence of page errors.
- Rust Desktop: **18 passed, 1 ignored** (existing opt-in real read-only test).
  Existing unused `chat_start` and linker informational warnings remain.
- IPC contracts: **28 passed**. No protocol modifications.
- TypeScript / Vite: **passed**.
- Tauri Release build: **passed**, optimized build completed in 1m43s.
- Production Python changes: **0**; full source pytest intentionally not repeated.
- `git diff --check`: passed; new files also checked using `git diff --no-index --check`.

One strengthened geometry rerun initially failed because a newly added
maximize-count assertion was accidentally placed before the maximize actions.
Moved that assertion after the actions/exclusion checks; final rerun passed all
16 groups. No production workaround or relaxed expectation was introduced.

Latest Release (2026-09-21 23:34:57 +08:00, 6,672,384 bytes):

`prototype/aurora-v4/desktop/src-tauri/target/release/aurora-v4-desktop.exe`

SHA256: `8DB843B7D71175A7C8177B17AAF4C9B90351EDC6DF9AC50919060729BC93BC2A`.
The executable was rebuilt after all runtime-source edits. Only tests/docs were
edited subsequently. Not launched as a substitute for user acceptance.

Reproduce from `prototype/aurora-v4/desktop`: `pnpm test`, `pnpm build`,
`pnpm test:geometry`, then from `src-tauri`: `cargo test --locked`.
Geometry test needs an already installed Playwright resolvable locally or through
`NODE_PATH` and Microsoft Edge; no additional production dependency was added.
`pnpm tauri build --no-bundle` generates the user acceptance EXE.

## Evidence boundary / manual gate

Browser deviceScaleFactor tests are **not Windows display-scaling acceptance**.
Mock native commands prove routing, not actual window movement. Synthetic
composition events do not prove real Chinese IME behavior. Computed CSS blur and
rectangle overlap do not prove perceived frosted-glass quality in WebView2.

| Acceptance | Status |
|---|---|
| Black minimal visual direction | PASS (previously user accepted) |
| Static geometry | PASS (automated coverage) |
| Window drag | PENDING MANUAL VALIDATION |
| Glass material, intensity 0/50/100 | PENDING MANUAL VALIDATION |
| Liquid Glass refraction | NOT IMPLEMENTED |
| Low GPU visual/performance distinction | PENDING MANUAL VALIDATION |
| Full Desktop Shell | NOT YET ACCEPTED |
| Manual Chat GUI Send / Stop / first-visible | NOT YET VERIFIED |
| Native WebView2 material rendering and GPU memory/scrolling cost | NOT YET MEASURED |

Following the requested build → stop gate, no model generation or real-user
conversation changes are made for the automatic stage. GPU memory numbers are
not inferred from headless Edge. User should test the newly built Release:

1. Drag near Aurora and the center of the titlebar; double-click, maximize,
   drag from maximized, restore; ensure caption/Developer controls do not drag.
2. Open a sufficiently long conversation and scroll messages under the composer.
   Compare 0, 50, 100 while the same text is behind it, including keyboard slider.
3. Toggle Low GPU on/off. Observe scrolling/input responsiveness and, if possible,
   WebView2 GPU-memory change for low GPU/50/100. Record rather than guess.
4. Confirm last lines remain reachable above the composer; expand input,
   resize narrow/normal/maximized; verify real IME, Send, Stop and first-visible.

Only explicit user acceptance authorizes the subsequent Git closure. No
commit/push or V4-5B work in this stage.

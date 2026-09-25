# Live2D Integration — historical audit and Gate 1 resolution

Original audit: 2026-09-25. The inventory and ledger below preserve the
pre-implementation observations; they are not current implementation claims.
On 2026-09-26 the user supplied the final historical directory and explicitly
authorized a new minimal host if it was unavailable. Current implementation
and validation are tracked in [LIVE2D_NATIVE_RUNTIME.md](LIVE2D_NATIVE_RUNTIME.md).

## Gate 1 resolution — 2026-09-26

`Test-Path -LiteralPath C:\AI\QwenGame\DesktopPet` returned **False**.
Therefore there is no directory, Rust source, Cargo.toml/lock, C++ shim, Cubism
interface, D3D11/DirectComposition implementation, asset loader or Git checkout
to audit at that location. Branch/HEAD/worktree: **N/A**. No old project was
built, edited or copied, and the search for historical runtime source stopped.

- Historical Native DesktopPet source: **UNAVAILABLE**
- Implementation route: **NEW MINIMAL NATIVE HOST**

The installed DesktopPet directory recorded in the original audit is also
unavailable on the current filesystem. The complete, read-only model now used
is `C:/Projects/Archive/live2d-v1.0/test-psd2live/test.model3.json`; its model3
and moc3 SHA256 match the originals below. The alternate
`Resources/Character/test` package has the same metadata/moc but no texture;
it is not a usable full package. Neither package was modified.

## Gate 0

- Branch: `refactor/aurora-v4`.
- HEAD and origin: `537d79be81882174ba6399f0c0130845ae2c0474`.
- Message: `feat(v4): add rust audio playback`.
- Worktree was clean before this audit document.
- Protected WIP: `adeee5aa4949a47e62ba9f7a2cb708f50a361970`, unchanged.

## Repository inventory

Search covered Live2D/Cubism/SDK, model3/moc3/motion/physics/expression files,
DesktopPet, rendering/window terms, lip sync/mouth/viseme, roadmap, architecture,
capabilities, dependencies and tests. No app-specific AGENTS.md was found.

Aurora contains no Live2D runtime, C++ Cubism shim, Rust Cubism FFI, SDK, exported
Live2D character package, or Live2D tests. Existing references in
`V4_3A_PRODUCTION_SIDECAR.md` and `V4_4B_POST_TURN.md` exclude/defer Live2D;
they do not define an implemented renderer or require a Web renderer.
The authoritative specification for this stage is the current user request.

`desktop/src-tauri/tauri.conf.json` has one transparent, undecorated main
WebView window with Mica. This is **not** a Native Live2D render surface.
`glass_material.ts` uses Canvas 2D for a displacement image, not character
rendering. Cargo/package manifests contain no Cubism or WebGL model runtime.
`build.rs` only calls tauri_build; there is no C++ build or FFI target.

Local Tauri 2.11.5 source exposes WindowBuilder, transparent, skip_taskbar,
focused, visible and set_ignore_cursor_events. Therefore a separate native
window is API-feasible; this does not validate D3D11/DirectComposition binding,
render-thread affinity, DPI, multi-monitor behavior, or shutdown integration.
`lib.rs` currently cleans up on application Exit. Adding a persistent secondary
window will require explicitly handling main-window close rather than assuming
the old last-window exit behavior remains sufficient.

Existing Rust Desktop Core validates epoch/generation/revision before emitting
ChatAccepted/ChatTerminal/VoiceState. Voice snapshots contain generation and
revision, with idle/preparing/speaking/stopping/error. Rust Audio owns the output
and reports facts; Python remains the unified Voice authority. Audio has no RMS
or amplitude tap. A first integration should consume speaking/idle only, without
modifying the decoder or falsely advertising lip sync.

Settings use Python SettingsService allowlisting, revision checks and atomic
persistence. No character settings exist. Future minimal enabled/character/show
settings must use that authority. Pure window-position preferences require an
explicit ownership decision; the architecture's planned Desktop preference row
is not evidence of an existing persisted position store.

## External, read-only discovery

These are local audit observations, **not repository dependencies or defaults**.
No external project was modified, launched, copied, or imported.

| Location | Actual finding | Reuse implication |
| --- | --- | --- |
| `%USERPROFILE%/Documents/ChatGPT/桌宠` | HaidePet, Rust Win32 + Animated WebP; README and Git confirm a different sprite runtime | Not the requested Cubism runtime; do not substitute animated sprites for Live2D |
| Nested `DesktopPet` under that directory | Python Sprite 2D project | Not the described Native Rust/C++ implementation |
| `%LOCALAPPDATA%/Programs/DesktopPet` | Installed DesktopPet.exe, FrameworkShaders, characters, README | Native Live2D/D3D11 binary exists, but no matching Rust/C++ sources or build manifest found there |
| `C:/Projects/Archive/live2d-v1.0` | SDK, models, placeholder README, src/app/audio/dialogue/live2d/pet/render/ui/util/window directories | Recursive application src file count is **zero**; no Cargo.toml, shim or application CMakeLists.txt; not a Git checkout |
| Archive `third_party/CubismSdkForNative-5-r.5` | Native SDK Core, Framework, Samples, licenses and metadata | Can inform a future minimal adapter, but is not the missing application runtime |

Search also covered Documents, Downloads, Desktop, C:/Projects, C:/Data and
available Codex project/worktree locations. Downloads has another test-psd2live
export. Do not conclude a missing SDK or missing model: both exist locally.
The unresolved item is the historical **application/runtime source**.

Installed `characters/default/model/test.model3.json` references:

- `test.moc3` (117312 bytes).
- One texture, `test.2048/texture_00.png` (6075369 bytes).
- `test.physics3.json` and display information.
- Idle, Blink, Nod, Shake motion groups.
- EyeBlink group and LipSync group `ParamMouthOpenY`.

Referenced files exist. This proves an exported package is present, not that
Aurora can load it or that its visual quality has been accepted. No expression
file is declared. Mouth parameter metadata is not an implemented lip-sync path.

Read-only SHA256 evidence:

- Installed test.moc3: `A8B7F8B88E7ED4710DC4507D20F3D3B94E55D71E6D75704C7EC84F692947660D`.
- Installed test.model3.json: `E82551B39BD402639CFD7F35F61D90C15EAF811ED96931F91374A7857FB10FDC`.

## SDK and distribution boundary

Archive `cubism-info.yml` declares SDK **5-r.5**, created 20260401, with component
hashes: Core `d96fa37f45ab8448936200c16a090ca9c2dc2945`, Framework
`251311083a8690601436de14b03057a0b189cb09`, Samples
`af65ec9b4171793f848e935600bd158ce2041df9`. Its changelog records release
2026-04-02. Core's own changelog records component version 06.00.0001; SDK
release and Core version are different identifiers. No binary version function
was executed and download provenance/signatures have not been independently
authenticated. Archive x64 Core DLL SHA256:
`D883C00D114FDF6CEF61F439FEB23E02D000FDF683E092803010470B80DFAF09`.

Local LICENSE files identify Framework/Samples under Live2D Open Software
License and Core under Live2D Proprietary Software License. Core has a
RedistributableFiles.txt listing permitted files subject to the agreement.
Official [SDK manual](https://docs.live2d.com/en/cubism-sdk-manual/cubism-sdk-for-native/)
states Core is not published on GitHub under its proprietary terms. Consult
the [current publication license](https://www.live2d.com/en/sdk/license/) before
distribution; no commercial eligibility or user agreement acceptance is assumed.
Model copyright is separate. Local read-only model testing does not authorize
committing or redistributing the character. No SDK binary or character asset
has been added to Aurora. Future builds should use explicitly configured local
SDK/model locations, record component identity and retain required notices.

## Gate 2: original evidence-based direction (now authorized)

Prefer **Native companion rendering**, since an existing Native SDK, D3D11
shaders, Windows runtime precedent and exported model exist locally. A Web
route would add a different Core/runtime and WebGL integration without an
existing Aurora implementation to reuse. No second renderer should be built.

For crash isolation, prefer a separately supervised renderer process/window
over loading unknown C++ code into the Chat Desktop process. Rust should own
that process, bounded latest-state delivery, its native window/render/GPU/model
lifetime and shutdown; a small C ABI shim should contain only Cubism adaptation.
This is a proposed boundary, not a proven reuse path: the historical sources,
build contract and existing IPC must be inspected first.

The renderer should receive only validated projected idle/thinking/speaking/error
state, not raw Python events or conversation text. Reuse generation, revision,
connection epoch; reject stale/duplicate state. Never block Chat/Audio on the
renderer. Main close must stop new work, stop the renderer, join/terminate only
its owned child and release the window/GPU. Renderer failure remains optional.
Start with <=60 FPS; hidden should suspend/reduce rendering. No full lip sync,
emotion inference, tracking camera, whole-project copy or renderer framework.

The original request for the missing source/implementation authorization has
been resolved by the user's subsequent explicit instruction and the check above.
This implementation is new, not a claim of reusing historical DesktopPet code.
An opaque installed EXE with undocumented control/lifecycle contract is not a
sufficient basis for claiming production integration.

## Original audit ledger — historical, superseded by implementation report

| Required item | Current verified status |
| --- | --- |
| 1 Branch | refactor/aurora-v4 |
| 2 Commit | Existing 537d79be81882174ba6399f0c0130845ae2c0474; no new commit |
| 3 Message | Existing feat(v4): add rust audio playback |
| 4 Local/Remote | Equal at audit |
| 5 Worktree | Initially clean; only this uncommitted audit document added |
| 6 Changed files | 1 documentation file; no production code |
| 7 Original specification | Deferred references only; current user request defines stage |
| 8 Old code/assets | SDK and real model present; matching application Rust/C++ source not found |
| 9 Native/Web | Native preferred; final implementation gate pending |
| 10 Reason | Existing local Native SDK/model/Windows precedent; no existing Web runtime |
| 11 SDK | Local Native 5-r.5 metadata; license/distribution boundary above |
| 12 Ownership | Proposed Rust execution, unchanged Python AI/Voice authority |
| 13 C++ shim | Not found in Aurora or located application archive |
| 14 Rust FFI | Not implemented |
| 15 Backend | D3D11/DirectComposition candidate; not integrated |
| 16 Window | Separate native companion proposed; current Aurora main WebView only |
| 17 Model loading | Package references inspected; no Aurora loader |
| 18 Texture/motion/physics | Assets exist; Aurora support not implemented |
| 19 Idle | Motion exists; not integrated |
| 20 Look tracking | Not integrated |
| 21 Thinking | Proposed existing Chat event mapping; not integrated |
| 22 Speaking | Proposed authoritative Voice mapping; not integrated |
| 23 Lip sync | NOT IMPLEMENTED |
| 24 State bridge | Proposed Rust projection; not implemented |
| 25 Stale | Existing Chat/Voice protection remains; new renderer not implemented |
| 26 Isolation | Proposed supervised child; not tested |
| 27 Settings | No changes |
| 28 Frontend | No changes |
| 29 Python | No changes |
| 30 Rust | No changes |
| 31 C++ | No changes |
| 32 Dependencies | None added |
| 33 Python tests | Not rerun for read-only/document audit |
| 34 Rust tests | Not rerun; no code changes |
| 35 Frontend tests | Not rerun; no code changes |
| 36 Live2D tests | Not implemented/run |
| 37 Stable regression | Not rerun; stable untouched |
| 38 compileall | Not rerun; no Python changes |
| 39 Release build | Not run for this stage |
| 40 Real Release smoke | NOT RUN; no renderer integration |
| 41 Disabled performance | NOT MEASURED in this stage |
| 42 Visible idle performance | NOT MEASURED |
| 43 Speaking performance | NOT MEASURED |
| 44 First-token regression | NOT MEASURED |
| 45 Throughput regression | NOT MEASURED |
| 46 VRAM change | NOT MEASURED; Win32 32-bit AdapterRAM is not reliable total VRAM evidence |
| 47 Exit resources | No renderer launched; cannot claim integration cleanup passed |
| 48 V4-6A | Unchanged, not revalidated in this stage |
| 49 V4-6B | Unchanged, not revalidated in this stage |
| 50 B-3 | Unchanged, not revalidated in this stage |
| 51 Ollama | Not installed/started/required by this audit |
| 52 LM Studio | Not started/required by this audit |
| 53 Limits | Missing historical application source/build/IPC contract blocks reuse decision |
| 54 Manual | Visual quality, motions, proportion, placement, transparency, click experience, mouth naturalness: NOT MANUALLY VERIFIED |
| 55 Next stage | Tkinter retirement remains later; not started |

At the original audit checkpoint the stage was **NOT PASS (audit only)**.
The source/reuse decision is now resolved. See the current implementation report
for remaining gates; do not interpret this historical table as current results.

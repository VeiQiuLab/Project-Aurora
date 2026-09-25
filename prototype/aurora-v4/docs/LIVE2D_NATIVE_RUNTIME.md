# Aurora Native Live2D minimum loop

## Route and ownership

Historical Native DesktopPet source: **UNAVAILABLE**.
Implementation route: **NEW MINIMAL NATIVE HOST**.
The user explicitly authorized this route after the final read-only directory
check. No application code was imported from DesktopPet.

One route only:

```text
Python Chat / Voice / settings authority
  -> existing authenticated, epoch-checked IPC
Rust Desktop projection + optional child supervisor
  -> bounded/coalesced state commands over private anonymous pipes
Rust native host (single owner thread)
  -> small C ABI adapter
Cubism Native 5-r.5 + D3D11 + DirectComposition + native transparent window
```

Rust owns start/stop, window/render lifetime, command parsing, rate limiting and
the C++ handle. The adapter owns RAII handles to Cubism/COM/D3D objects under that
Rust lifetime; no AI, settings, audio or network business logic lives in C++.
The host process isolates native faults. Desktop assigns its existing Windows
kill-on-close Job to this owned child. No attach to arbitrary existing processes.

Only idle/thinking/speaking/error, visibility, position, revision and shutdown
cross the private pipe. No prompt, conversation, audio, endpoint or credentials.
Incoming settings and Chat/Voice events are already authenticated and validated.
Generation identity, monotonic voice/settings revisions and explicit terminal
priority prevent stale or duplicate events from reviving a cancelled character
state. Chat's initial Voice idle does not erase active Chat thinking.
The host acknowledges applied revisions separately from 1 Hz FPS metrics.
There is no new public Python IPC family, WebSocket or renderer framework.

## Minimal behavior

- One externally configured real model3/moc3 package, with bounded WIC texture
  decode, first Idle motion and optional physics3. No asset writes.
- Relative asset paths must remain within the canonical model directory.
- Hardware D3D11, premultiplied-alpha DirectComposition swap chain.
- A separate no-activate tool window, no taskbar entry, transparent hit test.
  Position is clamped to the nearest monitor's work area. Per-monitor DPI
  handling resizes the surface; multi-monitor visual acceptance is still manual.
- Visible render budget is 17 ms (about 58–59 FPS, below 60). Hidden rendering
  stops; a 100 ms control/message loop remains for prompt show/exit.
- Thinking adds a small tilt; speaking adds a gentle pose movement. No text
  emotion inference, tracking, mouth amplitude or phoneme/lip-sync claims.
- No interactive drag, bubbles, tray, behavior scheduler, model editor, reload
  API or multi-character support. Position uses the existing settings panel.
- Main-window exit stops the child. EOF/parent exit also ends the host.
  Renderer and backend/audio shutdown run concurrently; an unresponsive
  character cannot defer the existing Voice/audio shutdown request.
  Desktop gives graceful shutdown 3 seconds, then kills only its owned child.
  Write timeout 500 ms; startup timeout 20 seconds; line buffer cap 4096 bytes.
- Missing configuration/assets or renderer failure is isolated and safely
  reported. No automatic restart loop: disable then enable retries explicitly.
  Chat, Voice and the model runtime are not stopped by a character failure.

## Configuration and build

Live2D is disabled by default. Four existing-authority settings were added:
`live2d.enabled=false`, `live2d.visible=true`, `live2d.x=64`, `live2d.y=64`.
Coordinates are signed integer physical pixels, range -32768 through 32767.
They use the same revision/conflict validation and atomic persistence as other
settings. No model path is exposed to WebView or added to production defaults.

Developer/runtime configuration is explicit: set `AURORA_LIVE2D_CONFIG` to an
absolute path to a private JSON file:

```json
{
  "executable": "<absolute path to aurora-live2d-host.exe>",
  "model": "<absolute path to a complete model3.json>",
  "shaders": "<absolute path to SDK Framework/src/Rendering/D3D11/Shaders>"
}
```

Place `aurora_live2d.dll` beside the host EXE. DLL loading uses that directory and
Windows default safe search paths, not the working directory. The configured
model package and SDK remain external and read-only. No install/discovery scan
or automatic SDK/model download is performed. Without a configured model this
is an optional unavailable feature, not a Chat startup prerequisite.

From the repository root, with local paths supplied by the developer:

```powershell
& prototype/aurora-v4/native-live2d/build.ps1 -SdkRoot $SdkRoot
$env:AURORA_LIVE2D_CONFIG = $PrivateConfigPath
cd prototype/aurora-v4/desktop
pnpm tauri build --no-bundle
# Optional real test; Playwright must be available in dev tooling via NODE_PATH.
node tests/live2d_runtime.mjs
```

The build reads the external Framework with an out-of-tree CMake binary
directory. It does not copy the SDK into Git. The host is a separate Rust crate
with pinned serde/serde_json/windows-sys and a lockfile. No new Python or
production frontend dependencies. Desktop retains its existing dependencies.

## Local SDK/model evidence and redistribution boundary

These are audit observations, not hardcoded defaults:

- SDK: `C:/Projects/Archive/live2d-v1.0/third_party/CubismSdkForNative-5-r.5`.
- Version: cubism-info.yml **5-r.5**; component identities in the audit document.
- Headers: `Core/include`, `Framework/src`; external Framework D3D11 sources.
- Library: `Core/lib/windows/x86_64/143/Live2DCubismCore_MD.lib` (MSVC x64 Release).
- Shaders: `Framework/src/Rendering/D3D11/Shaders/CubismEffect.fx` and
  `CubismBlendMode.fx`, read in place.
- Model: `C:/Projects/Archive/live2d-v1.0/test-psd2live/test.model3.json`.
  Model3 version 3, moc3, one PNG, Idle motion3 and physics3; hashes match audit.

Core is statically linked into the locally generated adapter DLL. Thus that
generated DLL contains proprietary Core code even though no separate Core DLL
is copied. It must not be committed or redistributed as an ordinary open-source
binary without checking the Cubism agreement, publication license, required
notices and model rights. Framework/Samples use Live2D Open Software License;
Core has separate proprietary terms. See the official links and external
RedistributableFiles.txt recorded in the audit. Local tests do not assert
commercial eligibility, grant model redistribution rights or authenticate
download provenance. SDK, models, generated DLL/EXE, reports and captures remain
outside Git (runtime-local and tests/output ignored).

## Validation — 2026-09-26

- Native Rust host unit tests: 3 passed.
- Desktop Live2D state/process tests: 10 passed. Synthetic subprocess tests use
  no SDK/GPU and cover start/stop, hide, malformed output, init failure, early
  exit, startup cancellation, revision/generation ownership and duplicate cancel.
- Python settings plus v4 regression: 240 passed.
- Frontend: 34 passed.
- Full Rust Desktop suite: 53 passed, 1 ignored (pre-existing opt-in Ollama test).
- Stable source suite: 989 passed, 3 skipped.
- compileall: 272 tracked/new Python files passed. Default settings JSON valid.
- git diff --check passed.
- Real standalone host: complete model loaded, actual GPU frame 480x640 with
  alpha 0–255 and 145759 nonzero-alpha pixels; idle/thinking/speaking/hide/show;
  58–59 FPS visible, 0 hidden, exit 0, reader joined.
- Native adapter/host and Desktop Release builds passed.
- Real integrated Release smoke passed twice: built-in Qwen3.5-4B-Q4_K_M
  Vulkan READY, real streaming chat, Edge TTS to physical Rust/rodio output,
  thinking/speaking/idle, Voice stop, hidden character with continued Voice,
  forced renderer-child exit with Chat/Voice/model runtime still working,
  explicit disable/enable recovery, remote unavailable isolated, persisted
  enable restored on restart, close during playback, no owned children left.
  Ollama and LM Studio were not running. All application data was disposable.
- A missing installed-model path and an incomplete archive copy were rejected;
  no assets were repaired or modified. Full package selected by hash/reference
  verification. These failures were not reported as successful rendering.
- Final Release lifecycle regression after concurrent renderer/backend shutdown:
  passed, including close during physical Edge/Rust playback, relaunch, settings
  restoration and zero remaining owned process identities. An earlier final
  smoke timed out in its accumulated PID-only residual check despite shutdown
  logs; that check now matches PID plus creation time to avoid Windows PID reuse.
  The initial failure report/log are retained, not counted as a pass.

Real evidence is kept under ignored `tests/output/live2d-host-current` and
`tests/output/live2d-desktop` and `tests/output/live2d-desktop-lifecycle`.
A GPU frame readback proves renderer pixels, not
OS compositing quality or subjective human acceptance.

Visual quality, motion naturalness, proportions, placement, transparency,
click experience and physical sound quality: **NOT MANUALLY VERIFIED**.
Computer Use could read the real Aurora main window, but did not return the
no-activate character tool window as a target. No character OS screenshot or
human visual acceptance is claimed; real render evidence is the GPU readback,
successful Present/applied-state acknowledgements and bounded frame metrics.
Remote Voice Node real playback: **NOT TESTED IN THIS STAGE**.
No Tkinter retirement, V4-6A/B rewrite, Rust Audio change or WIP Glass work.

## Representative performance

Latest Release run: one warm-up excluded, then three fresh-conversation turns
per mode, same short Chinese prompt, no compilation/tests running in parallel.
Resource samples cover idle after Chat or active real Edge playback. LLM timing
is measured on the corresponding generation with that mode enabled; this
completed-turn Voice path does not overlap LLM generation with that turn's TTS.

| Mode | TTFT ms (three runs) | Decode tokens/s (three runs) | FPS | Host CPU, one-core % | Host GPU engine % | Host dedicated VRAM |
| --- | --- | --- | --- | --- | --- | --- |
| Disabled | 78 / 109 / 78 | 73.79 / 73.08 / 72.62 | 0 | no host | no host | no host |
| Visible idle | 125 / 63 / 250 | 72.33 / 71.65 / 73.26 | 57.92–58.02 | 1.25–2.51 | about 0.29–0.30 | 31.95 MiB |
| Speaking | 140 / 62 / 47 | 72.37 / 72.73 / 72.22 | 57.83–57.94 | 1.25–3.77 | about 0.34–0.35 | 31.95 MiB |

Desktop + WebView + host CPU (one-core units) ranges: disabled 0–10.04%,
idle 1.25–2.54%, speaking 3.77–10.05%. Corresponding summed GPU engine usage:
about 0.09–0.10%, 0.34–0.37%, 0.39–0.40%. These are summed process/engine
counters, not the whole-machine GPU percentage shown by Task Manager.
Dedicated VRAM for the entire owned process tree (including the LLM) ranged
2964.88–2975.62 MiB disabled, 3017.57–3021.82 MiB idle, and
3015.57–3028.07 MiB speaking. Host-specific attribution is consistently
31.95 MiB; the entire-tree difference also includes WebView/LLM allocations.

GPU usage uses two explicit raw samples and the documented
[PERF_100NSEC_TIMER calculation](https://learn.microsoft.com/en-us/previous-versions/ms938529(v=msdn.10)).
The first smoke used integer formatted single-sample counters that all showed
zero; those GPU utilization values are not relied upon. Current measurements
use fractional deltas of UtilizationPercentage / Timestamp_Sys100NS.
Missing counter instances remain null rather than being asserted as zero.

An earlier independent three-round run had TTFT 47–62 ms disabled, 47–94 ms
idle, 47–94 ms speaking, and decode about 70–74 tokens/s. The latest idle
250 ms sample is retained, not discarded. No sustained throughput regression
or unbounded frame/render load was observed; the short TTFT samples vary and
do not isolate all background scheduling/caching effects. These are current
device representative measurements, not general latency/performance guarantees.
No LLM optimization was performed.

## Final report checklist

Git identity (items 1–6) is supplied with the closing commit in the task report:
branch `refactor/aurora-v4`, message `feat(v4): integrate live2d runtime`,
26 scoped source/test/document files; no generated binaries or model assets.
The original baseline remains recorded in the audit.

| Item | Result |
| --- | --- |
| 7 Original specification | No earlier implemented Aurora Live2D contract; current user stage and fallback authorization govern |
| 8 Historical source/assets | Historical app source UNAVAILABLE; SDK and complete real export AVAILABLE |
| 9 Route | NEW MINIMAL NATIVE HOST; independent native companion, not Web |
| 10 Reason | Existing read-only Native SDK/model and Windows D3D11 support; native fault isolation |
| 11 SDK | 5-r.5 external archive; headers, library, shaders and licensing boundary listed above |
| 12 Ownership | Rust execution/child lifetime; C++ resource RAII; unchanged Python AI/Voice/settings authority |
| 13 C++ shim | New adapter.cpp only; no old DesktopPet application import |
| 14 FFI | create/frame/destroy opaque handle; optional test GPU capture; same owner thread |
| 15 Renderer | D3D11 hardware + DirectComposition |
| 16 Window | Separate transparent, no-activate, taskbar-free native tool window |
| 17 Model | External model3 -> bounded moc3 -> Cubism model -> renderer |
| 18 Texture/motion/physics | WIC PNG -> GPU texture, first Idle motion3, optional physics3 |
| 19 Idle | Supported and real tested |
| 20 Look tracking | NOT IMPLEMENTED; excluded from the authorized minimal new-host loop |
| 21 Thinking | Existing accepted Chat projected to small pose; applied acknowledgement tested |
| 22 Speaking | Authoritative Voice speaking projected to gentle pose; stop returns idle |
| 23 Lip sync | NOT IMPLEMENTED; no amplitude or phoneme claim |
| 24 Bridge | Validated existing Rust events -> latest bounded state -> private pipe |
| 25 Stale suppression | Generation, revision, terminal priority and host command revision |
| 26 Isolation | Init/crash/protocol synthetic tests, real owned-child kill with Chat/Voice recovery |
| 27 Settings | Four allowlisted preferences; validated atomic revision-based persistence |
| 28 Frontend | One small settings group and safe Chinese status labels |
| 29 Python | Four settings rules/defaults and corresponding tests; no rendering |
| 30 Rust | Optional supervisor/projection, lifecycle hooks and independent host/FFI |
| 31 C++ | SDK/model/texture/D3D/window adaptation only |
| 32 Dependencies | Separate pinned Rust crate; external read-only SDK and Windows system libraries |
| 33 Python tests | Combined v4/settings regression 240 passed |
| 34 Rust tests | Desktop 53 passed, 1 ignored; host 3 passed |
| 35 Frontend tests | 34 passed and production frontend build passed |
| 36 Live2D tests | 10 Desktop + 3 host + 7 settings + 1 label test; real host and Release smoke passed |
| 37 Stable regression | 989 passed, 3 skipped |
| 38 compileall | 272 Python source files passed |
| 39 Release | Adapter, host and Desktop Release built successfully |
| 40 Real Release | Two full runs plus final lifecycle regression passed; no fake model/provider substitutions in success path |
| 41 Disabled performance | Three-run baseline above, no host process |
| 42 Visible idle performance | About 58 FPS, about 0.30% host GPU engine usage |
| 43 Speaking performance | About 58 FPS, about 0.34–0.35% host GPU engine usage |
| 44 TTFT | Variable 47–250 ms across representative runs; data retained above |
| 45 Throughput | Roughly 70–74 tokens/s; no sustained material drop observed |
| 46 VRAM | Host about 31.95 MiB; whole-tree differences and caveats above |
| 47 Exit | Host released, audio worker exited, sidecar graceful, owned process IDs gone |
| 48 V4-6A | Real built-in 4B Vulkan multi-turn path preserved |
| 49 V4-6B | Real Edge Voice, stop, recovery and unavailable-provider isolation preserved |
| 50 B-3 | Real Rust/rodio output, Python audio not loaded, close during playback passed |
| 51 Ollama | Not running or required |
| 52 LM Studio | Not running or required |
| 53 Limits | Windows x64/MSVC; external SDK/model/config required; single model; no installer, reload, tracking or lipsync |
| 54 Manual | NOT MANUALLY VERIFIED; precise native screenshot boundary above |
| 55 Next stage | Tkinter retirement remains later; not started |

Engineering gates: **PASS**. The closing task report records final staged-file
scope, commit/push and local/remote equality. This does not turn the explicitly
unverified manual visual/audio items into human acceptance.

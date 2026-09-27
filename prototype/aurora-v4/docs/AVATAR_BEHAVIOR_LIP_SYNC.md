# V4-7A — Avatar behavior and amplitude lip sync

## Baseline and scope

Started from `593034be37fcadcf2212411d19df37ff26db4a41`, clean and equal
to origin on `refactor/aurora-v4`. WIP Glass remains
`adeee5aa4949a47e62ba9f7a2cb708f50a361970`.
This extends the existing new Native Host, not historical DesktopPet code.
No Python production, frontend, settings, TTS provider, local model, packaging,
streaming PCM or Glass change. SDK/model assets remain external and read-only.

## Gates 1–3: actual model and runtime

Read-only model: `C:/Projects/Archive/live2d-v1.0/test-psd2live/test.model3.json`.
External SDK: `C:/Projects/Archive/live2d-v1.0/third_party/CubismSdkForNative-5-r.5`.
Version, library/linking and redistribution restrictions are unchanged from
[the native integration report](LIVE2D_NATIVE_RUNTIME.md). Neither SDK, generated
DLL/EXE nor assets are Git deliverables. This stage makes no new license grant.

`audit_model.py` loads the supplied Core DLL to enumerate the actual moc3, not
just display metadata. The script hashes all references and never modifies them.
Changing only the real mouth parameter also changes drawable vertices (maximum
delta 0.0135338157 model units), so the mouth ID is not merely a display label.

| Actual parameter | Minimum | Maximum | Default |
| --- | ---: | ---: | ---: |
| ParamAngleX | -45 | 45 | 0 |
| ParamAngleY, ParamAngleZ | -30 | 30 | 0 |
| ParamBodyAngleX, ParamBodyAngleY, ParamBodyAngleZ | -10 | 10 | 0 |
| ParamEyeLOpen, ParamEyeROpen | 0 | 1 | 1 |
| ParamEyeBallX, ParamEyeBallY, ParamEyeBallForm | -1 | 1 | 0 |
| ParamBrowLY, ParamBrowRY | -1 | 1 | 0 |
| ParamMouthForm | -1 | 1 | 0 |
| ParamMouthOpenY | 0 | 1 | 0 |
| ParamBreath | 0 | 1 | 0 |
| ParamHairFront, ParamHairBack | -1 | 1 | 0 |

18 real parameters. Reference inventory:

- `test.moc3` (117312 bytes; SHA256
  `a8b7f8b88e7ed4710dc4507d20f3d3b94e55d71e6d75704c7ec84f692947660d`).
- `test.2048/texture_00.png` (6075369 bytes).
- `test.physics3.json` (8556 bytes), `test.cdi3.json` (4072 bytes).
- Idle: `test.idle.motion3.json`, 6 seconds, loop declared. Curves drive breath,
  angle Z, body X and both eye-open parameters. Contains one blink per loop.
- Blink: `test.blink.motion3.json`, 1.2 seconds, both eye-open curves.
- Nod: `test.nod.motion3.json`, 2 seconds, angle Y/body Y/eye-open curves.
- Shake: `test.shake.motion3.json`, 2 seconds, angle X/body X/angle Z curves.
- No referenced pose, sound or expressions. Neutral/happy/sad/angry/surprised/
  thinking/speaking expressions: **NOT AVAILABLE**. Dedicated thinking or
  talking motion: **NOT AVAILABLE**. Nod/Shake are not assigned emotional meaning.

Before this stage: load saved parameters -> single Idle motion manager -> save
parameters -> thinking/speaking pose -> physics -> model update -> D3D draw.
Rust Audio decoded complete artifacts straight into the rodio Sink; no amplitude
tap. Audio authority, playback identity and cancellation already existed.

## Implemented minimal policy

One motion manager retains the audited Idle loop across states. No random motion
selection, duplicate expression manager or competing scheduler. Completion
restarts Idle, never every frame; missing/unreadable Idle degrades to built-in
Cubism blink/breath only when those real parameters exist. No expression resources
are fabricated. Current mapping for every state is neutral/no expression override.

Thinking uses the existing small real angle-Z tilt, now smoothed with a 120 ms
time constant. Speaking removes the old sinusoidal pose; it keeps real Idle motion
and adds audio-driven mouth. Error has no invented action. Hidden bypasses drawing
and closes mouth. Existing Chat/Voice generation projection supplies deterministic
state priority and cancel/stale suppression. Voice disabled cannot imply Speaking.

Final frame order:

1. Restore motion-only saved parameters.
2. Update/restart the single real Idle motion; save motion parameters.
3. Only if no Idle: optional SDK blink/breath fallback.
4. Smooth high-level thinking tilt using an existing angle parameter.
5. Evaluate existing physics.
6. Write mouth **last**, scaled to the actual model minimum/maximum.
7. Cubism model update, D3D11 draw, DirectComposition Present.

Mouth is not saved into base parameters. Missing mouth is a no-op, not a Cubism
phantom parameter; real parameter indices are enumerated before use. There is
no mouth-form guessing, phoneme recognizer, emotion model or look tracking.

## Audio and concurrency contract

`Tap<Source>` wraps the actual decoder consumed by rodio, not a second decoder
or offline waveform. Returned samples are unchanged. Every approximately 10 ms
of interleaved audio computes RMS across channels (not a phase-cancelling sum).
Nonfinite input contributes zero to the meter; samples are not rewritten.

- Noise floor: RMS 0.005 (about -46 dBFS).
- Gain: 6 after floor subtraction; target clamped to 0–1.
- Exponential attack: 25 ms; release: 80 ms.
- Dead zone: envelope below 0.01 becomes exactly zero.
- Audio callback publishes only request-local atomics. No mutex, allocation,
  IPC, thread spawn or Frontend/Python call in `next()`.
- If no samples arrive for 150 ms, meter reads zero. EOF also writes zero.

Each output owns a different meter. `AudioOwner::envelope()` checks its existing
allowed generation/revision, active output, cancel flag and closed state. Stop,
new generation, failure, completion and shutdown invalidate it. A retired source
can only write its retired atomic; it cannot affect N+1. The Desktop's weak audio
reference is replaced only after the existing connection epoch check succeeds.
The presentation projection also requires the current preparing snapshot's exact
generation/revision playback identity, including replays within one generation.
It reads the authorized meter afresh instead of carrying a bare amplitude across
stop/replay transitions. A dedicated replay test rejects the retired identity and
late completion while allowing only the new preparing identity.

Desktop reads at 33 ms intervals (~30 Hz) and sends only latest control values
over the existing private pipe. At most **one unacknowledged command** is in
flight; pending values are coalesced locally. No new global identity or IPC family.
Existing private command revision orders state+mouth atomically. A 100 ms
heartbeat keeps the host fresh; lack of acknowledgement for 500 ms isolates the
host as unavailable. The host independently closes mouth after 200 ms of stale
input. Hidden control remains at its existing 100 ms loop, rendering 0 FPS.

Normal stop/reset reaches the next control/render turn (not the 200 ms watchdog).
Actual WASAPI device buffering can make render-consumption timestamps slightly
lead physical sound; this is amplitude-based lip sync, not calibrated phoneme sync.
The renderer never cancels Voice. The C ABI frame export is explicitly versioned
`aurora_frame_v2`; mixed old host/adapter binaries fail closed rather than use an
incompatible signature.

## Validation and evidence

Deterministic Rust tests cover envelope math, audio pass-through, stereo,
nonfinite/floor/silence, EOF, stop/failure/completion/shutdown, retired meters,
Voice-disabled state, stale generation, hidden/freshness and bounded host control.
The SDK-independent C++ test covers range scaling, clamp, pose transitions,
real-parameter lookup with a missing mouth, and absent/throwing optional motion.

Opt-in real test: run the existing `desktop/tests/live2d_runtime.mjs` with
`--avatar --lifecycle-only` and the private `AURORA_LIVE2D_CONFIG`. This enables
at most 16 GPU readbacks per child under the test's disposable evidence directory.
Each image is paired with its actual post-update Cubism mouth value. No capture
occurs in ordinary production. The test uses built-in 4B Vulkan, real Edge TTS
and physical Rust Audio; it also tests completion, stop, Voice-disabled turns,
hide/show, Host crash during playback, recovery, persistence and clean shutdown.

### Engineering results — 2026-09-27

- Stable/legacy-supported source tests: **1005 passed, 3 skipped**.
- v4 sidecar/protocol tests: **185 passed**.
- Rust Desktop: **59 passed, 1 ignored** (existing opt-in Ollama-only test).
- Native Host: **4 passed**; native C++ policy: **1 passed**.
- Frontend: **34 passed**. compileall: **278 Python files passed**.
- Default settings JSON and `git diff --check`: passed.
- Native adapter/host and Tauri Desktop Release builds: passed.
- Real standalone host: actual GPU surface, idle/thinking/speaking, hide/show,
  0 hidden FPS, control-to-mouth mapping and stale-input watchdog, clean exit.
- Integrated Release avatar smoke passed on the final rebuilt playback-identity
  implementation (`run-8xY2sq`); it explicitly waited for mouth >0.05 before
  Stop Voice. That stop sampled **0.76976174 -> 0**, with **205.07 ms** from
  starting the Playwright click to observing Voice idle and
  mouth zero. This includes input automation and 50 ms polling, not a pure device
  stop latency measurement. Cancel does not wait for the remaining speech.
- Natural completion closed mouth; later generation recovered; Voice disabled
  never became Speaking; hide/show worked. Deliberately killing this test's
  owned Host **during active audio** left Voice speaking and Chat/model usable.
- Real GPU frames show closed -> open -> nearly closed mouths during real Edge
  audio (e.g. values 0, 0.99738246, 0.01427129 in the final run). These were viewed,
  not inferred only from event logs. Metadata matches actual post-update Cubism
  values. The audio samples, models and rendered frames are not Git content.
- Remote unavailable remained isolated; no Remote GPU playback claimed.
- Settings/history persisted in disposable test data. Exit during playback and
  relaunch passed. Owned process identity checks found **no remaining processes**.
- Ollama and LM Studio were absent from the smoke process inventory and were
  neither started nor required. Built-in **Qwen3.5-4B-Q4_K_M / Vulkan READY**.

The first broad `pytest tests` collection accidentally entered ignored historical
packaging outputs and found missing dependencies in third-party recipe tests.
The source-only rerun (`--ignore=tests/output`) passed above. No cache/output was
deleted and no production dependency was changed to hide that collection error.

One additional real repeat stopped its first playback correctly but the next
Edge synthesis returned `SYNTHESIS_FAILED`. Chat stayed READY, the avatar reported
error with mouth zero, and shutdown left no owned process. The provider did not
expose a detailed cause in that log, so this is not diagnosed as a specific network
fault. Its failure report/log are retained under `avatar-behavior/run-3zO4SP`;
the provider and retry semantics were not changed to mask it. Subsequent smoke
runs keep per-run reports/logs rather than retaining only the latest summary.
The final rebuilt Release subsequently passed the full avatar lifecycle smoke,
including real audio, natural end, explicit stop and crash isolation.

Evidence: ignored `tests/output/avatar-behavior`, `avatar-host-final` and
`avatar-performance`. The closing task response records final commit and push;
this report does not treat ignored test output as shipped product content.

### Representative performance

One warm-up excluded, three fresh-conversation samples per mode. No concurrent
builds or heavy tests. GPU capture disabled for performance. CPU is percent of
one core; GPU is the sum of the Host's per-engine raw counter deltas, not Task
Manager's whole-device percentage. VRAM attribution uses Windows GPU counters.

| Mode | TTFT ms (three runs) | Decode tokens/s | FPS | Host CPU % | Desktop core CPU % | Host GPU % | Host VRAM MiB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Disabled | 63 / 47 / 62 | 72.84 / 72.34 / 71.91 | 0 | no host | 2.48–6.25 | no host | no host |
| Visible idle | 109 / 63 / 62 | 71.27 / 71.20 / 71.44 | 57.70–57.89 | 0–2.47 | 4.93–9.92 | 0.303–0.311 | 31.95 |
| Thinking | 94 / 78 / 78 | 69.65 / 69.72 / 69.84 | 57.67–57.79 | 1.23–4.94 | 17.38–24.60 | 0.522–0.530 | 31.95 |
| Speaking + lip sync | 94 / 266 / 562 | 71.61 / 72.22 / 72.50 | 57.95–58.20 | 2.45–6.20 | 4.96–6.21 | 0.375–0.436 | 31.95 |

Thinking uses a deliberately longer 600-character-request prompt so the entire
resource sampling interval stays inside actual generation (asserted at both
ends). Other modes use the same short prompt. Do not attribute the ~69 tok/s
long-response result solely to avatar state. In the completed-turn Voice path,
that turn's LLM generation does not overlap its Edge playback; the Speaking row
records LLM timing for the corresponding turn and resources during actual audio.

Historical no-lipsync figures were ~58 FPS, 31.95 MiB Host VRAM, 0.29–0.35% Host
GPU and ~70–74 tok/s. Current FPS/VRAM are stable, GPU/CPU modestly higher within
sub-1% Host GPU usage, and no sustained material short-response throughput loss
was observed. The final build's first performance run (`run-Y3Hk8W`) retained
266/562 ms TTFT outliers: request-to-headers was 235/516 ms while prompt evaluation
was 44/42 ms and decode stayed above 72 tok/s. This locates the additional wait
before response headers, not its root cause. Desktop CPU peaks at 24.60% of one
core during the longer Thinking response (under 0.8% across this 32-logical-CPU
machine); short sampling windows and UI streaming activity limit attribution.
No new user-facing switch was added just to
produce a same-build lip-sync-off A/B; that comparison is historical, not causal.
Whole owned-tree dedicated VRAM ranged 2950.38–2950.63 MiB disabled and
3003.82–3095.82 MiB with the Host; this also includes WebView/model allocations.
Real playback completed/stopped/recovered without reported audio failures; no
claim of instrumented hardware underrun detection or subjective listening QA.
These are current-device representative observations, not general promises.

A bounded repeat on the same final binary (`run-rkbmij`) passed all performance
and cleanup checks. It retained all samples rather than replacing the table above:

| Mode | TTFT ms | Decode tokens/s | FPS | Host CPU % | Desktop core CPU % | Host GPU % |
| --- | --- | --- | --- | --- | --- | --- |
| Disabled | 47 / 63 / 78 | 73.40 / 73.05 / 72.33 | 0 | no host | 4.97–16.08 | no host |
| Visible idle | 110 / 47 / 47 | 71.54 / 71.96 / 72.06 | 57.47–57.78 | 0–1.25 | 3.70–8.65 | 0.296–0.304 |
| Thinking | 110 / 94 / 78 | 69.78 / 69.97 / 69.98 | 57.66–57.84 | 0–4.94 | 18.51–28.19 | 0.488–0.509 |
| Speaking + lip sync | 94 / 110 / 203 | 72.19 / 73.21 / 72.24 | 57.87–58.05 | 2.48–3.67 | 6.21–21.97 | 0.379–0.527 |

Host VRAM remained 31.95 MiB. The 562 ms delay did not persist in this repeat;
TTFT variability is recorded, not claimed solved. Neither run demonstrated a
sustained unacceptable FPS/decode-throughput or audio regression. CPU readings
remain short-window, single-core-equivalent observations, not a precise isolated
cost measurement of the mouth tap. All per-run reports remain in ignored output.

### Deliberate limits

Amplitude-based lip sync: **IMPLEMENTED**. Phoneme/viseme lip sync and mouse look
tracking: **NOT IMPLEMENTED**. Four audited motion groups exist; only real Idle
is selected for the minimal loop. There are zero expressions, so all expression
bindings are safely absent. No new dependency or settings authority was added.
Main-window Computer Use observation succeeded, but the no-activate character
tool window was not separately enumerated; GPU readbacks do not establish OS
compositing/click aesthetics. Next recommended work is user visual/listening
acceptance and any specifically approved tuning, not automatic packaging/model
management or a new mainline phase.

Visual/motion/mouth naturalness, expression taste, breath/blink aesthetics and
subjective audio quality: **NOT MANUALLY VERIFIED**.
Remote Voice Node real playback: **NOT TESTED IN THIS STAGE**.

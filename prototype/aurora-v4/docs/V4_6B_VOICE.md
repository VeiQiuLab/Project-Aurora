# V4-6B — completed-turn Voice integration

## Source audit and ownership

Before this stage the production sidecar did not call TTS. Its Chat execution
already owns generation IDs, cancellation, persistence and a unique terminal.
Stable `modules/experience/voice/integration.py::_create_tts` already constructs
the TTSRouter and registers Edge, Remote CosyVoice or Fake. Providers return
SpeechResult, accept an Event/timeout, and existing RealPlaybackController owns
pygame file playback plus speech-identity callbacks. No new provider, queue,
STT/VAD pipeline or second VoiceOrchestrator is needed for completed answers.

```
Chat successful terminal + complete final assistant text (Python)
  -> VoiceExecution (same Chat generation owner, settings snapshot)
  -> existing _create_tts / TTSRouter / selected provider.synthesize
  -> SpeechResult -> existing RealPlaybackController / pygame
  -> safe voice.changed metadata -> Rust epoch/revision gate -> Voice UI
```

Python owns settings, final TTS text, routing, request cancellation and audio.
Rust owns authenticated IPC, process supervision, shutdown grace and forwarding.
Frontend displays authoritative events and sends a generation-targeted Stop.
It neither guesses playback state nor gets audio, endpoint, private worker IDs,
provider error text or tokens. Production Voice is event-driven (no polling).
Capability `voice.ipc=true`; `streaming_pcm=false`, `cosyvoice_local=false`.
LocalCosyVoiceProvider is **NOT IMPLEMENTED**. Remote Voice Node is unchanged.

## Settings and UI

Existing validated/atomic SettingsService with revision/conflict is extended by
five descriptors, not a new settings file:

| Key | Constraint / use |
| --- | --- |
| voice.enabled | Enable optional completed-turn Voice |
| voice.playback.enabled | Enable physical playback |
| voice.tts.provider | edge_tts / remote_cosyvoice / fake |
| voice.tts.voice | Existing voice identifier, ASCII letters/digits/underscore/hyphen, max 128 |
| voice.tts.timeout_seconds | 0.1–120 seconds |

No default settings were changed. Edits stop current speech; the next successful
turn takes a fresh settings snapshot. A change during Chat generation suppresses
that turn's pending Voice. Remote URL remains in existing backend-only
`voice.tts.remote_cosyvoice.url`; configure it with the app closed and restart.
There is no endpoint editor or automatic provider fallback. Fake is a test
provider, not physical speech. UI additions are a small Chinese status/Stop row
and the existing settings form; no visual redesign. The composer clearance now
includes that row; its buttons explicitly receive pointer events.

## Lifecycle and failure isolation

- Successful Chat only: schedule the complete final answer once. Streaming
  tokens, cancelled/failed Chat and duplicate terminals cannot schedule Voice.
- Beginning N+1 cancels N first. Every callback checks run identity, original
  SpeechResult identity, Chat generation and cancellation truth.
- Stop sets cancellation before stopping playback/network. A later provider
  error cannot override cancellation. Stale stop targets cannot affect N+1.
- A serial lock holds synthesis/playback/cleanup as one ownership interval;
  cancelled waiting runs exit without calling a provider. Old audio monitor
  threads are joined outside locks before the next owner touches the mixer.
- Temporary per-request audio is unloaded and removed. Workers are reaped
  between operations and joined at close. Disconnect cancels only its owner.
- Voice Stop is independent of Chat Stop: completed Chat/history is preserved.
  Chat cancellation suppresses orphan TTS. Voice exceptions are safe Voice
  status only; existing post-turn/title/memory processing remains separate.
- Exit sends Python shutdown before waiting up to six seconds, then the
  existing supervisor/Windows Job containment applies. No Rust audio added.

States: idle, preparing, speaking, stopping, error. Revisions are process-local.
Rust rejects stale epochs/revisions; frontend resets on backend loss. Safe error
codes distinguish unavailable, synthesis, playback, timeout and invalid settings.

### Existing provider cancellation gaps fixed narrowly

Edge's blocking `asyncio.run(save)` previously inspected cancel only outside the
request. Its save task now checks cancellation/timeout and awaits task cleanup;
retry waits are interruptible. No Edge protocol changes.

Remote complete-WAV urllib requests previously could wait through headers/body
after cancel. Request-local HTTP/HTTPS connections now own their socket and a
short polling binary read adapter. Windows tests demonstrated that shutdown
alone did not promptly wake the old buffered read. The adapter explicitly
checks cancel, shuts down, closes response/socket and joins its watcher.
HTTP errors and successful WAV responses still retain existing validation.
`synthesize_stream`, Voice Node and streaming protocol are untouched.

Before a socket is available, connect uses at most five seconds; DNS remains
subject to the OS resolver. TLS/proxy establishment is bounded by connect
timeout, not claimed instantly interruptible. HTTP timeout remains an inactivity
timeout, not a whole-response deadline. External Edge/network availability and
OS audio device support remain prerequisites. No automatic fallback is added.

## Validation and evidence boundary

Deterministic tests cover enabled/disabled, duplicate terminal, cancellation,
stale callbacks/stops, provider/playback failure, persistence, revisions/private
fields, worker/monitor cleanup, and real localhost blocked header/body abort.
UI fixture tests exercise actual Stop hit testing separately from Chat Stop.

Real Release smoke: `desktop/tests/voice_runtime.mjs` launches the production
desktop with isolated ignored test data and the existing 4B Vulkan runtime.
It uses real Edge TTS and pygame, not fake speech. It refuses running external
Ollama/LM Studio and checks owned-process exit. It verifies disabled/enabled,
Stop, next-turn playback, Chat cancel, remote-unavailable isolation/persistence,
close during playback and settings restoration. Output is under ignored
`tests/output/v46b-voice/`; screenshots and metadata are not shipped.

Validated on 2026-09-25: latest Release smoke passed; Stop click to authoritative
idle was about **78 ms**. Real Edge synthesis and OS playback API execution
succeeded, including subsequent normal playback completion. Voice Node offline
did not change Chat completion or persistence. Closing during playback left no
owned desktop/sidecar/llama-server process. Earlier smoke exposed pointer-event
inheritance on the Stop row; that defect was fixed and the rebuilt binary passed.

This is automated interaction with the actual Release WebView, not a mock page
or human listening pass. Sound quality, subjective volume, Chinese phrasing,
physical speaker behavior and user visual satisfaction are
**NOT MANUALLY VERIFIED**. No claim of human hearing acceptance is made.

Final validation on the same implementation:

| Gate | Result |
| --- | --- |
| Full stable/source tests | 982 passed, 3 skipped |
| v4 sidecar + IPC contracts | 170 passed |
| Rust library tests | 35 passed, 1 ignored (opt-in old read-only Ollama smoke) |
| Frontend unit tests | 33 passed |
| Settings/Voice UI fixture | Passed, 28 descriptors, independent Stop hit testing |
| Geometry/interaction fixture | 20 groups passed, simulated 100/125/150/200% scale |
| TypeScript/Vite build | Passed |
| Tauri Release build | Passed |
| compileall | 267 tracked/new Python files passed |
| default_settings JSON / git diff --check | Passed |
| Real Voice Release smoke | Passed, Edge/pygame, Stop to idle 77.95 ms |
| Existing V4-6A Release regression | Passed, 8 turns, cancel 26.6 ms |

The existing local-runtime regression confirmed model bytes unchanged, model
handle released and no remaining owned child processes. Launch to READY was
about 3.53 seconds. These measurements are observations, not performance targets.
Existing linker/dead-code build warnings remain non-fatal; none required changing
the protected local model runtime. A UI fixture deliberately injects an SVG
renderer error to test fallback; its expected console warning is not a Voice
failure. Native DPI/visual satisfaction are not inferred from fixture results.

Reproduction (PowerShell, repository root; existing dependencies required):

```powershell
.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/output -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest prototype/aurora-v4/sidecar/tests prototype/aurora-v4/contracts -q -p no:cacheprovider
Set-Location prototype/aurora-v4/desktop
pnpm test
pnpm build
cargo test --manifest-path src-tauri/Cargo.toml --lib
pnpm tauri build --no-bundle
# Only after the build has exited successfully, and no Aurora is running:
node tests/voice_runtime.mjs
node tests/local_runtime.mjs
```

Smoke requires Playwright available to Node (use the local tooling's NODE_PATH
if not installed in the project). Never run the old executable while a build is
linking. Tests use disposable settings; personal production settings are untouched.

No model, EXE, DLL, runtime distribution, audio cache or secret belongs in Git.
Existing optional edge-tts 7.2.8 and pygame 2.6.1 were installed in the repository
venv for this acceptance; no manifest/framework dependency was added.
V4-6A runtime code/default provider and the WIP Glass branch are unchanged.
Next planned stage remains Rust Audio / B-3; it is not implemented here.

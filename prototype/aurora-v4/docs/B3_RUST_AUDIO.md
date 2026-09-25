# Rust Audio / B-3

## Gate 0 and implementation boundary

Baseline checked: `refactor/aurora-v4`, `532b93ca8afc436475200535c3a2bf73ebdda655`,
clean, matching origin. WIP Glass remains `adeee5aa4949a47e62ba9f7a2cb708f50a361970`.
Repository search found future Rust Audio/B-3 references, not a mandatory PCM
streaming implementation spec. IPC_V1 reserves binary PCM for future work.
The request's `voice.ipc=false` is historical: V4-6B already enabled metadata
Voice control. It stays true; streaming_pcm and cosyvoice_local stay false.

Current source: VoiceExecution calls `_create_tts` / TTSRouter / synthesize after
successful Chat terminal. Edge returns an MP3 path. Remote complete mode returns
PCM WAV bytes or a WAV path when output_dir is set; its independent streaming
API is not selected here. Fake returns fixture bytes (not real audio).
RealPlaybackController currently initializes pygame, loads files, plays/stops,
monitors completion and unloads. TemporaryDirectory owns each result until that
monitor has exited. These stable implementations remain for legacy consumers.

No existing cpal/rodio/symphonia/hound audio crate was found in Desktop. The
WebSocket supports JSON only at application level (binary frames are rejected).
Tauri channels carry small typed metadata, not audio. No large audio messages
or frontend audio paths will be introduced.

Chosen scope: complete encoded MP3/WAV file handoff inside a Rust-created,
per-sidecar private temporary root. Python still owns generation and final Voice
state; Rust owns playback/decoder/device, reporting started/completed/stopped/
failed. Identity reuses Chat generation plus the preparing Voice revision within
the existing transport epoch. No new global stream identifier. Stop and new
generation invalidate old playback, and duplicate play cannot enqueue twice.

One Rust worker and one pending slot; maximum encoded input 64 MiB. Decoder
consumes bounded owned bytes after closing the file handle; no complete decoded
PCM allocation or IPC. Cleanup releases stream/sink/decoder before terminal
acknowledgement. Python waits for that acknowledgement before deleting its
temporary result. No pygame fallback in v4 production.

Dependency choice: rodio **0.21.1** (MIT OR Apache-2.0), with only playback,
MP3 and WAV features, for its mature Windows cpal/WASAPI backend and decoder
integration. tempfile **3.27.0** (MIT OR Apache-2.0, already transitively present)
provides owned private directories. Resolved transitive cpal/symphonia versions
and licenses are recorded below. No TTS/provider rewrite.

## Implemented lifecycle

- Rust creates one private root per sidecar epoch and overrides any inherited
  root environment. Python creates per-run directories inside it. All creation
  and cleanup ownership is explicit; frontend never receives the root or files.
- Existing provider generation is unchanged. Encoded bytes (when returned) are
  materialized as an owned artifact. Rust validates relative name, canonical
  containment, normal file type, no symlinks/reparse points and encoded size.
  File handles close before playback; Python therefore never races a retained
  Windows decoder file handle. This is a private same-user IPC boundary, not a
  security sandbox against malicious code already running as that OS user.
- Python preparing revision authorizes exactly one play. Rust independently
  invalidates the old identity as soon as a new Chat starts or Voice Stop is
  clicked. Late preparing metadata cannot reauthorize an older generation.
  The audio worker rechecks ownership after device/decoder initialization and
  before unpausing output. Duplicate play is ignored even after terminal.
- Rust reports only bottom-level facts; Python maps them back to the unchanged
  five Voice states. The adapter does not invent speaking on command send or
  idle on Stop send. Its terminal acknowledgement follows actual Rust resource
  release. Stop is idempotent and cancellation side-effect errors cannot win.
- Rust polls completion/device error/cancel at 5 ms intervals. Normal queue EOF
  includes a 100 ms device-tail grace; explicit stop skips the grace. The next
  request opens the then-current default output device. There is no automatic
  device switch or fallback to another device or pygame.
- One actor worker, one pending slot and a bounded existing 32-message IPC writer.
  Replies use non-blocking try_send: blocked transport cannot hold audio output
  open. Encoded input is capped at 64 MiB, playback at 600 seconds in Rust and
  the existing Python playback timeout. No unbounded decoded PCM accumulator.
- Shutdown first blocks new work and stops audio, cancels Python synthesis,
  lets acknowledgements/close handshake complete, waits for Python exit, joins
  Rust Audio, then removes only the owned root. Disconnect halts the worker;
  the root is retained until child exit/restart to avoid deleting a live writer's
  directory. UI and Chat/history/post-turn processing do not consume audio errors.

Missing root, failed thread/device creation, invalid file, invalid decoder,
device stream errors and disconnected transport remain Voice-only failures.
Unavailable bridge never falls back to Python audio. Existing Python playback
interfaces are adapted, not migrated for Stable/Legacy. No source in `modules/`,
Voice Node, provider generation or the local model supervisor is modified.

## Dependencies and limits

| Dependency | Version | License | Purpose |
| --- | --- | --- | --- |
| rodio | 0.21.1 | MIT OR Apache-2.0 | Desktop sink/decoder integration |
| cpal (transitive) | 0.16.0 | Apache-2.0 | Windows WASAPI output/device errors |
| symphonia + MP3/PCM/RIFF components (transitive) | 0.5.5 | MPL-2.0 | MP3/WAV decoding |
| tempfile | 3.27.0 | MIT OR Apache-2.0 | Per-epoch owned root |

Only playback/MP3/WAV rodio features are enabled. No additional Python or frontend
dependency. Versions are pinned in Cargo.toml/lock. Rodio 0.21.1 matches the
project's Rust 1.85 compatibility floor; 0.22.2 advertises Rust 1.87.
API reference: [rodio 0.21.1 Sink](https://docs.rs/rodio/0.21.1/rodio/struct.Sink.html).

Limits: complete audio only, not low-latency PCM streaming; default device only.
Device initialization is an OS/driver call: cancellation prevents subsequent
playback but cannot forcibly interrupt a hung native driver call. Physical
unplug/Bluetooth routing and unusually large device buffers require manual
hardware acceptance; the 100 ms tail grace is not a hardware drain guarantee.
Forced process termination/power loss bypasses destructors and can leave a
private temporary directory on disk; normal close/restart cleanup is tested.
No unsafe broad startup directory sweeper is introduced. File-size validation
is not intended to turn a same-user directory into an adversarial filesystem
sandbox. Missing terminal acknowledgement closes the adapter after five seconds
and requires backend restart; it does not silently fall back or reuse that owner.

## Validation

Deterministic coverage includes once-only handoff, started/completed facts,
Stop ACK, stale events, repeated stop, no pygame fallback, missing/invalid files,
PCM16 WAV decoding, no device/device failure, factory panic containment,
shutdown in preparing/speaking/stopping, and 40 sequential fake-sink turns
without retained outputs/workers. Existing V4-6B tests remain intact.

Opt-in `desktop/tests/rust_audio_runtime.mjs` uses the actual Release/WebView,
real Edge generation and rodio output with isolated test settings. It checks
Rust backend log markers, pygame not imported, Stop, recovery, repeated playback,
thread/handle samples, empty per-turn artifact root, disabled Voice, Chat cancel,
Remote unavailable, intentional invalid Fake audio (real decoder error with Chat
persistence), close during playback, restart and root/worker cleanup. Logs contain
metadata only; generated conversations/audio/screenshots are ignored test output.
The existing `desktop/tests/local_runtime.mjs` remains the V4-6A regression gate.

Remote Voice Node real playback: **NOT TESTED IN THIS STAGE**. The laptop is not
required to be online. Real provider acceptance uses Edge TTS through Rust on the
local machine. Remote unavailable is an expected isolation scenario: Voice error,
successful persisted Chat, and a live Desktop. Remote PCM16 WAV decoding is also
covered deterministically without requiring a second computer or GPU.

Subjective quality, Chinese phrasing, physical speaker/headphone volume,
Bluetooth switching and diverse physical sound-card compatibility are
**NOT MANUALLY VERIFIED** without user confirmation. Automated Release playback
evidence is not a human hearing or hardware-certification claim.

## Completed engineering gates (2026-09-25)

| Gate | Result |
| --- | --- |
| Python audio bridge + unchanged Voice tests | 31 passed |
| All v4 sidecar + contract tests | 185 passed |
| Rust library tests | 43 passed, 1 ignored (opt-in Ollama test; not needed) |
| Frontend tests | 33 passed |
| Stable source regression | 982 passed, 3 skipped |
| compileall | 270 tracked/new Python files passed |
| default_settings JSON, diff whitespace | passed; defaults unchanged |
| Release | TypeScript/Vite and optimized Tauri EXE built |
| Real Edge -> Rust playback | passed, pygame not imported; no fallback |
| Stop -> authoritative idle | 81.58 ms in final smoke; not acoustic measurement |
| Remote unavailable / invalid Fake audio | Voice errors, persisted Chat unaffected |
| Close while speaking + restart | both Python exits graceful, no forced kill |
| Artifact/worker cleanup | owned roots removed; 2 Rust workers started/exited |
| V4-6A Release regression | 8 turns, history/post-turn, cancel, crash/restart passed |

Real output is the Windows default output device through rodio/cpal. The smoke
uses the actual Release EXE/WebView and real online Edge MP3 generation, not a
mock browser backend. The original model remains unchanged and its file handle
is released at exit. Ollama and LM Studio processes were absent throughout.

Across five post-play samples Desktop stayed at 51 threads / 466 handles.
Python samples were 13/308, 14/314, 14/314, 15/318, 15/318 (threads/handles):
small executor warm-up growth, not claimed to be perfectly constant or an
unlimited-duration soak. Each artifact root was empty after idle. Forty
deterministic sequential sink cycles also released every output, with one owned
worker and no accumulating per-turn map. After exit no owned child/audio worker
remained. Raw evidence stays ignored under `tests/output/b3-rust-audio` and
`tests/output/v46a-local`; no generated audio, screenshots, executable, model,
private settings, or test reports are committed.

The real gate uncovered two test/lifecycle issues before passing: a retained
audio reply sender prevented normal WebSocket close; shutdown now drains stale
frames without dispatch and flushes close, with explicit forced=false evidence.
The new smoke initially polled the settings file during Windows atomic replace;
it now waits for the UI save acknowledgement/refresh and reads once. No Settings
production change was needed. Rejected Chat requests also cannot steal the
accepted owner's audio reply connection (deterministic regression added).

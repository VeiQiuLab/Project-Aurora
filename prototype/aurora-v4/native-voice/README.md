# Offline local voice host

The independent Windows x64 C++ process consumes the **audited minimal Melo C
ABI DLL**, not the official broad TTS DLL. The build refuses the broad DLL by
SHA-256. The minimal DLL is reproduced with `scripts/sherpa_melo_clean` using
the pinned external sources described in `../docs/LICENSE_CLEAN_MELO_FEASIBILITY.md`.
Build `clean_melo`; oracle targets are never production dependencies.

```powershell
cmake -S prototype/aurora-v4/native-voice -B prototype/aurora-v4/runtime-local/voice-build `
  -G 'Visual Studio 17 2022' -A x64 `
  "-DCLEAN_RUNTIME=$CleanRuntime" "-DSHERPA_HEADERS=$SherpaHeaders"
cmake --build prototype/aurora-v4/runtime-local/voice-build --config Release --parallel 4
```

Supply the external minimal runtime directory containing its DLL/import library
and ORT DLLs, plus the pinned v1.13.8 C API include directory. No downloads occur
in this build. Binaries and model/data files remain outside Git. The production
asset/attribution contract is `assets.json`; future rebuilds require an explicit
hash review, dependency audit and matching Supervisor/CMake pin updates.

Discovery defaults:

* `%LOCALAPPDATA%/Aurora/runtime/voice/sherpa-melo-v1/aurora-local-voice-host.exe`
* `%LOCALAPPDATA%/Aurora/models/melo-zh-en-v2/{model.onnx,tokens.txt,lexicon.txt,date.fst,number.fst}`

Private developer overrides are `AURORA_LOCAL_VOICE_RUNTIME` and
`AURORA_LOCAL_VOICE_MODEL`. `AURORA_LOCAL_VOICE_DISABLE=1` is an explicit
benchmark-only Desktop launch override. There is no Voice Model Manager or
installer in this stage. Existing user Edge settings and the Edge default remain.

Desktop owns the dynamic authenticated loopback broker, private inherited stdin /
stdout, Job Object, readiness, two crash retries (1 s then 3 s cooldown), and
temp cleanup. The child owns one inference worker with four CPU threads. Pipes
are the native private IPC; the child has no listening socket. Only Python
inherits the broker endpoint/token. The browser receives sanitized metadata.

Native commands are tab-separated `synthesize KEY UTF8_HEX SPEED`, `cancel KEY`,
`health`, `shutdown`, followed by newline. KEY is the SHA-256 transport encoding
of existing generation/preparing-revision ownership; it is never a path. Model
load emits `loading` then `ready` only after all engine assets initialize. Health
runs on the control thread even during ONNX inference. Native busy requests are
rejected deterministically, without a queue. Errors never terminate Chat.

Stop is logical cancellation; a non-interruptible ONNX call may finish. Its
cancelled result is discarded, and the owned WAV is deleted. Rust reads a bounded
PCM16 WAV from its own session root, deletes it, and returns bytes to Python.
The existing VoiceExecution writes those bytes inside the existing Rust Audio
handoff root; playback receipt/stop/unload releases that request directory.
This preserves the existing Audio and Live2D generation/connection ownership.

Temp sessions are under `%LOCALAPPDATA%/Aurora/cache/local-voice/session-*`.
An exclusive Windows lease distinguishes living owners from crash leftovers.
Normal shutdown removes the session. A Host crash removes WAVs before bounded
restart. The next Desktop start reaps only marked, unlocked sessions containing
known regular artifacts; it never follows links or deletes unrelated files.
After an abrupt Desktop kill, Job Object process cleanup is immediate; disk
session cleanup occurs on the next start.

Speaker is fixed (`melo-fixed-0`, API sid=0 maps to model sid=1), speed .5–2.0,
PCM16 mono 44.1 kHz, complete WAV output. No cloning, PCM streaming, second lip
sync, network fallback, or LocalCosyVoiceProvider is introduced. English, rare
characters, punctuation and dictionary coverage retain the feasibility limits.
Manual listening is a separate, unperformed acceptance step.

Future distribution checklist (no packaging performed here): retain sherpa /
kaldifst / OpenFst Apache licenses and applicable notices; model MIT and lexicon
provenance / CMU acknowledgment; FST Apache provenance; ORT MIT and **complete
exact-version ThirdPartyNotices**; comply with Eigen **MPL-2.0 covered-source
availability** and applicable Microsoft redistributable terms. Review the exact
distributed dependency set and adapted source attribution.
**LEGAL REVIEW RECOMMENDED.** No absolute legal-safety claim.

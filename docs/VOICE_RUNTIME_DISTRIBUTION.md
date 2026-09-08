# Aurora 3.8 Windows Voice distribution

## Two portable builds

| Artifact | Included | External / on demand |
| --- | --- | --- |
| Aurora-Windows-Core-Test.zip | Aurora UI, Chat, Memory, RAG, Knowledge and Ollama integration | Ollama service/models; optional Voice components are absent |
| Aurora-Windows-Full-Test.zip | Core plus faster-whisper 1.2.1, CTranslate2 4.8.2, edge-tts 7.2.8, pygame 2.6.1, sounddevice 0.5.6, PyAV 18.1.0, Python/native dependencies and VAD asset | Whisper model, FFmpeg executable, Windows audio devices, internet access for Edge TTS |

Both contain their own CPython 3.12 runtime. End users extract the ZIP and run
Aurora.exe, without Python, pip, conda, a virtual environment or development
tools. Neither package installs Python packages at runtime. Full is not a
dynamic addon. To roll back, close Aurora and launch the retained Core directory.

Whisper tiers require confirmation: tiny (~75 MB), small (~500 MB), medium
(~1.5 GB). Downloads go to Aurora user-data `models/whisper/<tier>.download`;
required files are validated before publishing the complete directory. Failed
downloads stay resumable and are not Ready. Success selects the tier for STT
and diagnostics. Windows extended paths avoid long Hub temporary filename
failures. Previously cached valid Hugging Face models remain readable.
Validation checks content against Hub hashes or loads legacy local models once,
then caches the result by file identity. Published downloads have an atomic
SHA-256 manifest; changed or corrupt files invalidate readiness and can be
quarantined on an explicit download retry without overwriting the old copy.

## Binary and license inputs

The unrestricted PyPI PyAV wheel is **not** the Full package's codec input.
Full uses conda-forge `av 18.1.0 py312hb2f1342_0` with
`ffmpeg 9.0.1 lgpl_h098eaf0_0`. These are build-only inputs, not a shipped conda
environment. `prepare_voice_codec_overlay.py` walks the PE import closure,
verifies locked archive SHA-256 values, rejects GPL/nonfree FFmpeg configurations
and x264/x265 dependencies, and copies only PyAV plus 62 required DLLs.

`config/voice_codec_lock.json` pins native inputs and records FFmpeg's actual
configuration/license string. `_internal/third_party/voice-codecs` contains
licenses, exact build recipes/patches and hash-verified corresponding LGPL
sources. DLLs can be replaced with ABI-compatible modified versions; Aurora
does not restrict reverse engineering for debugging those modifications.
FreeType uses the FTL alternative. Pygame source, LGPL terms and SDL dependency
notices are in `_internal/third_party/playback`, with inputs pinned by
`config/voice_playback_sources_lock.json`. Additional Python/native notices
are under `_internal/third_party/python`.

This is an engineering packaging audit, not a claim about every jurisdiction's
codec patents or a substitute for a public-release legal review. FFmpeg.exe
remains outside both ZIPs. Setup checks bundled, configured and PATH FFmpeg,
validates the executable when Voice is enabled, and offers the
[official download page](https://ffmpeg.org/download.html#build-windows) plus
an existing-file selector. No binary is silently installed. See
[FFmpeg redistribution guidance](https://ffmpeg.org/legal.html) and
[pygame distribution guidance](https://www.pygame.org/wiki/distributing).

## Build procedure (release engineer only)

Use isolated Windows CPython 3.12 with Tcl/Tk, core requirements, PyInstaller,
and the exact `requirements-voice.lock.txt` versions. This lock records the
verified environment's existing transitive versions; no runtime updater uses it.
`build_exe.ps1` validates all 38 versions for Full builds.

Prepare an isolated conda-forge build prefix with Python 3.12 and the exact
`name=version=build` entries in `config/voice_codec_lock.json`. Keep it outside
the shipped app. An ASCII temporary prefix avoids micromamba's Windows Unicode
cache-path limitation. Preparation uses pefile and PyYAML in the build Python.

```powershell
& $BuildPython scripts/prepare_voice_notices.py --cache build/voice-notice-downloads --output build/voice-codec-overlay/third_party/playback --lock config/voice_playback_sources_lock.json
& $BuildPython scripts/prepare_voice_codec_overlay.py --prefix $CodecPrefix --output build/voice-codec-overlay --lock config/voice_codec_lock.json
.\build_portable.ps1 -Python $BuildPython
.\build_portable.ps1 -Python $BuildPython -FullVoice
```

Do not use `--create-lock` during a release build; it is only for reviewed input
updates. Changed/missing locks or file hashes fail the build. PyInstaller
explicitly collects PyAV's Cython extensions, metadata, native libraries and
the faster-whisper VAD asset. Core and Full use separate output directories.
No script pushes, tags or publishes. Full contains `voice-runtime-integrity.json`
with every file's SHA-256/size and the Python version lock. Both ZIPs are hashed.

## Setup and readiness

Voice Off means Not enabled: no runtime import, microphone enumeration, model
load or Edge TTS network check. Voice On checks loadable STT/TTS/playback,
a complete local model, usable FFmpeg, DirectShow microphone, an output device
and the online TTS voice-list service. All must pass for Ready. Enumeration
cannot guarantee capture permission or audible output; hardware checks remain.

The setup plan lists only missing work. Core explains how to switch to Full.
Full offers model download, FFmpeg download/configuration and a friendly-name
or Windows-default microphone picker. Ready components are not reinstalled.
The application owns one RuntimeState and publishes immutable RuntimeSnapshot
revisions to First Run, Runtime, Voice, the setup wizard, diagnostics and chat.
Only this service probes (with a consistent timeout); a changed configuration
invalidates in-flight results and triggers a latest-settings probe. Automatic
model selections from stale probes are discarded, not written over user choices.

Whisper selection, FFmpeg paths and input-device configuration apply in the
current process. The same accepted snapshot gates creation of the Voice runtime
and updates the existing chat surface. Rechecks reuse an unchanged Voice runtime.
Reconfiguration first cancels and joins the previous audio owner; a still-stopping
owner cannot be replaced with a second capture pipeline. Initialization failure
downgrades the shared product state rather than displaying false Ready.

Ordinary checks never set a restart flag. Only an explicit verified native-loader
limitation may persist runtime.restart_required with a reason and process token.
A new process probes again and clears that flag when native STT/TTS/playback load.
External conditions such as Edge TTS connectivity are not native-loader failures.
Setup completion/cancellation returns to its caller; no global/full-settings
detour is used. Separate category canvases retain their own scroll positions.
TTS Runtime Ready is separate from online availability: an outage is not Runtime
Missing. Voice-list access is a point-in-time check, not a guarantee that later
synthesis will succeed.
Frozen Full builds use CPU/int8 for the default `auto` STT configuration, which
does not require CUDA/cuDNN. Explicit device/compute choices remain unchanged
and require their own compatible external runtime. The frozen smoke uses the
same STT factory and defaults as production, not a separate CPU-only test path.

## Frozen verification

`--voice-runtime-check REPORT.json` runs after the same single-instance gate,
before stores, GUI and application services. It records actual imports and their
origins. Use a fresh `AURORA_USER_DATA_DIR`, clear PYTHONHOME/PYTHONPATH/VIRTUAL_ENV,
and restrict PATH to Windows system directories. All Python origins must be
inside `_internal`; no source or venv path may appear in `sys_path`.

```powershell
.\Aurora.exe --voice-runtime-check runtime.json --voice-enabled
# Explicit download and fixed, non-personal Chinese TTS sentence:
.\Aurora.exe --voice-runtime-check smoke.json --voice-enabled --download-whisper tiny --tts-smoke --playback-smoke --ffmpeg C:\TrustedTools\ffmpeg.exe
# Restart without downloading; use production STT/playback classes:
.\Aurora.exe --voice-runtime-check restart.json --voice-enabled --model tiny --stt-audio C:\TestAudio\sample.mp3 --playback-smoke --ffmpeg C:\TrustedTools\ffmpeg.exe
```

The diagnostic does not record the microphone. Capture, listening, USB/default
device changes and a genuinely clean Windows machine require human/hardware
acceptance; a sanitized local environment is not a clean VM.

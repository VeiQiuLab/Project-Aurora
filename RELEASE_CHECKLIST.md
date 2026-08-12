# Project Aurora Release Checklist

This checklist applies to the current Chat-first Windows application. Optional
Voice validation is separated from the core release gate because text chat must
remain usable when Voice dependencies or audio hardware are unavailable.

## Version and Repository

- [ ] Confirm the intended release version from `modules/version.py`
- [ ] Update VERSION and BUILD metadata only for an approved release
- [ ] Synchronize CHANGELOG and release metadata
- [ ] Confirm display VERSION and derived numeric Windows version agree
- [ ] Confirm the release commit and intended Git tag agree
- [ ] Confirm the staging set contains no private data or unrelated binaries
- [ ] Run `git diff --check`

## Static Validation

- [ ] Python syntax checks pass
- [ ] `compileall` passes for production modules and widgets
- [ ] Focused automated tests for the release scope pass
- [ ] UTF-8 Markdown, JSON, and locale files load successfully
- [ ] No test result is reported as real GUI or hardware validation unless it was actually run

## Core Application Acceptance

- [ ] Application starts successfully
- [ ] Chat is the initial AppShell page
- [ ] Ollama connectivity and configured Chat Model work
- [ ] A text prompt streams and completes normally
- [ ] Conversation save works
- [ ] Conversation restore preserves message roles, content, and order
- [ ] Conversation search, rename, and delete work
- [ ] Settings categories open successfully
- [ ] Persona loads and contributes context when enabled
- [ ] Memory retrieval and candidate workflow remain functional
- [ ] Knowledge retrieval works when enabled
- [ ] Optional RAG pipeline and fallback behavior are verified for the release scope
- [ ] Text chat continues to work when Voice is disabled or unavailable

## User Data Isolation

- [ ] First launch creates `%APPDATA%/Aurora/config/settings.json`
- [ ] First launch creates `%APPDATA%/Aurora/conversations`
- [ ] First launch creates `%APPDATA%/Aurora/memory`
- [ ] First launch creates `%APPDATA%/Aurora/knowledge`
- [ ] First launch creates `%APPDATA%/Aurora/persona`
- [ ] First launch creates `%APPDATA%/Aurora/logs`
- [ ] Build and installer contain no developer settings, Conversations, Memory, Knowledge, Persona, logs, or device identifiers

## Optional Voice Acceptance

Run this section when Voice is included in the release target. A Voice failure
must not make the core text application unusable.

- [ ] Voice Environment reports dependencies accurately
- [ ] Microphone discovery selects or requests a valid input device
- [ ] Real microphone capture receives non-empty audio
- [ ] Faster-Whisper STT produces a usable transcription
- [ ] Recognized text enters the shared ChatPage pipeline
- [ ] Voice Conversation messages are saved and restored normally
- [ ] Edge-TTS synthesis works in the target environment
- [ ] Playback starts and stops normally
- [ ] Basic interrupt stops current TTS/playback and returns the UI to a usable state
- [ ] Voice failure falls back safely to text chat

Voice acceptance does not imply realtime, full-duplex, or production-mature
interruption behavior.

## FFmpeg Release Resource

`tools/ffmpeg.exe` is not tracked by Git. The build environment must provide an
approved Windows binary before packaging.

- [ ] `tools/ffmpeg.exe` exists
- [ ] `tools/ffmpeg.exe -version` runs successfully
- [ ] The binary source is recorded
- [ ] A trusted SHA256 value is recorded and verified where available
- [ ] No unknown FFmpeg binary is downloaded automatically

## PyInstaller Build

- [ ] Use a complete Windows CPython 3.12 installation with Tcl/Tk
- [ ] `import tkinter`, `tkinter.ttk`, and `tkinter.filedialog` pass
- [ ] PyInstaller is installed in the selected build interpreter
- [ ] `assets/` contains the required release assets
- [ ] Run `build_exe.ps1` with the selected Python executable
- [ ] `dist/Aurora/Aurora.exe` exists
- [ ] `dist/Aurora/_internal` exists
- [ ] `dist/Aurora/assets` exists
- [ ] `dist/Aurora/tools/ffmpeg.exe` exists
- [ ] Launch the packaged application outside the source tree

The build interpreter is environment-specific. Public release instructions must
not depend on a developer's personal absolute Python path.

## Inno Setup Build

- [ ] Inno Setup 6 `ISCC.exe` is available
- [ ] The installer script and output name use the approved display version
- [ ] Windows FileVersion/ProductVersion numeric fields use the derived
      four-part version
- [ ] The installer consumes the complete `dist/Aurora/` directory
- [ ] Build the installer with `installer/build_installer.ps1`
- [ ] Confirm the generated Setup executable exists
- [ ] Confirm the installer is named `Aurora-v3.8.0-alpha-Setup.exe`
- [ ] Record installer SHA256:
      `7DEEB26723B7182B2475734438D61A3E26C101CCAFB2E3438F3F4F907FCF81A2`
- [ ] Document that the installer is unsigned and SmartScreen may warn
- [ ] Install to a user-selected test directory
- [ ] Desktop and Start Menu shortcuts work
- [ ] Uninstall completes successfully

Installer naming must follow the unified VERSION source. Do not permanently
encode `v3.7.2` as the release process for future versions.

## Installed Application Smoke Test

- [ ] First installed launch completes
- [ ] AppData directories and default settings are generated
- [ ] Chat and Ollama work from the installed application
- [ ] Conversation save and restore work after restart
- [ ] Settings opens and saves supported options
- [ ] Confirm uninstall preserves `%APPDATA%\Aurora` user data
- [ ] Confirm bundled `tools/ffmpeg.exe` is present after installation
- [ ] Confirm Ollama is documented as required for local chat runtime
- [ ] Optional Voice Environment diagnostics run without breaking startup
- [ ] Logs contain no startup attempts for removed Open WebUI, Docker, Remote, or Mobile services

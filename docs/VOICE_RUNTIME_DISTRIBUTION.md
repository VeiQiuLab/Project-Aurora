# Aurora Voice Runtime distribution

Aurora 3.8 has two deliberate Windows package profiles:

- **Core-only test build**: starts without optional Voice Python packages and never tries to add them at runtime.
- **Full Voice Build**: includes the exact package versions declared in `config/voice_runtime_build.json` after a release engineer explicitly confirms completion of the codec-license review.

The application never runs a general-purpose `pip install`. The Voice Setup Wizard only checks readiness and, after a separate user confirmation, may download one supported Whisper model tier. A dynamic Voice addon is not shipped in 3.8; introducing one later requires signed metadata, package-level SHA-256 verification, a version compatibility check, staging in an Aurora-controlled directory, atomic activation, and rollback.

`build_exe.ps1 -FullVoice` validates every installed Voice distribution against the pinned manifest before packaging. The additional `-VoiceCodecLicenseReviewed` gate is required because PyAV can redistribute codec libraries. This gate does not bundle `ffmpeg.exe`; that binary remains excluded until its own license and redistribution review is complete.

After a Full Voice Build, `voice-runtime-integrity.json` records the SHA-256 and size of every packaged file. The Core-only build remains the rollback artifact; deployment replaces a build directory as one unit rather than modifying an installed Python environment.

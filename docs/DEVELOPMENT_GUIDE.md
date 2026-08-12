# Project Aurora Development Guide

## Development Scope

Aurora development should be incremental, compatible, and easy to review.
Before changing a feature, identify its owner, configuration keys, persisted
data, user-visible behavior, and required tests.

Current module boundaries are:

- Chat: ChatPage, ChatPanel, ChatSession, and Ollama streaming
- Conversation: persistence, restore, search, metadata, and intelligence
- Context: ContextBuilder and prompt-context integration
- Persona: user-controlled assistant identity and system context
- Memory: retrieval, candidates, review, and persistence
- Knowledge/RAG: local knowledge retrieval and optional ranking pipeline
- Voice Experience: microphone, VAD, STT, shared Chat input, TTS, and playback
- Settings: configuration, migration, and current UI entry points
- Packaging: AppData isolation, PyInstaller, Inno Setup, assets, and FFmpeg

Do not regenerate the application or create parallel versions of these systems.
Remote, LAN, Mobile, Open WebUI, Docker, and the old Dashboard are historical or
removed product directions, not current development boundaries.

## Chat and Voice Boundary

Voice is an input/output Experience Layer around Chat, not a second Chat Core.
Recognized Voice text must enter through ChatPage and reuse ChatSession,
Conversation, ContextBuilder, Persona, Memory, Knowledge/RAG, and the normal text
message UI.

Voice, STT, TTS, playback, or device failures must fail safely and leave text
chat usable. Keep provider interfaces replaceable and preserve cancellation,
session/generation ownership, and stale-output checks when modifying asynchronous
Voice code.

## UI Text and Theme

Use `modules/ui_theme.py` for shared visual tokens. Prefer existing font, color,
spacing, and button helpers over page-specific hard-coded styles.

Where a surface uses localization, add new user-visible keys to both
`locales/zh_CN.json` and `locales/en_US.json`. Locale files must remain valid
UTF-8 JSON. Missing translation keys must not crash the application.

Run the i18n alignment check when locale keys change:

```powershell
python scripts/check_i18n.py
```

## Settings and Configuration

- Reuse `modules/settings.py` and `SettingsController`.
- Prefer `settings.update_many()` for related updates.
- Preserve unknown keys and existing user values during default merging.
- Do not change the settings schema without a compatibility migration.
- Keep configuration access at integration boundaries where practical.
- UI save actions must report success or failure clearly.
- Do not create a second configuration model.

## Error Isolation

- Optional Voice failure must not break Chat.
- RAG optimization failure must preserve a usable retrieval fallback.
- Conversation Intelligence and title failures must not break persistence.
- Missing audio devices or dependencies must produce actionable diagnostics.
- Background failures must return shared state to a usable condition.
- Network, process, indexing, model, audio, and heavy file work must not block
  the Tkinter UI thread.

## Runtime Data and Privacy

Release runtime data belongs under `%APPDATA%/Aurora/`. Do not commit or package
user settings containing private information, Conversations, Memory records,
Knowledge data, private Persona data, logs, device identifiers, installers,
FFmpeg, model files, or other large local binaries.

Approved defaults, examples, source code, and documentation may be tracked.
Data-directory or schema changes require a dedicated migration plan.

## Windows Compatibility

- Use a complete Windows CPython 3.12 installation with Tcl/Tk for GUI builds.
- Do not assume the Windows Python Launcher is functional.
- Keep subprocess windows hidden for background production processes.
- Preserve source and packaged executable path handling.
- Treat FFmpeg as an explicit local build resource and verify its source and
  checksum where available.
- Verify behavior from source and from the packaged application when required.

## Validation

Choose checks proportional to the change. Typical static validation is:

```powershell
git diff --check
python -m compileall main.py modules widgets
python scripts/check_i18n.py
```

Use focused tests for changed contracts and failure paths. Mock tests do not
replace real GUI, Ollama, microphone, Edge-TTS, playback, or installer smoke
tests. Report skipped checks and environmental limitations explicitly.

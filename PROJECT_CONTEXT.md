# Project Aurora Context

## Product Goal

Project Aurora is a Chat-first, Local-first personal AI companion for Windows.
It provides private local conversation, continuity, user-controlled memory,
knowledge retrieval, persona context, and an optional voice experience.

Aurora is not a general-purpose autonomous Agent, desktop automation platform,
Open WebUI control center, or Remote/LAN/Mobile service.

## Version State

- Committed baseline: `cb7abca` (`release: prepare Aurora v3.7.2 distribution`)
- Code and packaging version at that baseline: `3.7.2`
- Latest Git tag: `v3.7.0`
- Current uncommitted development: post-3.7.2 work in the v3.8 direction

Version 3.7.2 is a release-preparation baseline. It does not have a matching Git
tag and must not be described as a completed tagged release.

## Current Architecture

The shared text conversation path is:

```text
AppShell
  -> ChatPage
  -> ChatSession
  -> Context preparation
     -> Persona
     -> Memory retrieval
     -> Knowledge retrieval
     -> optional RAG pipeline
     -> ContextBuilder
  -> Ollama stream_chat()
  -> Conversation persistence
  -> Conversation Intelligence
  -> Memory candidates
```

The optional voice path is:

```text
Microphone / VAD / FrameRecorder
  -> Faster-Whisper STT
  -> ChatPage.handle_external_prompt()
  -> shared ChatPage and ChatSession pipeline
  -> text UI and Conversation persistence
  -> SentenceSplitter / TTSQueue
  -> Edge-TTS
  -> Playback
```

Voice does not own a separate ChatSession, Conversation store, Memory system, or
RAG pipeline.

## Current Top-level UI

The production AppShell registers two top-level pages:

- Chat
- Settings

Home, Library, Learning Center, standalone Persona/Memory pages, Remote pages,
and several window-based workflows may still have legacy files or compatibility
callbacks. They are not registered as current top-level AppShell pages.

## Stable / Active Components

- Ollama chat and model selection
- ChatSession and streaming text chat
- Conversation persistence, restore, search, rename, and delete
- Persona context
- Memory retrieval and candidate workflow
- Knowledge retrieval and optional RAG pipeline
- ContextBuilder and context diagnostics
- Chat-first AppShell with Chat and Settings
- AppData-based user data isolation
- PyInstaller and Inno Setup packaging baseline

## Experimental Components

The current dirty workspace contains post-3.7.2 development. These capabilities
must not be presented as released v3.7.2 behavior:

- LLM-assisted semantic Conversation titles
- Chat Bubble UI and streaming message presentation
- Voice Runtime stabilization on real devices
- VAD automatic recording stop
- SentenceSplitter and FIFO TTSQueue
- Voice interrupt and cancellation hardening
- Voice session/generation isolation
- Unified non-blocking Chat Turn Gate for text and voice

## Removed Components

The following are not part of the current product architecture and must not be
restored without explicit product approval:

- Open WebUI integration
- Docker and Docker Desktop integration
- Remote and LAN access
- Mobile Chat and Mobile UI
- old Dashboard/Home production routing
- independent Voice ChatSession or separate Voice conversation pipeline

Historical documentation, locale keys, compatibility migration code, or legacy
UI files may still mention some of these features. Their presence does not make
the features active.

## Persistence

User data is stored under `%APPDATA%/Aurora/`, including settings,
conversations, memory, knowledge, persona, and logs. Development or release
work must not commit private user data, local settings, device identifiers, or
generated logs.

## Known Issues

- Voice interrupt can stop TTS and playback, but an in-flight Ollama request may
  continue generating text until the current request exits its streaming loop.
- Voice and GUI behavior on real audio devices still need longer-running
  stability validation.
- `tools/ffmpeg.exe` is required by the Windows packaging flow but is ignored by
  Git; the build environment must provide it separately.
- Version 3.7.2 has no Git tag.
- The working tree contains substantial uncommitted post-3.7.2 development.

## Development Rules

- Audit the current architecture and working tree before changing code.
- Prefer small, scoped, reversible changes.
- Preserve unrelated user changes in the dirty working tree.
- Do not create parallel Conversation, Memory, Knowledge, Settings, state, or
  Voice systems.
- Voice input must enter through ChatPage and reuse ChatSession, context,
  Conversation, Memory, Knowledge, Persona, and RAG behavior.
- Do not restore removed features without explicit authorization.
- Do not expand Aurora into a general Agent or desktop automation platform
  without an explicit product-direction change.
- Do not commit conversations, memory, knowledge, persona, logs, local settings,
  device identifiers, installers, FFmpeg, or other large local binaries.
- Do not commit, tag, push, reset, or stash unless explicitly requested.
- Use a working Windows CPython 3.12 interpreter for project tests. Local Codex
  rules or local configuration may specify the exact interpreter path.
- Do not create a virtual environment, use `py.exe`, modify PATH, or install
  dependencies unless the user explicitly requests it.

## Next Direction

The current direction is repository and current-state consolidation followed by
v3.8 Voice/Chat stabilization. Near-term work should focus on reliable shared
Chat turns, real-device Voice lifecycle validation, and preparation for future
CompanionState-driven Live2D integration.

P0/P1/P2 labels are task-local engineering phases, not product version numbers.

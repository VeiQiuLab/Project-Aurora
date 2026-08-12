# Project Aurora Architecture

## Overview

Project Aurora is a Chat-first, Local-first personal AI companion for Windows.
The current architecture centers all text and voice input on one ChatPage,
ChatSession, context pipeline, and Conversation store.

The current release is the `v3.8.0-alpha` pre-release. Voice lifecycle and
streaming capabilities marked below remain experimental.

## UI Layer

`AppShell` is the production application frame. It currently registers two
top-level pages:

- Chat
- Settings

Chat is the initial page. Its Sidebar owns new-chat, search, Conversation
history, and Settings navigation. Settings groups AI, Voice, Appearance, Data,
and Developer surfaces; Persona, Memory, and Knowledge/RAG are reached through
Settings.

Home, Library, Learning Center, standalone Persona/Memory pages, old dashboard
widgets, and several standalone windows remain only as legacy or compatibility
code. They are not current top-level AppShell routes.

## Chat Core

The production text flow is:

```text
ChatPanel input
  -> ChatPage
  -> ChatSession
  -> context preparation
  -> stream_chat()
  -> Ollama /api/chat
  -> streaming ChatPanel update
  -> ChatSession assistant message
  -> Conversation persistence
```

`ChatSession` owns the ordered system, user, and assistant messages for the
active Conversation. `stream_chat()` appends the user and completed assistant
messages and queues Memory candidates after a successful, non-cancelled turn.

`ConversationManager` persists and restores the same role/content message
structure. Conversation identity comes from its ID, not its title.

## Context Layer

Before each Chat turn, `ChatPage` calls the injected context preparation
boundary. That boundary retrieves and assembles:

- Persona context
- relevant Memory records
- relevant Knowledge records
- optional normalized/ranked RAG results
- current Conversation messages

`ContextBuilder` assembles system-context sections and diagnostics. Conversation
history remains in `ChatSession.messages` and is sent to Ollama as chat messages;
it is not flattened into a replacement Memory or RAG store.

RAG is optional and has a fallback path. Failure in optional ranking or context
optimization must preserve usable base Memory and Knowledge retrieval.

## Conversation Intelligence

Conversation Intelligence runs asynchronously after Conversation persistence.
It stores analysis metadata such as summary, topics, events, message counts, and
Memory signals. It may trigger Conversation-derived Memory candidate analysis
without changing the Conversation storage format.

LLM-assisted semantic Conversation titles and their asynchronous Sidebar refresh
are included in the v3.8.0-alpha candidate. Manual titles must remain protected
from automatic replacement.

## Voice Experience

The current Voice architecture is:

```text
Microphone
  -> audio source and frame buffer
  -> RMS VAD / FrameRecorder
  -> Faster-Whisper STT
  -> ChatPage.handle_external_prompt()
  -> shared ChatSession and context pipeline
  -> Ollama streaming response
  -> text UI and Conversation persistence
  -> SentenceSplitter / TTSQueue
  -> Edge-TTS
  -> PlaybackController
```

Voice recognized text enters the same ChatPage business path as keyboard input.
There is no independent Voice ChatSession, Conversation store, Memory pipeline,
RAG pipeline, or Voice-only message UI.

Faster-Whisper and Edge-TTS are provider implementations behind Voice
interfaces. Text chat must remain usable when recording, STT, TTS, or playback
is unavailable.

VAD auto-stop, sentence-based TTS queueing, cancellation hardening, and
real-device stability work are experimental. Aurora does not currently provide
mature realtime full-duplex voice interaction.

## State and Concurrency

`CompanionStateStore` coordinates states such as IDLE, LISTENING, TRANSCRIBING,
THINKING, SPEAKING, and ERROR. Optional UI or future visual layers may observe
this state but must not create independent global state ownership.

The v3.8.0-alpha Voice work binds asynchronous work to `session_id` and
`generation_id`, uses cancellation events, and discards stale output. The
Unified Chat Turn Gate uses a non-blocking single-active-turn rule so text and
voice cannot mutate the same ChatSession concurrently. These protections remain
experimental until committed and validated on real devices.

## Persistence

Release builds keep user data under `%APPDATA%/Aurora/`:

```text
Aurora/
  config/settings.json
  conversations/
  memory/
  knowledge/
  persona/
  logs/
```

`config/default_settings.json` is the distributable first-run template. Private
runtime data, local settings, device identifiers, and logs must not be packaged
or committed.

## Packaging

The Windows distribution flow uses:

- `Project Aurora.spec` and PyInstaller for `dist/Aurora/`
- Inno Setup for `installer/Aurora-v3.8.0-alpha-Setup.exe`
- project-managed Inno Setup language resources
- full Windows CPython 3.12 with Tcl/Tk

The expected PyInstaller output contains:

```text
Aurora/
  Aurora.exe
  _internal/
  assets/
  tools/ffmpeg.exe
```

`tools/ffmpeg.exe` is a required local release resource but is intentionally
ignored by Git. A clean build environment must provide it separately; future
automation should download a pinned binary only with SHA256 verification.

## Removed Architecture

The following systems are not part of the current architecture:

- Open WebUI integration
- Docker and Docker Desktop integration
- Remote and LAN services
- Mobile Chat and Mobile UI
- old Dashboard/Home production routing
- independent Voice conversation or Memory systems

They may appear in historical documents, old locale keys, migration helpers, or
legacy UI code. Such references are historical or compatibility artifacts and
must not be treated as production entry points or restored without explicit
product approval.

## Architecture Principles

- Keep ChatPage and ChatSession as the shared text/voice turn boundary.
- Extend existing Conversation, Persona, Memory, Knowledge/RAG, ContextBuilder,
  Settings, state, and Voice interfaces instead of creating parallel systems.
- Keep optional Experience Layer failures isolated from text chat and core data.
- Do not block the GUI thread with network, model, process, audio, indexing, or
  heavy file work.
- Preserve existing data formats or provide an explicit migration.
- Distinguish committed active behavior from dirty experimental development.

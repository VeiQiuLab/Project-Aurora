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
history, and Settings navigation. Settings groups AI, Runtime/Dependencies,
Voice, Appearance, Data, and Developer surfaces; Persona, Memory, and
Knowledge/RAG are reached through Settings.

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
- normalized, deduplicated, ranked, and budget-optimized RAG results
- current Conversation messages

`ContextBuilder` assembles system-context sections and diagnostics. Conversation
history remains in `ChatSession.messages` and is sent to Ollama as chat messages;
it is not flattened into a replacement Memory or RAG store.

For the v3.8 alpha path, RAG is enabled by default but remains configurable.
The production adapter receives the current query, Conversation message count,
available result counts, and context budget from the shared Settings source.
Failure in normalization, deduplication, ranking, optimization, or integration
preserves usable legacy Memory and Knowledge context. Adaptive Context remains
disabled by default behind `context.adaptive_enabled`.

Memory retrieval first filters for `enabled == true` and lifecycle state
`active` (legacy records without a state are active), applies the configured
relevance gate, then ranks by relevance, confidence, importance, and freshness.
Pending candidates require explicit user approval or rejection. Approving a
possible update atomically creates the replacement and marks its target
superseded; possible conflicts never supersede automatically. Archive preserves
the record while excluding it from default retrieval, and permanent delete is a
separate user action.

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

## First Run and Runtime Dependencies

`RuntimeDependencyManager` is the shared read-only diagnostics boundary used by
First Run, Settings, and the production Voice startup gate. It distinguishes an
absent Ollama install, an installed but offline service, and a ready API; it also
classifies local models as Chat Supported or Embedding Only. Optional probe
failures are contained so they cannot prevent Aurora Core from opening.
When Voice is disabled, automatic checks do not enumerate microphone or playback
devices; hardware access begins only after Voice is enabled or the user explicitly
requests a device test. Ordinary status rows use actionable descriptions instead
of exposing raw driver, DirectShow, HTTP, or subprocess exception strings.

First Run persists no model choice until the user selects an existing model or
confirms a download. Hardware recommendations use RAM, CPU/core count, reliable
VRAM when available, and free disk space. Unknown VRAM remains unknown. Checks
and downloads run away from the GUI thread, and only Aurora-owned download or
service processes may be cancelled or stopped.

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

Memory and candidate JSON updates use same-directory temporary files, flush and
`fsync`, then `os.replace`. A `.bak` file retains the previous valid JSON list;
unrecoverable corrupt primary data is not silently overwritten.

`config/default_settings.json` is the distributable first-run template. Private
runtime data, local settings, device identifiers, and logs must not be packaged
or committed.

## Packaging

The Windows distribution flow uses:

- `Project Aurora.spec` and PyInstaller for `dist/Aurora/`
- `build_portable.ps1` for `dist/Aurora-Windows-Test.zip`
- Inno Setup for `installer/Aurora-v3.8.0-alpha-Setup.exe`
- project-managed Inno Setup language resources
- full Windows CPython 3.12 with Tcl/Tk

The expected PyInstaller output contains:

```text
Aurora/
  Aurora.exe
  _internal/
```

The portable package includes the Python runtime and Aurora Core dependencies,
but excludes source `.venv` data, developer runtimes, user data, logs, secrets,
Ollama/model files, Open WebUI, FFmpeg, PyAV/FFmpeg codec libraries, and the
optional Voice Python runtimes. This Core-only boundary avoids redistributing
unreviewed codec binaries. Optional runtimes are detected and explained at run
time instead of being silently installed or downloaded.

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

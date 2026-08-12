# Project Aurora

Project Aurora is a Local-first, Chat-first personal AI companion for Windows.
It uses Ollama for local model inference and brings together conversation,
Persona, Memory, Knowledge/RAG, and an optional Voice Experience in one desktop
application.

Aurora is not an Open WebUI frontend, Docker control center, remote-access
platform, general-purpose Agent, or desktop automation framework.

## Features

### Chat

- Local chat through Ollama
- Streaming responses
- Persistent Conversations and history search
- Conversation restore, rename, and delete
- Chat-first desktop UI

### Context and Intelligence

- Persona context
- User-controlled Memory and Memory candidates
- Local Knowledge base and retrieval
- Optional RAG normalization and ranking
- ContextBuilder-based prompt context
- Asynchronous Conversation Intelligence metadata

Semantic Conversation Titles are part of post-3.7.2 development and are not a
released v3.7.2 capability.

### Voice (Experimental)

The optional Voice flow is turn-based:

```text
Speech
  -> Faster-Whisper
  -> shared Chat Pipeline
  -> text response
  -> Edge-TTS
  -> Playback
```

Voice currently targets natural turn-based interaction. It is experimental and
should not be treated as realtime, full-duplex, or production-ready voice.
Text chat remains available when optional Voice components are unavailable.

### Local-first Data

Ollama inference and Aurora user data are primarily local. Some optional
providers may require network access; Edge-TTS is an online TTS provider.

## Current UI

The production AppShell has two top-level pages:

- Chat
- Settings

Persona, Memory, and Knowledge/RAG are available through Settings. Older Home,
Library, Dashboard, Remote, and Mobile surfaces are not current top-level pages.

## Requirements

- Windows
- Python 3.12 for source development
- Ollama
- CustomTkinter and the dependencies in `requirements.txt`

Optional Voice dependencies include:

- Faster-Whisper
- Edge-TTS
- pygame
- FFmpeg

The Windows Voice and packaging flow expects `tools/ffmpeg.exe`. This binary is
not tracked by Git and must be supplied by the development or build environment.

## Running from Source

1. Install Python 3.12 with Tcl/Tk support.
2. Install the dependencies from `requirements.txt`.
3. Install and start Ollama, then make the configured chat model available.
4. Start Aurora:

```powershell
python main.py
```

Select the actual Python interpreter appropriate for the local development
environment; Aurora does not assume that the Windows Python Launcher is usable.

## Data and Privacy

Release builds store user data under `%APPDATA%/Aurora/`, including:

```text
config/settings.json
conversations/
memory/
knowledge/
persona/
logs/
```

Do not commit Conversations, Memory data, Knowledge data, private Persona data,
logs, device identifiers, or user settings containing private information.

## Project Status

- Latest Git tag: `v3.7.0`
- Current committed code: `3.7.2` release-preparation baseline at `cb7abca`
- Current development: post-3.7.2 work in the v3.8 direction

Version 3.7.2 has not been published as a matching Git tag in this repository.
Uncommitted development must not be interpreted as released behavior.

## Removed and Historical Features

Earlier Aurora versions explored Remote/LAN access, Mobile Chat, and Open
WebUI/Docker-related integration. These remain part of the historical record but
are not part of the current product direction.

## Development

Start with:

- [Project context](PROJECT_CONTEXT.md)
- [Current architecture](docs/ARCHITECTURE.md)
- [Changelog](CHANGELOG.md)

Aurora development favors small incremental changes, one shared Chat Pipeline
for text and voice, local-first data ownership, and privacy-conscious release
practices.

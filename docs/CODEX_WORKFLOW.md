# Project Aurora Codex Workflow

## Purpose

This is the general development workflow for Project Aurora. It is not tied to
a historical version phase or milestone.

## Current Sources of Truth

Read these before making architecture or product-state decisions:

1. `PROJECT_CONTEXT.md`
2. `docs/ARCHITECTURE.md`
3. `AGENTS.md`, when the local ignored file is present

Documents under `docs/archive/` describe historical stages and are not current
implementation instructions.

## Start of Work

Inspect the current branch, working tree, and relevant files before editing:

```powershell
git branch --show-current
git status --short
```

Identify the requested scope, owning modules, affected data or configuration,
and required validation. Assume existing uncommitted changes belong to the user
and preserve them.

## Change Scope

- Audit the current implementation before changing it.
- Make small, scoped, reversible changes.
- Follow existing module and interface boundaries.
- Do not overwrite, revert, or reformat unrelated user work.
- Do not create duplicate Chat, Conversation, Context, Persona, Memory,
  Knowledge/RAG, Voice, Settings, state, or i18n systems.
- Documentation-only work must not modify runtime source.
- Removed features must not be restored without explicit product approval.
- Experimental work must not be described as stable or released.

## Runtime Architecture Safety

- Keep AppShell focused on the current Chat and Settings entry points.
- Voice input must enter through `ChatPage.handle_external_prompt()` and reuse
  the shared ChatSession, context, Conversation, Memory, Knowledge, Persona, and
  RAG pipeline.
- Do not create an independent Voice Conversation or Memory path.
- Keep optional Voice and Experience failures isolated from text chat.
- Do not block the GUI thread with network, model, process, audio, indexing, or
  heavy file work.
- Preserve data formats or provide an explicit migration.
- Treat legacy pages and windows as compatibility code until reachability is
  reviewed; do not promote them back to primary navigation implicitly.

## Configuration, UI, and i18n

- Reuse the existing Settings system and preserve unknown keys during migration.
- Use shared theme tokens for common UI colors, fonts, and controls.
- Add user-facing locale keys to both `zh_CN` and `en_US` when the surrounding
  UI uses i18n.
- Do not reintroduce a parallel translation system.
- Do not move AppData paths or package private runtime data without an approved
  migration or release task.

## Version and Release Safety

- `modules/version.py` is the version source of truth.
- Do not change versions during review or incomplete implementation work.
- Do not describe a commit as a tagged release unless the matching Git tag
  exists.
- Keep version metadata, CHANGELOG, packaging metadata, and release artifacts
  synchronized during an explicitly approved release.
- Do not include ignored installers, FFmpeg, user data, or other local binaries
  in source commits.

## Validation

Run checks appropriate to the changed surface. Common checks include:

```powershell
git diff --check
python -m compileall main.py modules widgets
python scripts/check_i18n.py
```

Use the project interpreter required by the local environment rather than
assuming `py.exe` is available. Do not install dependencies unless explicitly
authorized.

Distinguish static checks, mock tests, GUI smoke tests, and real Ollama/audio
device validation. Never report a validation level that was not performed.

## Git Hygiene

- Stage, commit, tag, push, reset, stash, or publish only when explicitly asked.
- Never use destructive Git operations on unrelated user changes.
- Inspect the staging set for private data and large binaries before release.
- Keep ignored local configuration and runtime data outside source control.

## Completion Report

Report files changed, reasons, checks and results, untested behavior, known
limitations, and Git/release state when relevant.

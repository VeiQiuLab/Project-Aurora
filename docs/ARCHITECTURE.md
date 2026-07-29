# Project Aurora Architecture

## Current Baseline

Project Aurora v2.6.0 Stable is the current frozen architecture baseline for
v2.7 planning.

The v2.6 architecture completed the transition from a collection of large UI
windows toward a structured local AI control center with:

- AppShell
- Pages Layer
- Windows Layer
- i18n system
- Theme system
- Shared modules
- Locale files
- Runtime data directories

## AppShell

The AppShell is the primary application frame. It owns the high-level layout
and navigation structure instead of placing the whole product inside one large
window implementation.

Responsibilities:

- Provide the main application shell.
- Route between primary pages.
- Keep global navigation separate from page-specific UI.
- Preserve a consistent visual frame for Aurora.

The AppShell should remain the center of the v2.6 structure during v2.7 work.

## Pages Layer

The Pages Layer contains user-facing application pages.

Responsibilities:

- Keep each major workflow separated by page.
- Render page-specific controls and state.
- Use existing service modules instead of duplicating business logic.
- Keep default views focused on common user actions.

Expected page boundaries include:

- Home
- Chat
- Library / Knowledge
- Memory
- Persona
- Remote
- Settings

Pages should not become large mixed surfaces for unrelated diagnostics,
developer tools, and user workflows.

## Windows Layer

The Windows Layer contains focused secondary windows and dialogs.

Responsibilities:

- Provide focused editors, confirmations, setup flows, and diagnostics when a
  full page is not appropriate.
- Keep window-specific layout and behavior outside the main shell.
- Preserve compatibility with legacy workflows during migration.

Windows should remain separated from pages. New v2.7 work should avoid moving
unrelated page behavior into dialog windows or placing large window workflows
back into `main.py`.

## i18n System

Aurora uses locale keys for user-facing strings.

Rules:

- All user-facing strings must use the i18n system.
- New UI strings must be added to both `locales/zh_CN.json` and
  `locales/en_US.json` when runtime UI work begins.
- `zh_CN` and `en_US` locale keys must remain aligned.
- Missing translation keys should not crash the app.
- Do not reintroduce legacy `TEXT` dictionaries.

Logs, exception details, debug payload keys, and API field names do not require
localization unless they are displayed directly in the UI.

## Theme System

Aurora uses the shared theme system for common visual tokens.

Responsibilities:

- Keep fonts, colors, and common styles centralized.
- Avoid one-off hard-coded button, label, and status styles.
- Preserve visual consistency across pages and windows.

New UI work should use existing theme helpers and tokens instead of adding
unrelated per-page styling.

## Modules

The `modules/` directory contains shared application logic and service
boundaries.

Current module responsibilities include areas such as:

- Version information
- Settings
- Models
- Health checks
- Launcher behavior
- Logging
- Theme support
- Memory, knowledge, conversation, persona, and remote capabilities where
  present

Architecture rules:

- Extend existing modules before creating parallel systems.
- Keep business logic out of page layout code when practical.
- Do not change stable data formats without a migration plan.
- `modules/version.py` remains the source of version information.

## Locales

The `locales/` directory contains translation JSON files.

Expected files include:

- `locales/zh_CN.json`
- `locales/en_US.json`

Rules:

- Keep locale JSON valid UTF-8.
- Keep key sets aligned between supported locales.
- Add locale keys in the same phase as UI text changes.
- Do not use hard-coded user-facing Chinese or English text in runtime UI.

## Data Directory

The project contains a `data/` directory for runtime data.

Typical runtime data areas may include:

- Memory
- Knowledge
- Conversations
- Persona
- Remote data

Rules:

- Runtime data should not be committed unless it is an approved template or
  example.
- Do not move or rename runtime data paths during v2.7 work without a dedicated
  migration plan.
- Expensive data operations must not block the GUI thread.

## Architectural Principles

- Keep UI pages separated.
- Keep windows separated.
- Preserve the AppShell as the main application structure.
- Do not reintroduce legacy `TEXT` dictionaries.
- All user-facing strings must use i18n.
- Keep `zh_CN` and `en_US` locale keys aligned.
- Avoid large unrelated rewrites.
- Prefer small, scoped changes that match existing architecture.
- Keep runtime behavior compatible with v2.6.0 Stable unless a phase explicitly
  changes it.
- Use background threads for network, process, indexing, file, and other
  expensive operations that could block the GUI.

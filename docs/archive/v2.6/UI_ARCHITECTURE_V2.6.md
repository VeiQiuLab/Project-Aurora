# Project Aurora v2.6 UI Architecture Design

## Background

Project Aurora v2.4.4 completed the UI Architecture Stabilization baseline.

Current state:

- Core business modules are already mature.
- Chat, Memory, Knowledge, Persona, and Remote are separate modules.
- Most large UI windows have been extracted from `main.py`.
- `main.py` has been reduced from 6500+ lines to about 1700 lines.

The current problem is not missing functionality. The main issue is UI information architecture.

Current UI shape:

- `ChatWindow`
- `KnowledgeWindow`
- `RemoteWindow`
- `SettingsWindow`
- `MemoryWindow`

Each window keeps accumulating controls and diagnostic tools. This causes:

- Long pages.
- Too many buttons.
- User-facing features mixed with developer tools.
- More searching than acting.
- High cognitive load for daily use.

The v2.6 goal is to move Project Aurora from a collection of tool windows to a unified AI Companion application interface.

## Core Design Principles

### Progressive Disclosure

Default UI should show the most common user actions.

Advanced users can enter Advanced sections for:

- Debug
- Diagnostics
- Raw Data
- Security

Aurora should not expose every tool by default.

### Separation of User and Developer Surfaces

User-facing features:

- Chat
- Memory
- Library
- Persona

Developer and diagnostic features:

- Context Inspector
- Logs
- Diagnostics
- API Status
- Raw Prompt

These surfaces should be visually and structurally separated.

### Information Hierarchy

Aurora UI should use a three-level hierarchy:

1. Navigation
2. Page
3. Advanced / Tools

## Target Application Shell

Planned module:

- `widgets/app_shell.py`

Target structure:

```text
Aurora

+----------------+-------------------------+
| Sidebar        | Content Area            |
|                |                         |
| Home           |                         |
| Chat           | Current Page            |
| Library        |                         |
| Memory         |                         |
| Persona        |                         |
| Remote         |                         |
| Settings       |                         |
+----------------+-------------------------+
```

Sidebar responsibilities:

- Page navigation.
- Current page state.
- Compact system status.

Content Area responsibilities:

- Render the selected page.
- Keep page-specific layout local to the page.

Aurora should stop using independent windows as the primary workflow. Dialog windows should remain only for confirmations, short editors, and focused setup flows.

## Primary Navigation

Recommended primary navigation:

- Home
- Chat
- Library
- Memory
- Persona
- Remote
- Settings

### Home

Replaces the current Dashboard as the default status center.

### Chat

Core AI conversation surface.

### Library

Replaces the Knowledge name in the main navigation.

Contains:

- Documents
- Knowledge Base
- Search
- Retrieval

### Memory

Long-term memory management.

### Persona

AI persona configuration and preview.

### Remote

Remote access and security status.

### Settings

System configuration.

## Page Design

### Home Page

Goal: status center.

Show:

- Aurora Status
- AI Runtime
- Memory
- Knowledge
- Persona
- Remote

Example:

```text
AI Runtime      Healthy
Memory          128 memories
Knowledge       24 documents
Persona         Haidee Aurora
Remote          Protected
```

Quick Actions should only include:

- New Chat
- Open Library
- Settings

Remove from default Home:

- Diagnostics
- Developer Tools
- Test Buttons

### Chat Page

Goal: primary Aurora experience.

Layout:

- Left: Conversation Sidebar
- Right: Chat Area
- Top: Current Model
- Bottom: Input Area

Conversation Sidebar:

- Conversation List
- Search
- New Conversation

Chat Settings:

- Model
- Context
- Memory
- Knowledge

Advanced:

- Context Inspector
- Debug Information
- Raw Prompt

Advanced tools should be hidden by default.

### Library Page

Library replaces the current Knowledge Window.

Sections:

- Documents
- Preview
- Index
- Retrieval
- Backup
- Health

Documents:

- Add File
- Remove File
- Search

Preview:

- Document Preview
- Search Preview

Index:

- Vector Index
- Rebuild

Retrieval:

- Retrieval Test

Backup:

- Export
- Import

Health:

- Metadata Check
- Repair

### Memory Page

Default view:

- Memory List
- Memory Detail
- Search

Advanced:

- Candidate Memory
- Extraction
- Quality Control

### Persona Page

Default view:

- Current Persona
- Name
- Description
- Style

Advanced:

- Prompt Preview
- Rules
- Reset

### Remote Page

Goal: reduce complexity.

Remote Center second-level pages:

- Status
- Devices
- Pairing
- Security
- Diagnostics

Default summary:

```text
Remote Status   Protected
Devices         1 Device
Security        Enabled
```

### Settings Page

Keep:

- `SettingsController`
- `settings.update_many()`

Layout:

- Left: Settings categories
- Right: category content
- Bottom: fixed Save / Cancel footer

Categories:

- General
- AI
- Persona
- Memory
- Library
- Remote
- Developer

## Component Standards

Existing component module:

- `widgets/ui_components.py`

Planned components:

- `NavigationItem`
- `PageHeader`
- `Toolbar`
- `Sidebar`
- `Tab`
- `EmptyState`
- `StatusCard`

New v2.6 pages must not create raw `ctk.CTkButton` directly.

Avoid:

- Hard-coded fonts.
- Hard-coded colors.
- Page-specific button styles.

Use:

- `widgets/ui_components.py`
- `modules/ui_theme.py`

## i18n Rules

New v2.6 UI must use:

- `t("key")`

Do not add:

- Hard-coded Chinese UI text.
- Hard-coded English UI text.

Legacy:

- `TEXT`

Migration order:

1. Stabilize UI.
2. Stabilize component contracts.
3. Migrate i18n keys.

## Migration Strategy

Do not rewrite everything at once.

Keep v2.4.4 stable while adding the new shell.

Migration style:

```text
AppShell
  -> ChatPage
      -> reuse existing ChatWindow logic where possible
```

Old window logic can remain during migration. New page wrappers should reuse existing services and callbacks.

## Implementation Phases

### Phase 1

Create UI Architecture Design document.

### Phase 2

Create `AppShell`.

Scope:

- Sidebar
- Page Container
- Router

No business migration.

### Phase 3

Migrate Home.

### Phase 4

Migrate Settings.

### Phase 5

Migrate Chat.

### Phase 6

Migrate Library.

### Phase 7

Migrate Remote.

### Phase 8

Unify i18n and Theme.

### Phase 9

Remove old entry points after feature parity is confirmed.

## Risk Control

Do not change:

- Chat core logic.
- Conversation Storage.
- Memory Schema.
- Knowledge data structure.
- Remote security logic.

Each phase must be committed separately.

Each migration phase must test:

- Startup.
- Chat.
- Memory.
- Knowledge.
- Remote status.

## Stable Baseline

v2.6 must start from the v2.4.4 stable baseline and preserve the current module boundaries:

- `widgets/` for UI.
- `modules/` for business logic.
- `data/` for runtime data.
- `config/` for local configuration.
- `docs/` for planning and handoff documents.

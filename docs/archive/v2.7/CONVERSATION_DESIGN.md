# Project Aurora v2.7 Conversation Intelligence Design

## Baseline

Project Aurora v2.6.0 Stable is frozen. This document is a v2.7 design note
only and does not change chat or conversation runtime behavior.

Conversation Intelligence should build on the existing Chat, Conversation,
Memory, and Knowledge systems while preserving the v2.6 AppShell and Pages
Layer.

## Current Conversation System

The current conversation system includes:

- `modules/conversation.py`
- `modules/chat.py`
- `modules/search.py`
- `widgets/pages/chat_page.py`
- `widgets/chat_window.py`
- `widgets/conversation_browser.py`
- Runtime data under `data/conversations/`

Current capabilities include:

- JSON-backed conversation storage.
- Conversation list, load, save, rename, and delete behavior.
- Conversation metadata field support.
- Chat session support.
- Prompt assembly and prompt preview helpers.
- Context debug reporting.
- Conversation search.
- Integration points for memory and knowledge context.

The v2.7 design should add intelligence around conversations without breaking
the existing conversation JSON format.

## v2.7 Conversation Intelligence Goals

Goals:

- Make old conversations easier to find and continue.
- Generate useful conversation summaries.
- Track context quality and context sources.
- Improve continuation suggestions.
- Connect conversations to Memory and Knowledge in an auditable way.
- Preserve existing conversation storage compatibility.
- Keep automatic analysis visible and controllable.

Non-goals for the first phase:

- Do not replace ConversationManager in one large rewrite.
- Do not change the conversation file path without a migration plan.
- Do not silently rewrite past conversations.
- Do not require all intelligence features to ship in one stable release.

## Conversation Summary Design

Conversation summaries should help users resume work quickly.

Recommended summary types:

- Short title.
- One-paragraph summary.
- Key decisions.
- Open tasks.
- Mentioned files or modules.
- Related memory candidates.
- Related knowledge sources.

Recommended storage approach:

- Store summaries in the existing conversation `metadata` object as optional
  additive fields.
- Keep original messages unchanged.
- Allow summary regeneration without changing user-authored messages.

Example future metadata:

```json
{
  "summary": {
    "short": "v2.7 documentation planning",
    "details": "The conversation initialized design docs for the next cycle.",
    "decisions": ["Keep v2.6.0 as frozen baseline"],
    "open_tasks": ["Design Memory 2.0 implementation phases"],
    "updated_time": "2026-07-29T00:00:00+00:00",
    "source": "conversation_intelligence"
  }
}
```

## Context Quality Signals

Conversation Intelligence should help users understand what context Aurora is
using.

Recommended signals:

- Conversation length.
- Estimated token usage.
- Memory context count.
- Knowledge context count.
- Missing context warning.
- Stale memory warning.
- Stale knowledge index warning.
- Model mismatch warning.

These signals should be displayed as optional status or advanced diagnostics.
They should not interrupt the main chat flow unless a serious issue would
produce a bad answer.

## Continuation Suggestions

Continuation suggestions should help users resume work.

Possible suggestions:

- Continue last open task.
- Review unresolved decisions.
- Summarize this conversation.
- Save useful memory candidates.
- Search related knowledge.
- Create a follow-up checklist.

Suggestions must be user-controlled. Aurora should not automatically perform
destructive or privacy-sensitive actions from a suggestion.

## Memory Integration

Conversation Intelligence may propose memory candidates from conversations.

Recommended behavior:

- Extract candidates after meaningful user messages or on conversation save.
- Save candidates to a review queue, not directly to durable memory.
- Link candidate source to conversation metadata when available.
- Show candidate reason and source snippet in the Memory review UI.
- Respect Memory 2.0 sensitivity and temporary-content filters.

The user must approve, edit, or reject memory candidates before they become
active memories.

## Knowledge Integration

Conversation Intelligence may connect conversation turns to Knowledge sources.

Recommended behavior:

- Track which knowledge items were retrieved for a response.
- Store source references in conversation metadata when useful.
- Allow users to reopen related documents from the Library page.
- Show retrieval diagnostics in advanced views.

Knowledge source tracking should be additive and should not duplicate large
document content inside conversation files.

## Data Structure Suggestions

Existing conversation records should continue to load:

```json
{
  "id": "conversation-id",
  "title": "New Conversation",
  "created_time": "2026-07-29T00:00:00+00:00",
  "updated_time": "2026-07-29T00:00:00+00:00",
  "model": "model-name",
  "messages": [],
  "metadata": {}
}
```

Future optional metadata may include:

```json
{
  "metadata": {
    "summary": {
      "short": "Short summary",
      "details": "Longer summary",
      "decisions": [],
      "open_tasks": [],
      "updated_time": "2026-07-29T00:00:00+00:00"
    },
    "context": {
      "estimated_tokens": 3200,
      "memory_count": 3,
      "knowledge_count": 2,
      "warnings": []
    },
    "sources": {
      "memory_ids": [],
      "knowledge_ids": []
    },
    "intelligence": {
      "version": "2.0",
      "last_analyzed_time": "2026-07-29T00:00:00+00:00"
    }
  }
}
```

Compatibility rules:

- New metadata fields must be optional.
- Existing conversations with empty metadata must remain valid.
- Message arrays should not be rewritten for summary generation.
- Unknown metadata fields should be preserved when saving.

## UI Design

Default Chat page should stay focused:

- Conversation list.
- Current conversation.
- Model state.
- Input area.
- Send and stop actions.

Conversation Intelligence UI should be layered:

- Summary in the conversation sidebar or conversation details.
- Context quality indicators near advanced context tools.
- Continuation suggestions as user-triggered actions.
- Source and retrieval details in advanced diagnostics.

All new user-facing UI strings must use i18n keys in a future runtime phase.

## Privacy and Control

Conversation Intelligence may process sensitive user content, so user control is
required.

Rules:

- Do not silently store new durable memory.
- Do not expose private conversation content outside local storage.
- Make analysis status visible.
- Allow users to regenerate or clear generated summaries.
- Avoid storing unnecessary full source snippets in metadata.

## Risks

Incorrect summaries:

- Summaries may omit important nuance or invent decisions.
- Mitigation: keep summaries editable or regenerable and preserve original
  messages as the source of truth.

Privacy issues:

- Conversations may include sensitive personal or project data.
- Mitigation: keep processing local where practical, avoid unnecessary
  duplication, and require confirmation for durable memory.

Metadata bloat:

- Large summaries, snippets, or source traces may make conversation files heavy.
- Mitigation: store compact references and bounded summaries.

Context confusion:

- Aurora may over-trust stale memory or unrelated knowledge.
- Mitigation: add context quality warnings and retrieval diagnostics.

Storage compatibility:

- New metadata may break old readers if saved carelessly.
- Mitigation: use optional fields and preserve unknown metadata.

GUI responsiveness:

- Summarization and analysis may be slow.
- Mitigation: run analysis in background threads and show progress.

## Phase Recommendation

Recommended implementation sequence:

1. Define additive metadata schema.
2. Add summary generation behind a manual action.
3. Add context quality diagnostics.
4. Add memory candidate links.
5. Add knowledge source references.
6. Add continuation suggestions after summary behavior is stable.

Each phase should preserve existing conversation files and report checks
performed.

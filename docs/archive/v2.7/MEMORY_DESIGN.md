# Project Aurora v2.7 Memory 2.0 Design

## Baseline

Project Aurora v2.6.0 Stable is frozen. This document is a v2.7 design note
only and does not describe completed runtime changes.

Memory 2.0 should build on the existing v2.6 structure instead of replacing it.
The design must preserve the AppShell, Pages Layer, Windows Layer, i18n system,
theme system, and current runtime data paths unless a future migration phase is
explicitly approved.

## Current Memory System

The current Memory system includes:

- `modules/memory.py`
- `modules/memory_retrieval.py`
- `modules/search.py`
- `widgets/pages/memory_page.py`
- `widgets/memory_window.py`
- Runtime data under `data/memory/`

Current capabilities include:

- JSON-backed memory storage.
- Manual memory creation, update, delete, and enable/disable behavior.
- Candidate memory extraction through rule-based patterns.
- Pending candidate queue support.
- Candidate approval and rejection.
- Basic memory importance labels.
- Retrieval helpers for injecting relevant memories into chat context.
- Memory search support.

Current memory types include:

- `preference`
- `fact`
- `instruction`

The v2.7 design should treat these as compatibility types. New categories may
be layered on top, but existing records must continue to load correctly.

## v2.7 Memory 2.0 Goals

Memory 2.0 should make Aurora's long-term memory more useful, safer, and more
reviewable.

Goals:

- Improve automatic memory candidate extraction.
- Classify memories into clearer user-facing categories.
- Add a more transparent importance scoring model.
- Require user confirmation before durable memory changes.
- Support edit, delete, disable, and pin workflows.
- Preserve existing memory data compatibility.
- Make memory provenance visible enough for users to understand why a memory
  exists.
- Keep sensitive or temporary information out of durable memory by default.

Non-goals for the first Memory 2.0 phase:

- Do not replace the existing MemoryStore in one large rewrite.
- Do not move `data/memory/` without a migration plan.
- Do not silently save private or sensitive facts.
- Do not require every planned Memory 2.0 feature to ship in a single release.

## Automatic Memory Extraction

Automatic extraction should produce candidates, not permanent memories.

Recommended flow:

1. Chat messages are scanned after a conversation turn or at conversation save
   time.
2. Extractor proposes memory candidates with type, category, score, source, and
   explanation.
3. Sensitive and temporary candidates are filtered before they appear in the
   review queue.
4. Similar candidates are deduplicated against existing memories and pending
   candidates.
5. Candidates remain pending until the user approves, edits, rejects, or pins
   them.

Candidate extraction sources:

- Explicit user requests such as "remember that..."
- Preference statements.
- Repeated user behavior across conversations.
- Stable project information.
- Long-term user facts.

Extraction rules should remain conservative. It is better to miss a possible
memory than to save an incorrect or private memory.

## Memory Type Classification

Memory 2.0 should separate stable storage type from user-facing category.

Compatibility storage types:

- `preference`
- `fact`
- `instruction`

Recommended user-facing categories:

- User preference
- User habit
- Project information
- Long-term fact
- Communication style
- Environment detail
- Workflow instruction

Examples:

- User preference: preferred language, tone, editor, model, or output format.
- User habit: repeated workflow choices or review patterns.
- Project information: project name, architecture rule, release branch, or
  local constraint.
- Long-term fact: stable user or environment information.
- Communication style: preferred level of detail or structure.
- Environment detail: local OS, toolchain, or app-specific setup.
- Workflow instruction: durable instruction for how Aurora should behave.

The UI may group by category while the storage layer keeps the existing type
field for compatibility.

## Importance Scoring

Importance should be explainable and editable.

Recommended score range:

- `0-2`: low value
- `3-7`: normal value
- `8-10`: high value

Recommended scoring inputs:

- Explicitness: direct "remember" requests score higher.
- Stability: long-term facts score higher than temporary facts.
- Reuse value: information likely to improve future conversations scores
  higher.
- Sensitivity: private or credential-like content should be rejected or require
  stronger confirmation.
- Confidence: clear, unambiguous statements score higher.
- Recurrence: repeated compatible signals may increase score.
- User action: pinned or manually created memories score higher.

Importance labels:

- `low`
- `normal`
- `high`

Memory 2.0 should store both machine score and user-facing label only when a
future implementation phase explicitly adds the migration. Until then, design
work should respect existing `importance` values.

## User Confirmation

Durable memory writes should require user control.

Recommended candidate states:

- `pending`
- `approved`
- `rejected`
- `edited`
- `archived`

Recommended confirmation actions:

- Approve as-is.
- Edit and approve.
- Reject.
- Disable future similar suggestions.
- Pin as important.

Confirmation UI principles:

- Show what Aurora wants to remember.
- Show why it was suggested.
- Show source conversation metadata when available.
- Make reject and delete actions easy to find.
- Never hide memory creation behind a background process.

## Edit, Delete, Disable, and Pin

Memory 2.0 should support the following user actions:

- Edit content.
- Edit type or category.
- Change importance.
- Disable memory from retrieval without deleting it.
- Delete memory permanently.
- Pin memory so it is treated as high-priority context.

Recommended behavior:

- Editing updates `updated_time`.
- Deleting removes the memory from active storage after confirmation.
- Disabling keeps history but excludes the memory from retrieval.
- Pinning should be visible in the Memory page and retrieval diagnostics.

Pinned memories should not override safety rules. A pinned memory can still be
excluded if it is disabled or fails validation.

## Data Structure Suggestions

Existing records should continue to load:

```json
{
  "id": "memory-id",
  "type": "fact",
  "content": "User prefers concise release summaries.",
  "created_time": "2026-07-29T00:00:00+00:00",
  "updated_time": "2026-07-29T00:00:00+00:00",
  "importance": "normal",
  "enabled": true
}
```

Future Memory 2.0 records may add optional fields:

```json
{
  "id": "memory-id",
  "type": "preference",
  "category": "user_preference",
  "content": "User prefers concise release summaries.",
  "importance": "high",
  "importance_score": 8.5,
  "confidence": 0.92,
  "enabled": true,
  "pinned": false,
  "source": {
    "kind": "conversation",
    "conversation_id": "conversation-id",
    "message_ids": ["message-id"],
    "created_by": "memory_extractor"
  },
  "review": {
    "status": "approved",
    "approved_time": "2026-07-29T00:00:00+00:00"
  },
  "created_time": "2026-07-29T00:00:00+00:00",
  "updated_time": "2026-07-29T00:00:00+00:00"
}
```

Compatibility rules:

- New fields must be optional.
- Existing records without new fields must remain valid.
- Migration should be additive and reversible where practical.
- Unknown fields should not break list, edit, delete, or retrieval behavior.

## Retrieval Design

Memory retrieval should prefer relevant, enabled, high-confidence memories.

Recommended ranking inputs:

- Prompt similarity.
- Importance score.
- Pinned status.
- Recency of update.
- Category match.
- User confirmation state.

Retrieval diagnostics should be available in an advanced view and should show:

- Which memories were considered.
- Which memories were included.
- Which memories were skipped.
- Ranking factors.
- Context size contribution.

## Risks

Wrong memories:

- Aurora may extract a statement that was temporary, sarcastic, incomplete, or
  context-specific.
- Mitigation: keep extraction conservative, require confirmation, and show
  source context.

Privacy issues:

- Memory may capture sensitive personal, credential, health, financial, or
  private project information.
- Mitigation: filter sensitive patterns, require explicit approval for risky
  content, and make delete controls obvious.

Stale memories:

- Old facts may become incorrect.
- Mitigation: expose updated time, add review prompts for old high-impact
  memories, and allow disabling without deletion.

Over-personalization:

- Too many memories may make responses rigid or noisy.
- Mitigation: limit retrieval count, use importance scoring, and provide clear
  retrieval diagnostics.

Data compatibility:

- New fields may break old tools if added carelessly.
- Mitigation: use optional additive fields and keep existing keys stable.

GUI responsiveness:

- Extraction, scoring, and deduplication can become expensive.
- Mitigation: run expensive work in background threads and keep the UI
  responsive.

## Phase Recommendation

Recommended implementation sequence:

1. Document Memory 2.0 schema additions.
2. Add non-breaking candidate metadata.
3. Improve candidate review UI.
4. Add pin and category support.
5. Add retrieval diagnostics.
6. Add migration and compatibility checks.

Each phase should include static checks and honest reporting of untested parts.

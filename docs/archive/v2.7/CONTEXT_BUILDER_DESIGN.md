# Project Aurora v2.7 Context Builder Design

## Baseline

Project Aurora v2.6.0 Stable is frozen. This document is a v2.7 design note
only and does not implement a runtime module.

Context Builder is the proposed context assembly layer before Aurora sends a
request to an LLM. It should connect existing Persona, Memory, Knowledge /
RAG, Conversation History, and current User Input without owning their durable
data.

## 1. Current Context Flow Analysis

In v2.6, context is already assembled from multiple sources, but the assembly
responsibility is spread across chat-related functions.

Current sources:

- System Prompt
- Persona
- Memory
- Knowledge
- Conversation
- User Message

Current flow:

1. The chat session owns a system context.
2. Persona context is loaded when persona is enabled.
3. Memory retrieval selects relevant memories from stored memory records.
4. Knowledge retrieval selects relevant knowledge items from the Knowledge
   Store.
5. Conversation messages remain in the chat session or conversation history.
6. The current user message is appended and sent to the model.
7. Prompt preview and Context Inspector helpers summarize the assembled
   sections.

Existing useful foundations:

- `modules/chat.py` has prompt assembly, prompt preview, token estimate, and
  context debug helpers.
- Memory retrieval is already separate from memory storage.
- Knowledge retrieval has vector search with keyword fallback.
- Persona has a context-building responsibility.
- Conversation storage already supports metadata.

Current issues:

- Context assembly is partly embedded in UI-level code.
- The order, limits, diagnostics, and fallback behavior are not centralized.
- Memory, Knowledge, Persona, and Conversation can become tightly coupled to
  Chat Page as v2.7 grows.
- Long context handling is limited to warning and preview behavior.
- Debug payloads and final prompt assembly may drift if multiple surfaces build
  context independently.

## 2. Context Builder Responsibilities

Context Builder should be a narrow orchestration layer.

It should be responsible for:

- Collecting context sources through clear inputs.
- Controlling context injection order.
- Formatting prompt sections consistently.
- Applying token and length budgets.
- Selecting or trimming low-priority context.
- Including conversation summaries when needed.
- Returning diagnostics for Context Inspector and debug views.
- Providing one unified interface for chat send, prompt preview, and future
  clients.

It should not be responsible for:

- Managing Memory data.
- Approving, editing, deleting, or saving Memory records.
- Managing Knowledge files.
- Building or repairing vector indexes.
- Saving Conversation records.
- Mutating Persona data.
- Directly controlling UI.
- Calling the LLM directly.
- Performing long-running embedding, indexing, or summarization work inline.

The key rule: Context Builder assembles context; it does not own durable data.

## 3. Input and Output Design

### Inputs

Recommended input fields:

```json
{
  "system_rules": "Base system behavior and non-overridable rules.",
  "persona": {
    "enabled": true,
    "name": "Aurora",
    "context": "Persona context text."
  },
  "memory_items": [],
  "knowledge_results": [],
  "conversation_history": [],
  "conversation_summary": null,
  "user_message": "Current user request.",
  "settings": {
    "max_context_tokens": 6000,
    "max_memory_items": 5,
    "max_knowledge_items": 3,
    "preview_limit": 4000
  }
}
```

Inputs should be plain data, not UI objects. Stores and managers may prepare
the inputs, but Context Builder should not depend on page or window classes.

### Outputs

Recommended output: a Prompt Package.

```json
{
  "messages": [
    {
      "role": "system",
      "content": "System, persona, memory, and knowledge context."
    },
    {
      "role": "user",
      "content": "Current user request."
    }
  ],
  "sections": [],
  "final_prompt": "Readable final prompt preview.",
  "diagnostics": {
    "estimated_tokens": 3200,
    "warnings": [],
    "included": [],
    "excluded": []
  },
  "source_refs": {
    "memory_ids": [],
    "knowledge_ids": [],
    "conversation_id": ""
  }
}
```

Field recommendations:

- `messages`: model-ready message list.
- `sections`: structured context sections for preview and debugging.
- `final_prompt`: optional text preview for current UI behavior.
- `diagnostics`: token use, trimming decisions, warnings, and source reasons.
- `source_refs`: compact references for future Conversation Intelligence.

Extensibility:

- New sources should be added as optional sections.
- Unknown diagnostic fields should be ignored by older UI.
- Output should support both chat send and preview without separate builders.

## 4. Context Priority Design

Recommended order:

```text
System
  -> Persona
  -> Memory
  -> Knowledge
  -> Conversation
  -> Current User Message
```

Why this order:

- System rules define non-overridable application behavior and safety.
- Persona shapes assistant voice and identity but must not override system
  rules.
- Memory provides durable user or project context that should influence
  interpretation.
- Knowledge provides source-backed facts relevant to the current request.
- Conversation history preserves local continuity.
- Current User Message is the immediate instruction and should remain closest
  to the model's response target.

Non-overridable content:

- System rules.
- Safety and privacy constraints.
- Explicit current user instruction, unless it conflicts with system rules.

Conflict handling:

- System rules win over all lower-priority context.
- Current user message wins over older conversation history when the conflict is
  about the current task.
- Approved Memory should win over stale inferred summaries.
- Knowledge should be treated as source evidence, not as instruction unless the
  user explicitly asks to follow it.
- Persona should never override user safety, project rules, or runtime
  constraints.

When conflict is detected, Context Builder should include a diagnostic warning
rather than silently hiding the issue.

## 5. Relationship with Other Modules

### ConversationManager

ConversationManager should provide saved messages and optional metadata.

Context Builder may read:

- Conversation history.
- Conversation summary.
- Conversation source references.

Context Builder should not:

- Save conversations.
- Rename conversations.
- Delete conversations.
- Rewrite message history.

### MemoryManager or MemoryStore

Memory should provide approved and enabled memory items.

Context Builder may receive:

- Retrieved memory items.
- Memory ids.
- Importance and pinned state.
- Optional source metadata.

Context Builder should not:

- Approve memory candidates.
- Save new memories.
- Edit or delete memories.
- Run durable memory migrations.

### KnowledgeManager or KnowledgeStore

Knowledge should provide retrieval results and source metadata.

Context Builder may receive:

- Knowledge snippets.
- Source ids.
- Retrieval scores.
- Index health warnings.

Context Builder should not:

- Add files.
- Parse documents.
- Generate embeddings.
- Rebuild vector indexes.
- Repair metadata.

### RetrievalManager

A future RetrievalManager may coordinate Memory and Knowledge retrieval before
Context Builder runs.

Recommended relationship:

- RetrievalManager selects relevant evidence.
- Context Builder decides how to fit selected evidence into the final prompt
  package.

If RetrievalManager does not exist yet, Chat Page or a thin service can prepare
retrieval inputs while Context Builder remains pure assembly logic.

### Persona System

Persona should provide formatted persona context.

Context Builder may receive:

- Persona enabled state.
- Persona name.
- Persona prompt or context text.

Context Builder should not:

- Mutate persona files.
- Decide persona configuration.
- Store user facts inside persona.

## 6. Long Context Handling

Context Builder should have explicit budget behavior.

Recommended controls:

- `max_context_tokens`
- `max_system_tokens`
- `max_persona_tokens`
- `max_memory_tokens`
- `max_knowledge_tokens`
- `max_conversation_tokens`
- `max_user_tokens`

Recommended strategy:

1. Always preserve System.
2. Preserve Current User Message.
3. Preserve essential Persona within a bounded size.
4. Include high-priority approved Memory.
5. Include top Knowledge snippets with source references.
6. Include recent conversation turns.
7. Insert conversation summary when history is too long.
8. Drop or trim lower-priority context first.

History compression:

- Preserve original conversation messages in storage.
- Use optional summaries for older history.
- Keep recent turns verbatim when budget allows.
- Prefer summaries for distant history.
- Record whether compression was used in diagnostics.

Important information retention:

- Keep pinned Memory before normal Memory.
- Keep user-confirmed Memory before inferred summaries.
- Keep Knowledge snippets with stronger retrieval scores.
- Keep explicit current task instructions.

Low-priority eviction:

- Disabled Memory.
- Stale Knowledge results.
- Low-score retrieval results.
- Older conversation turns already covered by summary.
- Repetitive context sections.

Diagnostics should report what was removed and why.

## 7. Future Extension Direction

### Multi-model Support

Different models may need different message formats, token budgets, or system
prompt handling.

Recommended extension:

- Add model profile settings to Context Builder input.
- Keep provider-specific conversion at the edge of chat sending.

### Different Persona

Aurora may support multiple personas or mode-specific personas.

Recommended extension:

- Treat persona as an input object.
- Keep persona selection outside Context Builder.
- Include persona id in diagnostics.

### Multi-user

Multi-user support would require user-scoped Memory, Conversation, Persona, and
Knowledge access.

Recommended extension:

- Add optional `user_id` or profile scope to input metadata.
- Do not mix user-scoped memories by default.

### Voice Assistant

Voice mode may need shorter context, more recent history, and lower latency.

Recommended extension:

- Add a mode field such as `chat`, `voice`, or `mobile`.
- Use mode-specific token budgets and formatting.

### Mobile Client

Mobile clients may need compact diagnostics and smaller prompt previews.

Recommended extension:

- Return full diagnostics internally.
- Let UI clients choose how much to display.

## 8. Risk Analysis

Context too long:

- The model may ignore important content or fail due to token limits.
- Mitigation: enforce budgets, compress history, and report trimming.

Wrong Memory injection:

- Incorrect or stale memories may bias the response.
- Mitigation: use only approved and enabled memories, prefer pinned and
  high-confidence records, and show memory diagnostics.

Knowledge contamination:

- Irrelevant or stale documents may pollute answers.
- Mitigation: use retrieval scores, health status, source references, and
  keyword fallback diagnostics.

Prompt conflicts:

- System, Persona, Memory, Knowledge, Conversation, and User Message may
  disagree.
- Mitigation: define priority order and emit conflict warnings.

Performance issues:

- Retrieval, formatting, token estimation, and diagnostics may slow chat.
- Mitigation: keep Context Builder lightweight, run expensive retrieval or
  summarization outside the UI thread, and cache safe intermediate results.

Over-design:

- A large generic context framework may slow v2.7 without clear benefit.
- Mitigation: start with a small Prompt Package interface and add fields only
  when a phase needs them.

## Implementation Phasing Recommendation

Phase 1:

- Keep this as design documentation only.
- Define Prompt Package and section shape.

Phase 2:

- Extract existing context assembly from UI-level code into a narrow module.
- Preserve existing prompt behavior.
- Keep existing Context Inspector output compatible.

Phase 3:

- Add token budget enforcement and diagnostics.
- Add compression hooks without rewriting conversations.

Phase 4:

- Connect Conversation Intelligence summaries.
- Add source reference metadata.

Phase 5:

- Add model profile and mode-specific context budgets.

Each implementation phase should be small, tested, and compatible with the
v2.6 stable structure.

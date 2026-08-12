# Project Aurora v2.7 Architecture Review

## Baseline

Project Aurora v2.6.0 Stable is frozen. This review is documentation-only and
does not approve runtime code changes by itself.

The review scope covers whether the v2.6 architecture can support the v2.7
planning direction:

- Memory 2.0
- Knowledge / RAG 2.0
- Conversation Intelligence

The recommended approach is incremental extension of the existing structure,
not a large rewrite.

## 1. v2.6 Architecture Compatibility Check

### AppShell

Status: compatible.

The AppShell provides the main navigation and content frame. It can support
v2.7 because Memory, Library / Knowledge, Chat, Persona, Remote, and Settings
already have separated page destinations.

Recommended use in v2.7:

- Keep AppShell responsible only for navigation and page hosting.
- Do not place Memory, RAG, or Conversation Intelligence logic in AppShell.
- Add status indicators only through page-owned or shared component contracts.

Potential issue:

- If v2.7 adds many intelligence indicators directly to global navigation,
  AppShell may become a mixed orchestration layer.

Recommendation:

- Keep intelligence state inside feature pages and expose only compact status
  summaries to AppShell when necessary.

### Pages Layer

Status: compatible.

The Pages Layer can support v2.7 because each major feature has a natural page:

- Memory 2.0 belongs primarily to Memory Page.
- Knowledge / RAG 2.0 belongs primarily to Library Page.
- Conversation Intelligence belongs primarily to Chat Page and conversation
  browser surfaces.

Recommended use in v2.7:

- Keep default page views focused on normal user workflows.
- Put diagnostics and advanced controls behind page-level advanced sections.
- Use pages as UI controllers, not as durable data owners.

Potential issue:

- Memory review, retrieval diagnostics, index health, and conversation summary
  tools may make pages too dense.

Recommendation:

- Keep advanced sections collapsed by default and move focused workflows to
  Windows Layer when a dialog is more appropriate.

### Windows Layer

Status: compatible.

The Windows Layer can support focused v2.7 workflows such as:

- Memory candidate review.
- Memory edit details.
- Knowledge rebuild confirmation.
- Retrieval diagnostics.
- Conversation summary review.

Recommended use in v2.7:

- Keep windows focused and short-lived.
- Do not move whole page workflows back into standalone windows.
- Do not duplicate page state ownership inside windows.

Potential issue:

- Existing legacy windows may overlap with page workflows.

Recommendation:

- Preserve compatibility first. Retire or simplify old window entry points only
  after feature parity is proven.

### Modules

Status: compatible with careful boundary control.

The current modules already include memory, memory retrieval, knowledge,
retrieval, embedding, conversation, chat, search, persona, settings, i18n, and
theme support.

Recommended use in v2.7:

- Extend current modules in small phases.
- Add thin manager modules only when coordination logic becomes shared across
  pages or features.
- Avoid duplicating existing store classes.

Potential issue:

- Memory, Knowledge, Conversation, and Chat may start calling each other
  directly as v2.7 features grow.

Recommendation:

- Introduce a small context coordination layer only when needed, with clear
  read-only boundaries for retrieval and prompt assembly.

### Locales

Status: compatible.

The i18n system and `locales/zh_CN.json` / `locales/en_US.json` structure can
support v2.7 UI expansion.

Recommended use in v2.7:

- Add all user-facing strings through i18n keys.
- Keep zh_CN and en_US key sets aligned.
- Do not reintroduce legacy `TEXT` dictionaries.

Potential issue:

- Large UI phases may add many keys and drift between locales.

Recommendation:

- Add locale keys in the same runtime phase as the UI change and run the i18n
  check after each phase.

### Data

Status: compatible with additive schema changes.

The current data directories can support v2.7 if schemas evolve additively:

- `data/memory/`
- `data/knowledge/`
- `data/conversations/`
- `data/persona/` where relevant
- `data/remote/` where relevant

Recommended use in v2.7:

- Keep existing paths stable.
- Add optional fields rather than replacing records.
- Version backup formats when import/export behavior changes.

Potential issue:

- Memory, Knowledge, and Conversation metadata can grow quickly if source
  traces and summaries are stored too aggressively.

Recommendation:

- Store compact references and bounded summaries. Avoid duplicating large
  document or conversation content across data files.

## 2. Memory 2.0 Architecture Review

### Should Memory Be Independently Modularized?

Current recommendation: yes, but incrementally.

Memory should remain an independent domain because it owns durable user memory,
candidate review, importance, enablement, deletion, and retrieval eligibility.
The current `modules/memory.py` and `modules/memory_retrieval.py` split is a
reasonable baseline.

Recommended direction:

- Keep `MemoryStore` as the compatibility storage boundary.
- Keep retrieval ranking separate from storage.
- Add a thin manager only if candidate review, scoring, pinning, and provenance
  begin to spread across UI and chat code.

Avoid:

- Moving memory extraction into ConversationManager.
- Letting Chat Page write durable memories directly.
- Creating a second memory storage format without migration.

### Boundary with Conversation

Conversation should own messages, titles, conversation metadata, and save/load
behavior.

Memory should own durable memory records and pending memory candidates.

Recommended boundary:

- Conversation may provide source messages for candidate extraction.
- Memory may store source references back to conversation ids.
- Conversation should not decide whether a candidate becomes durable memory.
- Memory should not rewrite conversation messages.

Potential issue:

- Automatic memory extraction can blur the boundary if it runs inside chat save
  logic and writes directly to memory.

Recommendation:

- Treat extraction as candidate generation. Durable memory writes require Memory
  review actions.

### Relationship with Persona

Persona represents the assistant's identity, tone, and behavior profile.
Memory represents user-specific or project-specific durable facts.

Recommended boundary:

- Persona can influence how Aurora speaks.
- Memory can inform what Aurora remembers about the user or project.
- Persona should not store user facts.
- Memory should not mutate persona prompts implicitly.

Potential issue:

- User communication preferences may look like either memory or persona.

Recommendation:

- Store user-specific preferences in Memory and let Persona read them as
  context only when building a response.

### Difference from Knowledge

Knowledge is document-backed reference material. Memory is curated durable
personal or project context.

Recommended boundary:

- Memory records are short, user-reviewed, and high-signal.
- Knowledge records are document-backed, searchable, and source-oriented.
- Memory retrieval should return compact facts.
- Knowledge retrieval should return source snippets or document references.

Potential issue:

- Project facts may fit both Memory and Knowledge.

Recommendation:

- Store stable, short project facts in Memory only when user-confirmed. Store
  source documents and larger reference material in Knowledge.

### Data Storage Risk

Current recommendation:

- Keep JSON-backed storage for v2.7 foundation work.
- Add optional fields for category, score, pin state, confidence, and source
  metadata only when implementation begins.
- Avoid a database migration until there is a concrete scaling need.

Potential problems:

- JSON files can become harder to merge, repair, or query as memory count grows.
- Candidate queues may accumulate stale pending items.
- Sensitive data may persist if filtering or review is weak.

Future extension direction:

- Add memory compaction and review aging.
- Add schema validation.
- Add export/import safeguards.
- Consider an indexed store only after JSON limits are measured.

## 3. Knowledge / RAG 2.0 Architecture Review

### Independent Knowledge Management Layer

Current recommendation: keep KnowledgeStore, consider a thin manager later.

The current KnowledgeStore already owns file ingestion, metadata, vector index,
health, backups, and repair. That is acceptable for the current scale, but RAG
2.0 may introduce enough orchestration to justify a small management layer.

Recommended direction:

- Keep file and metadata persistence in KnowledgeStore.
- Keep embedding provider access separate.
- Keep retrieval ranking separate.
- Add a knowledge manager only when a workflow must coordinate ingestion,
  parsing, chunking, embedding, health, and UI progress.

Avoid:

- A large replacement of KnowledgeStore.
- Mixing GUI progress logic into KnowledgeStore.
- Making vector retrieval the only retrieval path.

### Embedding Flow

Current embedding flow is reasonable:

- Validate record.
- Generate embedding through provider.
- Save vector with model, dimensions, hash, and timestamp.
- Mark stale or invalid vectors through health checks.

Recommended improvements:

- Keep provider errors visible.
- Keep keyword fallback available.
- Run embedding work in background threads.
- Store enough metadata to know whether vectors are stale.

Potential issue:

- Whole-document embedding may be too coarse for larger documents.

Recommendation:

- Add chunk-level indexing in a later phase after current diagnostics and
  health checks are stable.

### Should Retrieval Be Independent?

Current recommendation: yes.

Retrieval should remain independent from both storage and UI. The current
retrieval modules are useful boundaries because they allow Knowledge, Memory,
and Chat to evolve without embedding ranking logic into pages.

Recommended direction:

- Keep keyword and vector ranking out of UI code.
- Return explanation metadata for diagnostics.
- Let a future retrieval manager coordinate memory and knowledge retrieval for
  context building.

Potential issue:

- Memory retrieval and Knowledge retrieval may diverge in diagnostics and
  ranking conventions.

Recommendation:

- Standardize result shapes gradually, without forcing one generic model too
  early.

### Metadata Design

Metadata should stay additive and source-oriented.

Recommended fields:

- Existing record identity and file fields remain stable.
- Embedding status remains explicit.
- Future tags, summaries, language, chunk count, and parser version should be
  optional.
- Backup format changes should be versioned.

Potential issue:

- Storing full extracted content, summaries, chunks, and vectors in one file can
  make metadata heavy.

Recommendation:

- Keep document metadata, chunk metadata, and vector index separable if chunking
  is introduced.

### Connection to Conversation Context

Knowledge should connect to conversation through retrieval results, not through
direct conversation mutation.

Recommended boundary:

- Chat or a future context builder asks Knowledge for relevant records.
- Knowledge returns snippets, ids, scores, and diagnostics.
- Conversation metadata may store compact source references.
- Conversation files should not duplicate large knowledge content.

Potential issue:

- If source references are not tracked, users cannot audit why an answer used a
  document.

Recommendation:

- Add source ids and retrieval diagnostics as optional metadata in a later
  Conversation Intelligence phase.

## 4. Conversation Intelligence Architecture Review

### Current Conversation Manager Responsibility

ConversationManager currently owns JSON-backed conversation persistence:

- list
- load
- save
- rename
- delete
- metadata preservation

Current recommendation:

- Keep ConversationManager focused on persistence.
- Do not turn it into a summarizer, retrieval orchestrator, or memory writer.

Potential issue:

- Adding summary, context quality, and source tracking directly into
  ConversationManager would make it too broad.

Recommendation:

- Add intelligence behavior in a separate service or manager while storing only
  optional results in conversation metadata.

### Where Automatic Summary Should Live

Current recommendation:

- Automatic or manual summaries should live in a conversation intelligence
  service, not in ConversationManager.

Possible future module:

- `modules/conversation_intelligence.py`

Responsibilities:

- Generate or refresh summaries.
- Extract decisions and open tasks.
- Produce context quality signals.
- Return metadata updates for ConversationManager to save.

Potential issue:

- "Automatic" summaries can surprise users and slow down chat.

Recommendation:

- Start with manual summary generation. Add automatic background summaries only
  after user control and progress reporting are clear.

### Long Context Compression

Current recommendation:

- Treat long context compression as a context-building concern, not raw
  conversation storage.

Possible future module:

- `modules/context_builder.py`

Responsibilities:

- Estimate token budget.
- Select recent messages.
- Include approved memory context.
- Include selected knowledge snippets.
- Include conversation summary when needed.
- Produce debug information for advanced UI.

Potential issue:

- Compressing and rewriting old messages would risk data loss.

Recommendation:

- Preserve original messages. Store optional summaries separately and use them
  during prompt assembly.

### Memory Injection Timing

Recommended timing:

- Retrieve memory at prompt build time.
- Use only approved and enabled memories.
- Consider pinned memories and importance scoring.
- Show injected memories in advanced context diagnostics.

Avoid:

- Injecting memory into stored conversation messages.
- Saving candidate memories directly during injection.

### Knowledge Retrieval Timing

Recommended timing:

- Retrieve knowledge at prompt build time, after the user prompt is known.
- Prefer vector search when healthy.
- Fall back to keyword retrieval when vectors are unavailable.
- Store compact source references only after response generation if source
  tracking is implemented.

Avoid:

- Running expensive indexing during send unless explicitly requested.
- Blocking chat UI while retrieval or embedding work runs.

## 5. Module Boundary Recommendations

The v2.6 structure is already close to the recommended v2.7 direction. New
modules should be added only when coordination logic becomes shared or too large
for existing modules.

Recommended near-term structure:

```text
modules/
  memory.py
  memory_retrieval.py
  knowledge.py
  retrieval.py
  embedding.py
  conversation.py
  chat.py
  persona.py
```

Possible future additions:

```text
modules/
  memory_manager.py
  knowledge_manager.py
  conversation_intelligence.py
  retrieval_manager.py
  context_builder.py
```

Recommended responsibilities:

- `memory_manager.py`: coordinate candidate review, scoring, pinning, and
  provenance while preserving MemoryStore compatibility.
- `knowledge_manager.py`: coordinate ingestion, chunking, indexing, health, and
  repair workflows while preserving KnowledgeStore compatibility.
- `conversation_intelligence.py`: generate summaries, decisions, open tasks,
  and context quality signals.
- `retrieval_manager.py`: normalize retrieval across Memory and Knowledge only
  when shared diagnostics and result shapes are needed.
- `context_builder.py`: assemble prompt context from conversation, persona,
  memory, knowledge, and token budget rules.

Recommended dependency direction:

```text
UI Pages / Windows
  -> managers or existing stores
  -> stores / retrieval helpers / providers
  -> data files
```

Preferred context flow:

```text
Chat Page
  -> context_builder
  -> ConversationManager
  -> Memory retrieval
  -> Knowledge retrieval
  -> Persona
  -> chat prompt assembly
```

Rules:

- Stores should not import UI.
- Retrieval helpers should not write durable data.
- ConversationManager should not approve memories.
- Memory should not mutate persona.
- Knowledge should not rewrite conversations.
- Context Builder should assemble context, not own durable data.

## 6. Risk List

### Architecture Risks

- Feature coordination may accumulate inside Chat Page or AppShell.
- ConversationManager may become too broad if summary and context logic are
  added directly.
- Retrieval code may fragment between Memory and Knowledge.
- Legacy windows and new pages may diverge in behavior.

Mitigation:

- Add thin managers only where coordination is shared.
- Keep persistence, retrieval, context assembly, and UI separated.
- Retire old workflows only after feature parity is confirmed.

### Data Risks

- Additive metadata may still create compatibility issues if unknown fields are
  dropped during save.
- Conversation summaries and source traces may duplicate sensitive content.
- Knowledge metadata and vector index files may become large or stale.
- Memory candidates may store private or incorrect facts.

Mitigation:

- Preserve unknown metadata.
- Store compact references instead of large copied content.
- Keep schema additions optional.
- Require review for durable memory writes.

### Performance Risks

- Embedding, indexing, summary generation, and retrieval diagnostics can block
  the GUI if run on the main thread.
- Large documents may make whole-document retrieval slow or low quality.
- Long conversations may make context assembly expensive.

Mitigation:

- Use background threads for expensive operations.
- Add progress states and cancellation where practical.
- Introduce chunking only after diagnostics are stable.
- Keep prompt context bounded.

### Maintenance Risks

- Multiple managers may become over-designed if added too early.
- Locale keys may drift between zh_CN and en_US.
- Similar concepts may be represented differently across Memory, Knowledge, and
  Conversation metadata.

Mitigation:

- Start with current modules and add managers only when needed.
- Run i18n checks in UI phases.
- Standardize diagnostics gradually.

### Future Extension Risks

- A future database migration may be harder if JSON schemas are not documented.
- Retrieval ranking may need cross-feature normalization.
- Advanced AI features may need user privacy controls before release.
- Backup formats may need versioning if vector or chunk data is added.

Mitigation:

- Document schema changes before implementation.
- Keep migration plans separate and explicit.
- Preserve keyword fallback and source auditability.
- Version backup format changes.

## Overall Recommendation

The v2.6 architecture can support v2.7 if development remains incremental.

Recommended path:

1. Preserve AppShell, Pages Layer, Windows Layer, i18n, theme, and current data
   paths.
2. Keep existing stores as compatibility boundaries.
3. Add optional metadata only in scoped implementation phases.
4. Introduce thin manager modules only when shared coordination becomes
   necessary.
5. Build a context builder before context assembly spreads across pages,
   chat, memory, and knowledge modules.
6. Keep advanced diagnostics available but outside default user workflows.

The strongest immediate architecture candidate is `context_builder.py`, because
v2.7 Memory, Knowledge, Persona, and Conversation Intelligence all converge at
prompt assembly time. It should be introduced only when runtime implementation
begins and only with a narrow responsibility: assemble context and diagnostics
without owning durable data.

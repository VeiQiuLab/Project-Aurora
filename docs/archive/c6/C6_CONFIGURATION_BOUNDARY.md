# C6 Configuration Boundary

## Purpose

This document defines future configuration boundaries for C6. It does not
change runtime behavior, default values, the settings schema, or data files.

## Current Configuration Entry

Aurora currently uses `modules/settings.py` and `config/settings.json`.

Existing access should remain the only runtime configuration path:

- `settings.get("section.key", default)` for reads
- `settings.set(...)` and `settings.update_many(...)` for explicit writes
- `Settings.default_settings` for safe defaults and missing-key recovery

C6 core modules should not import or access the global settings object directly.
Future integration layers should read configuration and inject plain values into
core module calls.

## Future Boundaries

### RAG

Potential future keys:

- `rag.retrieval_limit`
- `rag.deduplication_enabled`
- `rag.ranking_strategy`
- `rag.ranking_weights`

Consumers:

- Retrieval integration layer
- RAG orchestrator

Core modules remain usable with their current safe defaults.

### Context

Potential future keys:

- `context.max_tokens`
- `context.section_budget`
- `context.trim_limit`
- `context.recent_message_limit`

Consumers:

- Context integration layer
- `ContextOptimizer` adapter

`ContextBuilder` remains responsible for assembly only.

### Memory

Existing related settings:

- `memory.max_injection`
- `memory.min_importance`

Potential future keys:

- `memory.confidence_threshold`
- `memory.analysis_enabled`

Consumers:

- Memory pipeline adapter
- Candidate review flow

`MemoryIntelligence` should continue to accept explicit parameters and defaults.

### Conversation

Potential future keys:

- `conversation.analysis_enabled`
- `conversation.analysis_trigger`
- `conversation.analysis_debounce_seconds`

Consumers:

- Conversation pipeline adapter

The storage and analysis core should not read configuration directly.

## Configuration Rules

1. Keep safe defaults in core APIs.
2. Inject configuration from an integration boundary.
3. Keep configuration declarative; business logic belongs in modules.
4. Do not migrate existing JSON data for future configuration keys.
5. Add new keys only when a pipeline integration requires them.
6. Preserve unknown settings during load and default merging.
7. Keep ranking weights, budgets, and thresholds independently configurable.

## C6 Integration Sequence

1. Define the integration-layer defaults.
2. Read settings at the integration boundary.
3. Validate and normalize values before injection.
4. Call the existing core module with explicit values.
5. Record effective configuration in diagnostics when debug tracing is enabled.

No step in this document is enabled by the current phase.

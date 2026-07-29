# Project Aurora v2.7 Knowledge / RAG 2.0 Design

## Baseline

Project Aurora v2.6.0 Stable is frozen. This document is a v2.7 design note
only and does not modify Knowledge runtime behavior.

Knowledge / RAG 2.0 should extend the existing KnowledgeStore, retrieval,
embedding, and Library page structure without replacing the v2.6 architecture.

## Current Knowledge System

The current Knowledge system includes:

- `modules/knowledge.py`
- `modules/retrieval.py`
- `modules/embedding.py`
- `modules/search.py`
- `widgets/pages/library_page.py`
- `widgets/knowledge_window.py`
- Runtime data under `data/knowledge/`

Current capabilities include:

- Local file-backed knowledge storage.
- Metadata JSON for knowledge records.
- Stored source files under the knowledge data directory.
- Supported file types for adding files: `.txt`, `.md`, `.pdf`.
- Readable text retrieval for text and Markdown files.
- PDF storage with limited preview support.
- Keyword retrieval fallback.
- Vector index support.
- Embedding generation through an Ollama embedding provider.
- Vector health checks for missing, stale, invalid, and orphaned entries.
- Backup import and export.
- Metadata repair.

The current system already has important foundations for RAG 2.0. v2.7 should
focus on quality, observability, and safer workflows before expanding file
support aggressively.

## v2.7 Knowledge / RAG 2.0 Goals

Goals:

- Improve retrieval quality and explainability.
- Make vector index health easier to understand.
- Support safer rebuild and repair workflows.
- Improve document metadata visibility.
- Provide clearer diagnostics for retrieval failures.
- Preserve existing knowledge metadata and file compatibility.
- Keep advanced retrieval tools out of the default user workflow.
- Keep expensive indexing work off the GUI thread.

Non-goals for the first RAG 2.0 phase:

- Do not replace KnowledgeStore in one large rewrite.
- Do not move `data/knowledge/` without a migration plan.
- Do not require every supported document format to be fully parsed in one
  release.
- Do not make vector retrieval mandatory when keyword retrieval can provide a
  safe fallback.

## RAG Pipeline Design

Recommended RAG 2.0 pipeline:

1. Ingest source document.
2. Normalize metadata.
3. Extract or read text content.
4. Validate retrievability.
5. Build or refresh embedding.
6. Store vector entry with content hash and model metadata.
7. Search by vector when available.
8. Fall back to keyword retrieval when vector retrieval is unavailable.
9. Format selected snippets for chat context.
10. Expose retrieval diagnostics in an advanced view.

The system should make each step observable enough to explain why a document
was or was not used.

## Document Metadata

Existing metadata should remain compatible.

Current fields include areas such as:

- `id`
- `file_name`
- `file_type`
- `stored_name`
- `file_size`
- `added_time`
- `updated_time`
- `enabled`
- `character_count`
- `source_path`
- `stored_path`
- `status`
- `embedding_status`
- `embedding_model`
- `embedding_updated_time`
- `embedding_dimensions`
- `content`

Possible future optional fields:

- `title`
- `summary`
- `tags`
- `language`
- `chunk_count`
- `last_retrieved_time`
- `retrieval_count`
- `source_hash`
- `parser_version`
- `privacy_level`

Compatibility rules:

- Existing metadata records must continue to load.
- New fields must be optional.
- Unknown fields should not break listing, preview, retrieval, backup, or
  import behavior.
- Backup format changes require explicit version handling.

## Chunking Design

RAG 2.0 may need chunk-level retrieval instead of whole-document retrieval.

Recommended chunk metadata:

```json
{
  "chunk_id": "chunk-id",
  "document_id": "knowledge-id",
  "index": 0,
  "text": "Chunk content",
  "character_start": 0,
  "character_end": 1200,
  "content_hash": "sha256",
  "embedding_status": "Indexed"
}
```

Chunking principles:

- Keep chunks stable when source text has not changed.
- Store document-level metadata separately from chunk-level vectors.
- Prefer readable snippet boundaries.
- Avoid over-small chunks that lose context.
- Avoid over-large chunks that crowd chat context.

Chunking can be a later phase. The first v2.7 implementation may improve
diagnostics and health checks before introducing chunk storage.

## Retrieval Quality

RAG 2.0 should rank results using multiple signals.

Recommended ranking inputs:

- Vector similarity.
- Keyword match.
- Document enabled state.
- Document health status.
- Staleness of embedding.
- Recency of update.
- User tags or selected scope.
- Minimum similarity threshold.

Retrieval should return both results and explanation metadata for diagnostics.

Possible diagnostic fields:

- Query text.
- Retrieval mode.
- Candidate count.
- Selected count.
- Fallback reason.
- Score per result.
- Snippet location.
- Excluded records with reason.

## Index Health

The current vector index health foundation should become a clearer user-facing
advanced tool.

Health states:

- Healthy
- Missing index
- Not indexed
- Stale
- Invalid vector
- Orphaned vector
- Unavailable for retrieval
- Rebuild recommended

Recommended health actions:

- Refresh status.
- Rebuild selected item.
- Rebuild all eligible items.
- Remove orphaned vectors.
- Repair metadata.
- Export backup before repair.

Safety rules:

- Rebuild and repair must run in background threads.
- Destructive repair should require confirmation.
- Failed embedding calls should not corrupt existing metadata.
- Keyword retrieval should remain available when vector index is unhealthy.

## Backup and Restore

Knowledge / RAG 2.0 should preserve existing backup behavior and make the
limits clear.

Recommended backup contents:

- Knowledge metadata.
- App version.
- Backup format version.
- Exported time.
- Relevant configuration summary.
- Optional future vector index metadata.

Open questions for future phases:

- Whether vector embeddings should be included in backups.
- Whether stored source files should be included or only metadata.
- Whether large backups need compression.

Any backup format change must be versioned and tested with import compatibility.

## UI Design

Default Library page should stay focused:

- Document list.
- Add file.
- Preview.
- Enable or disable.
- Search.

Advanced Library tools may include:

- Retrieval test.
- Vector index health.
- Rebuild index.
- Metadata repair.
- Backup import and export.
- Raw diagnostic output.

All new user-facing UI strings must use i18n keys in a future runtime phase.

## Risks

Poor retrieval quality:

- Retrieved snippets may be irrelevant or miss important context.
- Mitigation: add diagnostics, thresholds, fallback, and retrieval tests.

Stale vectors:

- Document content may change after indexing.
- Mitigation: keep content hashes and mark stale entries clearly.

Index corruption:

- Partial rebuilds or failed writes may leave invalid vectors.
- Mitigation: validate vector dimensions, preserve fallback, and write index
  updates carefully.

Embedding provider failure:

- Ollama or embedding model may be unavailable.
- Mitigation: surface provider errors and continue keyword retrieval.

Privacy and data leakage:

- Knowledge documents may contain sensitive information.
- Mitigation: make enabled state explicit and avoid hidden sharing.

Large files and GUI blocking:

- Parsing, embedding, and repair can be expensive.
- Mitigation: use background threads and progress states.

Format expansion risk:

- Adding many file types at once may create unstable parsing behavior.
- Mitigation: add formats in small phases with clear fallback behavior.

## Phase Recommendation

Recommended implementation sequence:

1. Improve retrieval diagnostics.
2. Improve index health reporting.
3. Add safer rebuild and repair flows.
4. Add optional chunk design behind compatibility checks.
5. Expand metadata only with additive fields.
6. Validate backup and restore compatibility.

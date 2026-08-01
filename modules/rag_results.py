"""Normalization helpers for retrieval results."""

from copy import deepcopy


_SCORE_DETAIL_KEYS = ("vector", "keyword", "importance", "final")


def _source_kind(result, source, source_kind):
    if source_kind:
        return str(source_kind)
    if source.get("kind"):
        return str(source["kind"])
    if result.get("memory_id"):
        return "memory"
    return "knowledge"


def normalize_result(result, *, source_kind=None, retrieval_method=None):
    """Return a normalized copy of one retrieval result."""

    source_result = deepcopy(result) if isinstance(result, dict) else {}
    source = source_result.get("source")
    source = deepcopy(source) if isinstance(source, dict) else {}
    kind = _source_kind(source_result, source, source_kind)

    source["kind"] = kind
    if "file_name" not in source:
        source["file_name"] = source_result.get("file_name", "")
    if "source_path" not in source:
        source["source_path"] = source_result.get("source_path", "")
    if "memory_id" not in source:
        source["memory_id"] = source_result.get("memory_id", "")
    if "chunk_id" not in source:
        source["chunk_id"] = source_result.get("chunk_id")

    metadata = source_result.get("metadata")
    metadata = deepcopy(metadata) if isinstance(metadata, dict) else {}

    score_details = source_result.get("score_details")
    score_details = deepcopy(score_details) if isinstance(score_details, dict) else {}
    for key in _SCORE_DETAIL_KEYS:
        score_details.setdefault(key, None)

    normalized = source_result
    normalized.update({
        "id": source_result.get("id", ""),
        "type": source_result.get("type", ""),
        "content": source_result.get("content", ""),
        "snippet": source_result.get("snippet", ""),
        "score": source_result.get("score", 0.0),
        "source": source,
        "metadata": metadata,
        "retrieval_method": (
            retrieval_method
            if retrieval_method is not None
            else source_result.get("retrieval_method", "")
        ),
        "score_details": score_details,
    })
    return normalized


def normalize_results(results, *, source_kind=None, retrieval_method=None):
    """Return normalized copies for a collection of retrieval results."""

    if not isinstance(results, (list, tuple)):
        return []
    return [
        normalize_result(
            result,
            source_kind=source_kind,
            retrieval_method=retrieval_method,
        )
        for result in results
    ]

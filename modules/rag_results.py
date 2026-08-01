"""Normalization helpers for retrieval results."""

from copy import deepcopy
import hashlib


_SCORE_DETAIL_KEYS = ("method", "vector", "keyword", "matched_terms", "importance", "final")


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
    if "name" not in source:
        source["name"] = source_result.get("name") or source_result.get("file_name", "")
    if "path" not in source:
        source["path"] = source_result.get("path") or source_result.get("source_path", "")
    if "id" not in source:
        source["id"] = source_result.get("id", "")
    if "file_name" not in source:
        source["file_name"] = source_result.get("file_name", "")
    if "source_path" not in source:
        source["source_path"] = source_result.get("source_path", "")
    if "memory_id" not in source:
        source["memory_id"] = source_result.get("memory_id", "")
    if kind == "memory" and not source["memory_id"]:
        source["memory_id"] = source_result.get("id", "")
    if "chunk_id" not in source:
        source["chunk_id"] = source_result.get("chunk_id")
    if "content_hash" not in source:
        source["content_hash"] = source_result.get("content_hash", "")
    if "timestamp" not in source:
        source["timestamp"] = (
            source_result.get("timestamp")
            or source_result.get("updated_time")
            or source_result.get("created_time", "")
        )
    if "embedding_updated_time" in source_result and "embedding_updated_time" not in source:
        source["embedding_updated_time"] = source_result["embedding_updated_time"]

    metadata = source_result.get("metadata")
    metadata = deepcopy(metadata) if isinstance(metadata, dict) else {}

    score_details = source_result.get("score_details")
    score_details = deepcopy(score_details) if isinstance(score_details, dict) else {}
    score_details.setdefault("method", source_result.get("retrieval_method", ""))
    score_details.setdefault("vector", None)
    score_details.setdefault("keyword", None)
    score_details.setdefault("matched_terms", [])
    score_details.setdefault("importance", None)
    score_details.setdefault("final", None)

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


def normalize_content(content):
    """Normalize whitespace without changing case, punctuation, or word order."""

    text = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(text.split())


def _content_key(content):
    normalized = normalize_content(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _duplicate_key(result):
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    kind = str(source.get("kind") or "knowledge")
    if kind == "memory":
        memory_id = str(source.get("memory_id") or "")
        if memory_id:
            return kind, "memory_id", memory_id
        return kind, "content", _content_key(result.get("content", ""))

    source_id = str(source.get("id") or "")
    if source_id:
        return kind, "source_id", source_id
    content_hash = str(source.get("content_hash") or "")
    if content_hash:
        return kind, "content_hash", content_hash
    return kind, "content", _content_key(result.get("content", ""))


def _score_value(result):
    try:
        return float(result.get("score", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _source_completeness(result):
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    fields = (
        "name",
        "path",
        "id",
        "chunk_id",
        "file_name",
        "source_path",
        "memory_id",
        "content_hash",
        "timestamp",
        "embedding_updated_time",
    )
    return sum(1 for field in fields if source.get(field) not in (None, ""))


def _is_better_result(candidate, current):
    candidate_score = _score_value(candidate)
    current_score = _score_value(current)
    if candidate_score != current_score:
        return candidate_score > current_score
    return _source_completeness(candidate) > _source_completeness(current)


def deduplicate_results(results):
    """Return stable, source-aware de-duplicated copies of normalized results."""

    if not isinstance(results, (list, tuple)):
        return []

    kept = {}
    order = []
    for result in results:
        if not isinstance(result, dict):
            continue
        candidate = deepcopy(result)
        key = _duplicate_key(candidate)
        if key not in kept:
            kept[key] = candidate
            order.append(key)
            continue
        if _is_better_result(candidate, kept[key]):
            kept[key] = candidate
    return [kept[key] for key in order]

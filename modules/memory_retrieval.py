"""Deterministic prompt-based Memory retrieval for Chat."""

from datetime import datetime, timezone
import re


_ALIASES = {
    "\u7528\u6237\u754c\u9762": "ui",
    "\u754c\u9762": "ui",
    "\u8bbe\u8ba1": "ui style",
    "\u98ce\u683c": "style",
}

_GENERIC_QUERIES = {
    "\u4f60\u597d", "\u7136\u540e\u5462", "\u8fd9\u4e2a\u600e\u4e48\u6837", "\u4e3a\u4ec0\u4e48", "\u53ef\u4ee5\u5417", "\u7ee7\u7eed",
    "hello", "hi", "then what", "what about this", "why", "can i", "continue",
}

_STOP_TOKENS = {
    "a", "an", "and", "are", "can", "continue", "do", "for", "hello", "hi", "how", "i",
    "in", "is", "it", "me", "of", "on", "or", "please", "project", "that", "the", "then",
    "this", "to", "user", "what", "why", "with", "you",
    "\u4f60\u597d", "\u7136\u540e", "\u7136\u540e\u5462", "\u8fd9\u4e2a", "\u90a3\u4e2a", "\u600e\u4e48", "\u600e\u4e48\u6837", "\u4e3a\u4ec0\u4e48", "\u53ef\u4ee5",
    "\u53ef\u4ee5\u5417", "\u7ee7\u7eed", "\u4e00\u4e2a", "\u6211\u4eec", "\u4f60\u4eec", "\u4ed6\u4eec", "\u4ee5\u53ca", "\u8fd8\u6709",
}

_DEFAULT_RANKING_WEIGHTS = {
    "relevance": 0.70,
    "confidence": 0.15,
    "importance": 0.10,
    "freshness": 0.05,
}


def _normalized_text(value):
    return " ".join(re.findall(r"[a-z0-9_\u3400-\u9fff]+", str(value or "").casefold()))


def _is_generic_query(value):
    return _normalized_text(value) in _GENERIC_QUERIES


def _tokens(value):
    text = str(value or "").casefold()
    for source, target in sorted(_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(source, f" {target} ")

    tokens = set()
    for part in re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", text):
        if re.fullmatch(r"[a-z0-9_]+", part):
            if part not in _STOP_TOKENS and (len(part) > 1 or part.isdigit()):
                tokens.add(part)
            continue
        chinese_tokens = {part} if len(part) <= 2 else {part[index:index + 2] for index in range(len(part) - 1)}
        tokens.update(token for token in chinese_tokens if token not in _STOP_TOKENS)
    return tokens


def _importance(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return {"high": 10.0, "normal": 5.0, "medium": 5.0, "low": 1.0}.get(
            str(value).casefold(), 0.0
        )


def _importance_score(value):
    raw = _importance(value)
    if raw > 1.0:
        raw /= 10.0
    return max(0.0, min(1.0, raw))


def _confidence_score(memory, default):
    metadata = memory.get("metadata") if isinstance(memory.get("metadata"), dict) else {}
    value = metadata.get("confidence", memory.get("confidence", default))
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return max(0.0, min(1.0, float(default)))


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness_score(memory, now=None):
    metadata = memory.get("metadata") if isinstance(memory.get("metadata"), dict) else {}
    timestamp = (
        memory.get("updated_time") or metadata.get("updated_time")
        or memory.get("created_time") or metadata.get("created_time")
    )
    parsed = _parse_time(timestamp)
    if parsed is None:
        return 0.5
    current = now or datetime.now(timezone.utc)
    age_days = max(0.0, (current - parsed).total_seconds() / 86400.0)
    return 1.0 / (1.0 + age_days / 365.0)


def _relevance_score(prompt_tokens, memory_tokens):
    if not prompt_tokens or not memory_tokens:
        return 0.0, []
    overlap = prompt_tokens.intersection(memory_tokens)
    if not overlap:
        return 0.0, []
    query_coverage = len(overlap) / len(prompt_tokens)
    overlap_quality = len(overlap) / max(1, min(len(prompt_tokens), len(memory_tokens)))
    score = 0.85 * query_coverage + 0.15 * overlap_quality
    return max(0.0, min(1.0, score)), sorted(overlap)


def _ranking_weights(value):
    weights = dict(_DEFAULT_RANKING_WEIGHTS)
    if isinstance(value, dict):
        for key in weights:
            try:
                candidate = float(value[key])
            except (KeyError, TypeError, ValueError):
                continue
            if candidate >= 0:
                weights[key] = candidate
    total = sum(weights.values())
    return {key: weight / total for key, weight in weights.items()} if total > 0 else dict(_DEFAULT_RANKING_WEIGHTS)


def _enabled(memory):
    enabled = memory.get("enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.strip().casefold() not in {"false", "0", "no"}
    return bool(enabled)


def build_memory_retrieval_config(settings_store):
    """Resolve Memory retrieval parameters from Aurora's Settings source."""

    def value(key, default):
        try:
            return settings_store.get(key, default)
        except (AttributeError, TypeError):
            return default

    try:
        max_results = max(1, int(value("memory.max_injection", 5)))
    except (TypeError, ValueError):
        max_results = 5
    try:
        min_importance = max(0.0, float(value("memory.min_importance", 0)))
    except (TypeError, ValueError):
        min_importance = 0.0
    try:
        min_relevance = max(0.0, min(1.0, float(value("memory.retrieval_threshold", 0.35))))
    except (TypeError, ValueError):
        min_relevance = 0.35
    try:
        confidence_default = max(0.0, min(1.0, float(value("memory.confidence_default", 0.5))))
    except (TypeError, ValueError):
        confidence_default = 0.5
    weights = value("rag.memory_ranking_weights", None)
    return {
        "max_results": max_results,
        "min_importance": min_importance,
        "min_relevance": min_relevance,
        "confidence_default": confidence_default,
        "ranking_weights": dict(weights) if isinstance(weights, dict) else None,
    }


def retrieve_memories(
    prompt,
    memories,
    max_results=5,
    min_importance=0,
    enriched=False,
    min_relevance=0.35,
    confidence_default=0.5,
    ranking_weights=None,
):
    """Return enabled, active Memories that pass the relevance gate."""

    if _is_generic_query(prompt):
        return []
    prompt_tokens = _tokens(prompt)
    if not prompt_tokens:
        return []
    try:
        relevance_threshold = max(0.0, min(1.0, float(min_relevance)))
    except (TypeError, ValueError):
        relevance_threshold = 0.35
    try:
        neutral_confidence = max(0.0, min(1.0, float(confidence_default)))
    except (TypeError, ValueError):
        neutral_confidence = 0.5
    weights = _ranking_weights(ranking_weights)

    matched = []
    for index, memory in enumerate(memories or []):
        if not isinstance(memory, dict) or not _enabled(memory):
            continue
        metadata = memory.get("metadata") if isinstance(memory.get("metadata"), dict) else {}
        state = str(metadata.get("state", memory.get("state", "active"))).casefold()
        if state != "active":
            continue
        importance = _importance(memory.get("importance", metadata.get("importance")))
        if importance < float(min_importance):
            continue
        memory_tokens = _tokens(
            f"{memory.get('content', '')} {memory.get('type', '')} {memory.get('category', '')}"
        )
        relevance, terms = _relevance_score(prompt_tokens, memory_tokens)
        if relevance < relevance_threshold:
            continue
        confidence = _confidence_score(memory, neutral_confidence)
        importance_normalized = _importance_score(memory.get("importance", metadata.get("importance")))
        freshness = _freshness_score(memory)
        final_score = (
            relevance * weights["relevance"]
            + confidence * weights["confidence"]
            + importance_normalized * weights["importance"]
            + freshness * weights["freshness"]
        )
        scores = {
            "relevance_score": relevance,
            "confidence_score": confidence,
            "importance_score": importance_normalized,
            "freshness_score": freshness,
            "final_score": final_score,
        }
        matched.append((final_score, relevance, confidence, importance_normalized, freshness, index, terms, scores, memory))

    matched.sort(key=lambda item: (-item[0], -item[1], -item[2], -item[3], -item[4], item[5]))
    results = []
    for _, _, _, _, _, _, terms, scores, memory in matched[:max(0, int(max_results))]:
        if not enriched:
            results.append(memory)
            continue
        enriched_memory = dict(memory)
        existing_details = enriched_memory.get("score_details")
        score_details = dict(existing_details) if isinstance(existing_details, dict) else {}
        score_details.setdefault("vector", None)
        score_details["keyword"] = len(terms)
        score_details["matched_terms"] = terms
        score_details["importance"] = memory.get("importance")
        score_details["confidence"] = scores["confidence_score"]
        score_details.update(scores)
        enriched_memory["score_details"] = score_details
        enriched_memory.update(scores)
        enriched_memory["retrieval_method"] = "keyword"
        results.append(enriched_memory)
    return results


def format_memory_context(memories, limit=1200):
    """Format matched Memory records for context preview and injection."""

    lines = []
    try:
        item_limit = max(100, int(limit))
    except (TypeError, ValueError):
        item_limit = 1200
    for memory in memories or []:
        if not isinstance(memory, dict):
            continue
        content = str(memory.get("content", "")).strip()
        if not content:
            continue
        if len(content) > item_limit:
            content = content[:item_limit] + "..."
        memory_type = str(memory.get("type", "")).strip()
        prefix = f"[{memory_type}] " if memory_type else ""
        lines.append(f"- {prefix}{content}")
    return "\n".join(lines)


def memory_context_status(memories):
    content = format_memory_context(memories)
    return {
        "name": "Memory",
        "enabled": bool(content),
        "characters": len(content),
        "items": len([item for item in memories or [] if isinstance(item, dict)])
    }

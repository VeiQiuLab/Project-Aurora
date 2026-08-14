"""Lightweight prompt-based Memory retrieval for Chat."""

import re


_ALIASES = {
    "\u754c\u9762": "ui",
    "\u8bbe\u8ba1": "ui style",
    "\u98ce\u683c": "style",
    "\u7528\u6237\u754c\u9762": "ui",
}


def _tokens(value):
    text = str(value or "").casefold()
    for source, target in _ALIASES.items():
        text = text.replace(source, f" {target} ")
    return set(re.findall(r"[a-z0-9_]+", text))


def _importance(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return {"high": 10.0, "normal": 5.0, "low": 1.0}.get(str(value).casefold(), 0.0)


def retrieve_memories(prompt, memories, max_results=5, min_importance=0, enriched=False):
    """Return enabled memories matching the prompt, ranked by relevance and importance."""

    prompt_tokens = _tokens(prompt)
    if not prompt_tokens:
        return []

    matched = []
    for memory in memories or []:
        if not isinstance(memory, dict):
            continue
        enabled = memory.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.strip().casefold() not in {"false", "0", "no"}
        if not enabled:
            continue
        metadata = memory.get("metadata") if isinstance(memory.get("metadata"), dict) else {}
        state = metadata.get("state", memory.get("state", "active"))
        if state != "active":
            continue
        importance = _importance(memory.get("importance"))
        if importance < float(min_importance):
            continue
        memory_tokens = _tokens(f"{memory.get('content', '')} {memory.get('type', '')}")
        overlap = prompt_tokens.intersection(memory_tokens)
        if not overlap:
            continue
        matched.append((len(overlap), importance, sorted(overlap), memory))

    matched.sort(key=lambda item: (item[1], item[0]), reverse=True)
    results = []
    for overlap_count, importance, terms, memory in matched[:max(0, int(max_results))]:
        if not enriched:
            results.append(memory)
            continue
        enriched_memory = dict(memory)
        existing_details = enriched_memory.get("score_details")
        score_details = dict(existing_details) if isinstance(existing_details, dict) else {}
        score_details.setdefault("vector", None)
        score_details["keyword"] = overlap_count
        score_details["matched_terms"] = terms
        score_details["importance"] = memory.get("importance")
        metadata = memory.get("metadata") if isinstance(memory.get("metadata"), dict) else {}
        score_details["confidence"] = metadata.get("confidence", memory.get("confidence"))
        enriched_memory["score_details"] = score_details
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

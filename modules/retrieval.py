"""Keyword retrieval for the local Knowledge Base."""

import re


_ALIASES = {
    "\u754c\u9762": "ui",
    "\u8bbe\u8ba1": "design",
    "\u77e5\u8bc6": "knowledge",
    "\u6587\u6863": "document",
}


def _tokens(value):
    text = str(value or "").casefold()
    for source, target in _ALIASES.items():
        text = text.replace(source, f" {target} ")
    return set(re.findall(r"[\w]+", text, flags=re.UNICODE))


def _enabled(item):
    enabled = item.get("enabled", True) if isinstance(item, dict) else True
    if isinstance(enabled, str):
        return enabled.strip().casefold() not in {"false", "0", "no", "disabled"}
    return bool(enabled)


def _normal(item):
    return str(item.get("status", "OK")) == "OK" if isinstance(item, dict) else False


def _retrievable(item):
    if not isinstance(item, dict):
        return False
    if not _enabled(item) or not _normal(item):
        return False
    file_type = str(item.get("file_type", "")).lower().lstrip(".")
    return file_type in {"txt", "md"} and bool(str(item.get("content", "")).strip())


def _match_record(prompt_tokens, item):
    haystack = " ".join(
        str(item.get(key, ""))
        for key in ("file_name", "file_type", "content")
    )
    item_tokens = _tokens(haystack)
    keywords = sorted(prompt_tokens.intersection(item_tokens))
    if not keywords:
        return None
    score = len(keywords) * 10 + min(len(str(item.get("content", ""))) // 1000, 5)
    return {
        "item": item,
        "score": score,
        "keywords": keywords
    }


def search_knowledge(prompt, items, max_results=3, enabled_only=True, enriched=False):
    """Return knowledge records matching the prompt by simple keyword overlap."""

    prompt_tokens = _tokens(prompt)
    if not prompt_tokens:
        return []

    matched = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if enabled_only and not _retrievable(item):
            continue
        match = _match_record(prompt_tokens, item)
        if match is None:
            continue
        matched.append(match)

    matched.sort(key=lambda value: (value["score"], len(str(value["item"].get("content", "")))), reverse=True)
    try:
        limit = max(0, int(max_results))
    except (TypeError, ValueError):
        limit = 3
    results = []
    for match in matched[:limit]:
        item = match["item"]
        if not enriched:
            results.append(item)
            continue
        enriched_item = dict(item)
        existing_details = enriched_item.get("score_details")
        score_details = dict(existing_details) if isinstance(existing_details, dict) else {}
        score_details.setdefault("vector", None)
        score_details["keyword"] = match["score"]
        score_details["matched_terms"] = list(match["keywords"])
        score_details.setdefault("importance", None)
        score_details.setdefault("confidence", None)
        enriched_item["score_details"] = score_details
        enriched_item["retrieval_method"] = "keyword"
        results.append(enriched_item)
    return results


def format_knowledge_context(items, limit=1200):
    """Format matched Knowledge records for context preview and injection."""

    lines = []
    try:
        item_limit = max(100, int(limit))
    except (TypeError, ValueError):
        item_limit = 1200
    for item in items or []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        title = item.get("file_name", "Knowledge")
        if len(content) > item_limit:
            content = content[:item_limit] + "..."
        lines.append(f"- Source: {title}\n{content}")
    return "\n".join(lines)


def knowledge_context_status(items):
    content = format_knowledge_context(items)
    return {
        "name": "Knowledge",
        "enabled": bool(content),
        "characters": len(content),
        "items": len([item for item in items or [] if isinstance(item, dict)])
    }


def knowledge_snippet(prompt, item, limit=280):
    """Return a compact matching snippet for a knowledge record."""

    content = str(item.get("content", "") if isinstance(item, dict) else "")
    if not content:
        return ""

    prompt_tokens = _tokens(prompt)
    lowered = content.casefold()
    start = 0
    for token in prompt_tokens:
        if not token:
            continue
        index = lowered.find(token.casefold())
        if index >= 0:
            start = max(0, index - 60)
            break

    try:
        snippet_limit = max(40, int(limit))
    except (TypeError, ValueError):
        snippet_limit = 280
    snippet = content[start:start + snippet_limit].strip()
    if start > 0:
        snippet = "..." + snippet
    if start + snippet_limit < len(content):
        snippet += "..."
    return snippet


def snippet_location(prompt, item, limit=280):
    content = str(item.get("content", "") if isinstance(item, dict) else "")
    if not content:
        return {"start": 0, "end": 0, "line": None}

    prompt_tokens = _tokens(prompt)
    lowered = content.casefold()
    start = 0
    for token in prompt_tokens:
        if not token:
            continue
        index = lowered.find(token.casefold())
        if index >= 0:
            start = max(0, index - 60)
            break

    try:
        snippet_limit = max(40, int(limit))
    except (TypeError, ValueError):
        snippet_limit = 280
    end = min(len(content), start + snippet_limit)
    line = content.count("\n", 0, start) + 1 if content else None
    return {"start": start, "end": end, "line": line}


def highlight_snippet(snippet, keywords):
    text = str(snippet or "")
    for keyword in sorted(keywords or [], key=len, reverse=True):
        if not keyword:
            continue
        pattern = re.compile(re.escape(str(keyword)), flags=re.IGNORECASE)
        text = pattern.sub(lambda match: f"[ {match.group(0)} ]", text)
    return text


def test_knowledge_retrieval(prompt, items, max_results=3):
    """Return retrieval diagnostics suitable for the Knowledge Base window."""

    prompt_tokens = _tokens(prompt)
    matched = []
    skipped = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        match = _match_record(prompt_tokens, item)
        if match is None:
            continue
        target = matched if _retrievable(item) else skipped
        target.append(match)

    matched.sort(key=lambda value: value["score"], reverse=True)
    skipped.sort(key=lambda value: value["score"], reverse=True)
    try:
        limit = max(0, int(max_results))
    except (TypeError, ValueError):
        limit = 3

    results = []
    for match in matched[:limit]:
        item = match["item"]
        snippet = knowledge_snippet(prompt, item)
        location = snippet_location(prompt, item)
        results.append({
            "file_name": item.get("file_name", "Unknown"),
            "file_type": item.get("file_type", ""),
            "enabled": True,
            "status": item.get("status", "OK"),
            "score": match["score"],
            "keywords": match["keywords"],
            "snippet": highlight_snippet(snippet, match["keywords"]),
            "start": location["start"],
            "end": location["end"],
            "line": location["line"],
            "injected": bool(str(item.get("content", "")).strip())
        })

    for match in skipped:
        item = match["item"]
        snippet = knowledge_snippet(prompt, item)
        location = snippet_location(prompt, item)
        results.append({
            "file_name": item.get("file_name", "Unknown"),
            "file_type": item.get("file_type", ""),
            "enabled": _enabled(item),
            "status": item.get("status", "OK"),
            "score": match["score"],
            "keywords": match["keywords"],
            "snippet": highlight_snippet(snippet, match["keywords"]),
            "start": location["start"],
            "end": location["end"],
            "line": location["line"],
            "injected": False
        })
    return results


def retrieval_summary(prompt, items, max_results=3, knowledge_enabled=True):
    records = list(items or [])
    enabled_records = [item for item in records if isinstance(item, dict) and _retrievable(item)]
    if not knowledge_enabled:
        return {
            "prompt": prompt,
            "knowledge_enabled": False,
            "max_results": max_results,
            "matched_count": 0,
            "injected_count": 0,
            "enabled_available": bool(enabled_records),
            "results": []
        }
    diagnostics = test_knowledge_retrieval(prompt, records, max_results=max_results)
    injected_count = sum(1 for item in diagnostics if item.get("injected"))
    return {
        "prompt": prompt,
        "knowledge_enabled": bool(knowledge_enabled),
        "max_results": max_results,
        "matched_count": len(diagnostics),
        "injected_count": injected_count,
        "enabled_available": bool(enabled_records),
        "results": diagnostics
    }

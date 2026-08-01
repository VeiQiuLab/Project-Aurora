"""Deterministic context budget and trimming helpers."""

from copy import deepcopy
from typing import Any


_DEFAULT_PRIORITIES = {
    "system": 100,
    "user": 100,
    "current user message": 100,
    "persona": 80,
    "memory": 60,
    "knowledge": 50,
    "conversation": 40,
}


class ContextOptimizer:
    """Optimize caller-provided context sections without assembling prompts."""

    def optimize_context(self, sections, max_tokens=4000, budget=None):
        normalized_sections = self._copy_sections(sections)
        token_limit = self._positive_int(max_tokens, 4000)
        budget_map = budget if isinstance(budget, dict) else {}
        enabled = [
            item for item in normalized_sections
            if item.get("enabled") and self._section_tokens(item) > 0
        ]
        allocations = self._allocate(enabled, token_limit, budget_map)
        truncated_sections = []
        section_diagnostics = []

        for item in normalized_sections:
            if item not in enabled:
                section_diagnostics.append(self._section_diagnostic(item, 0, False))
                continue
            name = str(item.get("name", "Context"))
            original_tokens = self._section_tokens(item)
            allocation = allocations.get(id(item), 0)
            content = self._conversation_content(item, allocation)
            if not self._is_conversation(item):
                content = self._trim_text(content, allocation)
            item["content"] = content
            item["enabled"] = bool(content)
            actual_tokens = self.estimate_tokens(content)
            was_truncated = actual_tokens < original_tokens
            if was_truncated:
                truncated_sections.append(name)
            section_diagnostics.append(
                self._section_diagnostic(item, actual_tokens, was_truncated, original_tokens)
            )

        used_tokens = sum(
            self.estimate_tokens(item.get("content", ""))
            for item in normalized_sections
            if item.get("enabled")
        )
        return {
            "sections": normalized_sections,
            "diagnostics": {
                "max_tokens": token_limit,
                "used_tokens": used_tokens,
                "remaining_tokens": max(0, token_limit - used_tokens),
                "truncated": bool(truncated_sections),
                "truncated_sections": truncated_sections,
                "sections": section_diagnostics,
            },
        }

    @classmethod
    def estimate_tokens(cls, text):
        content = str(text or "")
        if not content.strip():
            return 0
        return max(1, (len(content) + 3) // 4)

    def _copy_sections(self, sections):
        if not isinstance(sections, (list, tuple)):
            return []
        copied = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            item = deepcopy(section)
            item["name"] = str(item.get("name") or "Context")
            item["content"] = str(item.get("content") or "")
            item["enabled"] = bool(item.get("enabled", True))
            copied.append(item)
        return copied

    def _allocate(self, sections, max_tokens, budget):
        allocations = {}
        if not sections or max_tokens <= 0:
            return allocations

        ordered = sorted(
            sections,
            key=lambda item: self._priority(item),
            reverse=True,
        )
        desired = {}
        for item in ordered:
            cap = self._section_cap(item, max_tokens, budget)
            desired[id(item)] = min(self._section_tokens(item), cap)

        allocations = {id(item): 0 for item in ordered}
        remaining = max_tokens
        for item in ordered:
            if remaining <= 0:
                break
            if desired[id(item)] > 0:
                allocations[id(item)] = 1
                remaining -= 1

        while remaining > 0:
            changed = False
            for item in ordered:
                key = id(item)
                if allocations[key] >= desired[key]:
                    continue
                amount = min(remaining, desired[key] - allocations[key])
                allocations[key] += amount
                remaining -= amount
                changed = True
                if remaining <= 0:
                    break
            if not changed:
                break
        return allocations

    def _section_cap(self, section, max_tokens, budget):
        name = str(section.get("name", "Context"))
        value = budget.get(name)
        if value is None:
            value = budget.get(name.casefold())
        if value is None:
            return max_tokens
        return max(0, self._positive_int(value, max_tokens))

    def _priority(self, section):
        explicit = section.get("priority")
        if isinstance(explicit, (int, float)):
            return float(explicit)
        name = str(section.get("name", "")).casefold()
        for key, priority in _DEFAULT_PRIORITIES.items():
            if key in name:
                return priority
        return 10

    def _conversation_content(self, section, token_budget):
        messages = section.get("messages")
        if not self._is_conversation(section) or not isinstance(messages, list):
            return str(section.get("content", ""))
        if token_budget <= 0:
            return ""

        selected = []
        used = 0
        for message in reversed(messages):
            if not isinstance(message, dict):
                continue
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            line = f"{message.get('role', 'user')}: {content}"
            line_tokens = self.estimate_tokens(line)
            if selected and used + line_tokens > token_budget:
                break
            if not selected and line_tokens > token_budget:
                line = self._trim_text(line, token_budget, keep_tail=True)
                line_tokens = self.estimate_tokens(line)
            selected.append(line)
            used += line_tokens
        return "\n\n".join(reversed(selected))

    def _section_tokens(self, section):
        if self._is_conversation(section) and isinstance(section.get("messages"), list):
            return sum(
                self.estimate_tokens(
                    f"{message.get('role', 'user')}: {message.get('content', '')}"
                )
                for message in section.get("messages", [])
                if isinstance(message, dict) and str(message.get("content") or "").strip()
            )
        return self.estimate_tokens(section.get("content", ""))

    @staticmethod
    def _is_conversation(section):
        return "conversation" in str(section.get("name", "")).casefold()

    @classmethod
    def _trim_text(cls, text, token_budget, keep_tail=False):
        if token_budget <= 0:
            return ""
        content = str(text or "")
        max_chars = max(1, token_budget * 4)
        if len(content) <= max_chars:
            return content
        if keep_tail:
            return "..." + content[-max_chars + 3:]
        return content[:max_chars - 3] + "..."

    @staticmethod
    def _positive_int(value, fallback):
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return fallback

    def _section_diagnostic(self, section, tokens, truncated, original_tokens=None):
        if original_tokens is None:
            original_tokens = self._section_tokens(section)
        return {
            "name": section.get("name", "Context"),
            "enabled": bool(section.get("enabled")),
            "tokens": tokens,
            "original_tokens": original_tokens,
            "truncated": bool(truncated),
        }


def optimize_context(sections, max_tokens=4000, budget=None):
    """Optimize context sections using the default ContextOptimizer."""

    return ContextOptimizer().optimize_context(
        sections,
        max_tokens=max_tokens,
        budget=budget,
    )

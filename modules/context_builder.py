"""Context assembly helpers for Aurora chat prompts.

This module only assembles context that was already loaded or retrieved by
callers. It does not read runtime data, query Knowledge, manage Memory,
save conversations, control UI, or call an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


DEFAULT_SYSTEM_CONTEXT = "You are Aurora, a helpful local AI assistant."


class ContextSection(TypedDict):
    """A single ordered context section."""

    name: str
    enabled: bool
    content: str


class PromptPackage(TypedDict):
    """Model-ready prompt package plus inspection metadata."""

    messages: list[dict[str, str]]
    sections: list[ContextSection]
    final_prompt: str
    diagnostics: dict[str, Any]
    source_refs: dict[str, list[str]]


@dataclass(frozen=True)
class ContextBuilder:
    """Build prompt context from caller-provided context sources."""

    system_context: str = DEFAULT_SYSTEM_CONTEXT
    warning_tokens: int = 6000

    def build_context_sections(
        self,
        *,
        system_context: str | None = None,
        persona: str | dict[str, Any] | None = None,
        memory_items: list[dict[str, Any]] | None = None,
        knowledge_items: list[dict[str, Any]] | None = None,
        conversation_messages: list[dict[str, Any]] | None = None,
        user_message: str = "",
    ) -> list[ContextSection]:
        """Return ordered context sections without performing retrieval."""

        system_text = self._clean_text(system_context or self.system_context)
        persona_text = self._format_persona(persona)
        memory_text = self._format_records(memory_items, fallback_name="Memory")
        knowledge_text = self._format_records(knowledge_items, fallback_name="Knowledge")
        conversation_text = self._format_conversation(conversation_messages)
        user_text = self._clean_text(user_message)

        sections: list[ContextSection] = [
            {"name": "System Context", "enabled": bool(system_text), "content": system_text},
            {"name": "Persona", "enabled": bool(persona_text), "content": persona_text},
            {"name": "Memory", "enabled": bool(memory_text), "content": memory_text},
            {"name": "Knowledge", "enabled": bool(knowledge_text), "content": knowledge_text},
            {
                "name": "Conversation Context",
                "enabled": bool(conversation_text),
                "content": conversation_text,
            },
            {
                "name": "Current User Message",
                "enabled": bool(user_text),
                "content": user_text,
            },
        ]
        return sections

    def build_prompt_package(
        self,
        *,
        system_context: str | None = None,
        persona: str | dict[str, Any] | None = None,
        memory_items: list[dict[str, Any]] | None = None,
        knowledge_items: list[dict[str, Any]] | None = None,
        conversation_messages: list[dict[str, Any]] | None = None,
        user_message: str = "",
    ) -> PromptPackage:
        """Return a complete prompt package for future chat integration."""

        sections = self.build_context_sections(
            system_context=system_context,
            persona=persona,
            memory_items=memory_items,
            knowledge_items=knowledge_items,
            conversation_messages=conversation_messages,
            user_message=user_message,
        )
        final_prompt = self.assemble_final_prompt(sections)
        user_text = self._clean_text(user_message)
        messages = [{"role": "system", "content": final_prompt or self.system_context}]
        if user_text:
            messages.append({"role": "user", "content": user_text})

        return {
            "messages": messages,
            "sections": sections,
            "final_prompt": final_prompt,
            "diagnostics": self._build_diagnostics(sections),
            "source_refs": self._build_source_refs(memory_items, knowledge_items, conversation_messages),
        }

    @classmethod
    def assemble_final_prompt(cls, sections: list[ContextSection]) -> str:
        """Join enabled sections into a readable final prompt string."""

        lines: list[str] = []
        for section in sections or []:
            if not section.get("enabled"):
                continue
            content = cls._clean_text(section.get("content", ""))
            if not content:
                continue
            lines.extend([f"{section.get('name', 'Context')}:", content, ""])
        return "\n".join(lines).strip()

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Return a lightweight token estimate for diagnostics."""

        content = str(text or "")
        if not content.strip():
            return 0
        return max(1, len(content) // 4)

    @staticmethod
    def _clean_text(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _format_persona(cls, persona: str | dict[str, Any] | None) -> str:
        if isinstance(persona, str):
            return cls._clean_text(persona)
        if not isinstance(persona, dict):
            return ""
        parts = []
        for key in ("name", "description", "style", "prompt", "context"):
            value = cls._clean_text(persona.get(key, ""))
            if value:
                parts.append(value)
        return "\n".join(parts)

    @classmethod
    def _format_records(cls, items: list[dict[str, Any]] | None, *, fallback_name: str) -> str:
        lines: list[str] = []
        for index, item in enumerate(items or [], start=1):
            if not isinstance(item, dict):
                continue
            if item.get("enabled") is False:
                continue
            content = cls._clean_text(
                item.get("content")
                or item.get("snippet")
                or item.get("summary")
                or item.get("text")
                or item.get("file_name")
            )
            if not content:
                continue
            label = cls._clean_text(item.get("type") or item.get("file_name") or fallback_name)
            lines.append(f"- {label} {index}: {content}")
        return "\n".join(lines)

    @classmethod
    def _format_conversation(cls, messages: list[dict[str, Any]] | None) -> str:
        lines: list[str] = []
        for message in messages or []:
            if not isinstance(message, dict):
                continue
            role = cls._clean_text(message.get("role", ""))
            if role == "system":
                continue
            content = cls._clean_text(message.get("content", ""))
            if content:
                lines.append(f"{role}: {content}")
        return "\n\n".join(lines)

    def _build_diagnostics(self, sections: list[ContextSection]) -> dict[str, Any]:
        records = []
        total_characters = 0
        total_tokens = 0
        for section in sections:
            content = section.get("content", "")
            characters = len(content)
            tokens = self.estimate_tokens(content)
            total_characters += characters
            total_tokens += tokens
            records.append({
                "name": section.get("name", "Context"),
                "enabled": bool(section.get("enabled")),
                "characters": characters,
                "tokens": tokens,
            })

        warnings: list[str] = []
        if total_tokens > max(1, int(self.warning_tokens)):
            warnings.append("Total context exceeds recommended size.")

        return {
            "sections": records,
            "total_characters": total_characters,
            "total_tokens": total_tokens,
            "warning": bool(warnings),
            "warning_reasons": warnings,
        }

    @staticmethod
    def _ids(items: list[dict[str, Any]] | None) -> list[str]:
        values: list[str] = []
        for item in items or []:
            if isinstance(item, dict) and item.get("id"):
                values.append(str(item["id"]))
        return values

    def _build_source_refs(
        self,
        memory_items: list[dict[str, Any]] | None,
        knowledge_items: list[dict[str, Any]] | None,
        conversation_messages: list[dict[str, Any]] | None,
    ) -> dict[str, list[str]]:
        conversation_ids = []
        for message in conversation_messages or []:
            if isinstance(message, dict) and message.get("id"):
                conversation_ids.append(str(message["id"]))
        return {
            "memory_ids": self._ids(memory_items),
            "knowledge_ids": self._ids(knowledge_items),
            "conversation_message_ids": conversation_ids,
        }

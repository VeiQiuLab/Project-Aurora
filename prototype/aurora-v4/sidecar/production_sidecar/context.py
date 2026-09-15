"""Read-only bridge to production retrieval, RAG and ContextBuilder (no UI)."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from types import MappingProxyType
from typing import Mapping

from modules.chat_latency import PreLLMLatencyDiagnostics
from modules.context_builder import ContextBuilder, DEFAULT_SYSTEM_CONTEXT
from modules.embedding import OllamaEmbeddingProvider
from modules.knowledge import KnowledgeStore
from modules.memory import MemoryStore
from modules.memory_retrieval import build_memory_retrieval_config, retrieve_memories, format_memory_context
from modules.persona import PersonaStore
from modules.rag_integration import run_configured_rag_pipeline
from modules.retrieval import format_knowledge_context


class ContextCancelled(Exception):
    """Only safe scalar diagnostics may accompany a cancelled context."""

    diagnostics: dict | None = None


class ContextPreparationError(RuntimeError):
    def __init__(self, stage: str):
        super().__init__(f"Context preparation failed at {stage}.")
        self.stage = stage
        self.diagnostics = None


@dataclass(frozen=True)
class ContextSnapshot:
    system_context: str = field(repr=False)
    diagnostics: Mapping
    conversation_id: str | None = None
    generation_id: str | None = None
    user_turn: str = field(default="", repr=False)
    history: tuple = field(default=(), repr=False)
    settings: object = field(default=None, repr=False)


class ProductionContextAdapter:
    def __init__(self, composition, root: Path | None = None):
        self.composition = composition
        self.root = Path(root if root is not None else composition.context_root)
        self._memory = self._knowledge = self._persona = None

    @property
    def memory(self):
        if self._memory is None:
            self._memory = MemoryStore(self.root / "memory" / "memories.json", read_only=True)
        return self._memory

    @property
    def knowledge(self):
        if self._knowledge is None:
            self._knowledge = KnowledgeStore(self.root / "knowledge", read_only=True)
        return self._knowledge

    @property
    def persona(self):
        if self._persona is None:
            self._persona = PersonaStore(self.root / "persona" / "persona.json", read_only=True)
        return self._persona

    def prepare(self, prompt, history=(), stop_event=None, *, conversation_id=None, generation_id=None):
        # ReadOnlySettings is fixed at composition construction. Store results
        # are local values, never re-read during token generation.
        settings = self.composition.settings
        history = tuple(MappingProxyType(dict(item)) for item in history)
        latency = PreLLMLatencyDiagnostics(source="v4_context", clock=perf_counter)
        started = perf_counter()
        diagnostics = {
            "memory_enabled": True,  # Production has per-record filters, no global memory switch.
            "persona_enabled": bool(settings.get("persona.enabled", True)),
            "knowledge_enabled": bool(settings.get("knowledge.enabled", True)),
            "rag_enabled": bool(settings.get("rag.pipeline_enabled", False)),
            "history_message_count": len(history),
            "memory_item_count": 0, "knowledge_item_count": 0, "rag_result_count": 0,
            "context_error_stage": None,
        }

        def check_cancel():
            if stop_event is not None and stop_event.is_set():
                raise ContextCancelled()

        @contextmanager
        def stage(name, legacy_name, enabled=True):
            check_cancel()
            try:
                with latency.stage(legacy_name, enabled=enabled):
                    yield
            except ContextCancelled:
                raise
            except Exception:
                diagnostics["context_error_stage"] = name
                raise ContextPreparationError(name) from None
            check_cancel()

        def report():
            existing = latency.report()
            return {
                **diagnostics,
                "context_total_ms": max(0.0, (perf_counter() - started) * 1000),
                **{key: existing[key] for key in ("memory_ms", "persona_ms", "knowledge_ms", "rag_ms")},
                "prompt_assembly_ms": existing["context_builder_total_ms"],
            }

        try:
            rag_enabled = diagnostics["rag_enabled"]
            with stage("memory", "memory_context"):
                matched_memories = retrieve_memories(
                    prompt, self.memory.list_memories(), enriched=rag_enabled,
                    **build_memory_retrieval_config(settings),
                )
                diagnostics["memory_item_count"] = len(matched_memories)

            active_persona = None
            with stage("persona", "persona_context", diagnostics["persona_enabled"]):
                if diagnostics["persona_enabled"]:
                    # Missing/corrupt Persona retains production's DEFAULT_PERSONA
                    # fallback, but no directory creation or timestamp write-back.
                    active_persona = self.persona.load(update_timestamp=False)

            matched_knowledge = []
            with stage("knowledge", "knowledge_context", diagnostics["knowledge_enabled"]):
                if diagnostics["knowledge_enabled"]:
                    embedding = OllamaEmbeddingProvider(settings_store=settings)
                    matched_knowledge = self.knowledge.retrieve(
                        prompt, max_results=self._setting_int(settings, "knowledge.max_results", 3),
                        enriched=rag_enabled, embedding_provider=embedding,
                    )
                    diagnostics["knowledge_item_count"] = len(matched_knowledge)

            rag_result = {}
            with stage("rag", "rag_context", rag_enabled):
                if rag_enabled:
                    rag_result = run_configured_rag_pipeline(
                        matched_memories, matched_knowledge, settings_store=settings,
                        query=prompt, conversation_messages=[dict(item) for item in history], logger=None,
                    )
                    rag_diagnostics = rag_result.get("diagnostics", {})
                    count = rag_diagnostics.get("metrics", {}).get("optimized_count")
                    diagnostics["rag_result_count"] = count if isinstance(count, int) and count >= 0 else sum(
                        len(section.get("items", [])) for section in rag_result.get("sections", [])
                    )
                    if not rag_diagnostics.get("success"):
                        # The production pipeline returns fallback sections on failure.
                        diagnostics["context_error_stage"] = "rag"

            with stage("prompt_assembly", "context_builder"):
                optimized = {}
                if rag_enabled and rag_result.get("diagnostics", {}).get("success"):
                    optimized = {section["name"]: section.get("content", "")
                                 for section in rag_result.get("sections", []) if isinstance(section, dict)}
                package = ContextBuilder(
                    system_context=DEFAULT_SYSTEM_CONTEXT,
                    warning_tokens=self._setting_int(settings, "context.warning_tokens", 6000, minimum=1),
                ).build_from_formatted_context(
                    system_context=DEFAULT_SYSTEM_CONTEXT,
                    persona_text=self.persona.build_context(active_persona) if active_persona else "",
                    memory_text=optimized.get("Memory", format_memory_context(matched_memories)),
                    knowledge_text=optimized.get("Knowledge", format_knowledge_context(matched_knowledge)),
                )
                # Same four sections as legacy build_memory_context. History is
                # structured ChatSession messages, NOT appended to this string.
                system_context = "\n\n".join(section["content"] for section in package["sections"][:4]
                                             if section.get("content"))
                if not (active_persona or matched_memories or matched_knowledge or any(optimized.values())):
                    # Explicit no-context baseline preserves V4-3C's existing system.
                    system_context = ""
        except (ContextCancelled, ContextPreparationError) as error:
            error.diagnostics = report()
            raise

        return ContextSnapshot(system_context, MappingProxyType(report()), conversation_id,
                               generation_id, prompt, history, settings)

    @staticmethod
    def _setting_int(settings, key, default, *, minimum=0):
        try:
            return max(minimum, int(settings.get(key, default)))
        except (TypeError, ValueError):
            return default

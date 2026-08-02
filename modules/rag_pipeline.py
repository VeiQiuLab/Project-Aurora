"""Independent orchestration core for normalized RAG context results."""

from copy import deepcopy

from modules.context_optimizer import optimize_context
from modules.diagnostics import create_diagnostics
from modules.rag_ranker import rank_results
from modules.rag_results import deduplicate_results, normalize_results


class RAGPipeline:
    """Connect RAG result processing stages without performing retrieval."""

    def run(self, memory_results=None, knowledge_results=None, config=None):
        settings = config if isinstance(config, dict) else {}
        enabled = {
            "dedup": settings.get("enable_dedup", True),
            "ranking": settings.get("enable_ranking", True),
            "optimization": settings.get("enable_optimization", True),
        }
        raw = {
            "memory": deepcopy(memory_results) if isinstance(memory_results, list) else [],
            "knowledge": deepcopy(knowledge_results) if isinstance(knowledge_results, list) else [],
        }
        processed = {}
        warnings = []
        fallback_stage = ""

        for section, items in raw.items():
            try:
                processed[section] = normalize_results(items, source_kind=section)
            except Exception as error:
                processed[section] = deepcopy(items)
                warnings.append(f"{section} normalization failed: {error}")
                fallback_stage = fallback_stage or "normalization"

        normalized_count = sum(len(items) for items in processed.values())
        deduplicated = {}
        for section, items in processed.items():
            if not enabled["dedup"]:
                deduplicated[section] = deepcopy(items)
                continue
            try:
                deduplicated[section] = deduplicate_results(items)
            except Exception as error:
                deduplicated[section] = deepcopy(items)
                warnings.append(f"{section} duplicate filtering failed: {error}")
                fallback_stage = fallback_stage or "deduplication"

        deduplicated_count = sum(len(items) for items in deduplicated.values())
        ranked = {}
        for section, items in deduplicated.items():
            if not enabled["ranking"]:
                ranked[section] = deepcopy(items)
                continue
            try:
                ranked[section] = rank_results(
                    items,
                    section=section,
                    weights=settings.get(f"{section}_ranking_weights"),
                )
            except Exception as error:
                ranked[section] = deepcopy(items)
                warnings.append(f"{section} ranking failed: {error}")
                fallback_stage = fallback_stage or "ranking"

        ranked_count = sum(len(items) for items in ranked.values())
        base_sections = self._build_sections(ranked)
        if enabled["optimization"]:
            try:
                optimized = optimize_context(
                    base_sections,
                    max_tokens=settings.get("max_tokens", 4000),
                    budget=settings.get("section_budget"),
                )
                sections = optimized.get("sections", base_sections)
            except Exception as error:
                sections = base_sections
                warnings.append(f"context optimization failed: {error}")
                fallback_stage = fallback_stage or "optimization"
        else:
            sections = base_sections

        optimized_count = sum(
            len(section.get("items", []))
            for section in sections
            if isinstance(section, dict)
        )
        diagnostics = create_diagnostics(
            stage="rag_pipeline",
            success=not bool(fallback_stage),
            reason=(f"Fallback used at {fallback_stage}." if fallback_stage else ""),
            warnings=warnings,
            metrics={
                "memory_input": len(raw["memory"]),
                "knowledge_input": len(raw["knowledge"]),
                "normalized_count": normalized_count,
                "deduplicated_count": deduplicated_count,
                "ranked_count": ranked_count,
                "optimized_count": optimized_count,
            },
            trace={
                "enabled_stages": enabled,
                "fallback_stage": fallback_stage,
                "sections": [section.get("name", "") for section in sections],
            },
        )
        return {"sections": sections, "diagnostics": diagnostics}

    @staticmethod
    def _build_sections(ranked):
        sections = []
        for key, label in (("memory", "Memory"), ("knowledge", "Knowledge")):
            items = deepcopy(ranked.get(key, []))
            content = "\n".join(
                str(item.get("content", "")).strip()
                for item in items
                if isinstance(item, dict) and str(item.get("content", "")).strip()
            )
            sections.append({
                "name": label,
                "enabled": bool(content),
                "content": content,
                "items": items,
            })
        return sections


def run_rag_pipeline(memory_results=None, knowledge_results=None, config=None):
    """Run the RAG processing core without retrieval or runtime integration."""

    return RAGPipeline().run(
        memory_results=memory_results,
        knowledge_results=knowledge_results,
        config=config,
    )

"""Runtime adapter for optional RAG pipeline integration."""

from copy import deepcopy
import time

from modules.diagnostics import create_diagnostics
from modules.rag_pipeline import run_rag_pipeline


def run_rag_pipeline_with_fallback(
    memory_results,
    knowledge_results,
    *,
    enabled=False,
    config=None,
    pipeline_runner=None,
    logger=None,
):
    """Run the optional pipeline while preserving the legacy result path."""

    original_memory = deepcopy(memory_results) if isinstance(memory_results, list) else []
    original_knowledge = deepcopy(knowledge_results) if isinstance(knowledge_results, list) else []
    pipeline_memory = _prepare_rag_inputs(original_memory)
    pipeline_knowledge = _prepare_rag_inputs(original_knowledge)
    started_at = time.perf_counter()
    metrics = {
        "pipeline_enabled": bool(enabled),
        "memory_input": len(original_memory),
        "knowledge_input": len(original_knowledge),
        "optimized_count": 0,
    }
    if not enabled:
        return {
            "memory_results": original_memory,
            "knowledge_results": original_knowledge,
            "sections": [],
            "diagnostics": create_diagnostics(
                stage="rag_runtime_integration",
                reason="RAG pipeline disabled.",
                metrics=metrics,
                trace={"fallback_stage": "disabled", "elapsed_ms": _elapsed_ms(started_at)},
            ),
        }

    try:
        runner = pipeline_runner or run_rag_pipeline
        result = runner(
            memory_results=pipeline_memory,
            knowledge_results=pipeline_knowledge,
            config=config,
        )
        result = result if isinstance(result, dict) else {}
        pipeline_diagnostics = result.get("diagnostics")
        pipeline_metrics = pipeline_diagnostics.get("metrics", {}) if isinstance(pipeline_diagnostics, dict) else {}
        metrics.update({
            key: pipeline_metrics[key]
            for key in ("normalized_count", "deduplicated_count", "ranked_count", "optimized_count")
            if key in pipeline_metrics
        })
        sections = deepcopy(result.get("sections", []))
        metrics["optimized_count"] = pipeline_metrics.get("optimized_count", _section_item_count(sections))
        warnings = pipeline_diagnostics.get("warnings", []) if isinstance(pipeline_diagnostics, dict) else []
        pipeline_success = pipeline_diagnostics.get("success", True) if isinstance(pipeline_diagnostics, dict) else True
        return {
            "memory_results": original_memory,
            "knowledge_results": original_knowledge,
            "sections": sections,
            "diagnostics": create_diagnostics(
                stage="rag_runtime_integration",
                success=bool(pipeline_success),
                reason="" if pipeline_success else "RAG pipeline reported a fallback.",
                warnings=warnings,
                metrics=metrics,
                trace={
                    "fallback_stage": (
                        pipeline_diagnostics.get("trace", {}).get("fallback_stage", "")
                        if isinstance(pipeline_diagnostics, dict)
                        else ""
                    ),
                    "elapsed_ms": _elapsed_ms(started_at),
                    "enabled_stages": (
                        pipeline_diagnostics.get("trace", {}).get("enabled_stages", {})
                        if isinstance(pipeline_diagnostics, dict)
                        else {}
                    ),
                },
            ),
        }
    except Exception as error:
        if logger:
            try:
                logger.error(f"RAG runtime integration failed: {error}")
            except Exception:
                pass
        return {
            "memory_results": original_memory,
            "knowledge_results": original_knowledge,
            "sections": [],
            "diagnostics": create_diagnostics(
                stage="rag_runtime_integration",
                success=False,
                reason="RAG pipeline integration failed; legacy context retained.",
                warnings=[str(error)],
                metrics=metrics,
                trace={"fallback_stage": "pipeline", "elapsed_ms": _elapsed_ms(started_at)},
            ),
        }


def _section_item_count(sections):
    return sum(
        len(section.get("items", []))
        for section in sections or []
        if isinstance(section, dict)
    )


def _prepare_rag_inputs(results):
    """Copy enriched retrieval metadata without inventing unavailable scores."""

    prepared = []
    for result in results:
        item = deepcopy(result) if isinstance(result, dict) else result
        if isinstance(item, dict) and isinstance(item.get("score_details"), dict):
            item["score_details"] = deepcopy(item["score_details"])
        prepared.append(item)
    return prepared


def _elapsed_ms(started_at):
    return int((time.perf_counter() - started_at) * 1000)

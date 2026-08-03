"""Read-only explanation and citation builders for Aurora decisions."""

from copy import deepcopy

from modules.diagnostics import create_diagnostics


EXPLANATION_VERSION = "explainability_v1"


def create_explanation(
    *,
    reason="",
    sources=None,
    ranking_factors=None,
    confidence=None,
    warnings=None,
    diagnostics=None,
):
    """Create a detached, serializable explanation record."""

    normalized_sources = deepcopy(sources) if isinstance(sources, list) else []
    normalized_warnings = list(warnings) if isinstance(warnings, list) else []
    if diagnostics is None:
        diagnostics = create_diagnostics(
            stage="explainability",
            metrics={
                "sources_count": len(normalized_sources),
                "memory_refs": sum(
                    1 for source in normalized_sources
                    if isinstance(source, dict) and source.get("source_type") == "memory"
                ),
                "warnings": len(normalized_warnings),
            },
        )
    return {
        "explanation_version": EXPLANATION_VERSION,
        "reason": str(reason or ""),
        "sources": normalized_sources,
        "ranking_factors": deepcopy(ranking_factors) if isinstance(ranking_factors, dict) else {},
        "confidence": confidence,
        "warnings": normalized_warnings,
        "diagnostics": _diagnostics_summary(diagnostics),
    }


def build_citation(record, *, source_kind=None):
    """Build one citation from existing source and provenance fields only."""

    if not isinstance(record, dict):
        return {}
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    kind = str(source.get("kind") or source_kind or "").casefold()
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    if kind == "memory":
        return {
            "source_type": "memory",
            "memory_id": str(source.get("memory_id") or record.get("id") or ""),
            "conversation_id": str(metadata.get("conversation_id") or ""),
            "signal_type": str(metadata.get("signal_type") or ""),
        }
    if kind == "knowledge":
        return {
            "source_type": "knowledge",
            "source_id": str(source.get("id") or record.get("id") or ""),
            "title": str(source.get("file_name") or source.get("name") or record.get("file_name") or ""),
            "location": str(source.get("source_path") or source.get("path") or ""),
            "chunk_id": source.get("chunk_id"),
        }
    return {}


def explain_rag_result(result, *, diagnostics=None):
    """Explain one normalized or legacy RAG result without changing it."""

    if not isinstance(result, dict):
        return _safe_failure("invalid_input")
    warnings = []
    warnings.extend(_diagnostic_warnings(diagnostics))
    citation = build_citation(result)
    if not citation:
        warnings.append("source_metadata_missing")
    ranking = result.get("ranking_details")
    ranking = deepcopy(ranking) if isinstance(ranking, dict) else {}
    if not ranking:
        warnings.append("ranking_details_unavailable")
    reason = str(ranking.get("reason") or "")
    if not reason:
        warnings.append("ranking_reason_unavailable")
    confidence = _existing_confidence(result)
    if confidence is None:
        warnings.append("confidence_unavailable")
    explanation = create_explanation(
        reason=reason,
        sources=[citation] if citation else [],
        ranking_factors=ranking,
        confidence=confidence,
        warnings=warnings,
        diagnostics=diagnostics,
    )
    return explanation


def explain_memory(memory, *, diagnostics=None):
    """Explain one Memory record using stored evaluation and provenance."""

    if not isinstance(memory, dict):
        return _safe_failure("invalid_input")
    warnings = []
    warnings.extend(_diagnostic_warnings(diagnostics))
    citation = build_citation(memory, source_kind="memory")
    metadata = memory.get("metadata") if isinstance(memory.get("metadata"), dict) else {}
    if not metadata:
        warnings.append("memory_metadata_missing")
    if not citation.get("conversation_id"):
        warnings.append("conversation_provenance_missing")
    confidence = memory.get("confidence", metadata.get("confidence"))
    if confidence is None:
        warnings.append("confidence_unavailable")
    reason = str(memory.get("explanation") or metadata.get("explanation") or "")
    if not reason:
        warnings.append("memory_explanation_unavailable")
    if not isinstance(memory.get("approval_history"), list):
        warnings.append("approval_history_unavailable")
    ranking_factors = {
        key: deepcopy(memory[key])
        for key in (
            "importance",
            "importance_score",
            "risk",
            "status",
            "created_time",
            "updated_time",
        )
        if key in memory
    }
    if not ranking_factors:
        ranking_factors = {
            key: deepcopy(metadata[key])
            for key in (
                "importance",
                "importance_score",
                "risk",
                "status",
                "created_time",
                "updated_time",
            )
            if key in metadata
        }
    if diagnostics is None:
        diagnostics = create_diagnostics(
            stage="memory_explainability",
            metrics={
                "memory_refs": 1 if citation else 0,
                "warnings": len(_unique_strings(warnings)),
            },
        )
    return create_explanation(
        reason=reason,
        sources=[citation] if citation else [],
        ranking_factors=ranking_factors,
        confidence=confidence,
        warnings=warnings,
        diagnostics=diagnostics,
    )


def explain_rag_pipeline(result):
    """Explain selected items from an existing RAG pipeline result."""

    if not isinstance(result, dict):
        return _safe_failure("invalid_input")
    try:
        sections = result.get("sections")
        sections = sections if isinstance(sections, list) else []
        pipeline_diagnostics = result.get("diagnostics")
        pipeline_diagnostics = (
            pipeline_diagnostics if isinstance(pipeline_diagnostics, dict) else {}
        )
        warnings = []
        warnings.extend(pipeline_diagnostics.get("warnings", []))
        sources = []
        ranking_factors = {}
        selected_sections = []
        for section_index, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            section_name = str(section.get("name") or "")
            selected_sections.append(section_name)
            items = section.get("items") if isinstance(section.get("items"), list) else []
            for item_index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                citation = build_citation(item, source_kind=section_name.casefold())
                if not isinstance(item.get("source"), dict):
                    warnings.append("source_metadata_missing")
                if citation:
                    sources.append(citation)
                else:
                    warnings.append("source_metadata_missing")
                ranking = item.get("ranking_details")
                ranking = deepcopy(ranking) if isinstance(ranking, dict) else {}
                if not ranking or not ranking.get("reason"):
                    warnings.append("ranking_reason_unavailable")
                ranking_factors[f"{section_name}:{item_index}"] = {
                    "score": item.get("score"),
                    "rank_score": item.get("rank_score"),
                    "ranking_details": ranking,
                }

        trace = pipeline_diagnostics.get("trace")
        if not isinstance(trace, dict):
            warnings.append("trimming_trace_unavailable")
            warnings.append("duplicate_trace_unavailable")
        else:
            if not trace.get("trimming_trace"):
                warnings.append("trimming_trace_unavailable")
            if not trace.get("duplicate_trace"):
                warnings.append("duplicate_trace_unavailable")
        warnings = _unique_strings(warnings)
        memory_refs = sum(
            1 for source in sources if source.get("source_type") == "memory"
        )
        pipeline_metrics = pipeline_diagnostics.get("metrics")
        pipeline_metrics = pipeline_metrics if isinstance(pipeline_metrics, dict) else {}
        selected_items = sum(
            len(section.get("items", []))
            for section in sections
            if isinstance(section, dict) and isinstance(section.get("items"), list)
        )
        metrics = {
            "sources_count": len(sources),
            "selected_items": selected_items,
            "memory_refs": memory_refs,
            "warnings": len(warnings),
        }
        for key in ("normalized_count", "deduplicated_count", "ranked_count", "optimized_count"):
            if key in pipeline_metrics:
                metrics[key] = pipeline_metrics[key]
        diagnostics = create_diagnostics(
            stage="rag_explainability",
            success=bool(pipeline_diagnostics.get("success", True)),
            reason=pipeline_diagnostics.get("reason", ""),
            warnings=warnings,
            metrics=metrics,
            trace={
                "pipeline_stage": pipeline_diagnostics.get("stage", ""),
                "sections": selected_sections,
            },
        )
        return create_explanation(
            reason=(
                pipeline_diagnostics.get("reason", "")
                or "Selected sources preserved from optimized RAG sections."
            ),
            sources=sources,
            ranking_factors=ranking_factors,
            warnings=warnings,
            diagnostics=diagnostics,
        )
    except Exception:
        return _safe_failure("explainability_failure")


class Explainability:
    """Convenience facade for the read-only explanation helpers."""

    create = staticmethod(create_explanation)
    citation = staticmethod(build_citation)
    rag = staticmethod(explain_rag_result)
    rag_pipeline = staticmethod(explain_rag_pipeline)
    memory = staticmethod(explain_memory)


def _existing_confidence(result):
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    details = result.get("score_details") if isinstance(result.get("score_details"), dict) else {}
    return result.get("confidence", details.get("confidence", metadata.get("confidence")))


def _diagnostics_summary(diagnostics):
    if not isinstance(diagnostics, dict):
        return {}
    return {
        "stage": diagnostics.get("stage", ""),
        "success": bool(diagnostics.get("success", True)),
        "reason": diagnostics.get("reason", ""),
        "warnings": deepcopy(diagnostics.get("warnings", [])) if isinstance(diagnostics.get("warnings"), list) else [],
        "metrics": deepcopy(diagnostics.get("metrics", {})) if isinstance(diagnostics.get("metrics"), dict) else {},
        "trace": deepcopy(diagnostics.get("trace", {})) if isinstance(diagnostics.get("trace"), dict) else {},
    }


def _diagnostic_warnings(diagnostics):
    if not isinstance(diagnostics, dict):
        return []
    warnings = []
    trace = diagnostics.get("trace")
    if not isinstance(trace, dict):
        warnings.append("trace_unavailable")
    elif trace.get("fallback_stage"):
        warnings.append("fallback_used")
    return warnings


def _unique_strings(values):
    unique = []
    for value in values:
        value = str(value)
        if value and value not in unique:
            unique.append(value)
    return unique


def _safe_failure(reason):
    return create_explanation(
        reason="",
        warnings=[reason],
        diagnostics=create_diagnostics(
            stage="explainability",
            success=False,
            reason=reason,
            metrics={"sources_count": 0, "memory_refs": 0, "warnings": 1},
        ),
    )

"""Runtime adapter for optional RAG pipeline integration."""

from copy import deepcopy
import time

from modules.context_policy import build_context_policy
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
    query="",
    conversation_state=None,
    available_context=None,
    budget=None,
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
    adaptive_enabled = _adaptive_enabled(config)
    policy_config, policy_info = _context_policy_config(
        config=config,
        adaptive_enabled=adaptive_enabled,
        query=query,
        conversation_state=conversation_state,
        available_context=available_context,
        budget=budget,
        input_context_count=len(original_memory) + len(original_knowledge),
    )
    metrics.update(policy_info["metrics"])
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
        runner_config = deepcopy(config) if isinstance(config, dict) else config
        if policy_config is not None:
            if not isinstance(runner_config, dict):
                runner_config = {}
            runner_config.update(policy_config)
        result = runner(
            memory_results=pipeline_memory,
            knowledge_results=pipeline_knowledge,
            config=runner_config,
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
        warnings = list(warnings) + list(policy_info["warnings"])
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
                    "context_policy": policy_info["trace"],
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
                trace={
                    "fallback_stage": "pipeline",
                    "elapsed_ms": _elapsed_ms(started_at),
                    "context_policy": policy_info["trace"],
                },
            ),
        }


def _section_item_count(sections):
    return sum(
        len(section.get("items", []))
        for section in sections or []
        if isinstance(section, dict)
    )


def _adaptive_enabled(config):
    settings = config if isinstance(config, dict) else {}
    return bool(settings.get("context.adaptive_enabled", settings.get("adaptive_enabled", False)))


def _context_policy_config(
    *,
    config,
    adaptive_enabled,
    query,
    conversation_state,
    available_context,
    budget,
    input_context_count,
):
    metrics = {
        "adaptive_enabled": bool(adaptive_enabled),
        "input_context_count": input_context_count,
        "allocated_budget": 0,
        "fallback": False,
    }
    if not adaptive_enabled:
        return None, {
            "metrics": metrics,
            "warnings": [],
            "trace": {"selected_policy": "static", "priority_order": []},
        }

    settings = config if isinstance(config, dict) else {}
    policy_budget = deepcopy(budget) if isinstance(budget, dict) else {}
    policy_budget.setdefault("total_budget", settings.get("max_tokens", 4000))
    policy_budget.setdefault("reserved_output", settings.get("reserved_output", 0))
    state = {
        "query": query if isinstance(query, str) else "",
        "conversation_state": deepcopy(conversation_state) if isinstance(conversation_state, dict) else {},
        "available_context": (
            deepcopy(available_context)
            if isinstance(available_context, dict)
            else {
                "memory_count": input_context_count,
                "knowledge_count": 0,
                "conversation_count": 0,
            }
        ),
        "budget": policy_budget,
        "adaptive_enabled": True,
    }
    try:
        policy = build_context_policy(state)
        if not _valid_policy(policy, policy_budget):
            raise ValueError("Invalid context policy output.")
        allocated = sum(
            int(policy.get(key, 0))
            for key in ("memory_budget", "knowledge_budget", "conversation_budget")
        )
        metrics["allocated_budget"] = allocated
        diagnostics = policy.get("diagnostics") if isinstance(policy.get("diagnostics"), dict) else {}
        if diagnostics.get("success") is False or diagnostics.get("metrics", {}).get("fallback"):
            raise ValueError(diagnostics.get("reason") or "Context policy fallback reported.")
        return {
            "section_budget": {
                "Memory": int(policy["memory_budget"]),
                "Knowledge": int(policy["knowledge_budget"]),
                "Conversation": int(policy["conversation_budget"]),
            }
        }, {
            "metrics": metrics,
            "warnings": list(diagnostics.get("warnings", [])) if isinstance(diagnostics.get("warnings"), list) else [],
            "trace": {
                "selected_policy": "adaptive",
                "priority_order": deepcopy(policy.get("priority_order", [])),
                "policy_reason": str(policy.get("policy_reason", "")),
                "section_budget": {
                    "memory": int(policy["memory_budget"]),
                    "knowledge": int(policy["knowledge_budget"]),
                    "conversation": int(policy["conversation_budget"]),
                },
                "policy_diagnostics": deepcopy(diagnostics),
            },
        }
    except Exception as error:
        metrics["fallback"] = True
        return None, {
            "metrics": metrics,
            "warnings": ["context_policy_fallback", str(error)],
            "trace": {
                "selected_policy": "static_fallback",
                "priority_order": ["memory", "knowledge", "conversation"],
                "fallback_reason": str(error),
            },
        }


def _valid_policy(policy, budget):
    if not isinstance(policy, dict):
        return False
    keys = ("memory_budget", "knowledge_budget", "conversation_budget")
    try:
        values = [int(policy.get(key, -1)) for key in keys]
        total = max(0, int(budget.get("total_budget", 0)))
        reserved = max(0, int(budget.get("reserved_output", 0)))
    except (TypeError, ValueError):
        return False
    if any(value < 0 for value in values):
        return False
    return sum(values) <= max(0, total - min(total, reserved))


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

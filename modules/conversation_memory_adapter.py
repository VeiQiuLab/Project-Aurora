"""Convert conversation memory signals into reviewable Memory candidates."""

from copy import deepcopy
import re

from modules.diagnostics import create_diagnostics


VALID_MEMORY_TYPES = {"preference", "fact", "instruction"}
VALID_IMPORTANCE = {"low", "normal", "high"}


def adapt_memory_signals(memory_signals, *, conversation_id=None):
    """Adapt signals without storage, model calls, or MemoryStore access."""

    return ConversationMemoryAdapter().adapt(
        memory_signals,
        conversation_id=conversation_id,
    )


def queue_conversation_memory_candidates(memory_store, memory_signals, *, conversation_id=None):
    """Evaluate adapted signals and persist them as pending candidates only."""

    input_count = len(memory_signals) if isinstance(memory_signals, list) else 0
    metrics = {
        "signals_input": input_count,
        "candidates_created": 0,
        "evaluated": 0,
        "stored_pending": 0,
        "unevaluated": 0,
    }
    try:
        adapted = adapt_memory_signals(memory_signals, conversation_id=conversation_id)
        adapter_diagnostics = adapted.get("diagnostics", {})
        candidates = adapted.get("candidates", [])
        metrics["candidates_created"] = len(candidates)
        if not adapter_diagnostics.get("success", True):
            return {
                "candidates": [],
                "diagnostics": create_diagnostics(
                    stage="memory_candidate_pipeline",
                    success=False,
                    reason=adapter_diagnostics.get("reason", "Adapter failed."),
                    warnings=adapter_diagnostics.get("warnings", []),
                    metrics=metrics,
                ),
            }

        from modules.memory_intelligence import analyze_memory_candidates

        evaluated = []
        for candidate in candidates:
            try:
                results = analyze_memory_candidates(
                    "",
                    base_candidates=[candidate],
                    min_score=0,
                    source="conversation",
                )
                if not results:
                    raise ValueError("MemoryIntelligence returned no candidate.")
                result = results[0]
                result["evaluation_status"] = "evaluated"
                evaluated.append(result)
                metrics["evaluated"] += 1
            except Exception as error:
                failed = deepcopy(candidate)
                failed["evaluation_status"] = "unevaluated"
                failed["evaluation_error"] = str(error)
                evaluated.append(failed)
                metrics["unevaluated"] += 1

        stored = memory_store.queue_candidate_records(evaluated)
        metrics["stored_pending"] = len(stored)
        return {
            "candidates": stored,
            "diagnostics": create_diagnostics(
                stage="memory_candidate_pipeline",
                success=True,
                metrics=metrics,
            ),
        }
    except Exception as error:
        return {
            "candidates": [],
            "diagnostics": create_diagnostics(
                stage="memory_candidate_pipeline",
                success=False,
                reason="Pending candidate pipeline failed.",
                warnings=[str(error)],
                metrics=metrics,
            ),
        }


class ConversationMemoryAdapter:
    """Validate and convert one conversation analysis signal batch."""

    def adapt(self, memory_signals, *, conversation_id=None):
        metrics = {
            "signals_input": len(memory_signals) if isinstance(memory_signals, list) else 0,
            "candidates_created": 0,
            "filtered_invalid": 0,
            "filtered_duplicates": 0,
        }
        if not isinstance(memory_signals, list):
            return {
                "candidates": [],
                "diagnostics": create_diagnostics(
                    stage="conversation_memory_adapter",
                    success=False,
                    reason="memory_signals must be a list.",
                    metrics=metrics,
                ),
            }

        try:
            candidates = []
            seen = set()
            for signal in memory_signals:
                candidate = self._convert_signal(signal, conversation_id)
                if candidate is None:
                    metrics["filtered_invalid"] += 1
                    continue
                key = candidate["content"]
                if key in seen:
                    metrics["filtered_duplicates"] += 1
                    continue
                seen.add(key)
                candidates.append(candidate)
            metrics["candidates_created"] = len(candidates)
            return {
                "candidates": candidates,
                "diagnostics": create_diagnostics(
                    stage="conversation_memory_adapter",
                    metrics=metrics,
                ),
            }
        except Exception as error:
            return {
                "candidates": [],
                "diagnostics": create_diagnostics(
                    stage="conversation_memory_adapter",
                    success=False,
                    reason="Conversation memory signal adaptation failed.",
                    warnings=[str(error)],
                    metrics=metrics,
                ),
            }

    @staticmethod
    def _convert_signal(signal, conversation_id):
        if not isinstance(signal, dict):
            return None
        content = re.sub(r"\s+", " ", str(signal.get("content", ""))).strip()
        signal_type = str(signal.get("type", "")).strip().casefold()
        if not content or signal_type not in VALID_MEMORY_TYPES:
            return None

        candidate = {
            "content": content,
            "source": "conversation",
            "metadata": {
                "conversation_id": str(conversation_id or ""),
                "signal_type": signal_type,
            },
        }
        importance = signal.get("importance")
        if isinstance(importance, str) and importance.casefold() in VALID_IMPORTANCE:
            candidate["importance"] = importance.casefold()
        confidence = signal.get("confidence")
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            if 0.0 <= float(confidence) <= 1.0:
                candidate["confidence"] = confidence
        return deepcopy(candidate)

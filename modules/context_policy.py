"""Deterministic context allocation policy, independent from runtime assembly."""

from copy import deepcopy

from modules.diagnostics import create_diagnostics


SECTION_NAMES = ("memory", "knowledge", "conversation")
STATIC_WEIGHTS = {"memory": 0.4, "knowledge": 0.4, "conversation": 0.2}


class ContextPolicy:
    """Calculate bounded context budgets without retrieval or model calls."""

    def decide(self, context=None):
        try:
            state = deepcopy(context) if isinstance(context, dict) else {}
            budget = state.get("budget") if isinstance(state.get("budget"), dict) else {}
            available = state.get("available_context")
            available = available if isinstance(available, dict) else {}
            conversation = state.get("conversation_state")
            conversation = conversation if isinstance(conversation, dict) else {}
            query = state.get("query")
            query_text = query if isinstance(query, str) else ""
            total_budget, reserved_output, budget_warning = self._budget_values(budget)
            usable_budget = max(0, total_budget - reserved_output)
            adaptive_enabled = bool(
                state.get("adaptive_enabled", budget.get("adaptive_enabled", False))
            )
            counts = self._counts(available)
            message_count = self._number(conversation.get("message_count"), 0)
            if adaptive_enabled:
                weights, reason_parts = self._adaptive_weights(
                    query_text, counts, message_count
                )
                policy_name = "adaptive"
            else:
                weights = dict(STATIC_WEIGHTS)
                reason_parts = ["static section priorities"]
                policy_name = "static"
            allocations = self._allocate(usable_budget, weights)
            warnings = [budget_warning] if budget_warning else []
            diagnostics = create_diagnostics(
                stage="context_policy",
                success=True,
                warnings=warnings,
                metrics={
                    "adaptive_enabled": adaptive_enabled,
                    "total_budget": total_budget,
                    "allocated_budget": sum(allocations.values()),
                    "fallback": False,
                },
                trace={
                    "selected_policy": policy_name,
                    "reason_summary": "; ".join(reason_parts),
                },
            )
            return {
                "memory_budget": allocations["memory"],
                "knowledge_budget": allocations["knowledge"],
                "conversation_budget": allocations["conversation"],
                "priority_order": (
                    list(SECTION_NAMES)
                    if not adaptive_enabled
                    else self._priority_order(weights, counts)
                ),
                "policy_reason": "; ".join(reason_parts),
                "diagnostics": diagnostics,
            }
        except Exception as error:
            return self._fallback(str(error))

    def static_policy(self, context=None):
        state = deepcopy(context) if isinstance(context, dict) else {}
        state["adaptive_enabled"] = False
        return self.decide(state)

    @staticmethod
    def _budget_values(budget):
        warning = ""
        try:
            total = max(0, int(budget.get("total_budget", 0)))
            if int(budget.get("total_budget", 0)) < 0:
                warning = "invalid_total_budget"
        except (TypeError, ValueError):
            total = 0
            warning = "invalid_total_budget"
        try:
            reserved = max(0, int(budget.get("reserved_output", 0)))
        except (TypeError, ValueError):
            reserved = 0
            warning = warning or "invalid_reserved_output"
        return total, min(total, reserved), warning

    @staticmethod
    def _number(value, default=0):
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return default

    @classmethod
    def _counts(cls, available):
        return {
            name: cls._number(available.get(f"{name}_count"), 0)
            for name in SECTION_NAMES
        }

    @staticmethod
    def _adaptive_weights(query, counts, message_count):
        weights = dict(STATIC_WEIGHTS)
        reasons = ["adaptive section priorities"]
        query_words = set(str(query).casefold().split())
        memory_words = {"memory", "remember", "preference", "user", "history"}
        knowledge_words = {"knowledge", "document", "docs", "file", "source"}
        if counts["memory"] > counts["knowledge"]:
            weights = {"memory": 0.5, "knowledge": 0.3, "conversation": 0.2}
            reasons.append("memory context is dominant")
        elif counts["knowledge"] > counts["memory"]:
            weights = {"memory": 0.3, "knowledge": 0.5, "conversation": 0.2}
            reasons.append("knowledge context is dominant")
        if query_words.intersection(memory_words):
            weights = {"memory": 0.6, "knowledge": 0.25, "conversation": 0.15}
            reasons.append("query contains memory-oriented terms")
        elif query_words.intersection(knowledge_words):
            weights = {"memory": 0.25, "knowledge": 0.6, "conversation": 0.15}
            reasons.append("query contains knowledge-oriented terms")
        if len(query_words) <= 4:
            weights["conversation"] = min(weights["conversation"], 0.1)
            reasons.append("short query reduces conversation allocation")
        if message_count >= 12:
            weights["conversation"] = min(weights["conversation"], 0.1)
            reasons.append("long conversation reduces conversation allocation")
        weights = ContextPolicy._redistribute(weights)
        return weights, reasons

    @staticmethod
    def _redistribute(weights):
        weights = {name: max(0.0, float(weights.get(name, 0))) for name in SECTION_NAMES}
        total = sum(weights.values()) or 1.0
        return {name: weights[name] / total for name in SECTION_NAMES}

    @staticmethod
    def _allocate(budget, weights):
        allocations = {name: int(budget * weights[name]) for name in SECTION_NAMES}
        remainder = budget - sum(allocations.values())
        order = sorted(SECTION_NAMES, key=lambda name: (-weights[name], SECTION_NAMES.index(name)))
        for index in range(remainder):
            allocations[order[index % len(order)]] += 1
        return allocations

    @staticmethod
    def _priority_order(weights, counts):
        return sorted(
            SECTION_NAMES,
            key=lambda name: (-weights[name], -counts[name], SECTION_NAMES.index(name)),
        )

    @staticmethod
    def _fallback(reason):
        diagnostics = create_diagnostics(
            stage="context_policy",
            success=False,
            reason="Context policy fallback used.",
            warnings=[reason or "policy_failure"],
            metrics={
                "adaptive_enabled": False,
                "total_budget": 0,
                "allocated_budget": 0,
                "fallback": True,
            },
            trace={"selected_policy": "static_fallback"},
        )
        return {
            "memory_budget": 0,
            "knowledge_budget": 0,
            "conversation_budget": 0,
            "priority_order": list(SECTION_NAMES),
            "policy_reason": "Static fallback policy.",
            "diagnostics": diagnostics,
        }


def build_context_policy(context=None):
    """Convenience entry point for deterministic context policy decisions."""

    return ContextPolicy().decide(context)

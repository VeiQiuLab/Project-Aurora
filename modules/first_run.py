"""Pure state and validation rules for Aurora's first-run experience.

The UI owns presentation and background threads.  This module owns the
decisions that must remain true even when the UI changes: optional components
can be skipped, embedding-only models never become chat models, placeholders
are never persisted, and completing or closing the wizard is idempotent.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from modules.dependency_actions import validate_ollama_model_name
from modules.models import infer_model_capability


FIRST_RUN_STEPS = ("welcome", "environment", "local_model", "complete")
ENVIRONMENT_KEYS = (
    "aurora_core",
    "ollama",
    "local_ai_service",
    "chat_model",
    "embedding_model",
    "voice",
)
VALID_RUNTIME_STATUSES = {"Ready", "Missing", "Offline", "Optional", "Degraded"}


@dataclass(frozen=True)
class ModelDownloadPlan:
    """A display-ready plan.  Creating it does not start a download."""

    model: str
    approximate_size: str
    reason: str
    recommended: bool
    requires_confirmation: bool = True


def empty_runtime_report() -> dict[str, Any]:
    """Return a safe, Core-ready report while a real check is pending/failed."""

    rows = {
        "aurora_core": _runtime_item("aurora_core", "Aurora Core", "Ready", True),
        "ollama": _runtime_item("ollama", "Ollama", "Missing", False),
        "local_ai_service": _runtime_item(
            "local_ai_service", "Local AI Service", "Offline", False
        ),
        "chat_model": _runtime_item("chat_model", "Chat Model", "Missing", False),
        "embedding_model": _runtime_item(
            "embedding_model", "Embedding", "Optional", False
        ),
        "voice": _runtime_item("voice", "Voice", "Optional", False),
    }
    return {
        "status": "Degraded",
        "core_ready": True,
        "items": list(rows.values()),
        "items_by_key": rows,
        "ollama": {
            "state": "Not Installed",
            "available": False,
            "executable_path": "",
            "models": {"all": [], "chat": [], "embedding": []},
        },
        "hardware": {
            "ram_gb": None,
            "cpu": "unknown",
            "logical_cores": None,
            "gpu": None,
            "vram_gb": None,
            "vram_status": "unknown",
            "disk_free_gb": None,
        },
        "recommendation": {
            "tier": "Lightweight",
            "model": "qwen3:4b",
            "parameter_range": "3B/4B",
            "approximate_download_gb": 2.6,
            "reason": "A conservative recommendation until hardware is checked.",
            "existing_model": False,
            "download_required": True,
            "can_download": True,
            "requires_user_confirmation": True,
        },
    }


class FirstRunController:
    """Side-effect-free state machine shared by first-run UI and tests."""

    def __init__(
        self,
        report: Mapping[str, Any] | None = None,
        *,
        configured_chat_model: str = "",
        configured_embedding_model: str = "",
    ):
        self.step_index = 0
        self.configured_chat_model = _clean_model(configured_chat_model)
        self.configured_embedding_model = _clean_model(configured_embedding_model)
        self.selected_chat_model = ""
        self.selected_embedding_model = ""
        self.model_decision = "pending"
        self.download_status = "idle"
        self.download_message = ""
        self._download_model = ""
        self.report: dict[str, Any] = {}
        self.chat_models: list[dict[str, Any]] = []
        self.embedding_models: list[dict[str, Any]] = []
        self.apply_report(report or empty_runtime_report())

    @property
    def step(self) -> str:
        return FIRST_RUN_STEPS[self.step_index]

    def next_step(self) -> str:
        if self.step == "local_model" and self.model_decision == "pending":
            self.accept_recommended_existing_or_skip()
        self.step_index = min(self.step_index + 1, len(FIRST_RUN_STEPS) - 1)
        return self.step

    def previous_step(self) -> str:
        self.step_index = max(0, self.step_index - 1)
        return self.step

    def apply_report(self, report: Mapping[str, Any] | None) -> None:
        """Replace diagnostics while preserving only still-valid selections."""

        source = deepcopy(dict(report or empty_runtime_report()))
        baseline = empty_runtime_report()
        source.setdefault("core_ready", True)
        source.setdefault("items_by_key", {})
        source.setdefault("ollama", baseline["ollama"])
        source.setdefault("hardware", baseline["hardware"])
        source.setdefault("recommendation", baseline["recommendation"])

        raw_models = source.get("ollama", {}).get("models", {})
        all_models: list[Any] = []
        if isinstance(raw_models, Mapping):
            all_models.extend(_as_model_list(raw_models.get("all")))
            if not all_models:
                all_models.extend(_as_model_list(raw_models.get("chat")))
                all_models.extend(_as_model_list(raw_models.get("embedding")))
        self.chat_models, self.embedding_models = _classify_models(all_models)

        if self.selected_chat_model and not self.is_existing_chat_model(
            self.selected_chat_model
        ) and self.model_decision != "downloaded":
            self.selected_chat_model = ""
        if self.selected_embedding_model and not self.is_embedding_model(
            self.selected_embedding_model
        ):
            self.selected_embedding_model = ""

        if not self.selected_chat_model:
            if self.is_existing_chat_model(self.configured_chat_model):
                self.selected_chat_model = self.configured_chat_model
            else:
                resolution = source.get("model_resolution", {})
                resolution = resolution if isinstance(resolution, Mapping) else {}
                chat_resolution = resolution.get("chat", {})
                chat_resolution = (
                    chat_resolution if isinstance(chat_resolution, Mapping) else {}
                )
                resolved = _clean_model(chat_resolution.get("model"))
                recommended = _clean_model(source.get("recommendation", {}).get("model"))
                if self.is_existing_chat_model(resolved):
                    self.selected_chat_model = resolved
                elif self.is_existing_chat_model(recommended):
                    self.selected_chat_model = recommended
                elif self.chat_models:
                    self.selected_chat_model = self.chat_models[0]["name"]

        if not self.selected_embedding_model and self.is_embedding_model(
            self.configured_embedding_model
        ):
            self.selected_embedding_model = self.configured_embedding_model

        source["items_by_key"] = _normalize_environment_items(
            source.get("items_by_key"), source.get("items"), baseline["items_by_key"]
        )
        self.report = source

    def environment_items(self) -> list[dict[str, Any]]:
        rows = self.report.get("items_by_key", {})
        return [deepcopy(rows[key]) for key in ENVIRONMENT_KEYS]

    def hardware(self) -> dict[str, Any]:
        baseline = empty_runtime_report()["hardware"]
        hardware = dict(self.report.get("hardware") or {})
        for key, value in baseline.items():
            hardware.setdefault(key, value)
        if hardware.get("vram_gb") is None:
            hardware["vram_status"] = "unknown"
        return hardware

    def recommendation(self) -> dict[str, Any]:
        result = dict(empty_runtime_report()["recommendation"])
        candidate = self.report.get("recommendation")
        if isinstance(candidate, Mapping):
            result.update(candidate)
        result["model"] = _clean_model(result.get("model")) or "qwen3:4b"
        result["requires_user_confirmation"] = True
        return result

    def existing_chat_names(self) -> list[str]:
        return [item["name"] for item in self.chat_models]

    def existing_embedding_names(self) -> list[str]:
        return [item["name"] for item in self.embedding_models]

    def is_existing_chat_model(self, name: str) -> bool:
        target = _model_key(name)
        return bool(target) and any(
            _model_key(item["name"]) == target for item in self.chat_models
        )

    def is_embedding_model(self, name: str) -> bool:
        target = _model_key(name)
        return bool(target) and any(
            _model_key(item["name"]) == target for item in self.embedding_models
        )

    def use_existing_model(self, name: str) -> str:
        normalized = _clean_model(name)
        if not self.is_existing_chat_model(normalized):
            raise ValueError("The selected model is not an installed chat model.")
        self.selected_chat_model = normalized
        self.model_decision = "use_existing"
        return normalized

    def use_automatically(self) -> str:
        if not self.is_existing_chat_model(self.selected_chat_model):
            raise ValueError("No installed Chat Supported model is available.")
        self.model_decision = "auto"
        return self.selected_chat_model

    def accept_recommended_existing_or_skip(self) -> str:
        if self.is_existing_chat_model(self.selected_chat_model):
            resolution = self.report.get("model_resolution", {})
            chat_resolution = (
                resolution.get("chat", {}) if isinstance(resolution, Mapping) else {}
            )
            self.model_decision = (
                "auto"
                if isinstance(chat_resolution, Mapping)
                and chat_resolution.get("mode") == "auto"
                else "use_existing"
            )
        else:
            self.model_decision = "skipped"
        return self.model_decision

    def skip_model_setup(self) -> None:
        self.model_decision = "skipped"
        self.download_status = "idle"
        self.download_message = ""

    def prepare_download(self, model: str | None = None) -> ModelDownloadPlan:
        recommendation = self.recommendation()
        candidate = validate_ollama_model_name(model or recommendation["model"])
        if infer_model_capability(candidate) != "Chat Supported":
            raise ValueError("Embedding-only models cannot be selected for chat.")
        is_recommended = _model_key(candidate) == _model_key(recommendation["model"])
        size_value = recommendation.get("approximate_download_gb") if is_recommended else None
        approximate_size = (
            f"about {float(size_value):g} GB" if _positive_number(size_value) else "size unknown"
        )
        reason = (
            str(recommendation.get("reason") or "Recommended for this device.")
            if is_recommended
            else "User-selected Ollama chat model; download size depends on the model."
        )
        return ModelDownloadPlan(
            model=candidate,
            approximate_size=approximate_size,
            reason=reason,
            recommended=is_recommended,
        )

    def mark_download_started(self, model: str) -> None:
        plan = self.prepare_download(model)
        self._download_model = plan.model
        self.download_status = "running"
        self.download_message = ""

    def mark_download_result(self, status: str, message: str = "") -> None:
        normalized = str(status or "error").strip().casefold()
        if normalized not in {"success", "error", "cancelled", "confirmation_required"}:
            normalized = "error"
        self.download_status = normalized
        self.download_message = str(message or "")
        if normalized == "success" and self._download_model:
            self.selected_chat_model = self._download_model
            self.model_decision = "downloaded"

    def completion_updates(self) -> dict[str, Any]:
        """Return one idempotent Settings.update_many payload."""

        updates: dict[str, Any] = {"first_run.completed": True}
        if self.model_decision == "auto":
            model = _clean_model(self.selected_chat_model)
            if model and self.is_existing_chat_model(model):
                resolution = self.report.get("model_resolution", {})
                chat_resolution = (
                    resolution.get("chat", {})
                    if isinstance(resolution, Mapping)
                    else {}
                )
                reason = (
                    str(chat_resolution.get("reason") or "only_compatible_model")
                    if isinstance(chat_resolution, Mapping)
                    else "only_compatible_model"
                )
                updates.update(
                    {
                        "chat_model_mode": "auto",
                        "chat_model": model,
                        "resolved_chat_model": model,
                        "chat_model_resolution_reason": reason,
                        "last_successful_chat_model": model,
                    }
                )
        elif self.model_decision in {"use_existing", "downloaded"}:
            model = _clean_model(self.selected_chat_model)
            if model and infer_model_capability(model) == "Chat Supported":
                updates.update(
                    {
                        "chat_model_mode": "manual",
                        "chat_model": model,
                        "resolved_chat_model": "",
                        "chat_model_resolution_reason": "manual_selection",
                        "last_successful_chat_model": model,
                    }
                )
        if self.selected_embedding_model and self.is_embedding_model(
            self.selected_embedding_model
        ):
            # Preserve a valid existing selection.  First-run never recommends
            # or downloads embeddings; semantic Knowledge setup owns that flow.
            updates["embedding_model"] = self.selected_embedding_model
        return updates


def _runtime_item(
    key: str, name: str, status: str, available: bool | None
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "status": status,
        "detail": "",
        "required": key in {"aurora_core", "ollama", "local_ai_service", "chat_model"},
        "available": available,
        "data": {},
    }


def _normalize_environment_items(
    items_by_key: Any,
    items: Any,
    fallback: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    candidates: dict[str, Any] = {}
    if isinstance(items_by_key, Mapping):
        candidates.update(items_by_key)
    if isinstance(items, Iterable) and not isinstance(items, (str, bytes, Mapping)):
        for item in items:
            if isinstance(item, Mapping) and item.get("key"):
                candidates.setdefault(str(item["key"]), item)
    for key in ENVIRONMENT_KEYS:
        base = deepcopy(dict(fallback[key]))
        candidate = candidates.get(key)
        if isinstance(candidate, Mapping):
            base.update(deepcopy(dict(candidate)))
        status = str(base.get("status") or fallback[key]["status"])
        base["status"] = status if status in VALID_RUNTIME_STATUSES else "Degraded"
        base["key"] = key
        result[key] = base
    return result


def _as_model_list(value: Any) -> list[Any]:
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
        return list(value)
    return []


def _classify_models(models: Iterable[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chat: list[dict[str, Any]] = []
    embedding: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in models:
        record = dict(item) if isinstance(item, Mapping) else {"name": str(item or "")}
        name = _clean_model(record.get("name") or record.get("model"))
        key = _model_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        capability = infer_model_capability(name)
        record["name"] = name
        record["capability"] = capability
        (chat if capability == "Chat Supported" else embedding).append(record)
    return chat, embedding


def _clean_model(value: Any) -> str:
    return str(value or "").strip()


def _model_key(value: Any) -> str:
    normalized = _clean_model(value).casefold()
    tail = normalized.rsplit("/", 1)[-1]
    return normalized[:-7] if normalized.endswith(":latest") and tail.count(":") == 1 else normalized


def _positive_number(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


__all__ = [
    "ENVIRONMENT_KEYS",
    "FIRST_RUN_STEPS",
    "FirstRunController",
    "ModelDownloadPlan",
    "empty_runtime_report",
]

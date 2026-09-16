"""Settings wire shape; independent of production modules for mock transport."""
import math

KEYS = frozenset(["ollama.host","ollama.thinking_mode","ollama.keep_alive","chat_model","chat_model_mode","embedding_model","embedding_model_mode","resolved_chat_model","resolved_embedding_model","memory.max_injection","memory.min_importance","memory.retrieval_threshold","memory.confidence_default","persona.enabled","knowledge.enabled","knowledge.max_results","rag.pipeline_enabled","rag.enable_dedup","rag.enable_ranking","rag.enable_optimization","rag.context_budget","rag.reserved_output","context.warning_tokens"])
ERRORS = {"INVALID_SETTING", "INVALID_VALUE", "READ_ONLY", "RESTART_REQUIRED", "PERSISTENCE_ERROR", "CONFLICT"}


def validate_settings(kind, payload):
    def require(ok):
        if not ok:
            raise ValueError("Invalid settings payload.")

    def revision(value):
        require(type(value) is int and 0 <= value <= 9007199254740991)

    def scalar(value):
        require(value is None or type(value) in {str, bool, int, float})
        if isinstance(value, str):
            require(len(value) <= 512)
        elif type(value) in {int, float}:
            require(abs(value) <= 9007199254740991 and math.isfinite(value))

    if kind == "settings.get.request":
        require(payload == {})
    elif kind == "settings.update.request":
        revision(payload["expected_revision"])
        patch = payload["patch"]
        require(isinstance(patch, dict) and len(patch) <= len(KEYS))
        for key, value in patch.items():
            require(isinstance(key, str) and 0 < len(key) <= 128)
            scalar(value)  # Unknown keys receive INVALID_SETTING from the owner.
    elif kind == "settings.get.response":
        revision(payload["revision"])
        require(payload["status"] in {"loaded", "missing_defaults", "invalid_defaults"})
        items = payload["descriptors"]
        require(isinstance(items, list) and len(items) == len(KEYS))
        seen = set()
        for item in items:
            require(isinstance(item, dict) and set(item) == {
                "key", "type", "value", "default", "mutable", "restart_required",
                "apply", "options", "min", "max", "label_id", "value_valid"})
            key = item["key"]
            require(isinstance(key, str) and key in KEYS and key not in seen)
            seen.add(key)
            require(item["type"] in {"string", "nullable_string", "integer", "number", "boolean"})
            require(all(type(item[k]) is bool for k in ("mutable", "restart_required", "value_valid")))
            require(item["apply"] in {"read_only", "next_request", "restart_required"})
            require(item["label_id"] == "settings." + key)
            scalar(item["value"])
            scalar(item["default"])
            def typed(value):
                kind = item["type"]
                return ((kind == "boolean" and type(value) is bool) or
                        (kind == "integer" and type(value) is int) or
                        (kind == "number" and type(value) in {int, float}) or
                        (kind in {"string", "nullable_string"} and isinstance(value, str)) or
                        (kind == "nullable_string" and value is None))
            require(typed(item["default"]))
            require(typed(item["value"]) if item["value_valid"] else item["value"] is None)
            if key == "ollama.host":
                from urllib.parse import urlsplit
                for host in (item["value"], item["default"]):
                    if host is not None:
                        parsed = urlsplit(host)
                        require(parsed.scheme in {"http", "https"} and parsed.hostname and
                                parsed.username is None and parsed.password is None and
                                parsed.path in {"", "/"} and not parsed.query and not parsed.fragment)
            require(item["options"] is None or isinstance(item["options"], list) and
                    len(item["options"]) <= 16 and all(isinstance(x, str) and len(x) <= 128 for x in item["options"]))
            for bound in ("min", "max"):
                require(item[bound] is None or type(item[bound]) in {int, float})
                scalar(item[bound])
    else:
        revision(payload["revision"])
        for field in ("changed_keys", "restart_required_keys"):
            values = payload[field]
            require(isinstance(values, list) and len(values) <= len(KEYS) and
                    all(isinstance(k, str) and k in KEYS for k in values) and len(set(values)) == len(values))
        require(set(payload["restart_required_keys"]) <= set(payload["changed_keys"]))

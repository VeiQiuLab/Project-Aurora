from urllib.parse import urlparse

from modules.i18n import normalize_language
from modules.settings import settings as default_settings


class SettingsController:
    SUPPORTED_LANGUAGES = {"zh_CN", "en_US"}

    def __init__(self, settings_store=None):
        self.settings = settings_store or default_settings

    def save(self, values):
        valid, normalized_values, errors = self.validate(values)
        if not valid:
            return {
                "ok": False,
                "errors": errors,
                "values": normalized_values
            }

        self.settings.update_many(normalized_values, save=True)
        return {
            "ok": True,
            "errors": [],
            "values": normalized_values
        }

    def validate(self, values):
        if not isinstance(values, dict):
            return False, {}, ["Settings values must be a dictionary."]

        normalized = dict(values)
        errors = []

        if "language" in normalized:
            language = normalize_language(normalized.get("language"))
            if language not in self.SUPPORTED_LANGUAGES:
                errors.append("Invalid language.")
            normalized["language"] = language

        for key in ("ollama.host", "openwebui.host"):
            if key in normalized and not self._is_valid_url(normalized.get(key)):
                errors.append(f"Invalid URL: {key}")

        for key in ("chat_model", "embedding_model"):
            if key in normalized and not str(normalized.get(key) or "").strip():
                errors.append(f"Missing value: {key}")

        self._validate_number(normalized, errors, "services.docker.startup_timeout", minimum=1, numeric_type=int)
        self._validate_number(normalized, errors, "status.refresh_interval", minimum=0.01, numeric_type=float)
        self._validate_number(normalized, errors, "memory.max_injection", minimum=1, numeric_type=int)
        self._validate_number(normalized, errors, "memory.min_importance", minimum=0, numeric_type=float)
        self._validate_number(normalized, errors, "knowledge.max_results", minimum=0, numeric_type=int)

        return not errors, normalized, errors

    def _validate_number(self, values, errors, key, minimum, numeric_type):
        if key not in values:
            return

        try:
            value = numeric_type(values[key])
        except (TypeError, ValueError):
            errors.append(f"Invalid number: {key}")
            return

        if value < minimum:
            errors.append(f"Value too small: {key}")
            return

        values[key] = value

    def _is_valid_url(self, value):
        try:
            parsed = urlparse(str(value or "").strip())
        except ValueError:
            return False
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

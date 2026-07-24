"""Authentication status foundation for Remote Access.

This module intentionally does not generate tokens, store secrets,
or implement remote login. It only normalizes and reports configuration state.
"""

import json
from pathlib import Path


DEFAULT_AUTH_CONFIG = {
    "auth_enabled": False,
    "authentication_type": "none",
    "token_configured": False,
    "authentication_configured": False,
    "last_token_update": None,
    "credential_storage": "windows_credential_manager",
    "secure_storage_configured": False,
    "secure_storage_available": False,
    "credential_test_passed": False,
    "credential_last_check": None,
    "credential_last_result": None,
    "credential_command_status": "Unavailable",
    "credential_last_operation": None,
    "credential_operation_result": None,
    "credential_duration_ms": 0,
    "credential_error_suggestion": None,
    "last_storage_error": None,
    "credential_history": [],
    "credential_steps": []
}


class AuthenticationManager:
    """Read and report Remote Authentication configuration status."""

    _TEMP_TOKEN_STATE = {}

    def __init__(self, file_path=None):
        root = Path(__file__).resolve().parent.parent
        self.file_path = Path(file_path) if file_path else root / "data" / "remote" / "remote.json"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self):
        try:
            with self.file_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError, json.JSONDecodeError):
            data = {}
        return data if isinstance(data, dict) else {}

    def _write(self, data):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with self.file_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)

    def normalize(self, data):
        if not isinstance(data, dict):
            data = {}
        normalized = dict(data)
        for key, value in DEFAULT_AUTH_CONFIG.items():
            normalized.setdefault(key, value)
        normalized["auth_enabled"] = bool(normalized.get("auth_enabled", False))
        normalized["authentication_type"] = str(normalized.get("authentication_type") or "none").lower()
        if normalized["authentication_type"] not in {"none", "token", "password"}:
            normalized["authentication_type"] = "none"
        normalized["token_configured"] = bool(normalized.get("token_configured", False))
        normalized["last_token_update"] = normalized.get("last_token_update")
        normalized["credential_storage"] = str(normalized.get("credential_storage") or "none").lower()
        if normalized["credential_storage"] not in {
            "none",
            "windows_credential_manager",
            "encrypted_local_storage",
            "plain_text_file"
        }:
            normalized["credential_storage"] = "none"
        normalized["secure_storage_configured"] = bool(normalized.get("secure_storage_configured", False))
        normalized["secure_storage_available"] = bool(normalized.get("secure_storage_available", False))
        normalized["credential_test_passed"] = bool(normalized.get("credential_test_passed", False))
        normalized["credential_last_check"] = normalized.get("credential_last_check")
        normalized["credential_last_result"] = normalized.get("credential_last_result")
        normalized["credential_command_status"] = str(normalized.get("credential_command_status") or "Unavailable")
        normalized["credential_last_operation"] = normalized.get("credential_last_operation")
        normalized["credential_operation_result"] = normalized.get("credential_operation_result")
        try:
            normalized["credential_duration_ms"] = max(0, int(normalized.get("credential_duration_ms", 0) or 0))
        except (TypeError, ValueError):
            normalized["credential_duration_ms"] = 0
        normalized["credential_error_suggestion"] = normalized.get("credential_error_suggestion")
        normalized["last_storage_error"] = normalized.get("last_storage_error")
        if not isinstance(normalized.get("credential_history"), list):
            normalized["credential_history"] = []
        if not isinstance(normalized.get("credential_steps"), list):
            normalized["credential_steps"] = []
        normalized["authentication_configured"] = bool(
            normalized.get("auth_enabled", False)
            and normalized.get("authentication_type") != "none"
            and normalized.get("token_configured", False)
        )
        return normalized

    def load(self):
        data = self.normalize(self._read())
        self._write(data)
        return data

    def status(self):
        data = self.load()
        temp = self._TEMP_TOKEN_STATE.get(str(self.file_path), {})
        token_configured = bool(data.get("token_configured", False) or temp.get("token_configured", False))
        authentication_type = temp.get("authentication_type") or data.get("authentication_type", "none")
        auth_enabled = bool(data.get("auth_enabled", False) or temp.get("auth_enabled", False))
        credential_storage = data.get("credential_storage", "none")
        secure_storage_configured = bool(data.get("secure_storage_configured", False))
        secure_storage_available = bool(data.get("secure_storage_available", False))
        credential_test_passed = bool(data.get("credential_test_passed", False))
        configured = bool(
            auth_enabled
            and authentication_type != "none"
            and token_configured
        )
        storage_ready = bool(
            credential_storage != "plain_text_file"
            and (secure_storage_available or secure_storage_configured)
        )
        security_ready = bool(configured and storage_ready)
        return {
            "required": True,
            "configured": configured,
            "auth_enabled": auth_enabled,
            "authentication_type": authentication_type,
            "token_configured": token_configured,
            "last_token_update": temp.get("last_token_update") or data.get("last_token_update") or "Never configured.",
            "status": "Configured" if configured else "Not Configured",
            "token_status": "Configured" if token_configured else "Not Configured",
            "credential_storage": credential_storage,
            "secure_storage_configured": secure_storage_configured,
            "secure_storage_available": secure_storage_available,
            "credential_test_passed": credential_test_passed,
            "credential_last_check": data.get("credential_last_check"),
            "credential_last_result": data.get("credential_last_result"),
            "credential_command_status": data.get("credential_command_status", "Unavailable"),
            "credential_last_operation": data.get("credential_last_operation"),
            "credential_operation_result": data.get("credential_operation_result"),
            "credential_duration_ms": data.get("credential_duration_ms", 0),
            "credential_error_suggestion": data.get("credential_error_suggestion"),
            "last_storage_error": data.get("last_storage_error"),
            "credential_history": data.get("credential_history", [])[-10:],
            "credential_steps": data.get("credential_steps", []),
            "provider": "Windows Credential Manager",
            "provider_status": "Available" if secure_storage_available else "Unavailable",
            "storage_status": "Available" if storage_ready else "Unavailable",
            "storage_type": credential_storage,
            "credential_security": {
                "no_plain_text_storage": credential_storage != "plain_text_file",
                "authentication_framework_ready": True,
                "secure_storage_configured": secure_storage_configured,
                "secure_storage_available": secure_storage_available,
                "credential_test_passed": credential_test_passed
            },
            "readiness": {
                "required": "Yes",
                "token": "Configured" if token_configured else "Missing",
                "storage": "Available" if storage_ready else "Missing",
                "provider": "Windows Credential Manager",
                "security": "Ready" if security_ready else "Warning",
                "overall": "Ready" if security_ready else "Blocked"
            },
            "secret_storage_note": "Authentication secrets should not be stored as plain text."
        }

    def is_configured(self):
        return bool(self.status().get("configured", False))

    def setup_token_placeholder(self, updated_time):
        """Mark token setup as configured for the current app session only."""

        self._TEMP_TOKEN_STATE[str(self.file_path)] = {
            "auth_enabled": True,
            "authentication_type": "token",
            "token_configured": True,
            "last_token_update": str(updated_time)
        }
        return self.status()

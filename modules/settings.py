import json
import os
import copy
from pathlib import Path


class Settings:
    def __init__(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.config_dir = self.base_dir / "config"
        self.config_file = self.config_dir / "settings.json"

        self.default_settings = {
            "app_name": "Project Aurora · Xu",
            "theme": "System",
            "appearance": "System",
            "language": "简体中文",
            "memory": {
                "max_injection": 5,
                "min_importance": 0
            },
            "persona": {
                "enabled": True
            },
            "knowledge": {
                "enabled": True,
                "max_results": 3,
                "preview_limit": 5000,
                "enabled_filter": "All",
                "sort_field": "Updated Time",
                "sort_direction": "Descending",
                "backup_path": "data/knowledge/backups",
                "max_backup_count": 10
            },
            "context": {
                "warning_tokens": 6000,
                "preview_limit": 4000,
                "inspector_preview_limit": 4000
            },
            "chat_model": "qwen3:8b",
            "embedding_model": "nomic-embed-text:latest",
            "mobile_chat_timeout": 60,
            "mobile_debug_mode": False,
            "mobile_response_limit": 12000,
            "network": {
                "preferred_interface": "",
                "ignore_virtual_adapter": True
            },
            "remote": {
                "enabled": False,
                "mode": "local",
                "auth_required": True,
                "authentication_configured": False,
                "authentication_required": True,
                "authentication_type": "none",
                "auth_enabled": False,
                "token_configured": False,
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
                "credential_steps": [],
                "network_history": [],
                "security_history": [],
                "authentication_history": [],
                "remote_history": [],
                "lan_status_page_enabled": False,
                "lan_status_port": 8765,
                "lan_status_user_confirmed": False,
                "lan_chat_enabled": False,
                "lan_chat_port": 8765,
                "mobile_access_confirmed": False,
                "mobile_debug_mode": False,
                "mobile_response_limit": 12000,
                "selected_lan_ip": "",
                "selected_adapter": "",
                "last_mobile_error": "",
                "last_mobile_stage": "",
                "last_mobile_status": "",
                "last_mobile_duration_ms": 0,
                "last_mobile_model": "",
                "last_mobile_capability": "",
                "last_mobile_ollama_url": "",
                "last_mobile_client": "",
                "last_mobile_time": "",
                "lan_ready": False,
                "ios_access_ready": False,
                "tailscale_ready": False,
                "user_confirmed": False,
                "security_confirmed": False
            },
            "window": {
                "width": 1200,
                "height": 760
            },
            "ollama": {
                "host": "http://127.0.0.1:11434",
                "auto_start": True
            },
            "openwebui": {
                "host": "http://localhost:8080",
                "auto_start": True,
                "type": "docker",
                "container_name": "open-webui",
                "quit_docker_on_close": False
            },
            "services": {
                "ollama": {
                    "command": "ollama serve"
                },
                "openwebui": {
                    "command": "docker start open-webui"
                },
                "docker": {
                    "start_command": "docker desktop start",
                    "stop_command": "docker desktop stop",
                    "auto_start": True,
                    "path": r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
                    "startup_timeout": 60
                }
            }
        }

        self.data = {}
        self.load()

    def load(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)

        if not self.config_file.exists():
            self.data = self.default_settings.copy()
            self.save()
            return

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = self.default_settings.copy()
            self.save()
            return

        if self._merge_defaults(self.data, self.default_settings):
            try:
                self.save()
            except OSError:
                pass
        if self._migrate_model_settings():
            try:
                self.save()
            except OSError:
                pass

    def _migrate_model_settings(self):
        changed = False
        if not isinstance(self.data, dict):
            return False
        legacy_model = str(self.data.get("model") or self.data.get("mobile", {}).get("model", "") or "").strip()
        current_chat_model = str(self.data.get("chat_model", "") or "").strip()
        if legacy_model and (not current_chat_model or current_chat_model == self.default_settings["chat_model"]):
            self.data["chat_model"] = legacy_model
            changed = True
        if not str(self.data.get("chat_model", "") or "").strip():
            self.data["chat_model"] = self.default_settings["chat_model"]
            changed = True
        if not str(self.data.get("embedding_model", "") or "").strip():
            self.data["embedding_model"] = self.default_settings["embedding_model"]
            changed = True
        return changed

    def _merge_defaults(self, target, defaults):
        changed = False
        if not isinstance(target, dict):
            return False
        for key, default_value in defaults.items():
            if key not in target:
                target[key] = copy.deepcopy(default_value)
                changed = True
            elif isinstance(default_value, dict):
                if not isinstance(target[key], dict):
                    target[key] = copy.deepcopy(default_value)
                    changed = True
                elif self._merge_defaults(target[key], default_value):
                    changed = True
        return changed

    def save(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)

        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)

    def get(self, key, default=None):
        keys = key.split(".")
        value = self.data

        for k in keys:
            if not isinstance(value, dict):
                return default

            if k not in value:
                return default

            value = value[k]

        return value

    def set(self, key, value):
        keys = key.split(".")
        target = self.data

        for k in keys[:-1]:
            if k not in target or not isinstance(target[k], dict):
                target[k] = {}

            target = target[k]

        target[keys[-1]] = value
        self.save()


settings = Settings()

{
    "app_name": "Project Aurora · Xu",
    "theme": "System",
    "appearance": "System",
    "window": {
        "width": 1200,
        "height": 760
    },
    "ollama": {
        "host": "http://127.0.0.1:11434",
        "auto_start": False
    },
    "openwebui": {
        "host": "http://127.0.0.1:3000",
        "auto_start": False
    }
}

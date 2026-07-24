import json
import os
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

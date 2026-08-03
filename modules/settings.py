import copy
import json
from pathlib import Path


class Settings:
    def __init__(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.config_dir = self.base_dir / "config"
        self.config_file = self.config_dir / "settings.json"

        self.default_settings = {
            "app_name": "Project Aurora \u00b7 Xu",
            "theme": "System",
            "appearance": "System",
            "language": "zh_CN",
            "first_run": {
                "completed": False
            },
            "memory": {
                "max_injection": 5,
                "min_importance": 0
            },
            "persona": {
                "enabled": True
            },
            "voice": {
                "enabled": False,
                "stt": {
                    "provider": "faster_whisper",
                    "model_size": "small",
                    "device": "auto",
                    "compute_type": "auto"
                },
                "tts": {
                    "provider": "edge_tts",
                    "voice": "zh-CN-XiaoxiaoNeural"
                },
                "playback": {
                    "backend": "pygame",
                    "enabled": True,
                    "wait_for_completion": True,
                    "timeout_seconds": 120.0
                }
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
            self.data = copy.deepcopy(self.default_settings)
            self.save()
            return

        try:
            with self.config_file.open("r", encoding="utf-8") as file:
                self.data = json.load(file)
        except Exception:
            self.data = copy.deepcopy(self.default_settings)
            self.save()
            return

        changed = False
        if self._merge_defaults(self.data, self.default_settings):
            changed = True
        if self._migrate_model_settings():
            changed = True
        if self._migrate_language_settings():
            changed = True
        if changed:
            try:
                self.save()
            except OSError:
                pass

    def _migrate_language_settings(self):
        if not isinstance(self.data, dict):
            return False
        current = str(self.data.get("language", "") or "").strip()
        normalized = self.normalize_language(current)
        if current != normalized:
            self.data["language"] = normalized
            return True
        return False

    @staticmethod
    def normalize_language(language):
        value = str(language or "").strip().lower().replace("-", "_")
        if value in {"english", "en", "en_us"}:
            return "en_US"
        if value in {"zh", "zh_cn", "chinese", "\u4e2d\u6587", "\u7b80\u4f53\u4e2d\u6587"}:
            return "zh_CN"
        return "zh_CN"

    def _migrate_model_settings(self):
        changed = False
        if not isinstance(self.data, dict):
            return False
        legacy_mobile = self.data.get("mobile", {})
        legacy_model = str(
            self.data.get("model")
            or (legacy_mobile.get("model", "") if isinstance(legacy_mobile, dict) else "")
            or ""
        ).strip()
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
        with self.config_file.open("w", encoding="utf-8") as file:
            json.dump(self.data, file, indent=4, ensure_ascii=False)

    def get(self, key, default=None):
        keys = key.split(".")
        value = self.data
        for item in keys:
            if not isinstance(value, dict):
                return default
            if item not in value:
                return default
            value = value[item]
        return value

    def set(self, key, value):
        self._set_value(key, value)
        self.save()

    def update_many(self, values, save=True):
        if not isinstance(values, dict):
            raise TypeError("Settings.update_many() expects a dict.")
        for key, value in values.items():
            self._set_value(key, value)
        if save:
            self.save()

    def _set_value(self, key, value):
        keys = key.split(".")
        target = self.data
        for item in keys[:-1]:
            if item not in target or not isinstance(target[item], dict):
                target[item] = {}
            target = target[item]
        target[keys[-1]] = value


settings = Settings()

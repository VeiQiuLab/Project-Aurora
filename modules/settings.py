import copy
import json

from modules.app_paths import CONFIG_DIR, CONFIG_FILE, DEFAULT_SETTINGS_FILE


class Settings:
    def __init__(self):
        self.config_dir = CONFIG_DIR
        self.config_file = CONFIG_FILE

        self.default_settings = self._load_default_settings()
        self.data = {}
        self.load()

    @staticmethod
    def _fallback_default_settings():
        return {
            "app_name": "Project Aurora",
            "theme": "System",
            "appearance": "System",
            "language": "zh_CN",
            "first_run": {
                "completed": False
            },
            "qq": {
                "enabled": False,
                "private_replies": False,
                "group_mentions_only": True,
                "ws_endpoint": "ws://127.0.0.1:3001",
                "http_endpoint": "http://127.0.0.1:3000",
                "access_token": ""
            },
            "memory": {
                "max_injection": 5,
                "min_importance": 0,
                "retrieval_threshold": 0.35,
                "confidence_default": 0.5
            },
            "rag": {
                "pipeline_enabled": True,
                "enable_dedup": True,
                "enable_ranking": True,
                "enable_optimization": True,
                "context_budget": 4000,
                "reserved_output": 0,
                "memory_ranking_weights": {
                    "relevance": 0.7,
                    "confidence": 0.15,
                    "importance": 0.1,
                    "freshness": 0.05
                },
                "knowledge_ranking_weights": {
                    "vector": 0.45,
                    "keyword": 0.35,
                    "freshness": 0.1,
                    "source": 0.1
                }
            },
            "persona": {
                "enabled": True
            },
            "voice": {
                "enabled": False,
                "recorder": {
                    "device_id": "windows-default-input",
                    "device_display_name": "",
                    "device_name": "",
                    "preferred_device_keyword": "",
                    "last_successful_device_guid": "",
                    "backend": "frame_pipeline",
                    "sample_rate": 16000,
                    "channels": 1,
                    "ffmpeg_path": "ffmpeg",
                    "pre_roll_ms": 500,
                    "pre_roll_buffer_ms": 1000,
                    "maximum_recording_duration": 180.0,
                    "silence_end_threshold": 0.8,
                    "min_duration_ms": 750
                },
                "vad": {
                    "threshold": 0.014,
                    "frame_duration_ms": 20,
                    "minimum_active_duration_ms": 100,
                    "peak_threshold": 0.03
                },
                "session": {
                    "inactivity_timeout_seconds": 180.0
                },
                "stt": {
                    "provider": "faster_whisper",
                    "model_size": "small",
                    "device": "auto",
                    "compute_type": "auto"
                },
                "tts": {
                    "provider": "edge_tts",
                    "voice": "zh-CN-XiaoxiaoNeural",
                    "timeout_seconds": 30.0,
                    "remote_cosyvoice": {
                        "url": ""
                    }
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
                "backup_path": "knowledge/backups",
                "max_backup_count": 10
            },
            "context": {
                "warning_tokens": 6000,
                "preview_limit": 4000,
                "inspector_preview_limit": 4000,
                "adaptive_enabled": False
            },
            "chat_model_mode": "auto",
            "chat_model": "",
            "resolved_chat_model": "",
            "chat_model_resolution_reason": "",
            "last_successful_chat_model": "",
            "embedding_model_mode": "manual",
            "embedding_model": "",
            "resolved_embedding_model": "",
            "embedding_model_resolution_reason": "",
            "window": {
                "width": 1200,
                "height": 760
            },
            "status": {
                "refresh_interval": 3
            },
            "ollama": {
                "host": "http://127.0.0.1:11434",
                "auto_start": False
            },
            "services": {
                "ollama": {
                    "command": "ollama serve"
                }
            }
        }

    @classmethod
    def _load_default_settings(cls):
        if DEFAULT_SETTINGS_FILE.exists():
            try:
                with DEFAULT_SETTINGS_FILE.open("r", encoding="utf-8") as file:
                    data = json.load(file)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return cls._fallback_default_settings()

    def load(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)

        if not self.config_file.exists():
            if DEFAULT_SETTINGS_FILE.exists():
                try:
                    self.config_file.write_text(
                        DEFAULT_SETTINGS_FILE.read_text(encoding="utf-8"),
                        encoding="utf-8"
                    )
                    with self.config_file.open("r", encoding="utf-8") as file:
                        self.data = json.load(file)
                    return
                except Exception:
                    pass
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
        if self._migrate_first_run_settings():
            changed = True
        if self._migrate_model_settings():
            changed = True
        if self._merge_defaults(self.data, self.default_settings):
            changed = True
        if self._migrate_language_settings():
            changed = True
        if self._remove_legacy_remote_settings():
            changed = True
        if self._remove_legacy_openwebui_settings():
            changed = True
        if changed:
            try:
                self.save()
            except OSError:
                pass

    def _migrate_first_run_settings(self):
        """Keep existing Aurora users out of a newly introduced first-run loop.

        A settings file already present on disk represents an existing user.  Old
        releases did not store ``first_run.completed``; treating the new default
        (False) as their value would unexpectedly hide the application behind the
        setup wizard.  Brand-new installs still receive the default file and keep
        ``completed=False``.
        """

        if not isinstance(self.data, dict):
            return False
        first_run = self.data.get("first_run")
        if isinstance(first_run, dict) and "completed" in first_run:
            return False
        if not isinstance(first_run, dict):
            first_run = {}
            self.data["first_run"] = first_run
        first_run["completed"] = True
        return True

    def _migrate_language_settings(self):
        if not isinstance(self.data, dict):
            return False
        current = str(self.data.get("language", "") or "").strip()
        normalized = self.normalize_language(current)
        if current != normalized:
            self.data["language"] = normalized
            return True
        return False

    def _remove_legacy_remote_settings(self):
        """Remove settings belonging to the retired LAN/mobile feature."""

        changed = False
        for key in ("remote", "network", "mobile_chat_timeout", "mobile_debug_mode", "mobile_response_limit"):
            if key in self.data:
                del self.data[key]
                changed = True
        return changed

    def _remove_legacy_openwebui_settings(self):
        """Remove settings belonging to the retired Open WebUI integration."""

        if not isinstance(self.data, dict):
            return False
        changed = False
        if "openwebui" in self.data:
            del self.data["openwebui"]
            changed = True
        services = self.data.get("services")
        if isinstance(services, dict):
            for key in ("openwebui", "docker"):
                if key in services:
                    del services[key]
                    changed = True
        return changed

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
        legacy_config = self.data.get("mobile", {})
        legacy_model = str(
            self.data.get("model")
            or (legacy_config.get("model", "") if isinstance(legacy_config, dict) else "")
            or ""
        ).strip()
        current_chat_model = str(self.data.get("chat_model", "") or "").strip()
        if legacy_model and (
            not current_chat_model
            or current_chat_model == str(self.default_settings.get("chat_model", "") or "")
        ):
            self.data["chat_model"] = legacy_model
            current_chat_model = legacy_model
            changed = True
        if "chat_model_mode" not in self.data:
            # A non-empty model from an older Aurora release was an explicit
            # user choice.  Preserve it as a pinned Manual selection.
            self.data["chat_model_mode"] = "manual" if current_chat_model else "auto"
            changed = True
        else:
            normalized_chat_mode = str(self.data.get("chat_model_mode") or "").strip().casefold()
            if normalized_chat_mode not in {"auto", "manual"}:
                self.data["chat_model_mode"] = "manual" if current_chat_model else "auto"
                changed = True

        if "embedding_model_mode" not in self.data:
            # Embedding remains opt-in.  Existing values stay pinned and an
            # empty legacy value does not silently enable semantic features.
            self.data["embedding_model_mode"] = "manual"
            changed = True
        else:
            normalized_embedding_mode = str(
                self.data.get("embedding_model_mode") or ""
            ).strip().casefold()
            if normalized_embedding_mode not in {"auto", "manual"}:
                self.data["embedding_model_mode"] = "manual"
                changed = True
        default_chat_model = str(self.default_settings.get("chat_model", "") or "").strip()
        default_embedding_model = str(self.default_settings.get("embedding_model", "") or "").strip()
        if default_chat_model and not str(self.data.get("chat_model", "") or "").strip():
            self.data["chat_model"] = self.default_settings["chat_model"]
            changed = True
        if default_embedding_model and not str(self.data.get("embedding_model", "") or "").strip():
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

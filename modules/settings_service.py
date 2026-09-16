"""Headless production settings owner: safe snapshots and validated patch IO.

Importing this module creates no owner, file, thread, UI or network connection.
Only explicitly allowlisted AI keys cross IPC; raw storage is never a DTO.
"""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit

from modules.app_paths import CONFIG_FILE
from modules.settings import Settings
from modules.ollama_request_policy import normalize_keep_alive, normalize_thinking_mode, resolve_ollama_request_policy
from modules.models import infer_model_capability


class SettingsError(ValueError):
    def __init__(self, code):
        super().__init__("Settings operation could not complete.")
        self.code = code


# Explicit inventory, not auto-exposure of default_settings or raw user data.
# Bounds for numeric values match SettingsController; caps apply only to wire
# string/patch sizes, not model loading or product defaults.
RULES = {
    "ollama.host": ("string", None, None, None),
    "ollama.thinking_mode": ("string", ["off", "on", "default"], None, None),
    "ollama.keep_alive": ("nullable_string", None, None, None),
    "chat_model": ("string", None, None, None),
    "chat_model_mode": ("string", ["auto", "manual"], None, None),
    "embedding_model": ("string", None, None, None),
    "embedding_model_mode": ("string", ["auto", "manual"], None, None),
    "resolved_chat_model": ("string", None, None, None),
    "resolved_embedding_model": ("string", None, None, None),
    "memory.max_injection": ("integer", None, 1, None),
    "memory.min_importance": ("number", None, 0, None),
    "memory.retrieval_threshold": ("number", None, 0, 1),
    "memory.confidence_default": ("number", None, 0, 1),
    "persona.enabled": ("boolean", None, None, None),
    "knowledge.enabled": ("boolean", None, None, None),
    "knowledge.max_results": ("integer", None, 0, None),
    "rag.pipeline_enabled": ("boolean", None, None, None),
    "rag.enable_dedup": ("boolean", None, None, None),
    "rag.enable_ranking": ("boolean", None, None, None),
    "rag.enable_optimization": ("boolean", None, None, None),
    "rag.context_budget": ("integer", None, 1, None),
    "rag.reserved_output": ("integer", None, 0, None),
    "context.warning_tokens": ("integer", None, 1, None),
}
READ_ONLY = {"resolved_chat_model", "resolved_embedding_model", "embedding_model_mode"}
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@+-]{0,199}$")


def valid_host(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = parsed.hostname
        if (parsed.scheme not in {"http", "https"} or not host or parsed.username is not None
                or parsed.password is not None or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or any(c.isspace() for c in value)
                or "\\" in value or "?" in value or "#" in value or parsed.netloc.endswith(":")
                or (port is not None and not 1 <= port <= 65535)):
            return False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if len(host) > 253 or not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in host.split(".")):
                return False
        return True
    except (ValueError, TypeError):
        return False


def validate_value(key, value):
    kind, choices, low, high = RULES[key]
    valid_type = {"string": isinstance(value, str), "nullable_string": value is None or isinstance(value, str),
                  "integer": type(value) is int, "number": type(value) in {int, float},
                  "boolean": type(value) is bool}[kind]
    if not valid_type or (isinstance(value, str) and len(value) > 512):
        raise SettingsError("INVALID_VALUE")
    if kind in {"integer", "number"}:
        if abs(value) > 9007199254740991 or not math.isfinite(value) or (low is not None and value < low) or (high is not None and value > high):
            raise SettingsError("INVALID_VALUE")
    if choices and value not in choices:
        raise SettingsError("INVALID_VALUE")
    if key == "ollama.host" and not valid_host(value):
        raise SettingsError("INVALID_VALUE")
    if "model" in key and not key.endswith("_mode") and value:
        if not MODEL_RE.fullmatch(value):
            raise SettingsError("INVALID_VALUE")
        if key == "chat_model" and infer_model_capability(value) != "Chat Supported":
            raise SettingsError("INVALID_VALUE")
        if key == "embedding_model" and infer_model_capability(value) != "Embedding Only":
            raise SettingsError("INVALID_VALUE")
    try:
        if key == "ollama.keep_alive":
            if isinstance(value, str) and len(value) > 128:
                raise ValueError()
            value = normalize_keep_alive(value)
        elif key == "ollama.thinking_mode":
            value = normalize_thinking_mode(value)
    except ValueError:
        raise SettingsError("INVALID_VALUE") from None
    return value


@dataclass(frozen=True, init=False, repr=False, eq=False)
class SettingsSnapshot:
    def __init__(self, data, *, revision=0, status="loaded"):
        object.__setattr__(self, "_SettingsSnapshot__data", copy.deepcopy(data))
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "policy", resolve_ollama_request_policy(self))

    def get(self, key, default=None):
        value = self.__data
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return copy.deepcopy(default)
            value = value[part]
        return copy.deepcopy(value)

    def snapshot(self):
        return self  # private copied data; get never returns owned mutable objects


class SettingsService:
    def __init__(self, config_file=None):
        self.config_file = Path(config_file) if config_file is not None else CONFIG_FILE
        self._lock = threading.RLock()
        self.closed = False
        self.revision = 0
        self._base = Settings(config_file=self.config_file, initialize=False)
        self._raw = {}
        self.load()

    def _fingerprint(self):
        try:
            raw = self.config_file.read_bytes()
            stat = self.config_file.stat()
            return (hashlib.sha256(raw).hexdigest(), stat.st_mtime_ns, len(raw)), raw
        except FileNotFoundError:
            return None, None

    def load(self):
        with self._lock:
            if self.closed:
                raise SettingsError("READ_ONLY")
            if hasattr(self, "_snapshot"):
                self.revision += 1
            try:
                self._disk, raw = self._fingerprint()
                data = json.loads(raw) if raw is not None else {}
                if not isinstance(data, dict):
                    raise ValueError()
                self._raw = data
                status = "loaded" if raw is not None else "missing_defaults"
            except (OSError, ValueError, UnicodeError):
                self._raw, status = {}, "invalid_defaults"
                self._disk = None
            self._publish(status)

    def _publish(self, status="loaded"):
        self._snapshot = self._prepare(self._raw, self.revision, status)

    def _prepare(self, raw, revision, status="loaded"):
        self._base.data = copy.deepcopy(raw if status == "loaded" else self._base.default_settings)
        if status == "loaded":
            self._base.normalize_loaded()
        return SettingsSnapshot(self._base.data, revision=revision, status=status)

    @property
    def status(self):
        return self.snapshot().status

    @property
    def policy(self):
        return self.snapshot().policy

    def get(self, key, default=None):
        return self.snapshot().get(key, default)

    def snapshot(self):
        with self._lock:
            return self._snapshot

    def describe(self):
        with self._lock:
            defaults = SettingsSnapshot(self._base.default_settings)
            descriptors = []
            for key, (kind, choices, low, high) in RULES.items():
                value = self.get(key)
                try:
                    validate_value(key, value)
                    valid = True
                except SettingsError:
                    value, valid = None, False
                descriptors.append(dict(key=key, type=kind, value=value, default=defaults.get(key),
                    mutable=key not in READ_ONLY, restart_required=False,
                    apply="read_only" if key in READ_ONLY else "next_request",
                    options=choices, min=low, max=high, label_id="settings."+key, value_valid=valid))
            return dict(revision=self.revision, status=self.status, descriptors=descriptors)

    def validate_patch(self, patch):
        if not isinstance(patch, dict) or len(patch) > len(RULES):
            raise SettingsError("INVALID_SETTING")
        values = {}
        for key, value in patch.items():
            if key not in RULES:
                raise SettingsError("INVALID_SETTING")
            if key in READ_ONLY:
                raise SettingsError("READ_ONLY")
            values[key] = validate_value(key, value)
        return values

    def _persist(self, data):
        # Serialize before touching disk; no partial target or in-memory publish.
        payload = json.dumps(data, ensure_ascii=False, indent=4, allow_nan=False).encode("utf-8")
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.config_file.parent, prefix=".settings-", suffix=".tmp", delete=False) as output:
                temporary = output.name
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            if self._fingerprint()[0] != self._disk:
                raise SettingsError("CONFLICT")
            fingerprint = (hashlib.sha256(payload).hexdigest(), Path(temporary).stat().st_mtime_ns, len(payload))
            os.replace(temporary, self.config_file)
            temporary = None
            return fingerprint
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass  # Preserve the original transaction failure.

    def apply_patch(self, patch, expected_revision):
        with self._lock:
            if self.closed:
                raise SettingsError("READ_ONLY")
            if type(expected_revision) is not int or expected_revision != self.revision:
                raise SettingsError("CONFLICT")
            values = self.validate_patch(patch)
            try:
                if self.status == "invalid_defaults":
                    raise SettingsError("PERSISTENCE_ERROR")
                if self._fingerprint()[0] != self._disk:
                    raise SettingsError("CONFLICT")
                changed = {key: value for key, value in values.items() if self.get(key) != value}
                if changed:
                    target = copy.deepcopy(self._raw)
                    for key, value in changed.items():
                        branch = target
                        parts = key.split(".")
                        for part in parts[:-1]:
                            if not isinstance(branch.get(part), dict):
                                branch[part] = {}
                            branch = branch[part]
                        branch[parts[-1]] = value
                    if changed.get("chat_model") == "":
                        # Explicitly clearing a modern model must not resurrect a
                        # retired model/mobile.model alias on this or the next load.
                        target.pop("model", None)
                        if isinstance(target.get("mobile"), dict):
                            target["mobile"].pop("model", None)
                    snapshot = self._prepare(target, self.revision + 1)
                    disk = self._persist(target)
                    self._raw = target
                    self.revision += 1
                    self._disk = disk
                    self._snapshot = snapshot
                return dict(revision=self.revision, changed_keys=list(changed), restart_required_keys=[])
            except SettingsError:
                raise
            except (OSError, TypeError, ValueError, OverflowError):
                raise SettingsError("PERSISTENCE_ERROR") from None

    def close(self):
        # Serialize shutdown with any in-flight file transaction.
        with self._lock:
            self.closed = True

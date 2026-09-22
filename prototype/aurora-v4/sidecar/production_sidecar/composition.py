"""Production composition: Python-owned settings snapshots and bounded GET health."""
from __future__ import annotations

import asyncio
import http.client
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from time import monotonic

from modules import app_paths
from modules.settings_service import SettingsService

LOGGER = logging.getLogger("aurora-v4-production")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OllamaHealth:
    """Only /api/tags: no subprocess, generation, auto-selection, load or save."""

    def __init__(self, settings, timeout=1.0):
        self.settings = settings
        self.timeout = timeout

    def probe(self):
        started = monotonic()
        raw_host = self.settings.get("ollama.host", "http://127.0.0.1:11434")
        model = self.settings.get("chat_model", "")
        if self.settings.get("chat_model_mode", "auto") == "auto":
            model = self.settings.get("resolved_chat_model", "") or model
        model = model if isinstance(model, str) and re.fullmatch(r"[\w./:@+-]{0,200}", model) else ""
        result = dict(reachable=False, host="", configured_model=model,
                      model_available=False, error_code="", probe_duration_ms=0.0)
        try:
            parsed = urllib.parse.urlsplit(raw_host)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or parsed.path not in {"", "/"}):
                raise ValueError("invalid host")
            # Do not copy untrusted paths, credentials, queries or exception text to diagnostics.
            host = parsed.hostname
            if ":" in host:
                host = f"[{host}]"
            result["host"] = f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else "")
            request = urllib.request.Request(result["host"] + "/api/tags", method="GET")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(request, timeout=self.timeout) as response:
                raw = response.read(1_048_577)
                if len(raw) > 1_048_576:
                    raise ValueError("oversized health")
                payload = json.loads(raw)
            models = payload.get("models") if isinstance(payload, dict) else None
            if not isinstance(models, list) or any(not isinstance(m, dict) for m in models):
                raise ValueError("invalid health")
            names = {m.get("name", m.get("model")) for m in models
                     if isinstance(m.get("name", m.get("model")), str)}
            result["reachable"] = True
            result["model_available"] = bool(model) and (model in names or model + ":latest" in names)
            if not model:
                result["error_code"] = "MODEL_NOT_CONFIGURED"
            elif not result["model_available"]:
                result["error_code"] = "MODEL_UNAVAILABLE"
        except (TypeError, ValueError, UnicodeError):
            result["error_code"] = "INVALID_HOST" if not result["host"] else "INVALID_OLLAMA_RESPONSE"
        except http.client.HTTPException:
            result["error_code"] = "INVALID_OLLAMA_RESPONSE"
        except (urllib.error.URLError, OSError, TimeoutError):
            result["error_code"] = "OLLAMA_UNAVAILABLE"
        result["probe_duration_ms"] = round((monotonic() - started) * 1000, 3)
        return result


class ProductionComposition:
    def __init__(self, root: Path | None = None, config_file: Path | None = None,
                 conversation_root: Path | None = None,
                 context_root: Path | None = None):
        self.root = root or app_paths.PROGRAM_ROOT
        self.settings = SettingsService(config_file)
        self.local_provider = None
        if os.environ.get("AURORA_V4_CHAT_PROVIDER") == "builtin_local":
            from production_sidecar.local_provider import BuiltInLlamaProvider
            self.local_provider = BuiltInLlamaProvider.from_environment()
        self.ollama = OllamaHealth(self.settings)
        self._conversation_root = conversation_root
        self._context_root = context_root
        self._conversations = None
        self._context = None
        self.post_turn = None
        self.diagnostics = {}
        self.state = "DEGRADED"
        self.closed = False
        self._refresh_lock = asyncio.Lock()

    @property
    def conversations(self):
        """Lazily expose the existing Aurora conversation store."""

        if self._conversations is None:
            from production_sidecar.conversations import ConversationPersistence

            self._conversations = ConversationPersistence(self._conversation_root)
        return self._conversations

    @property
    def context_root(self):
        if self._context_root is not None:
            return self._context_root
        if self._conversation_root is not None:
            return Path(self._conversation_root).parent
        return app_paths.USER_DATA_DIR

    @property
    def context(self):
        """Lazily expose the headless production context adapter."""

        if self._context is None:
            from production_sidecar.context import ProductionContextAdapter

            self._context = ProductionContextAdapter(self, self.context_root)
        return self._context

    def capabilities(self):
        exists = lambda path: (self.root / path).is_file()
        return {
            "chat_streaming": True, "chat_cancel": True,
            "settings": {"read": True, "update": True, "ui": False},
            "conversation": {"list": True, "get": True, "create": True, "save": True},
            "memory": False, "knowledge": False, "rag": False,
            "voice": {"ipc": False,
                      "edge_tts": exists("modules/experience/voice/providers/edge_tts.py"),
                      "cosyvoice_remote": exists("modules/experience/voice/providers/remote_cosyvoice.py"),
                      "cosyvoice_local": False, "streaming_pcm": False},
            "implementation": {"chat_streaming": exists("modules/chat.py"),
                               "chat_cancel": exists("modules/chat.py"),
                               "memory": exists("modules/memory.py"),
                               "knowledge": exists("modules/knowledge.py"),
                               "rag": exists("modules/rag_pipeline.py")},
        }

    async def refresh(self, settings_snapshot=None):
        async with self._refresh_lock:
            if self.closed:
                raise RuntimeError("BACKEND_CLOSED")
            snapshot = settings_snapshot or self.settings.snapshot()
            if self.local_provider is not None:
                local = await asyncio.to_thread(self.local_provider.probe)
                # Retained legacy field is explicitly unavailable, never a disguised llama endpoint.
                probe = dict(reachable=False, host="", configured_model="", model_available=False,
                             error_code="OLLAMA_UNAVAILABLE", probe_duration_ms=0.0)
            else:
                local = None
                probe = await asyncio.to_thread(OllamaHealth(snapshot).probe)
            self.diagnostics = {
                "backend_mode": "production", "backend_ready": True,
                "settings_status": snapshot.status,
                **snapshot.policy.diagnostics(), "ollama": probe,
            }
            if local is not None:
                self.diagnostics["local_model"] = local
                self.diagnostics.update(ollama_think_mode="default", think_payload_value=None, ollama_keep_alive=None)
            selected = local if local is not None else probe
            valid_settings = snapshot.status != "invalid_defaults" if local is not None else snapshot.status == "loaded"
            self.state = "READY" if not selected["error_code"] and valid_settings else "DEGRADED"
            LOGGER.info("event=health state=%s ollama=%s duration_ms=%s", self.state,
                        probe["error_code"] or "AVAILABLE", probe["probe_duration_ms"])
            return self.diagnostics

    def close(self):
        self.closed = True
        if self.post_turn is not None:
            self.post_turn.close()
        elif self.local_provider is not None:
            self.local_provider.cancel_background()
        self.settings.close()

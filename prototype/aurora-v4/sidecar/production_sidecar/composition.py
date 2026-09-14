"""Production composition: paths, read-only settings, policy, bounded GET health."""
from __future__ import annotations

import asyncio
import http.client
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from time import monotonic

from modules import app_paths
from production_sidecar.aurora_adapter import ReadOnlySettings

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
    def __init__(self, root: Path | None = None, config_file: Path | None = None):
        self.root = root or app_paths.PROGRAM_ROOT
        self.settings = ReadOnlySettings(self.root, config_file)
        self.ollama = OllamaHealth(self.settings)
        self.diagnostics = {}
        self.state = "DEGRADED"
        self.closed = False
        self._refresh_lock = asyncio.Lock()

    def capabilities(self):
        exists = lambda path: (self.root / path).is_file()
        return {
            "chat_streaming": True, "chat_cancel": True,
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

    async def refresh(self):
        async with self._refresh_lock:
            if self.closed:
                raise RuntimeError("BACKEND_CLOSED")
            probe = await asyncio.to_thread(self.ollama.probe)
            self.diagnostics = {
                "backend_mode": "production", "backend_ready": True,
                "settings_status": self.settings.status,
                **self.settings.policy.diagnostics(), "ollama": probe,
            }
            self.state = "READY" if not probe["error_code"] and self.settings.status == "loaded" else "DEGRADED"
            LOGGER.info("event=health state=%s ollama=%s duration_ms=%s", self.state,
                        probe["error_code"] or "AVAILABLE", probe["probe_duration_ms"])
            return self.diagnostics

    def close(self):
        self.closed = True

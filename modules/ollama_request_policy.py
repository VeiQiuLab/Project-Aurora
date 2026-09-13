"""Centralized policy for optional Ollama chat request fields."""

from __future__ import annotations

import re
from dataclasses import dataclass


THINKING_MODES = frozenset({"off", "on", "default"})
DEFAULT_THINKING_MODE = "off"
DEFAULT_KEEP_ALIVE = "30m"

_DURATION_RE = re.compile(
    r"^(?:0|(?:\d+(?:\.\d+)?(?:ns|us|µs|μs|ms|s|m|h))+)$"
)


def normalize_thinking_mode(value):
    """Return a supported thinking mode or raise ``ValueError``."""

    mode = str(value or "").strip().casefold()
    if mode not in THINKING_MODES:
        raise ValueError("Ollama thinking mode must be off, on, or default.")
    return mode


def thinking_payload_value(mode):
    """Map one normalized mode to Ollama's optional boolean value."""

    normalized = normalize_thinking_mode(mode)
    if normalized == "off":
        return False
    if normalized == "on":
        return True
    return None


def normalize_keep_alive(value):
    """Normalize Aurora's nullable Ollama duration-string setting."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Ollama keep_alive must be a duration string or null.")
    duration = value.strip()
    if not duration or duration.casefold() == "default":
        return None
    if not _DURATION_RE.fullmatch(duration):
        raise ValueError("Invalid Ollama keep_alive duration.")
    return duration


@dataclass(frozen=True)
class OllamaRequestPolicy:
    """Resolved request-local values for Ollama's optional chat fields."""

    thinking_mode: str
    keep_alive: str | None

    @property
    def think_payload_value(self):
        return thinking_payload_value(self.thinking_mode)

    def apply(self, payload):
        """Apply optional fields to *payload* without changing other entries."""

        think_value = self.think_payload_value
        if think_value is not None:
            payload["think"] = think_value
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive
        return payload

    def diagnostics(self):
        return {
            "ollama_think_mode": self.thinking_mode,
            "think_payload_value": self.think_payload_value,
            "ollama_keep_alive": self.keep_alive,
        }


def resolve_ollama_request_policy(settings_store, *, thinking_mode=None):
    """Resolve production settings, with an optional request-local think override."""

    if thinking_mode is None:
        raw_mode = settings_store.get(
            "ollama.thinking_mode",
            DEFAULT_THINKING_MODE,
        )
        try:
            resolved_mode = normalize_thinking_mode(raw_mode)
        except ValueError:
            resolved_mode = DEFAULT_THINKING_MODE
    else:
        resolved_mode = normalize_thinking_mode(thinking_mode)

    try:
        keep_alive = normalize_keep_alive(
            settings_store.get("ollama.keep_alive", DEFAULT_KEEP_ALIVE)
        )
    except ValueError:
        keep_alive = None

    return OllamaRequestPolicy(
        thinking_mode=resolved_mode,
        keep_alive=keep_alive,
    )

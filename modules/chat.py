import copy
import json
import socket
import threading
import urllib.error
import urllib.request

from modules.settings import settings

DEFAULT_SYSTEM_CONTEXT = "You are Aurora, a helpful local AI assistant."
DEFAULT_CONTEXT_WARNING_TOKENS = 6000


class ChatError(Exception):
    """Friendly error raised when an Ollama chat request cannot complete."""

    def __init__(self, message, category="chat_generation_failed", stage="ollama_request", detail=None):
        super().__init__(message)
        self.category = category
        self.stage = stage
        self.detail = detail or message


def estimate_tokens(text):
    """Return a lightweight token estimate for UI previews."""

    content = str(text or "")
    if not content.strip():
        return 0
    return max(1, len(content) // 4)


def build_context_debug_report(sections, warning_tokens=DEFAULT_CONTEXT_WARNING_TOKENS):
    """Build a readable context summary for Chat debug and preview windows."""

    rows = ["Context Build Process:"]
    for section in sections or []:
        status = "loaded" if section.get("enabled") else "disabled"
        rows.append(f"\u2713 {section.get('name', 'Context')} {status}")

    rows.append("")
    rows.append("Context Summary:")
    total_tokens = 0
    for section in sections or []:
        content = str(section.get("content", "") or "")
        tokens = estimate_tokens(content)
        total_tokens += tokens
        enabled = "Enabled" if section.get("enabled") else "Disabled"
        rows.append(
            f"- {section.get('name', 'Context')}: {enabled} | "
            f"Characters: {len(content)} | Estimated Tokens: {tokens}"
        )
    rows.append(f"Total Estimated Tokens: {total_tokens}")

    try:
        limit = max(1, int(warning_tokens))
    except (TypeError, ValueError):
        limit = DEFAULT_CONTEXT_WARNING_TOKENS
    warning = total_tokens > limit
    if warning:
        rows.extend([
            "",
            "Context size warning.",
            "Suggestion: reduce Knowledge results or shorten injected context."
        ])
    return "\n".join(rows), warning, total_tokens


def build_final_prompt_preview(sections, warning_tokens=DEFAULT_CONTEXT_WARNING_TOKENS, preview_limit=4000):
    """Build a capped final prompt preview without changing the active Chat session."""

    report, warning, total_tokens = build_context_debug_report(sections, warning_tokens)
    try:
        limit = max(500, int(preview_limit))
    except (TypeError, ValueError):
        limit = 4000

    lines = [report, "", "Preview Final Prompt:"]
    for section in sections or []:
        name = section.get("name", "Context")
        enabled = "Enabled" if section.get("enabled") else "Disabled"
        content = str(section.get("content", "") or "")
        if len(content) > limit:
            content = content[:limit] + "\n\n[Context preview truncated]"
        lines.extend(["", f"{name} ({enabled}):", content if content.strip() else "[No content]"])
    return "\n".join(lines), warning, total_tokens


def assemble_final_prompt(sections):
    """Return the complete final prompt text represented by enabled context sections."""

    lines = []
    for section in sections or []:
        if not section.get("enabled"):
            continue
        content = str(section.get("content", "") or "").strip()
        if not content:
            continue
        lines.extend([f"{section.get('name', 'Context')}:", content, ""])
    return "\n".join(lines).strip()


def summarize_context_sections(sections, warning_tokens=DEFAULT_CONTEXT_WARNING_TOKENS):
    """Return structured context statistics for the Context Inspector."""

    try:
        limit = max(1, int(warning_tokens))
    except (TypeError, ValueError):
        limit = DEFAULT_CONTEXT_WARNING_TOKENS

    records = []
    total_characters = 0
    total_tokens = 0
    for section in sections or []:
        content = str(section.get("content", "") or "")
        characters = len(content)
        tokens = estimate_tokens(content)
        total_characters += characters
        total_tokens += tokens
        records.append({
            "name": section.get("name", "Context"),
            "enabled": bool(section.get("enabled")),
            "content": content,
            "characters": characters,
            "tokens": tokens
        })

    warning_reasons = []
    if total_tokens > limit:
        warning_reasons.append("Total context exceeds recommended size.")
    for record in records:
        if record["name"] == "Knowledge" and record["tokens"] > max(1, int(limit * 0.45)):
            warning_reasons.append("Knowledge content too large.")
        if record["name"] == "Conversation Context" and record["tokens"] > max(1, int(limit * 0.45)):
            warning_reasons.append("Conversation history too long.")

    return {
        "sections": records,
        "total_characters": total_characters,
        "total_tokens": total_tokens,
        "warning": bool(warning_reasons),
        "warning_reasons": warning_reasons
    }


def chat_with_ollama(model, prompt):
    """Send one prompt to Ollama and return the assistant response."""

    return chat_with_messages(model, [{"role": "user", "content": prompt}])


def chat_with_messages(model, messages, timeout=120):
    """Send prepared chat messages to Ollama and return the assistant response."""

    try:
        from modules.models import model_supports_chat
        if not model_supports_chat(model):
            raise ChatError(
                "Model cannot chat. Please select a chat model.",
                category="model_capability",
                stage="model_capability",
                detail={"model": model, "capability": "Embedding Only"}
            )
    except ChatError:
        raise
    except Exception:
        pass

    host = str(settings.get("ollama.host", "")).strip().rstrip("/")
    if not host:
        raise ChatError(
            "Ollama host is not configured.",
            category="ollama_unavailable",
            stage="ollama_connection"
        )

    url = f"{host}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {
                "role": str(message.get("role", "user")),
                "content": str(message.get("content", ""))
            }
            for message in messages or []
            if isinstance(message, dict) and message.get("role") in {"system", "user", "assistant"}
        ],
        "stream": False
    }
    if not payload["messages"]:
        payload["messages"] = [{"role": "user", "content": ""}]

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            details = error.read().decode("utf-8", errors="ignore")
            message = json.loads(details).get("error", "")
        except (OSError, ValueError, json.JSONDecodeError):
            message = ""

        if "not found" in message.lower():
            raise ChatError(
                f"Model not found. HTTP {error.code}: {message}".strip(),
                category="model_unavailable",
                stage="model_check",
                detail={"http_status": error.code, "error_detail": message}
            ) from error
        detail = message or getattr(error, "reason", "") or "Ollama request failed"
        raise ChatError(
            f"Ollama request failed. HTTP {error.code}: {detail}",
            category="chat_generation_failed",
            stage="ollama_request",
            detail={"http_status": error.code, "error_detail": detail}
        ) from error
    except (socket.timeout, TimeoutError) as error:
        raise ChatError("Ollama request timed out.", category="timeout", stage="ollama_request") from error
    except urllib.error.URLError as error:
        if isinstance(error.reason, ConnectionRefusedError):
            raise ChatError("Ollama is not connected.", category="ollama_unavailable", stage="ollama_connection") from error
        raise ChatError("Unable to connect to Ollama.", category="ollama_unavailable", stage="ollama_connection") from error
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ChatError(
            f"Invalid Ollama response: {error}",
            category="invalid_response",
            stage="ollama_response",
            detail={"error_detail": str(error)}
        ) from error

    if data.get("error"):
        error_message = str(data["error"])
        if "not found" in error_message.lower():
            raise ChatError("Model not found.", category="model_unavailable", stage="model_check")
        raise ChatError(error_message, category="chat_generation_failed", stage="ollama_response")

    message = data.get("message", {})
    content = message.get("content") if isinstance(message, dict) else None
    if not content:
        raise ChatError("Ollama returned an empty response.", category="invalid_response", stage="ollama_response")

    return str(content)


class ChatSession:
    """Store the current system, user, and assistant conversation messages."""

    def __init__(self, system_context=None):
        self.system_context = system_context or DEFAULT_SYSTEM_CONTEXT
        self.messages = [
            {
                "role": "system",
                "content": self.system_context
            }
        ]
        self._lock = threading.Lock()

    def add_user(self, content):
        with self._lock:
            self.messages.append({"role": "user", "content": content})

    def set_system_context(self, content):
        with self._lock:
            self.system_context = content or DEFAULT_SYSTEM_CONTEXT
            if self.messages and self.messages[0].get("role") == "system":
                self.messages[0]["content"] = self.system_context
            else:
                self.messages.insert(0, {"role": "system", "content": self.system_context})

    def add_assistant(self, content):
        with self._lock:
            self.messages.append({"role": "assistant", "content": content})

    def remove_last_user(self):
        with self._lock:
            if self.messages and self.messages[-1].get("role") == "user":
                self.messages.pop()

    def clear(self):
        with self._lock:
            self.messages = [
                {
                    "role": "system",
                    "content": self.system_context
                }
            ]

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self.messages)

    def replace(self, messages):
        valid = []
        for message in messages or []:
            if isinstance(message, dict) and message.get("role") in {"system", "user", "assistant"}:
                valid.append({"role": str(message["role"]), "content": str(message.get("content", ""))})
        if not any(item["role"] == "system" for item in valid):
            valid.insert(0, {"role": "system", "content": self.system_context})
        with self._lock:
            self.messages = valid


def stream_chat(model, prompt, session, on_chunk, stop_event):
    """Stream one Ollama response while preserving the session context."""

    try:
        from modules.models import model_supports_chat
        if not model_supports_chat(model):
            raise ChatError(
                "Model cannot chat. Please select a chat model.",
                category="model_capability",
                stage="model_capability",
                detail={"model": model, "capability": "Embedding Only"}
            )
    except ChatError:
        raise
    except Exception:
        pass

    host = str(settings.get("ollama.host", "")).strip().rstrip("/")
    if not host:
        raise ChatError(
            "Ollama host is not configured.",
            category="ollama_unavailable",
            stage="ollama_connection"
        )

    session.add_user(prompt)
    payload = {
        "model": model,
        "messages": session.snapshot(),
        "stream": True
    }
    request = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    assistant_parts = []

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            for raw_line in response:
                if stop_event.is_set():
                    break
                if not raw_line.strip():
                    continue

                data = json.loads(raw_line.decode("utf-8"))
                if data.get("error"):
                    raise ChatError(str(data["error"]))

                message = data.get("message", {})
                chunk = message.get("content", "")
                if chunk:
                    assistant_parts.append(chunk)
                    on_chunk(chunk)

                if data.get("done"):
                    break
    except urllib.error.HTTPError as error:
        session.remove_last_user()
        if error.code == 404:
            raise ChatError("Model not found.", category="model_unavailable", stage="model_check") from error
        raise ChatError("Ollama request failed.", category="chat_generation_failed", stage="ollama_request") from error
    except (socket.timeout, TimeoutError) as error:
        session.remove_last_user()
        raise ChatError("Ollama request timed out.", category="timeout", stage="ollama_request") from error
    except urllib.error.URLError as error:
        session.remove_last_user()
        if isinstance(error.reason, ConnectionRefusedError):
            raise ChatError("Ollama is not connected.", category="ollama_unavailable", stage="ollama_connection") from error
        raise ChatError("Unable to connect to Ollama.", category="ollama_unavailable", stage="ollama_connection") from error
    except (OSError, ValueError, json.JSONDecodeError) as error:
        session.remove_last_user()
        raise ChatError("Invalid Ollama response.", category="invalid_response", stage="ollama_response") from error

    assistant_response = "".join(assistant_parts)
    if assistant_response:
        session.add_assistant(assistant_response)
        if not stop_event.is_set():
            try:
                from modules.memory import MemoryStore
                MemoryStore().queue_candidates(session.snapshot(), source="chat")
            except Exception:
                pass
    return "stopped" if stop_event.is_set() else "completed"

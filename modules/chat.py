import copy
import json
import math
import socket
import threading
import urllib.error
import urllib.request
from time import monotonic

from modules.ollama_request_policy import resolve_ollama_request_policy
from modules.settings import settings

DEFAULT_SYSTEM_CONTEXT = "You are Aurora, a helpful local AI assistant."
DEFAULT_CONTEXT_WARNING_TOKENS = 6000

_STREAM_TIMING_FIELDS = (
    "chat_request_start_monotonic",
    "payload_ready_monotonic",
    "urlopen_start_monotonic",
    "response_headers_monotonic",
    "first_raw_line_monotonic",
    "first_json_message_monotonic",
    "first_model_output_monotonic",
    "first_nonempty_content_monotonic",
    "stream_end_monotonic",
)
_STREAM_DURATION_FIELDS = {
    "request_to_payload_ms": ("chat_request_start_monotonic", "payload_ready_monotonic"),
    "payload_to_urlopen_ms": ("payload_ready_monotonic", "urlopen_start_monotonic"),
    "urlopen_to_headers_ms": ("urlopen_start_monotonic", "response_headers_monotonic"),
    "request_to_headers_ms": ("chat_request_start_monotonic", "response_headers_monotonic"),
    "headers_to_first_raw_line_ms": ("response_headers_monotonic", "first_raw_line_monotonic"),
    "first_raw_to_first_content_ms": ("first_raw_line_monotonic", "first_nonempty_content_monotonic"),
    "request_to_first_model_output_ms": ("chat_request_start_monotonic", "first_model_output_monotonic"),
    "request_to_first_content_ms": ("chat_request_start_monotonic", "first_nonempty_content_monotonic"),
    "stream_total_ms": ("chat_request_start_monotonic", "stream_end_monotonic"),
}
_OLLAMA_DURATION_FIELDS = (
    "total_duration",
    "load_duration",
    "prompt_eval_duration",
    "eval_duration",
)
_OLLAMA_COUNT_FIELDS = ("prompt_eval_count", "eval_count")


class ChatError(Exception):
    """Friendly error raised when an Ollama chat request cannot complete."""

    def __init__(self, message, category="chat_generation_failed", stage="ollama_request", detail=None):
        super().__init__(message)
        self.category = category
        self.stage = stage
        self.detail = detail or message


class StreamingRequestHandle:
    """Own and cancel one synchronous Ollama streaming response."""

    def __init__(self, stop_event, diagnostics=None, *, clock=monotonic):
        self.stop_event = stop_event
        self._clock = clock
        self._lock = threading.Lock()
        self._response = None
        self._finished = False
        self._diagnostics = diagnostics if diagnostics is not None else {}
        self._diagnostics.update({
            "cancel_requested_monotonic": None,
            "transport_abort_monotonic": None,
            "stream_exit_monotonic": None,
            "cancel_transport_latency_ms": None,
            "active_response": False,
            "status": "pending",
        })
        for field in _STREAM_TIMING_FIELDS:
            self._diagnostics.setdefault(field, None)
        for field in _STREAM_DURATION_FIELDS:
            self._diagnostics.setdefault(field, None)
        for field in _OLLAMA_DURATION_FIELDS:
            self._diagnostics.setdefault(f"{field}_ms", None)
        for field in _OLLAMA_COUNT_FIELDS:
            self._diagnostics.setdefault(field, None)
        self._diagnostics.setdefault("message_count", None)
        self._diagnostics.setdefault("approx_input_chars", None)
        self._diagnostics.setdefault("approx_input_tokens", None)
        self._diagnostics.setdefault("system_chars", None)
        self._diagnostics.setdefault("history_chars", None)
        self._diagnostics.setdefault("current_user_chars", None)
        self._diagnostics.setdefault("reasoning_chars", 0)
        self._diagnostics.setdefault("ollama_think_mode", None)
        self._diagnostics.setdefault("think_payload_value", None)
        self._diagnostics.setdefault("ollama_keep_alive", None)

    @property
    def diagnostics(self):
        return self._diagnostics

    @property
    def cancelled(self):
        with self._lock:
            requested = self._diagnostics["cancel_requested_monotonic"] is not None
        return requested or self.stop_event.is_set()

    @property
    def active_response(self):
        with self._lock:
            return self._response

    def mark_timing(self, name, *, first=False):
        """Record one request-local monotonic timestamp without blocking I/O."""

        now = self._clock()
        with self._lock:
            if first and self._diagnostics.get(name) is not None:
                return now
            self._diagnostics[name] = now
        return now

    def update_diagnostics(self, values):
        """Merge small diagnostic values under the request-local lock."""

        with self._lock:
            self._diagnostics.update(values)

    def increment_diagnostic(self, name, amount):
        """Increment one numeric request-local counter."""

        with self._lock:
            self._diagnostics[name] = self._diagnostics.get(name, 0) + amount

    def register_response(self, response):
        """Register *response*, or abort it immediately after an earlier cancel."""

        with self._lock:
            if self._finished:
                self._response = response
                self._diagnostics["active_response"] = True
                should_abort = True
            elif self._response is not None:
                raise RuntimeError("Streaming request already has an active response")
            else:
                self._response = response
                self._diagnostics["active_response"] = True
                should_abort = (
                    self._diagnostics["cancel_requested_monotonic"] is not None
                    or self.stop_event.is_set()
                )
        if should_abort:
            self._abort_registered_response(response)
            return False
        return True

    def cancel(self):
        """Set the high-level cancellation truth and abort this request's response."""

        now = self._clock()
        with self._lock:
            if self._finished:
                return False
            first_request = self._diagnostics["cancel_requested_monotonic"] is None
            if first_request:
                self._diagnostics["cancel_requested_monotonic"] = now
                self._diagnostics["status"] = "cancelled"
            self.stop_event.set()
            response = self._response
        if response is not None:
            self._abort_registered_response(response)
        return first_request

    def close(self):
        """Close the currently owned response without marking cancellation."""

        with self._lock:
            response = self._response
        if response is None:
            return False
        return self.close_response(response)

    def close_response(self, response):
        """Close *response* only if it is still owned by this handle."""

        with self._lock:
            if self._response is not response:
                return False
            self._response = None
            self._diagnostics["active_response"] = False
        _close_http_response(response, abort=False)
        return True

    def finish(self, status):
        now = self._clock()
        with self._lock:
            if self._finished:
                return
            self._finished = True
            self._response = None
            self._diagnostics["active_response"] = False
            self._diagnostics["stream_exit_monotonic"] = now
            self._diagnostics["stream_end_monotonic"] = now
            cancel_requested = self._diagnostics["cancel_requested_monotonic"]
            if cancel_requested is not None:
                status = "cancelled"
                self._diagnostics["cancel_transport_latency_ms"] = max(
                    0.0,
                    (now - cancel_requested) * 1000.0,
                )
            self._diagnostics["status"] = status
            _derive_stream_durations(self._diagnostics)

    def _abort_registered_response(self, response):
        now = self._clock()
        with self._lock:
            if self._response is not response:
                return False
            self._response = None
            self._diagnostics["active_response"] = False
            if self._diagnostics["transport_abort_monotonic"] is None:
                self._diagnostics["transport_abort_monotonic"] = now
        _close_http_response(response, abort=True)
        return True


def _close_http_response(response, *, abort):
    """Close one urllib response, shutting down only its socket when aborting."""

    if response is None:
        return
    if abort:
        fp = getattr(response, "fp", None)
        raw = getattr(fp, "raw", None)
        candidates = (
            getattr(raw, "_sock", None),
            getattr(fp, "_sock", None),
            getattr(response, "_sock", None),
        )
        for candidate in candidates:
            if candidate is None or not callable(getattr(candidate, "shutdown", None)):
                continue
            try:
                candidate.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            break
    try:
        response.close()
    except OSError:
        pass


def _watch_stream_cancellation(handle, finished_event):
    """Bridge a plain threading.Event to the request-local transport handle."""

    while not finished_event.wait(0.02):
        if handle.stop_event.is_set():
            handle.cancel()
            return


def _derive_stream_durations(diagnostics):
    for output_name, (start_name, end_name) in _STREAM_DURATION_FIELDS.items():
        start = diagnostics.get(start_name)
        end = diagnostics.get(end_name)
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            diagnostics[output_name] = max(0.0, (end - start) * 1000.0)
        else:
            diagnostics[output_name] = None


def _stream_input_diagnostics(messages, current_prompt):
    contents = [str(message.get("content", "") or "") for message in messages]
    total_chars = sum(len(content) for content in contents)
    system_chars = sum(
        len(content)
        for message, content in zip(messages, contents)
        if message.get("role") == "system"
    )
    current_user_chars = len(str(current_prompt or ""))
    history_chars = max(0, total_chars - system_chars - current_user_chars)
    return {
        "message_count": len(messages),
        "approx_input_chars": total_chars,
        "approx_input_tokens": estimate_tokens("\n".join(contents)),
        "system_chars": system_chars,
        "history_chars": history_chars,
        "current_user_chars": current_user_chars,
    }


def _finite_nonnegative_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _ollama_metrics(data):
    metrics = {}
    for field in _OLLAMA_DURATION_FIELDS:
        value = _finite_nonnegative_number(data.get(field))
        if value is not None:
            metrics[f"{field}_ms"] = value / 1_000_000.0
    for field in _OLLAMA_COUNT_FIELDS:
        value = _finite_nonnegative_number(data.get(field))
        if value is not None and value.is_integer():
            metrics[field] = int(value)
    return metrics


def _raw_line_observation(timestamp, data):
    message = data.get("message")
    if not isinstance(message, dict):
        message = {}
    content = message.get("content")
    thinking = message.get("thinking", data.get("thinking"))
    reasoning = message.get("reasoning", data.get("reasoning"))
    return {
        "timestamp": timestamp,
        "top_level_keys": sorted(str(key) for key in data),
        "message_keys": sorted(str(key) for key in message),
        "done": bool(data.get("done")),
        "content_length": len(content) if isinstance(content, str) else 0,
        "thinking_length": len(thinking) if isinstance(thinking, str) else 0,
        "reasoning_length": len(reasoning) if isinstance(reasoning, str) else 0,
    }


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


def stream_chat(
    model,
    prompt,
    session,
    on_chunk,
    stop_event,
    *,
    request_handle=None,
    diagnostics=None,
    raw_line_observer=None,
    thinking_mode=None,
):
    """Stream one Ollama response while preserving the session context."""

    handle = request_handle or StreamingRequestHandle(stop_event, diagnostics)
    if handle.stop_event is not stop_event:
        raise ValueError("request_handle must own the supplied stop_event")
    handle.mark_timing("chat_request_start_monotonic", first=True)

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

    if stop_event.is_set():
        handle.cancel()
        handle.finish("cancelled")
        return "stopped"

    request_policy = resolve_ollama_request_policy(
        settings,
        thinking_mode=thinking_mode,
    )
    session.add_user(prompt)
    messages = session.snapshot()
    payload = {
        "model": model,
        "messages": messages,
        "stream": True
    }
    request_policy.apply(payload)
    request = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    handle.update_diagnostics(_stream_input_diagnostics(messages, prompt))
    handle.update_diagnostics(request_policy.diagnostics())
    handle.mark_timing("payload_ready_monotonic", first=True)
    assistant_parts = []
    response = None
    stream_finished = threading.Event()
    cancel_watcher = threading.Thread(
        target=_watch_stream_cancellation,
        args=(handle, stream_finished),
        name="ollama-stream-cancel",
        daemon=True,
    )
    cancel_watcher.start()
    status = "completed"

    try:
        handle.mark_timing("urlopen_start_monotonic", first=True)
        response = urllib.request.urlopen(request, timeout=120)
        handle.mark_timing("response_headers_monotonic", first=True)
        if handle.register_response(response):
            for raw_line in response:
                if handle.cancelled:
                    status = "cancelled"
                    break
                if not raw_line.strip():
                    continue

                raw_timestamp = handle.mark_timing("first_raw_line_monotonic", first=True)
                data = json.loads(raw_line.decode("utf-8"))
                handle.mark_timing("first_json_message_monotonic", first=True)
                if handle.cancelled:
                    status = "cancelled"
                    break
                if data.get("error"):
                    raise ChatError(str(data["error"]))

                message = data.get("message", {})
                thinking = message.get("thinking", data.get("thinking", ""))
                reasoning = message.get("reasoning", data.get("reasoning", ""))
                reasoning_chars = sum(
                    len(value)
                    for value in (thinking, reasoning)
                    if isinstance(value, str)
                )
                chunk = message.get("content", "")
                if reasoning_chars:
                    handle.mark_timing("first_model_output_monotonic", first=True)
                    handle.increment_diagnostic("reasoning_chars", reasoning_chars)
                if callable(raw_line_observer):
                    try:
                        raw_line_observer(_raw_line_observation(raw_timestamp, data))
                    except Exception:
                        pass
                if chunk:
                    if handle.cancelled:
                        status = "cancelled"
                        break
                    handle.mark_timing("first_model_output_monotonic", first=True)
                    handle.mark_timing("first_nonempty_content_monotonic", first=True)
                    assistant_parts.append(chunk)
                    on_chunk(chunk)

                if data.get("done"):
                    metrics = _ollama_metrics(data)
                    if metrics:
                        handle.update_diagnostics(metrics)

                if data.get("done"):
                    break
        else:
            status = "cancelled"
    except ChatError:
        if handle.cancelled:
            status = "cancelled"
        else:
            status = "failed"
            session.remove_last_user()
            raise
    except urllib.error.HTTPError as error:
        if handle.cancelled:
            status = "cancelled"
            _close_http_response(error, abort=True)
        else:
            status = "failed"
            session.remove_last_user()
            _close_http_response(error, abort=False)
            if error.code == 404:
                raise ChatError("Model not found.", category="model_unavailable", stage="model_check") from error
            raise ChatError("Ollama request failed.", category="chat_generation_failed", stage="ollama_request") from error
    except (socket.timeout, TimeoutError) as error:
        if handle.cancelled:
            status = "cancelled"
        else:
            status = "failed"
            session.remove_last_user()
            raise ChatError("Ollama request timed out.", category="timeout", stage="ollama_request") from error
    except urllib.error.URLError as error:
        if handle.cancelled:
            status = "cancelled"
        else:
            status = "failed"
            session.remove_last_user()
            if isinstance(error.reason, ConnectionRefusedError):
                raise ChatError("Ollama is not connected.", category="ollama_unavailable", stage="ollama_connection") from error
            raise ChatError("Unable to connect to Ollama.", category="ollama_unavailable", stage="ollama_connection") from error
    except (OSError, ValueError, json.JSONDecodeError) as error:
        if handle.cancelled:
            status = "cancelled"
        else:
            status = "failed"
            session.remove_last_user()
            raise ChatError("Invalid Ollama response.", category="invalid_response", stage="ollama_response") from error
    except Exception:
        if handle.cancelled:
            status = "cancelled"
        else:
            status = "failed"
            session.remove_last_user()
            raise
    finally:
        if stop_event.is_set():
            handle.cancel()
        stream_finished.set()
        if response is not None:
            handle.close_response(response)
        cancel_watcher.join(timeout=0.25)
        handle.finish("cancelled" if handle.cancelled else status)

    assistant_response = "".join(assistant_parts)
    if assistant_response and not handle.cancelled:
        session.add_assistant(assistant_response)
        try:
            from modules.memory import MemoryStore
            MemoryStore().queue_candidates(session.snapshot(), source="chat")
        except Exception:
            pass
    return "stopped" if handle.cancelled else "completed"

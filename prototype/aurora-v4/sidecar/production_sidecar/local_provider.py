"""V4-only llama.cpp transport. Rust owns process, endpoint, token and residency.

Reuse the production request-local cancellation owner, not Ollama's wire format.
No prompts, response bodies, credentials or paths are written to diagnostics.
"""
from __future__ import annotations

import http.client
import io
import json
import os
import select
import threading
import urllib.error
import urllib.parse
import urllib.request
from time import monotonic

from modules.chat import ChatError, ChatSession, StreamingRequestHandle, _watch_stream_cancellation


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class _OwnedConnection:
    """Keep a duplicate socket handle alive even when HTTPResponse closes its owner.

    shutdown() on the duplicate wakes the same TCP connection on Windows. The
    request handle can register it before waiting for response headers as well.
    """
    def __init__(self, connection):
        self.connection = connection
        self._sock = connection.sock.dup()
        self.response = None

    def readline(self, limit):
        return self.response.readline(limit)

    def close(self):
        try:
            if self.response is not None:
                self.response.close()
        finally:
            self.connection.close()
            self._sock.close()


class _CancellableRead(io.RawIOBase):
    def __init__(self, sock, stop_event, timeout):
        self.sock, self.stop_event, self.timeout = sock, stop_event, timeout

    def readable(self):
        return True

    def readinto(self, buffer):
        deadline = monotonic() + self.timeout
        while not self.stop_event.is_set():
            if monotonic() >= deadline:
                raise TimeoutError("LOCAL_READ_TIMEOUT")
            # Windows select need not wake merely because another thread called
            # shutdown. Bounded polling checks cancellation without poisoning a
            # socket.makefile buffer with recoverable socket.timeout exceptions.
            if select.select([self.sock], [], [], 0.02)[0]:
                data = self.sock.recv(len(buffer))
                buffer[:len(data)] = data
                return len(data)
        return 0


class _CancellableSocket:
    def __init__(self, original, reader_socket, stop_event, timeout):
        self.original, self.reader_socket = original, reader_socket
        self.stop_event, self.timeout = stop_event, timeout

    def __getattr__(self, name):
        return getattr(self.original, name)

    def makefile(self, mode, *args, **kwargs):
        if mode != "rb":
            raise ValueError("Only binary HTTP reads are supported")
        return io.BufferedReader(_CancellableRead(self.reader_socket, self.stop_event, self.timeout))


class BuiltInLlamaProvider:
    def __init__(self, endpoint, token, model, *, opener=None):
        parsed = urllib.parse.urlsplit(endpoint)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
                or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password):
            raise ValueError("INVALID_PRIVATE_RUNTIME_ENDPOINT")
        if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError("INVALID_PRIVATE_RUNTIME_TOKEN")
        self._endpoint, self._token = endpoint, token
        self.model = model
        self._opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self._background_lock = threading.Lock()
        self._background = None
        self._foreground = False

    @classmethod
    def from_environment(cls):
        if os.environ.get("AURORA_V4_CHAT_PROVIDER") != "builtin_local":
            return None
        return cls(os.environ["AURORA_LOCAL_ENDPOINT"], os.environ["AURORA_LOCAL_TOKEN"],
                   os.environ.get("AURORA_LOCAL_MODEL", "aurora-local"))

    def _request(self, path, payload=None):
        return urllib.request.Request(self._endpoint + path,
            data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf8"),
            headers={"Authorization": "Bearer " + self._token, "Content-Type": "application/json"})

    def probe(self):
        started = monotonic()
        result = dict(provider="builtin_local", backend="vulkan", state="FAILED",
                      configured_model=self.model, reachable=False, model_available=False,
                      error_code="LOCAL_MODEL_UNAVAILABLE", probe_duration_ms=0.0)
        try:
            with self._opener.open(self._request("/health"), timeout=1) as response:
                ready = json.loads(response.read(65537)).get("status") == "ok"
            with self._opener.open(self._request("/v1/models"), timeout=1) as response:
                models = json.loads(response.read(65537)).get("data", [])
            available = ready and any(m.get("id") == self.model for m in models)
            result.update(reachable=True, model_available=available,
                          state="READY" if available else "LOADING_MODEL",
                          error_code="" if available else "LOCAL_MODEL_UNAVAILABLE")
        except (ValueError, TypeError, AttributeError, OSError, http.client.HTTPException):
            pass
        result["probe_duration_ms"] = round((monotonic() - started) * 1000, 3)
        return result

    @staticmethod
    def payload(model, messages, *, num_predict=1024, temperature=0.7, thinking_mode="off"):
        if thinking_mode not in (None, "off", "default", "on"):
            raise ValueError("INVALID_THINKING_MODE")
        return dict(model=model, messages=messages, stream=True, max_tokens=num_predict,
                    temperature=temperature, stream_options={"include_usage": True},
                    chat_template_kwargs={"enable_thinking": thinking_mode == "on"})

    def _stream(self, messages, handle, on_chunk, *, observer=None, timeout=120,
                num_predict=1024, thinking_mode="off"):
        handle.mark_timing("chat_request_start_monotonic", first=True)
        handle.update_diagnostics({"provider": "builtin_local", "ollama_think_mode": "default",
                                   "think_payload_value": None, "ollama_keep_alive": None})
        finished = threading.Event()
        watcher = threading.Thread(target=_watch_stream_cancellation, args=(handle, finished),
                                   name="builtin-stream-cancel", daemon=True)
        response = None
        parts, status, done, terminal = [], "completed", False, False
        watcher.start()
        try:
            if handle.cancelled:
                return ""
            address = urllib.parse.urlsplit(self._endpoint)
            connection = http.client.HTTPConnection(address.hostname, address.port, timeout=min(timeout, 5))
            connection.connect()
            connection.sock.settimeout(timeout)
            response = _OwnedConnection(connection)
            connection.sock = _CancellableSocket(connection.sock, response._sock, handle.stop_event, timeout)
            if not handle.register_response(response):
                return ""
            body = json.dumps(self.payload(self.model, messages, num_predict=num_predict,
                                          thinking_mode=thinking_mode), ensure_ascii=False).encode("utf8")
            connection.request("POST", "/v1/chat/completions", body=body,
                headers={"Authorization": "Bearer " + self._token, "Content-Type": "application/json"})
            response.response = connection.getresponse()
            handle.mark_timing("response_headers_monotonic", first=True)
            if response.response.status != 200:
                raise OSError("LOCAL_HTTP_ERROR")
            # llama.cpp emits one JSON object per SSE data line. Bound each line.
            while not handle.cancelled:
                line = response.readline(1_048_577)
                if not line:
                    break
                if len(line) > 1_048_576:
                    raise ValueError("oversized SSE record")
                if line in (b"\r\n", b"\n") or line.startswith(b":"):
                    continue
                if not line.startswith(b"data:"):
                    raise ValueError("invalid SSE record")
                raw = line[5:].strip()
                handle.mark_timing("first_raw_line_monotonic", first=True)
                if raw == b"[DONE]":
                    done = True
                    if not terminal:
                        raise ValueError("missing finish reason")
                    if observer:
                        observer({"done": True})
                    break
                obj = json.loads(raw)
                if not isinstance(obj, dict) or obj.get("error"):
                    raise ValueError("server error")
                choices = obj.get("choices")
                if not isinstance(choices, list):
                    raise ValueError("invalid choices")
                for choice in choices:
                    delta = choice.get("delta", {})
                    content = delta.get("content") or ""
                    reasoning = delta.get("reasoning_content") or ""
                    if not isinstance(content, str) or not isinstance(reasoning, str):
                        raise ValueError("invalid delta")
                    if content or reasoning:
                        handle.mark_timing("first_model_output_monotonic", first=True)
                    if reasoning:
                        handle.increment_diagnostic("reasoning_chars", len(reasoning))
                    if content and not handle.cancelled:
                        handle.mark_timing("first_nonempty_content_monotonic", first=True)
                        parts.append(content)
                        on_chunk(content)
                    reason = choice.get("finish_reason")
                    if reason is not None:
                        if reason not in {"stop", "length"}:
                            raise ValueError("unsupported finish reason")
                        terminal = True
                usage = obj.get("usage") or {}
                for wire, metric in (("prompt_tokens", "prompt_eval_count"), ("completion_tokens", "eval_count")):
                    if isinstance(usage.get(wire), int) and usage[wire] >= 0:
                        handle.update_diagnostics({metric: usage[wire]})
                timings = obj.get("timings") or {}
                for wire, metric in (("prompt_ms", "prompt_eval_duration_ms"), ("predicted_ms", "eval_duration_ms")):
                    value = timings.get(wire)
                    if type(value) in (int, float) and 0 <= value < float("inf"):
                        handle.update_diagnostics({metric: value})
            if not handle.cancelled and not done:
                raise ValueError("incomplete SSE stream")
        except Exception as error:
            if not handle.cancelled:
                status = "failed"
                category = "timeout" if isinstance(error, TimeoutError) else (
                    "provider_unavailable" if isinstance(error, (OSError, http.client.HTTPException)) else "invalid_response")
                raise ChatError("Local model request failed.", category=category, stage="builtin_transport") from None
        finally:
            finished.set()
            watcher.join()
            if response is not None:
                handle.close_response(response)
                response.close()
            handle.finish("cancelled" if handle.cancelled else status)
        return "".join(parts)

    def stream_chat(self, model, prompt, session, on_chunk, stop_event, *, request_handle=None,
                    diagnostics=None, raw_line_observer=None, thinking_mode="off", **_):
        handle = request_handle or StreamingRequestHandle(stop_event, diagnostics)
        if handle.stop_event is not stop_event:
            raise ValueError("mismatched cancellation owner")
        if handle.cancelled:
            handle.finish("cancelled")
            return "stopped"
        before = session.snapshot()
        session.add_user(prompt)
        try:
            text = self._stream(session.snapshot(), handle, on_chunk, observer=raw_line_observer,
                                thinking_mode=thinking_mode)
            if handle.cancelled:
                session.replace(before)
                return "stopped"
            session.add_assistant(text)
            return text
        except Exception:
            session.replace(before)
            raise

    def chat_with_messages(self, model, messages, *, timeout=30, thinking_mode="off",
                           num_predict=32, diagnostics=None, **_):
        handle = StreamingRequestHandle(threading.Event(), diagnostics)
        with self._background_lock:
            if self._foreground:
                raise ChatError("Background request deferred.", category="background_deferred", stage="builtin_transport")
            self._background = handle
        try:
            return self._stream(messages, handle, lambda _: None, timeout=timeout,
                                num_predict=num_predict, thinking_mode=thinking_mode)
        finally:
            with self._background_lock:
                if self._background is handle:
                    self._background = None

    def cancel_background(self):
        with self._background_lock:
            handle = self._background
        if handle:
            handle.cancel()

    def foreground_started(self):
        with self._background_lock:
            self._foreground = True
            handle = self._background
        if handle:
            handle.cancel()

    def foreground_finished(self):
        with self._background_lock:
            self._foreground = False

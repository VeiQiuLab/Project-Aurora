"""Real loopback SSE tests; never load model weights or require a GPU."""
import asyncio
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic

import pytest
from test_production_sidecar import ProductionComposition
from production_sidecar.local_provider import BuiltInLlamaProvider
from production_sidecar.direct_chat import DirectChatAdapter, ChatRequest
from modules.chat import ChatSession, ChatError, StreamingRequestHandle

TOKEN = "fixture-private-key-" * 3


@contextmanager
def llama_fixture(mode="success"):
    calls, release = [], threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            if self.path == "/health": payload = {"status": "ok"}
            else:
                if self.headers.get("Authorization") != "Bearer " + TOKEN:
                    self.send_error(401); return
                payload = {"data": [{"id": "fixture-4B"}]}
            raw = json.dumps(payload).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, self.headers.get("Authorization"), payload))
            if mode == "blocked_headers": release.wait(5)
            if mode == "error": self.send_error(500); return
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            try:
                def frame(delta, reason=None):
                    raw = json.dumps({"choices": [{"delta": delta, "finish_reason": reason}]}).encode()
                    self.wfile.write(b"data: " + raw + b"\n\n"); self.wfile.flush()
                frame({"reasoning_content": "not-saved-reasoning"})
                frame({"content": "你好"})
                if mode == "blocked": release.wait(5)
                if mode == "invalid": self.wfile.write(b"data: not-json\n\n"); return
                if mode == "incomplete": return
                frame({"content": "世界"})
                frame({}, "stop")
                self.wfile.write(b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":4}}\n\ndata: [DONE]\n\n')
                self.wfile.flush()
            except (ConnectionError, OSError): pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try: yield BuiltInLlamaProvider(f"http://127.0.0.1:{server.server_port}", TOKEN, "fixture-4B"), calls
    finally:
        release.set(); server.shutdown(); server.server_close(); thread.join(3)
        assert not thread.is_alive()


def test_mapping_stream_completion_diagnostics_and_no_secrets():
    with llama_fixture() as (provider, calls):
        session, chunks, stop, diagnostics = ChatSession(), [], threading.Event(), {}
        result = provider.stream_chat("ignored-legacy-model", "fixture", session, chunks.append, stop, diagnostics=diagnostics)
        assert result == "你好世界" and chunks == ["你好", "世界"]
        assert session.snapshot()[-1] == {"role": "assistant", "content": "你好世界"}
        path, auth, payload = calls[0]
        assert path == "/v1/chat/completions" and auth == "Bearer " + TOKEN
        assert payload["model"] == "fixture-4B" and payload["stream"] is True
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        assert not ({"think", "keep_alive", "options", "num_predict"} & payload.keys())
        assert diagnostics["eval_count"] == 4 and diagnostics["request_to_first_content_ms"] >= 0
        assert diagnostics["reasoning_chars"] == len("not-saved-reasoning")
        assert not any(secret in json.dumps(diagnostics) for secret in (TOKEN, "not-saved-reasoning", "你好"))
        assert not diagnostics["active_response"]


@pytest.mark.parametrize("mode", ["incomplete", "invalid", "error"])
def test_failure_does_not_commit_partial_assistant(mode):
    with llama_fixture(mode) as (provider, _):
        session = ChatSession(); before = session.snapshot()
        with pytest.raises(ChatError): provider.stream_chat("m", "fixture", session, lambda _: None, threading.Event())
        assert session.snapshot() == before


def test_cancel_unblocks_real_read_and_next_request_recovers():
    with llama_fixture("blocked") as (provider, _):
        session = ChatSession(); before = session.snapshot(); ready = threading.Event(); diagnostics = {}
        handle = StreamingRequestHandle(threading.Event(), diagnostics)
        worker = threading.Thread(target=lambda: provider.stream_chat("m", "fixture", session, lambda _: ready.set(), handle.stop_event, request_handle=handle))
        worker.start(); assert ready.wait(2)
        started = monotonic(); handle.cancel(); handle.cancel(); worker.join(2)
        assert not worker.is_alive() and monotonic() - started < 2
        assert diagnostics["status"] == "cancelled" and handle.active_response is None
        assert session.snapshot() == before
        handle.close(); assert not handle.close()
    with llama_fixture() as (provider, _):
        assert provider.stream_chat("m", "recovery", session, lambda _: None, threading.Event()) == "你好世界"


def test_precancel_does_not_open_request():
    with llama_fixture() as (provider, calls):
        stop = threading.Event(); stop.set()
        assert provider.stream_chat("m", "fixture", ChatSession(), lambda _: None, stop) == "stopped"
        assert not calls


def test_cancel_while_response_headers_are_blocked():
    with llama_fixture("blocked_headers") as (provider, calls):
        handle = StreamingRequestHandle(threading.Event(), {})
        session = ChatSession()
        before = session.snapshot()
        worker = threading.Thread(target=lambda: provider.stream_chat("m", "fixture", session, lambda _: None,
                                  handle.stop_event, request_handle=handle))
        worker.start()
        deadline = monotonic() + 2
        while not calls and monotonic() < deadline: threading.Event().wait(.005)
        assert calls
        handle.cancel(); worker.join(2)
        assert not worker.is_alive() and handle.active_response is None
        assert session.snapshot() == before


def test_read_timeout_is_real_failure_not_cancellation():
    with llama_fixture("blocked") as (provider, _):
        diagnostics = {}
        handle = StreamingRequestHandle(threading.Event(), diagnostics)
        with pytest.raises(ChatError) as caught:
            provider._stream([{"role": "user", "content": "fixture"}], handle, lambda _: None, timeout=.1)
        assert caught.value.category == "timeout"
        assert diagnostics["status"] == "failed" and handle.active_response is None


def test_foreground_aborts_inflight_title_and_prevents_new_background_request():
    with llama_fixture("blocked") as (provider, calls):
        diagnostics = {}
        worker = threading.Thread(target=lambda: provider.chat_with_messages("m", [], diagnostics=diagnostics))
        worker.start()
        deadline = monotonic() + 2
        while not calls and monotonic() < deadline: threading.Event().wait(.005)
        assert calls
        provider.foreground_started(); worker.join(2)
        assert not worker.is_alive() and diagnostics["status"] == "cancelled"
        assert provider._background is None
        with pytest.raises(ChatError) as caught: provider.chat_with_messages("m", [])
        assert caught.value.category == "background_deferred"
        assert len(calls) == 1
        provider.foreground_finished()
        provider.cancel_background()


def test_title_mapping_and_private_health():
    with llama_fixture() as (provider, calls):
        assert provider.probe()["state"] == "READY"
        assert provider.chat_with_messages("m", [{"role": "user", "content": "fixture"}], num_predict=32) == "你好世界"
        assert calls[0][2]["max_tokens"] == 32
        assert TOKEN not in json.dumps(provider.probe())


def test_v4_selection_context_history_legacy_unchanged(tmp_path, monkeypatch):
    with llama_fixture() as (provider, calls):
        monkeypatch.setenv("AURORA_V4_CHAT_PROVIDER", "builtin_local")
        monkeypatch.setenv("AURORA_LOCAL_ENDPOINT", provider._endpoint)
        monkeypatch.setenv("AURORA_LOCAL_TOKEN", TOKEN)
        monkeypatch.setenv("AURORA_LOCAL_MODEL", "fixture-4B")
        composition = ProductionComposition(config_file=tmp_path/"settings.json", conversation_root=tmp_path/"conversations")
        try:
            health = asyncio.run(composition.refresh())
            assert composition.state == "READY" and health["ollama"]["reachable"] is False
            assert health["local_model"]["state"] == "READY"
            adapter = DirectChatAdapter(composition)
            request = ChatRequest("r", "s", "g", "next", history=({"role": "user", "content": "earlier"}, {"role": "assistant", "content": "remembered"}))
            context = {"system_context": "context-from-production"}
            handle = adapter.new_handle(threading.Event(), {})
            result, saved = adapter.stream(request, "fixture-4B", handle, lambda _: None, context)
            assert result == "你好世界"
            assert calls[0][2]["messages"][0]["content"] == "context-from-production"
            assert any(m["content"] == "earlier" for m in calls[0][2]["messages"])
            assert all(m["content"] != "context-from-production" for m in saved)
        finally: composition.close()
        monkeypatch.delenv("AURORA_V4_CHAT_PROVIDER")
        composition = ProductionComposition(config_file=tmp_path/"legacy.json")
        try: assert composition.local_provider is None
        finally: composition.close()


@pytest.mark.parametrize("endpoint", ["http://0.0.0.0:10", "http://localhost:10", "https://127.0.0.1:10", "http://127.0.0.1:10/x", "http://user@127.0.0.1:10"])
def test_endpoint_is_private_and_strict(endpoint):
    with pytest.raises(ValueError): BuiltInLlamaProvider(endpoint, TOKEN, "fixture")

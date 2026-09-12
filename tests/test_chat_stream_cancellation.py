import http.client
import json
import threading
from collections import deque
from unittest.mock import Mock

import pytest

from modules import chat
from modules.chat import ChatError, ChatSession, StreamingRequestHandle


MODEL = "qwen3:8b"


def ollama_line(content="", *, done=False):
    return (
        json.dumps({"message": {"content": content}, "done": done}) + "\n"
    ).encode("utf-8")


class ListResponse:
    def __init__(self, lines):
        self.lines = list(lines)
        self.close_calls = 0

    def __iter__(self):
        return iter(self.lines)

    def close(self):
        self.close_calls += 1


class ErrorResponse(ListResponse):
    def __init__(self, error):
        super().__init__([])
        self.error = error

    def __iter__(self):
        raise self.error


class BlockingResponse:
    def __init__(self, lines=(), *, close_error=None):
        self.lines = deque(lines)
        self.close_error = close_error or ConnectionResetError("response closed")
        self.blocked = threading.Event()
        self.closed = threading.Event()
        self.close_calls = 0
        self._lock = threading.Lock()

    def __iter__(self):
        return self

    def __next__(self):
        with self._lock:
            if self.lines:
                return self.lines.popleft()
        self.blocked.set()
        self.closed.wait(5)
        raise self.close_error

    def close(self):
        with self._lock:
            self.close_calls += 1
        self.closed.set()


class ShutdownSocket:
    def __init__(self, released):
        self.released = released
        self.shutdown_calls = []

    def shutdown(self, how):
        self.shutdown_calls.append(how)
        self.released.set()


class SocketBlockedResponse:
    def __init__(self):
        self.blocked = threading.Event()
        self.released = threading.Event()
        self.close_calls = 0
        self.socket = ShutdownSocket(self.released)
        self.fp = type("Buffer", (), {})()
        self.fp.raw = type("Raw", (), {"_sock": self.socket})()

    def __iter__(self):
        return self

    def __next__(self):
        self.blocked.set()
        self.released.wait(5)
        raise ConnectionResetError("socket shutdown")

    def close(self):
        self.close_calls += 1


class CancelOnDecode(bytes):
    def __new__(cls, value, stop_event):
        instance = super().__new__(cls, value)
        instance.stop_event = stop_event
        return instance

    def decode(self, *args, **kwargs):
        self.stop_event.set()
        return super().decode(*args, **kwargs)


@pytest.fixture(autouse=True)
def configured_chat(monkeypatch):
    original_get = chat.settings.get

    def get_setting(key, default=None):
        if key == "ollama.host":
            return "http://127.0.0.1:11434"
        return original_get(key, default)

    monkeypatch.setattr(chat.settings, "get", get_setting)
    monkeypatch.setattr("modules.memory.MemoryStore.queue_candidates", lambda *args, **kwargs: [])


def run_stream(monkeypatch, response, *, stop_event=None, diagnostics=None, on_chunk=None):
    event = stop_event or threading.Event()
    session = ChatSession()
    chunks = []
    monkeypatch.setattr(chat.urllib.request, "urlopen", Mock(return_value=response))
    result = chat.stream_chat(
        MODEL,
        "hello",
        session,
        on_chunk or chunks.append,
        event,
        diagnostics=diagnostics,
    )
    return result, session, chunks


def test_normal_streaming_multiple_chunks_and_cleanup(monkeypatch):
    response = ListResponse([
        ollama_line("hello "),
        ollama_line("world"),
        ollama_line(done=True),
    ])
    diagnostics = {}

    result, session, chunks = run_stream(
        monkeypatch,
        response,
        diagnostics=diagnostics,
    )

    assert result == "completed"
    assert chunks == ["hello ", "world"]
    assert session.snapshot()[-1] == {"role": "assistant", "content": "hello world"}
    assert response.close_calls == 1
    assert diagnostics["status"] == "completed"
    assert diagnostics["active_response"] is False
    assert diagnostics["cancel_requested_monotonic"] is None
    assert diagnostics["stream_exit_monotonic"] is not None


def test_cancel_before_request_skips_urlopen_and_session_mutation(monkeypatch):
    stop_event = threading.Event()
    stop_event.set()
    urlopen = Mock()
    diagnostics = {}
    monkeypatch.setattr(chat.urllib.request, "urlopen", urlopen)
    session = ChatSession()

    result = chat.stream_chat(
        MODEL,
        "hello",
        session,
        lambda _chunk: None,
        stop_event,
        diagnostics=diagnostics,
    )

    assert result == "stopped"
    urlopen.assert_not_called()
    assert session.snapshot() == [{"role": "system", "content": session.system_context}]
    assert diagnostics["status"] == "cancelled"
    assert diagnostics["transport_abort_monotonic"] is None


def test_cancel_closes_response_and_unblocks_a_real_blocked_iterator(monkeypatch):
    response = BlockingResponse()
    stop_event = threading.Event()
    diagnostics = {}
    results = []
    session = ChatSession()
    monkeypatch.setattr(chat.urllib.request, "urlopen", Mock(return_value=response))

    worker = threading.Thread(
        target=lambda: results.append(
            chat.stream_chat(
                MODEL,
                "hello",
                session,
                lambda _chunk: None,
                stop_event,
                diagnostics=diagnostics,
            )
        )
    )
    worker.start()
    assert response.blocked.wait(1), "fake transport never reached its blocked read"

    stop_event.set()
    worker.join(1)

    assert not worker.is_alive()
    assert results == ["stopped"]
    assert response.close_calls == 1
    assert diagnostics["cancel_requested_monotonic"] is not None
    assert diagnostics["transport_abort_monotonic"] is not None
    assert diagnostics["stream_exit_monotonic"] is not None
    assert diagnostics["cancel_transport_latency_ms"] >= 0
    assert diagnostics["status"] == "cancelled"
    assert diagnostics["active_response"] is False


def test_cancel_shuts_down_only_the_active_urllib_socket(monkeypatch):
    response = SocketBlockedResponse()
    stop_event = threading.Event()
    results = []
    monkeypatch.setattr(chat.urllib.request, "urlopen", Mock(return_value=response))

    worker = threading.Thread(
        target=lambda: results.append(
            chat.stream_chat(
                MODEL,
                "hello",
                ChatSession(),
                lambda _chunk: None,
                stop_event,
            )
        )
    )
    worker.start()
    assert response.blocked.wait(1)
    stop_event.set()
    worker.join(1)

    assert results == ["stopped"]
    assert response.socket.shutdown_calls == [chat.socket.SHUT_RDWR]
    assert response.close_calls == 1
    assert not worker.is_alive()


def test_cancel_after_first_chunk_does_not_commit_partial_assistant(monkeypatch):
    response = BlockingResponse([ollama_line("partial")])
    stop_event = threading.Event()
    diagnostics = {}
    chunks = []
    result = []
    session = ChatSession()
    monkeypatch.setattr(chat.urllib.request, "urlopen", Mock(return_value=response))

    worker = threading.Thread(
        target=lambda: result.append(
            chat.stream_chat(
                MODEL,
                "hello",
                session,
                chunks.append,
                stop_event,
                diagnostics=diagnostics,
            )
        )
    )
    worker.start()
    assert response.blocked.wait(1)
    stop_event.set()
    worker.join(1)

    assert result == ["stopped"]
    assert chunks == ["partial"]
    assert [item["role"] for item in session.snapshot()] == ["system", "user"]
    assert diagnostics["status"] == "cancelled"


def test_cancel_set_by_first_callback_prevents_later_callback_and_completion(monkeypatch):
    stop_event = threading.Event()
    response = ListResponse([
        ollama_line("first"),
        ollama_line("late"),
        ollama_line(done=True),
    ])
    chunks = []

    def cancel_on_first(chunk):
        chunks.append(chunk)
        stop_event.set()

    result, session, _ = run_stream(
        monkeypatch,
        response,
        stop_event=stop_event,
        on_chunk=cancel_on_first,
    )

    assert result == "stopped"
    assert chunks == ["first"]
    assert not any(item["role"] == "assistant" for item in session.snapshot())


def test_cancel_during_json_decode_prevents_chunk_delivery(monkeypatch):
    stop_event = threading.Event()
    raw = CancelOnDecode(ollama_line("must not be delivered"), stop_event)

    result, session, chunks = run_stream(
        monkeypatch,
        ListResponse([raw]),
        stop_event=stop_event,
    )

    assert result == "stopped"
    assert chunks == []
    assert not any(item["role"] == "assistant" for item in session.snapshot())


@pytest.mark.parametrize(
    "error",
    [
        ConnectionResetError("closed"),
        http.client.IncompleteRead(b"partial", 10),
        ValueError("read of closed file"),
    ],
)
def test_transport_error_caused_by_cancel_is_cancelled(monkeypatch, error):
    response = BlockingResponse(close_error=error)
    stop_event = threading.Event()
    result = []
    monkeypatch.setattr(chat.urllib.request, "urlopen", Mock(return_value=response))

    worker = threading.Thread(
        target=lambda: result.append(
            chat.stream_chat(
                MODEL,
                "hello",
                ChatSession(),
                lambda _chunk: None,
                stop_event,
            )
        )
    )
    worker.start()
    assert response.blocked.wait(1)
    stop_event.set()
    worker.join(1)

    assert result == ["stopped"]
    assert not worker.is_alive()


@pytest.mark.parametrize(
    "error",
    [ConnectionResetError("broken"), ValueError("bad response")],
)
def test_same_transport_error_without_cancel_remains_failure(monkeypatch, error):
    response = ErrorResponse(error)

    with pytest.raises(ChatError) as captured:
        run_stream(monkeypatch, response)

    assert captured.value.category == "invalid_response"


def test_request_handle_cancel_and_close_are_idempotent():
    stop_event = threading.Event()
    response = ListResponse([])
    handle = StreamingRequestHandle(stop_event)
    assert handle.register_response(response)

    assert handle.cancel() is True
    first_requested = handle.diagnostics["cancel_requested_monotonic"]
    assert handle.cancel() is False
    assert handle.close_response(response) is False

    assert response.close_calls == 1
    assert handle.diagnostics["cancel_requested_monotonic"] == first_requested
    assert handle.active_response is None


def test_normal_close_is_idempotent_and_clears_active_response():
    response = ListResponse([])
    handle = StreamingRequestHandle(threading.Event())
    assert handle.register_response(response)

    assert handle.close() is True
    assert handle.close() is False
    assert handle.close_response(response) is False

    assert response.close_calls == 1
    assert handle.active_response is None


def test_cancel_observed_in_stream_loop_still_records_diagnostics(monkeypatch):
    stop_event = threading.Event()
    diagnostics = {}

    def cancel_on_first(_chunk):
        stop_event.set()

    result, _session, _chunks = run_stream(
        monkeypatch,
        ListResponse([ollama_line("first"), ollama_line("late")]),
        stop_event=stop_event,
        diagnostics=diagnostics,
        on_chunk=cancel_on_first,
    )

    assert result == "stopped"
    assert diagnostics["cancel_requested_monotonic"] is not None
    assert diagnostics["transport_abort_monotonic"] is not None
    assert diagnostics["stream_exit_monotonic"] is not None
    assert diagnostics["cancel_transport_latency_ms"] >= 0
    assert diagnostics["status"] == "cancelled"


def test_old_request_cleanup_cannot_clear_or_close_next_response():
    old_response = ListResponse([])
    new_response = ListResponse([])
    old_handle = StreamingRequestHandle(threading.Event())
    new_handle = StreamingRequestHandle(threading.Event())
    assert old_handle.register_response(old_response)
    assert new_handle.register_response(new_response)

    old_handle.cancel()
    old_handle.finish("cancelled")

    assert old_response.close_calls == 1
    assert new_response.close_calls == 0
    assert new_handle.active_response is new_response
    assert old_handle.close_response(new_response) is False
    assert new_handle.active_response is new_response
    assert new_handle.close_response(new_response) is True


def test_repeated_cancel_start_cycles_leave_no_worker_or_watcher(monkeypatch):
    for _ in range(3):
        response = BlockingResponse()
        stop_event = threading.Event()
        results = []
        monkeypatch.setattr(chat.urllib.request, "urlopen", Mock(return_value=response))
        worker = threading.Thread(
            target=lambda: results.append(
                chat.stream_chat(
                    MODEL,
                    "hello",
                    ChatSession(),
                    lambda _chunk: None,
                    stop_event,
                )
            )
        )
        worker.start()
        assert response.blocked.wait(1)
        stop_event.set()
        worker.join(1)
        assert results == ["stopped"]
        assert not worker.is_alive()

    assert not any(
        thread.name == "ollama-stream-cancel" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_cancel_while_urlopen_waits_is_applied_when_response_arrives(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    stop_event = threading.Event()
    response = ListResponse([])
    result = []

    def delayed_urlopen(_request, timeout):
        assert timeout == 120
        entered.set()
        release.wait(2)
        return response

    monkeypatch.setattr(chat.urllib.request, "urlopen", delayed_urlopen)
    worker = threading.Thread(
        target=lambda: result.append(
            chat.stream_chat(
                MODEL,
                "hello",
                ChatSession(),
                lambda _chunk: None,
                stop_event,
            )
        )
    )
    worker.start()
    assert entered.wait(1)
    stop_event.set()
    release.set()
    worker.join(1)

    assert result == ["stopped"]
    assert response.close_calls == 1
    assert not worker.is_alive()

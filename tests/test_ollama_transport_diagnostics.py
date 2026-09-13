import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from modules import chat
from modules.chat import ChatSession, StreamingRequestHandle
from scripts import smoke_ollama_transport_latency as transport_smoke


MODEL = "qwen3.5:9b"


class ManualClock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class TimedResponse:
    def __init__(self, lines, clock, first_read_delay=0.0):
        self.lines = list(lines)
        self.clock = clock
        self.first_read_delay = first_read_delay
        self.close_calls = 0

    def __iter__(self):
        for index, raw_line in enumerate(self.lines):
            if index == 0:
                self.clock.advance(self.first_read_delay)
            yield raw_line

    def close(self):
        self.close_calls += 1


def ndjson(message=None, *, done=False):
    return (json.dumps({"message": message or {}, "done": done}) + "\n").encode("utf-8")


@pytest.fixture(autouse=True)
def configured_chat(monkeypatch):
    original_get = chat.settings.get

    def get_setting(key, default=None):
        values = {
            "ollama.host": "http://127.0.0.1:11434",
            "ollama.thinking_mode": "off",
            "ollama.keep_alive": "30m",
        }
        return values.get(key, original_get(key, default))

    monkeypatch.setattr(chat.settings, "get", get_setting)
    monkeypatch.setattr("modules.memory.MemoryStore.queue_candidates", lambda *args, **kwargs: [])


def run_stream(monkeypatch, *, urlopen_delay=0.0, first_read_delay=0.0, prompt="hello"):
    clock = ManualClock()
    response = TimedResponse(
        [ndjson({"thinking": "hidden"}), ndjson({"content": "ok"}), ndjson(done=True)],
        clock,
        first_read_delay,
    )

    def urlopen(_request, timeout):
        assert timeout == 120
        clock.advance(urlopen_delay)
        return response

    monkeypatch.setattr(chat.urllib.request, "urlopen", urlopen)
    diagnostics = {}
    stop_event = threading.Event()
    handle = StreamingRequestHandle(stop_event, diagnostics, clock=clock)
    result = chat.stream_chat(
        MODEL,
        prompt,
        ChatSession(),
        lambda _chunk: None,
        stop_event,
        request_handle=handle,
    )
    return result, diagnostics, response


def test_fast_transport_records_ordered_honest_boundaries(monkeypatch):
    result, diagnostics, response = run_stream(monkeypatch)

    assert result == "completed"
    names = (
        "payload_serialized_monotonic",
        "request_object_ready_monotonic",
        "urlopen_call_start_monotonic",
        "urlopen_return_monotonic",
        "first_response_read_start_monotonic",
        "first_raw_line_monotonic",
    )
    assert all(diagnostics[name] is not None for name in names)
    assert [diagnostics[name] for name in names] == sorted(diagnostics[name] for name in names)
    assert diagnostics["urlopen_start_monotonic"] == diagnostics["urlopen_call_start_monotonic"]
    assert diagnostics["response_headers_monotonic"] == diagnostics["urlopen_return_monotonic"]
    assert diagnostics["transport_urlopen_blocking_ms"] == 0.0
    assert diagnostics["transport_first_read_wait_ms"] == 0.0
    assert response.close_calls == 1


def test_delayed_urlopen_is_reported_as_one_unsplit_transport_block(monkeypatch):
    _result, diagnostics, _response = run_stream(monkeypatch, urlopen_delay=2.5)

    assert diagnostics["transport_urlopen_blocking_ms"] == pytest.approx(2500.0)
    assert diagnostics["urlopen_to_headers_ms"] == pytest.approx(2500.0)
    assert "connect_ms" not in diagnostics
    assert "ollama_server_queue_ms" not in diagnostics


def test_delayed_first_ndjson_read_is_measured_after_headers(monkeypatch):
    _result, diagnostics, _response = run_stream(monkeypatch, first_read_delay=0.75)

    assert diagnostics["transport_urlopen_blocking_ms"] == 0.0
    assert diagnostics["transport_first_read_wait_ms"] == pytest.approx(750.0)
    assert diagnostics["headers_to_first_raw_line_ms"] == pytest.approx(750.0)


def test_transport_diagnostics_never_store_prompt_or_reasoning_body(monkeypatch):
    secret_prompt = "private user prompt 74c0"
    _result, diagnostics, _response = run_stream(monkeypatch, prompt=secret_prompt)
    serialized = json.dumps(diagnostics, ensure_ascii=False)

    assert secret_prompt not in serialized
    assert "hidden" not in serialized
    assert diagnostics["current_user_chars"] == len(secret_prompt)
    assert diagnostics["reasoning_chars"] == len("hidden")


@pytest.mark.parametrize(
    ("mode", "present", "value"),
    [("default", False, None), ("on", True, True), ("off", True, False)],
)
def test_diagnostic_client_builds_explicit_bounded_policy_payload(mode, present, value):
    payload = transport_smoke.build_payload(MODEL, "secret", mode, "30m")

    assert ("think" in payload) is present
    if present:
        assert payload["think"] is value
    assert payload["keep_alive"] == "30m"


def test_diagnostic_cli_is_bounded_and_defaults_to_safe_current_policy():
    args = transport_smoke.parse_args(["--model", MODEL])

    assert args.runs == 5
    assert args.think == "off"
    assert args.keep_alive == "30m"
    transport_smoke.validate_args(args)
    with pytest.raises(ValueError, match="between 1 and 20"):
        transport_smoke.validate_args(SimpleNamespace(**{**vars(args), "runs": 21}))


def test_proxy_snapshot_redacts_credentials(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://user:password@127.0.0.1:7890")

    snapshot = transport_smoke.proxy_environment_snapshot()
    serialized = json.dumps(snapshot)

    assert snapshot["HTTP_PROXY"]["credentials_present"] is True
    assert "user" not in serialized
    assert "password" not in serialized


def test_independent_client_reports_timings_without_echoing_bodies(monkeypatch):
    hidden = "model-private-reasoning"
    visible = "model-visible-answer"
    lines = [
        ndjson({"thinking": hidden}),
        ndjson({"content": visible}),
        (json.dumps({
            "message": {},
            "done": True,
            "total_duration": 4_000_000,
            "eval_count": 2,
        }) + "\n").encode("utf-8"),
    ]

    class FakeResponse:
        status = 200

        def __init__(self):
            self.pending = list(lines)
            self.first = self.pending.pop(0)

        def read(self, size):
            assert size == 1
            value, self.first = self.first[:1], self.first[1:]
            return value

        def readline(self):
            if self.first:
                value, self.first = self.first, b""
                return value
            return self.pending.pop(0) if self.pending else b""

        def close(self):
            return None

    class FakeConnection:
        def __init__(self):
            self.response = FakeResponse()

        def putrequest(self, *_args, **_kwargs):
            return None

        def putheader(self, *_args):
            return None

        def endheaders(self):
            return None

        def send(self, _body):
            return None

        def getresponse(self):
            return self.response

        def close(self):
            return None

    monkeypatch.setattr(transport_smoke.socket, "getaddrinfo", lambda *_args, **_kwargs: [object()])
    monkeypatch.setattr(
        transport_smoke,
        "_open_connection",
        lambda *_args, **_kwargs: FakeConnection(),
    )

    report = transport_smoke.run_once(
        "http://127.0.0.1:11434",
        MODEL,
        "user-private-prompt",
        "off",
        "30m",
        10.0,
        1,
        2000.0,
    )
    serialized = json.dumps(report)

    assert report["status"] == "completed"
    assert report["http_status"] == 200
    assert report["ndjson_line_count"] == 3
    assert report["reasoning_chars"] == len(hidden)
    assert report["visible_content_chars"] == len(visible)
    assert report["total_duration_ms"] == 4.0
    assert report["request_to_first_body_byte_ms"] is not None
    assert report["request_to_first_model_output_ms"] is not None
    assert "user-private-prompt" not in serialized
    assert hidden not in serialized
    assert visible not in serialized

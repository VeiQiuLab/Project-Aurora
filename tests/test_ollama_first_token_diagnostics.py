import inspect
import json
import threading
from unittest.mock import Mock

import pytest

from modules import chat
from modules.chat import ChatSession, StreamingRequestHandle
from scripts import smoke_ollama_first_token as smoke


MODEL = "qwen3.5:9b"


class ListResponse:
    def __init__(self, lines):
        self.lines = list(lines)
        self.close_calls = 0

    def __iter__(self):
        return iter(self.lines)

    def close(self):
        self.close_calls += 1


class StepClock:
    def __init__(self, start=100.0, step=0.01):
        self.value = start - step
        self.step = step

    def __call__(self):
        self.value += self.step
        return self.value


def line(message=None, *, done=False, **metrics):
    payload = {"message": message or {}, "done": done}
    payload.update(metrics)
    return (json.dumps(payload) + "\n").encode("utf-8")


@pytest.fixture(autouse=True)
def configured_chat(monkeypatch):
    original_get = chat.settings.get

    def get_setting(key, default=None):
        if key == "ollama.host":
            return "http://127.0.0.1:11434"
        if key == "ollama.thinking_mode":
            return "off"
        if key == "ollama.keep_alive":
            return "30m"
        return original_get(key, default)

    monkeypatch.setattr(chat.settings, "get", get_setting)
    monkeypatch.setattr("modules.memory.MemoryStore.queue_candidates", lambda *args, **kwargs: [])


def test_stream_records_first_token_timings_context_and_final_metrics(monkeypatch):
    response = ListResponse([
        b"\n",
        line({"role": "assistant", "thinking": "internal"}),
        line({"role": "assistant", "content": "visible"}),
        line({"role": "assistant", "content": " answer"}),
        line(
            {"role": "assistant", "content": ""},
            done=True,
            total_duration=4_000_000,
            load_duration=1_000_000,
            prompt_eval_count=12,
            prompt_eval_duration=2_000_000,
            eval_count=3,
            eval_duration=500_000,
        ),
    ])
    monkeypatch.setattr(chat.urllib.request, "urlopen", Mock(return_value=response))
    diagnostics = {}
    stop_event = threading.Event()
    handle = StreamingRequestHandle(stop_event, diagnostics, clock=StepClock())
    observations = []
    chunks = []
    session = ChatSession("sys")
    session.replace([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old user"},
        {"role": "assistant", "content": "old assistant"},
    ])

    result = chat.stream_chat(
        MODEL,
        "new",
        session,
        chunks.append,
        stop_event,
        request_handle=handle,
        raw_line_observer=observations.append,
    )

    assert result == "completed"
    assert chunks == ["visible", " answer"]
    assert diagnostics["status"] == "completed"
    for name in (
        "chat_request_start_monotonic",
        "payload_ready_monotonic",
        "urlopen_start_monotonic",
        "response_headers_monotonic",
        "first_raw_line_monotonic",
        "first_json_message_monotonic",
        "first_model_output_monotonic",
        "first_nonempty_content_monotonic",
        "stream_end_monotonic",
    ):
        assert diagnostics[name] is not None
    assert diagnostics["first_model_output_monotonic"] < diagnostics["first_nonempty_content_monotonic"]
    assert diagnostics["request_to_first_content_ms"] > 0
    assert diagnostics["stream_total_ms"] >= diagnostics["request_to_first_content_ms"]
    assert diagnostics["message_count"] == 4
    assert diagnostics["system_chars"] == 3
    assert diagnostics["history_chars"] == len("old userold assistant")
    assert diagnostics["current_user_chars"] == 3
    assert diagnostics["approx_input_chars"] == len("sysold userold assistantnew")
    assert diagnostics["approx_input_tokens"] > 0
    assert diagnostics["reasoning_chars"] == len("internal")
    assert diagnostics["ollama_think_mode"] == "off"
    assert diagnostics["think_payload_value"] is False
    assert diagnostics["ollama_keep_alive"] == "30m"
    assert diagnostics["total_duration_ms"] == 4.0
    assert diagnostics["load_duration_ms"] == 1.0
    assert diagnostics["prompt_eval_duration_ms"] == 2.0
    assert diagnostics["eval_duration_ms"] == 0.5
    assert diagnostics["prompt_eval_count"] == 12
    assert diagnostics["eval_count"] == 3
    assert observations[0]["content_length"] == 0
    assert observations[0]["thinking_length"] == len("internal")
    assert "internal" not in json.dumps(observations)
    assert response.close_calls == 1


def test_empty_and_reasoning_only_lines_never_become_visible_content(monkeypatch):
    response = ListResponse([
        b"\r\n",
        line({"thinking": "hidden"}),
        line({}, done=True),
    ])
    monkeypatch.setattr(chat.urllib.request, "urlopen", Mock(return_value=response))
    diagnostics = {}
    chunks = []

    result = chat.stream_chat(
        MODEL,
        "hello",
        ChatSession(),
        chunks.append,
        threading.Event(),
        diagnostics=diagnostics,
    )

    assert result == "completed"
    assert chunks == []
    assert diagnostics["first_raw_line_monotonic"] is not None
    assert diagnostics["first_json_message_monotonic"] is not None
    assert diagnostics["first_model_output_monotonic"] is not None
    assert diagnostics["first_nonempty_content_monotonic"] is None
    assert diagnostics["request_to_first_content_ms"] is None


def test_first_visible_content_timestamp_is_recorded_only_once(monkeypatch):
    response = ListResponse([
        line({"content": "one"}),
        line({"content": "two"}),
        line({}, done=True),
    ])
    monkeypatch.setattr(chat.urllib.request, "urlopen", Mock(return_value=response))
    diagnostics = {}
    stop_event = threading.Event()
    clock = StepClock()
    handle = StreamingRequestHandle(stop_event, diagnostics, clock=clock)
    visible_timestamps = []

    def on_chunk(_chunk):
        visible_timestamps.append(diagnostics["first_nonempty_content_monotonic"])

    chat.stream_chat(
        MODEL,
        "hello",
        ChatSession(),
        on_chunk,
        stop_event,
        request_handle=handle,
    )

    assert diagnostics["first_nonempty_content_monotonic"] < diagnostics["stream_end_monotonic"]
    assert visible_timestamps == [
        diagnostics["first_nonempty_content_monotonic"],
        diagnostics["first_nonempty_content_monotonic"],
    ]


@pytest.mark.parametrize(
    "metrics",
    [
        {},
        {
            "total_duration": "bad",
            "load_duration": -1,
            "prompt_eval_count": 1.5,
            "prompt_eval_duration": float("nan"),
            "eval_count": True,
            "eval_duration": float("inf"),
        },
    ],
)
def test_missing_or_malformed_optional_metrics_do_not_break_stream(monkeypatch, metrics):
    response = ListResponse([line({"content": "ok"}), line({}, done=True, **metrics)])
    monkeypatch.setattr(chat.urllib.request, "urlopen", Mock(return_value=response))
    diagnostics = {}
    chunks = []

    result = chat.stream_chat(
        MODEL,
        "hello",
        ChatSession(),
        chunks.append,
        threading.Event(),
        diagnostics=diagnostics,
    )

    assert result == "completed"
    assert chunks == ["ok"]
    assert diagnostics["total_duration_ms"] is None
    assert diagnostics["prompt_eval_count"] is None


def test_payload_and_public_call_shape_remain_compatible(monkeypatch):
    response = ListResponse([line({"content": "ok"}), line({}, done=True)])
    captured = {}

    def urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return response

    monkeypatch.setattr(chat.urllib.request, "urlopen", urlopen)
    signature = inspect.signature(chat.stream_chat)

    result = chat.stream_chat(
        MODEL,
        "hello",
        ChatSession(),
        lambda _chunk: None,
        threading.Event(),
    )

    assert result == "completed"
    assert list(signature.parameters)[:5] == ["model", "prompt", "session", "on_chunk", "stop_event"]
    assert captured["payload"]["model"] == MODEL
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["think"] is False
    assert captured["payload"]["keep_alive"] == "30m"
    assert set(captured["payload"]) == {
        "model",
        "messages",
        "stream",
        "think",
        "keep_alive",
    }
    assert captured["timeout"] == 120


def test_cancel_before_transport_keeps_timing_diagnostics_consistent(monkeypatch):
    stop_event = threading.Event()
    stop_event.set()
    diagnostics = {}
    urlopen = Mock()
    monkeypatch.setattr(chat.urllib.request, "urlopen", urlopen)

    result = chat.stream_chat(
        MODEL,
        "hello",
        ChatSession(),
        lambda _chunk: None,
        stop_event,
        diagnostics=diagnostics,
    )

    assert result == "stopped"
    assert diagnostics["status"] == "cancelled"
    assert diagnostics["chat_request_start_monotonic"] is not None
    assert diagnostics["stream_end_monotonic"] is not None
    assert diagnostics["stream_total_ms"] >= 0
    assert diagnostics["urlopen_start_monotonic"] is None
    assert diagnostics["active_response"] is False
    urlopen.assert_not_called()


def test_invalid_thinking_override_does_not_mutate_session_or_open_transport(monkeypatch):
    session = ChatSession()
    urlopen = Mock()
    monkeypatch.setattr(chat.urllib.request, "urlopen", urlopen)

    with pytest.raises(ValueError, match="thinking mode"):
        chat.stream_chat(
            MODEL,
            "hello",
            session,
            lambda _chunk: None,
            threading.Event(),
            thinking_mode="invalid",
        )

    assert session.snapshot() == [{"role": "system", "content": session.system_context}]
    urlopen.assert_not_called()


@pytest.mark.parametrize(
    ("think_mode", "expected_present", "expected_value"),
    [
        ("default", False, None),
        ("on", True, True),
        ("off", True, False),
    ],
)
def test_smoke_think_mode_only_changes_diagnostic_payload(
    monkeypatch,
    think_mode,
    expected_present,
    expected_value,
):
    captured = {}

    def urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return ListResponse([line({"content": "ok"}), line({}, done=True)])

    monkeypatch.setattr(chat.urllib.request, "urlopen", urlopen)

    report = smoke.run_once(
        MODEL,
        "hello",
        "minimal",
        1,
        None,
        think_mode,
    )

    assert report["status"] == "completed"
    assert report["think_mode"] == think_mode
    assert report["think_payload_value"] is expected_value
    assert report["ollama_think_mode"] == think_mode
    assert report["ollama_keep_alive"] == "30m"
    assert ("think" in captured["payload"]) is expected_present
    if expected_present:
        assert captured["payload"]["think"] is expected_value
    else:
        assert set(captured["payload"]) == {
            "model",
            "messages",
            "stream",
            "keep_alive",
        }


def test_smoke_summary_counts_reasoning_and_visible_text_without_saving_body(
    monkeypatch,
    capsys,
):
    secret_reasoning = "private chain"
    response = ListResponse([
        line({"thinking": secret_reasoning}),
        line({"content": "visible"}),
        line({}, done=True),
    ])
    monkeypatch.setattr(chat.urllib.request, "urlopen", Mock(return_value=response))

    report = smoke.run_once(MODEL, "hello", "minimal", 1, None, "on")
    printed = capsys.readouterr().out

    assert report["think_mode"] == "on"
    assert report["reasoning_chars"] == len(secret_reasoning)
    assert report["visible_content_chars"] == len("visible")
    assert secret_reasoning not in printed
    assert secret_reasoning not in json.dumps(report)


def test_smoke_cli_defaults_to_omitting_think(monkeypatch):
    monkeypatch.setattr("sys.argv", ["smoke_ollama_first_token.py", "--model", MODEL])

    args = smoke.parse_args()

    assert args.think == "default"
    assert args.mode == "both"
    assert args.runs == 3

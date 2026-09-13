import json
import threading

import pytest

from modules.chat import ChatSession
from modules.chat_latency import PreLLMLatencyDiagnostics
from widgets.pages import chat_page
from widgets.pages.chat_page import ChatPage


class StepClock:
    def __init__(self, start=10.0, step=0.01):
        self.value = start - step
        self.step = step

    def __call__(self):
        self.value += self.step
        return self.value


class Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(str(message))


class CompanionState:
    def transition(self, *_args, **_kwargs):
        return None

    def force_idle(self, *_args, **_kwargs):
        return None


def make_external_page(prepare_callback, stream_callback):
    page = ChatPage.__new__(ChatPage)
    page.prepare_prompt_context_callback = prepare_callback
    page.stream_chat_callback = stream_callback
    page.selected_model = {"name": "qwen3.5:9b"}
    page.settings = {"chat_model": "qwen3.5:9b"}
    page.session = ChatSession("system")
    page._turn_lock = threading.Lock()
    page._external_message_lock = page._turn_lock
    page._turn_counter = 0
    page.logger = Logger()
    page.companion_state = CompanionState()
    page.last_latency_diagnostics = None
    page.is_open = lambda: True
    page.append_message = lambda *_args, **_kwargs: None
    page.append_assistant_header = lambda: None
    page.append_stream_chunk = lambda _chunk: None
    page.finish_stream_message = lambda: None
    page.save_conversation = lambda **_kwargs: None
    page.after = lambda _delay, callback: callback()
    return page


def test_all_pre_llm_stages_generate_independent_wall_clock_durations():
    clock = StepClock()
    diagnostics = PreLLMLatencyDiagnostics(source="text", clock=clock)

    with diagnostics.stage("session_snapshot"):
        pass
    with diagnostics.stage("context_builder"):
        with diagnostics.stage("memory_context"):
            pass
        with diagnostics.stage("persona_context"):
            pass
        with diagnostics.stage("knowledge_context"):
            pass
        with diagnostics.stage("rag_context"):
            pass
    diagnostics.mark("final_messages_ready_monotonic")
    diagnostics.mark("stream_chat_enter_monotonic")
    diagnostics.update(urlopen_start_monotonic=clock())

    report = diagnostics.finish_turn("completed")

    assert report["session_snapshot_ms"] == pytest.approx(10.0)
    assert report["memory_ms"] == pytest.approx(10.0)
    assert report["persona_ms"] == pytest.approx(10.0)
    assert report["knowledge_ms"] == pytest.approx(10.0)
    assert report["rag_ms"] == pytest.approx(10.0)
    assert report["context_builder_total_ms"] > sum(
        report[name]
        for name in ("memory_ms", "persona_ms", "knowledge_ms", "rag_ms")
    )
    assert report["turn_to_stream_chat_ms"] > 0
    assert report["turn_to_ollama_request_ms"] > report["turn_to_stream_chat_ms"]
    assert report["context_ready_to_stream_chat_ms"] == pytest.approx(10.0)
    assert report["ollama_request_start_monotonic"] == report["urlopen_start_monotonic"]


def test_disabled_sources_are_not_run_and_never_report_zero_duration():
    diagnostics = PreLLMLatencyDiagnostics(source="text", clock=StepClock())

    with diagnostics.stage("knowledge_context", enabled=False):
        pass
    with diagnostics.stage("persona_context", enabled=False):
        pass
    report = diagnostics.finish_turn("completed")

    assert report["knowledge_context_status"] == "not_run"
    assert report["knowledge_context_enabled"] is False
    assert report["knowledge_ms"] is None
    assert report["persona_context_status"] == "not_run"
    assert report["persona_ms"] is None


def test_source_failure_records_safe_type_and_preserves_exception():
    diagnostics = PreLLMLatencyDiagnostics(source="text", clock=StepClock())

    with pytest.raises(RuntimeError, match="private payload"):
        with diagnostics.stage("context_builder"):
            with diagnostics.stage("memory_context"):
                raise RuntimeError("private payload")

    report = diagnostics.finish_turn("failed")
    assert report["memory_context_status"] == "failed"
    assert report["context_builder_status"] == "failed"
    assert report["error_stage"] == "memory_context"
    assert report["error_type"] == "RuntimeError"
    assert "private payload" not in json.dumps(report)


def test_report_filters_prompt_memory_rag_persona_and_reasoning_bodies():
    diagnostics = PreLLMLatencyDiagnostics(source="text", clock=StepClock())
    diagnostics.update(
        prompt_text="secret prompt",
        memory_text="secret memory",
        rag_text="secret rag",
        persona_text="secret persona",
        reasoning_text="secret reasoning",
        reasoning_chars=16,
        memory_match_count=2,
    )

    rendered = diagnostics.to_log_line()

    assert "secret" not in rendered
    assert diagnostics.report()["reasoning_chars"] == 16
    assert diagnostics.report()["memory_match_count"] == 2


def test_chat_page_connects_pre_llm_and_first_token_diagnostics(monkeypatch):
    clock = StepClock()
    monkeypatch.setattr(
        chat_page,
        "PreLLMLatencyDiagnostics",
        lambda *, source: PreLLMLatencyDiagnostics(source=source, clock=clock),
    )

    def prepare(_prompt, _messages, _debug, *, latency_diagnostics=None):
        with latency_diagnostics.stage("memory_context"):
            pass
        with latency_diagnostics.stage("persona_context", enabled=False):
            pass
        with latency_diagnostics.stage("knowledge_context"):
            pass
        with latency_diagnostics.stage("rag_context", enabled=False):
            pass
        latency_diagnostics.update(memory_match_count=1, knowledge_match_count=2)
        return {"system_context": "system", "debug_text": ""}

    def stream(_model, _prompt, _session, on_chunk, _stop_event, *, diagnostics=None):
        diagnostics["chat_request_start_monotonic"] = clock()
        diagnostics["urlopen_start_monotonic"] = clock()
        diagnostics["first_model_output_monotonic"] = clock()
        diagnostics["first_nonempty_content_monotonic"] = clock()
        diagnostics["ollama_think_mode"] = "off"
        diagnostics["think_payload_value"] = False
        diagnostics["ollama_keep_alive"] = "30m"
        on_chunk("ok")
        return "completed"

    page = make_external_page(prepare, stream)

    result = page.handle_external_prompt("hello", source="voice")
    report = page.last_latency_diagnostics

    assert result == "ok"
    assert report["turn_source"] == "voice"
    assert report["turn_id"] == 1
    assert report["turn_status"] == "completed"
    assert report["memory_match_count"] == 1
    assert report["knowledge_match_count"] == 2
    assert report["persona_context_status"] == "not_run"
    assert report["rag_context_status"] == "not_run"
    assert report["turn_to_ollama_request_ms"] > 0
    assert report["first_nonempty_content_monotonic"] is not None
    assert report["ollama_think_mode"] == "off"
    assert report["think_payload_value"] is False
    assert report["ollama_keep_alive"] == "30m"
    assert any(message.startswith("chat_latency_diagnostics ") for message in page.logger.messages)


def test_legacy_callbacks_keep_their_existing_call_shapes():
    calls = []

    def prepare(prompt, messages, debug):
        calls.append(("prepare", prompt, len(messages), debug))
        return {"system_context": "system", "debug_text": ""}

    def stream(model, prompt, session, on_chunk, stop_event):
        calls.append(("stream", model, prompt, stop_event.is_set()))
        on_chunk("ok")
        return "completed"

    page = make_external_page(prepare, stream)

    assert page.handle_external_prompt("hello") == "ok"
    assert calls[0][0] == "prepare"
    assert calls[1][0] == "stream"


def test_cancelled_turn_and_n_plus_one_reports_do_not_share_state(monkeypatch):
    clocks = iter((StepClock(), StepClock(start=20.0)))
    monkeypatch.setattr(
        chat_page,
        "PreLLMLatencyDiagnostics",
        lambda *, source: PreLLMLatencyDiagnostics(source=source, clock=next(clocks)),
    )
    outcomes = iter(("stopped", "completed"))

    def prepare(_prompt, _messages, _debug, *, latency_diagnostics=None):
        with latency_diagnostics.stage("memory_context"):
            pass
        return {"system_context": "system", "debug_text": ""}

    def stream(_model, _prompt, _session, on_chunk, _stop_event, *, diagnostics=None):
        diagnostics["urlopen_start_monotonic"] = diagnostics["turn_start_monotonic"] + 0.05
        result = next(outcomes)
        if result == "completed":
            on_chunk("recovered")
        return result

    page = make_external_page(prepare, stream)

    assert page.handle_external_prompt("cancel me") == "stopped"
    cancelled = dict(page.last_latency_diagnostics)
    assert page.handle_external_prompt("next") == "recovered"
    recovered = dict(page.last_latency_diagnostics)

    assert cancelled["turn_id"] == 1
    assert cancelled["turn_status"] == "cancelled"
    assert recovered["turn_id"] == 2
    assert recovered["turn_status"] == "completed"
    assert cancelled["turn_start_monotonic"] != recovered["turn_start_monotonic"]
    assert cancelled["turn_status"] == "cancelled"

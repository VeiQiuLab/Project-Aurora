import json
import threading
from unittest.mock import Mock

import pytest

from modules import chat
from modules.conversation import (
    TITLE_GENERATION_IDLE_SECONDS,
    ConversationManager,
    schedule_conversation_intelligence,
)
from modules.conversation_intelligence import (
    TITLE_GENERATION_MAX_TOKENS,
    TITLE_GENERATION_TIMEOUT_SECONDS,
    generate_title_summary,
)
from widgets.pages import chat_page
from widgets.pages.chat_page import ChatPage


MODEL = "qwen3.5:9b"


class Logger:
    def __init__(self):
        self.infos = []
        self.errors = []

    def info(self, message):
        self.infos.append(str(message))

    def error(self, message):
        self.errors.append(str(message))


def saved_first_turn(tmp_path):
    manager = ConversationManager(tmp_path)
    messages = [
        {"role": "user", "content": "请规划语音测试"},
        {"role": "assistant", "content": "可以先检查实时链路"},
    ]
    record = manager.save(None, MODEL, messages, title="新对话")
    return manager, record, messages


def test_foreground_turn_during_debounce_defers_title_without_blocking(tmp_path):
    manager, record, messages = saved_first_turn(tmp_path)
    logger = Logger()
    foreground_active = threading.Event()
    analysis_ready = threading.Event()
    title_started = threading.Event()
    calls = []

    def analyzer(_messages):
        analysis_ready.set()
        return {"title_summary": "语音测试"}

    def title_generator(_messages, _model):
        calls.append("title")
        title_started.set()
        return "语音测试", "llm"

    worker = schedule_conversation_intelligence(
        manager,
        record["id"],
        messages,
        expected_updated_time=record["updated_time"],
        expected_title=record["title"],
        generate_title=True,
        analyzer=analyzer,
        title_generator=title_generator,
        title_model=MODEL,
        title_idle_seconds=0.1,
        foreground_active=foreground_active.is_set,
        logger=logger,
    )
    assert analysis_ready.wait(1.0)
    foreground_active.set()

    assert not title_started.wait(0.2)
    foreground_active.clear()
    assert title_started.wait(0.5)
    worker.join(1.0)

    assert not worker.is_alive()
    assert calls == ["title"]
    assert any("title_generation_cancelled_pending" in entry for entry in logger.infos)
    assert any("title_generation_skipped_foreground" in entry for entry in logger.infos)
    assert sum("title_generation_started" in entry for entry in logger.infos) == 1


def test_quick_foreground_turn_resets_idle_window_even_if_already_finished(tmp_path):
    manager, record, messages = saved_first_turn(tmp_path)
    generation = {"value": 1}
    analysis_ready = threading.Event()
    title_started = threading.Event()

    def analyzer(_messages):
        analysis_ready.set()
        return {"summary": "safe"}

    worker = schedule_conversation_intelligence(
        manager,
        record["id"],
        messages,
        generate_title=True,
        analyzer=analyzer,
        title_generator=lambda *_args: (title_started.set() or "语音测试", "llm"),
        title_idle_seconds=0.1,
        foreground_active=lambda: False,
        foreground_generation=lambda: generation["value"],
    )
    assert analysis_ready.wait(1.0)
    generation["value"] = 2

    assert not title_started.wait(0.15)
    assert title_started.wait(0.2)
    worker.join(1.0)

    assert not worker.is_alive()


def test_idle_title_runs_once_after_debounce_and_persists(tmp_path):
    manager, record, messages = saved_first_turn(tmp_path)
    logger = Logger()
    calls = []

    worker = schedule_conversation_intelligence(
        manager,
        record["id"],
        messages,
        expected_updated_time=record["updated_time"],
        expected_title=record["title"],
        generate_title=True,
        analyzer=lambda _messages: {"summary": "safe"},
        title_generator=lambda _messages, _model: (
            calls.append("title") or "语音测试",
            "llm",
        ),
        title_model=MODEL,
        title_idle_seconds=0.01,
        foreground_active=lambda: False,
        logger=logger,
    )
    worker.join(1.0)

    assert worker.daemon is True
    assert not worker.is_alive()
    assert calls == ["title"]
    assert manager.load(record["id"])["title"] == "语音测试"
    completed = next(entry for entry in logger.infos if "title_generation_completed" in entry)
    assert "wait_ms=" in completed
    assert "request_ms=" in completed
    assert "请规划语音测试" not in "\n".join(logger.infos)


def test_launch_guard_reschedules_title_if_foreground_activates_at_boundary(tmp_path):
    manager, record, messages = saved_first_turn(tmp_path)
    states = iter((False, True))
    title_generator = Mock(return_value=("边界标题", "llm"))
    logger = Logger()

    worker = schedule_conversation_intelligence(
        manager,
        record["id"],
        messages,
        expected_title=record["title"],
        generate_title=True,
        analyzer=lambda _messages: {"summary": "safe"},
        title_generator=title_generator,
        title_idle_seconds=0,
        foreground_active=lambda: next(states),
        logger=logger,
    )
    worker.join(1.0)

    title_generator.assert_called_once()
    assert any("reason=launch_guard" in entry for entry in logger.infos)


def test_shutdown_cancels_pending_daemon_without_title_request(tmp_path):
    manager, record, messages = saved_first_turn(tmp_path)
    cancel_event = threading.Event()
    title_generator = Mock(return_value=("不应生成", "llm"))
    logger = Logger()

    worker = schedule_conversation_intelligence(
        manager,
        record["id"],
        messages,
        generate_title=True,
        analyzer=lambda _messages: {"summary": "safe"},
        title_generator=title_generator,
        title_idle_seconds=10,
        title_cancel_event=cancel_event,
        logger=logger,
    )
    cancel_event.set()
    worker.join(1.0)

    assert worker.daemon is True
    assert not worker.is_alive()
    title_generator.assert_not_called()
    assert any("reason=shutdown" in entry for entry in logger.infos)


def test_title_generation_selects_off_policy_timeout_and_output_bound(monkeypatch):
    captured = {}

    def fake_chat_with_messages(model, messages, timeout, **kwargs):
        captured.update({
            "model": model,
            "messages": messages,
            "timeout": timeout,
            **kwargs,
        })
        return "语音测试"

    monkeypatch.setattr(chat, "chat_with_messages", fake_chat_with_messages)
    title, source = generate_title_summary(
        [{"role": "user", "content": "规划语音测试"}],
        MODEL,
    )

    assert (title, source) == ("语音测试", "llm")
    assert captured["timeout"] == TITLE_GENERATION_TIMEOUT_SECONDS == 20
    assert captured["thinking_mode"] == "off"
    assert captured["num_predict"] == TITLE_GENERATION_MAX_TOKENS == 32


def test_title_request_failure_falls_back_without_touching_saved_messages(tmp_path):
    manager, record, messages = saved_first_turn(tmp_path)
    logger = Logger()

    def failed_title(*_args):
        raise TimeoutError("private title prompt")

    worker = schedule_conversation_intelligence(
        manager,
        record["id"],
        messages,
        expected_title=record["title"],
        generate_title=True,
        analyzer=lambda _messages: {"summary": "safe"},
        title_generator=failed_title,
        title_idle_seconds=0,
        logger=logger,
    )
    worker.join(1.0)

    saved = manager.load(record["id"])
    assert saved["messages"] == messages
    assert saved["title"] == record["title"]
    assert saved["metadata"]["conversation_intelligence"]["title_source"] == "default"
    assert any("title_generation_failed" in entry for entry in logger.infos)
    assert "private title prompt" not in "\n".join(logger.infos)


class JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_nonstreaming_policy_is_opt_in_and_title_inherits_keep_alive(monkeypatch):
    payloads = []
    original_get = chat.settings.get

    def get_setting(key, default=None):
        values = {
            "ollama.host": "http://127.0.0.1:11434",
            "ollama.keep_alive": "30m",
            "ollama.thinking_mode": "off",
        }
        return values[key] if key in values else original_get(key, default)

    def urlopen(request, timeout):
        payloads.append((json.loads(request.data.decode("utf-8")), timeout))
        return JsonResponse({"message": {"content": "语音测试"}})

    monkeypatch.setattr(chat.settings, "get", get_setting)
    monkeypatch.setattr(chat.urllib.request, "urlopen", urlopen)

    chat.chat_with_messages(MODEL, [{"role": "user", "content": "one"}])
    chat.chat_with_messages(
        MODEL,
        [{"role": "user", "content": "title"}],
        timeout=20,
        thinking_mode="off",
        num_predict=32,
    )

    regular, title = payloads
    assert set(regular[0]) == {"model", "messages", "stream"}
    assert title[0]["think"] is False
    assert title[0]["keep_alive"] == "30m"
    assert title[0]["options"] == {"num_predict": 32}
    assert title[1] == 20


def test_chat_page_only_marks_first_saved_turn_for_title_generation(tmp_path, monkeypatch):
    manager, _record, messages = saved_first_turn(tmp_path)
    manager = ConversationManager(tmp_path / "page")
    scheduled = []
    page = ChatPage.__new__(ChatPage)
    page.stream_state = {"running": False, "stop_event": None}
    page.session = Mock(snapshot=Mock(return_value=messages))
    page.conversation_state = {"id": None, "created_at": None, "title": "New Conversation"}
    page.conversation_manager = manager
    page.selected_model = {"name": MODEL}
    page.settings = {"chat_model": MODEL}
    page._turn_lock = threading.Lock()
    page._title_generation_cancel_event = threading.Event()
    page.logger = Logger()
    page.t = lambda value: value
    page.set_active_conversation_id = lambda _value: None
    page.refresh_conversations = lambda: None
    page.update_current_title = lambda: None
    page.set_status = lambda *_args: None
    page._on_title_updated = lambda _data: None

    monkeypatch.setattr(
        chat_page,
        "schedule_conversation_intelligence",
        lambda *_args, **kwargs: scheduled.append(kwargs),
    )

    page.save_conversation(auto=True)
    page.save_conversation(auto=True)

    assert [item["generate_title"] for item in scheduled] == [True, False]
    assert scheduled[0]["title_idle_seconds"] == TITLE_GENERATION_IDLE_SECONDS
    assert callable(scheduled[0]["foreground_generation"])
    assert scheduled[0]["title_cancel_event"] is page._title_generation_cancel_event

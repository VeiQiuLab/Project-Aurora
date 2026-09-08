import time
import threading

from connectors.qq.connector import QQConnector
from connectors.qq.models import QQConfig
from connectors.qq.message_adapter import adapt_event
from connectors.qq.onebot_client import OneBotClient, OneBotError
from connectors.qq.response_style import (
    QQ_CHANNEL_INSTRUCTION,
    build_qq_system_context,
    normalize_qq_reply,
)


class FakeClient:
    status = "disconnected"

    def __init__(self):
        self.sent = []

    def test_connection(self):
        self.status = "connected"
        return True

    def send(self, message, text):
        self.sent.append((message.conversation_id, text))


def napcat_private_event(event_id="1001", user="24680"):
    return {
        "time": 1730000000,
        "self_id": 13579,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "user_id": 24680,
        "message_id": event_id,
        "message": [{"type": "text", "data": {"text": "你好"}}],
        "raw_message": "你好",
        "font": 0,
        "sender": {"user_id": int(user), "nickname": "NapCat Tester", "sex": "unknown", "age": 0},
    }


def private(event_id="1", user="42", text="你好"):
    return {
        "post_type": "message", "message_type": "private", "message_id": event_id,
        "self_id": "99", "message": text,
        "sender": {"user_id": user, "nickname": "Tester"},
    }


def group(event_id="2", mentioned=True, group_id="7", text="你好"):
    segments = []
    if mentioned:
        segments.append({"type": "at", "data": {"qq": "99"}})
    segments.append({"type": "text", "data": {"text": text}})
    return {
        "post_type": "message", "message_type": "group", "message_id": event_id,
        "self_id": "99", "group_id": group_id, "message": segments,
        "sender": {"user_id": "42", "nickname": "Tester"},
    }


def make_connector(private_enabled=True, generator=None):
    client = FakeClient()
    connector = QQConnector(
        QQConfig(private_replies=private_enabled, group_mentions_only=True),
        reply_generator=generator or (lambda _cid, prompt, _session: "回复:" + prompt),
        client=client,
    )
    return connector, client


def wait(connector):
    assert connector.wait_idle(2)
    time.sleep(0.01)


def test_private_receive_and_send():
    connector, client = make_connector()
    assert connector.handle_event(private())["accepted"]
    wait(connector)
    assert client.sent == [("qq:private:42", "回复:你好")]


def test_realistic_napcat_private_event_reaches_generation_and_sends_once():
    calls = []
    connector, client = make_connector(True, lambda cid, prompt, session: calls.append((cid, prompt)) or "收到")
    result = connector.handle_event(napcat_private_event())
    assert result["accepted"] is True
    wait(connector)
    assert calls == [("qq:private:24680", "你好")]
    assert client.sent == [("qq:private:24680", "收到")]


def test_napcat_raw_message_fallback_and_top_level_user_id():
    event = napcat_private_event("1002")
    event.pop("sender")
    event["message"] = None
    event["raw_message"] = "纯文字"
    parsed = adapt_event(event)
    assert parsed.sender_id == "24680"
    assert parsed.text == "纯文字"


def test_private_disabled_does_not_generate():
    calls = []
    connector, client = make_connector(False, lambda *_: calls.append(1) or "x")
    assert connector.handle_event(private())["reason"] == "private_disabled"
    wait(connector)
    assert calls == [] and client.sent == []


def test_group_requires_mention_and_strips_it():
    connector, client = make_connector()
    assert connector.handle_event(group(mentioned=False))["reason"] == "group_not_mentioned"
    assert connector.handle_event(group(event_id="3", mentioned=True))["accepted"]
    wait(connector)
    assert client.sent == [("qq:group:7", "回复:你好")]


def test_self_and_duplicate_events_are_ignored():
    connector, client = make_connector()
    own = private("own", user="99")
    assert connector.handle_event(own)["accepted"] is False
    assert connector.handle_event(private("dup"))["accepted"]
    assert connector.handle_event(private("dup"))["reason"] == "duplicate"
    wait(connector)
    assert len(client.sent) == 1


def test_conversations_are_isolated_and_external_memory_disabled():
    connector, client = make_connector()
    assert connector.handle_event(private("a", user="1", text="A"))["accepted"]
    assert connector.handle_event(private("b", user="2", text="B"))["accepted"]
    wait(connector)
    assert set(connector.sessions) == {"qq:private:1", "qq:private:2"}
    assert adapt_event(private("memory", user="3", text="我喜欢咖啡")).allow_memory is False
    assert [item[0] for item in client.sent] == ["qq:private:1", "qq:private:2"]


def test_non_message_and_unsupported_segments_are_ignored():
    assert adapt_event({"post_type": "notice"}) is None
    assert adapt_event({**private(), "message": [{"type": "image", "data": {}}]}) is None


def test_message_sent_is_explicitly_classified_as_self_message():
    connector, _client = make_connector()
    result = connector.handle_event({"post_type": "message_sent", "message_id": "sent-1", "self_id": 99})
    assert result == {"accepted": False, "reason": "self_message"}


def test_connection_failure_is_friendly_and_reconnect_backoff():
    class Broken(FakeClient):
        def test_connection(self):
            raise RuntimeError("secret-token-should-not-be-logged")

    connector = QQConnector(QQConfig(access_token="secret-token"), client=Broken())
    assert connector.connect(start_events=False) is False
    assert connector.status == "error"
    assert connector.last_error == "NapCat is unavailable or rejected the connection"
    assert "secret-token" not in connector.last_error
    assert connector.reconnect_delay() == 1
    assert connector.reconnect_delay() == 2


def test_websocket_idle_timeout_continues(monkeypatch):
    import websocket

    stop = threading.Event()
    calls = []

    class IdleSocket:
        def recv(self):
            if not calls:
                calls.append("timeout")
                raise websocket.WebSocketTimeoutException("idle")
            stop.set()
            return ""

        def close(self):
            pass

    monkeypatch.setattr(websocket, "create_connection", lambda *args, **kwargs: IdleSocket())
    client = OneBotClient("http://127.0.0.1:3000")
    client.run_event_loop(lambda _event: calls.append("event"), stop)
    assert calls == ["timeout"]


def test_disconnect_stops_event_loop_without_reconnect():
    class PersistentClient(FakeClient):
        def run_event_loop(self, callback, stop_event):
            while not stop_event.wait(0.01):
                pass

    connector = QQConnector(QQConfig(), client=PersistentClient())
    assert connector.connect(start_events=True)
    time.sleep(0.03)
    assert connector.status == "connected"
    connector.disconnect()
    time.sleep(0.03)
    assert connector.status == "disconnected"
    assert connector._event_thread is not None and not connector._event_thread.is_alive()


def test_server_close_is_classified_and_reconnects_once():
    class ClosingClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def run_event_loop(self, callback, stop_event):
            self.calls += 1
            if self.calls == 1:
                raise OneBotError("closed", reason="connection_closed", exception_type="FakeClosed")
            stop_event.set()

    client = ClosingClient()
    connector = QQConnector(QQConfig(), client=client)
    connector.reconnect_delay = lambda: 0
    assert connector.connect(start_events=True)
    deadline = time.time() + 2
    while time.time() < deadline and connector._event_thread.is_alive():
        time.sleep(0.01)
    assert client.calls == 2


def test_qq_style_is_scoped_to_qq_session_and_not_global_persona():
    context = build_qq_system_context()
    assert QQ_CHANNEL_INSTRUCTION in context
    assert "不使用 Markdown 粗体" in context
    assert "不使用 Markdown 粗体" not in "You are Aurora, a helpful local AI assistant."


def test_qq_normalization_only_compresses_excess_blank_lines():
    assert normalize_qq_reply("  你好\n\n\n\n欢迎  ") == "你好\n\n欢迎"
    assert normalize_qq_reply("**保留**\n- item\n```python\nprint(1)\n```") == "**保留**\n- item\n```python\nprint(1)\n```"


def test_qq_generation_receives_private_style_and_group_extra_style():
    seen = []
    connector, _client = make_connector(True, lambda _cid, _prompt, session: seen.append(session.snapshot()[0]["content"]) or "短回复")
    assert connector.handle_event(private("style-private"))["accepted"]
    assert connector.handle_event(group("style-group", mentioned=True))["accepted"]
    wait(connector)
    assert any("QQ 即时聊天" in value for value in seen)
    assert any("群聊中请进一步简洁" in value for value in seen)

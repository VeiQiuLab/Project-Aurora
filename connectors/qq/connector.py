"""Reliable, deliberately small OneBot text bridge."""

from collections import OrderedDict, defaultdict, deque
import threading
import time

from modules.chat import ChatSession

from .message_adapter import parse_event
from .models import QQConfig
from .onebot_client import OneBotClient, OneBotError
from .response_style import build_qq_system_context, normalize_qq_reply


class QQConnector:
    def __init__(self, config=None, *, reply_generator=None, client=None, logger=None):
        self.config = config or QQConfig()
        self.logger = logger
        self.reply_generator = reply_generator
        self.client = client or OneBotClient(self.config.http_endpoint, self.config.access_token, ws_endpoint=self.config.ws_endpoint, logger=logger)
        self.sessions = {}
        self._queues = defaultdict(deque)
        self._workers = set()
        self._lock = threading.RLock()
        self._seen = OrderedDict()
        self._seen_limit = 2048
        self.status = "disconnected"
        self.last_error = ""
        self.reconnect_attempt = 0
        self._event_stop = None
        self._event_thread = None

    def configure(self, config):
        self.config = config
        self.client = OneBotClient(config.http_endpoint, config.access_token, ws_endpoint=config.ws_endpoint, logger=self.logger)

    def connect(self, *, start_events=True):
        try:
            self.client.test_connection()
            self.status = "connecting"
            self.last_error = ""
            self.reconnect_attempt = 0
            if start_events:
                self.start_event_loop()
            return True
        except Exception:
            self.status = "error"
            self.last_error = "NapCat is unavailable or rejected the connection"
            return False

    def disconnect(self):
        if self._event_stop is not None:
            self._event_stop.set()
        socket = getattr(self.client, "_socket", None)
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass
        self.status = "disconnected"

    def _log(self, level, message):
        if self.logger:
            getattr(self.logger, level, self.logger.info)(message)

    @staticmethod
    def _safe_sender(sender_id):
        value = str(sender_id or "")
        return f"***{value[-4:]}" if value else "unknown"

    @staticmethod
    def _event_id(event):
        if not isinstance(event, dict):
            return ""
        return str(event.get("message_id", event.get("time", "")) or "")

    @classmethod
    def _event_diagnostics(cls, event):
        event = event if isinstance(event, dict) else {}
        return {
            "post_type": str(event.get("post_type", "") or ""),
            "message_type": str(event.get("message_type", "") or ""),
            "sub_type": str(event.get("sub_type", "") or ""),
            "meta_event_type": str(event.get("meta_event_type", "") or ""),
            "self_id": cls._safe_sender(event.get("self_id", "")),
            "user_id": cls._safe_sender(
                (event.get("sender") or {}).get("user_id", event.get("user_id", ""))
            ),
            "event_id": cls._event_id(event),
        }

    @staticmethod
    def _format_diagnostics(values, *, include_ids=True):
        keys = ("post_type", "message_type", "sub_type", "meta_event_type", "self_id", "user_id", "event_id")
        if not include_ids:
            keys = ("post_type", "message_type", "meta_event_type")
        return " ".join(f"{key}={values[key]}" for key in keys)

    def start_event_loop(self):
        """Start the injected OneBot WebSocket event reader without blocking Aurora UI."""
        if self._event_thread and self._event_thread.is_alive():
            self._log("info", "[QQ] event_loop_already_running")
            return False
        self._event_stop = threading.Event()

        def run():
            self._log("info", "[QQ] event_loop_start")
            while not self._event_stop.is_set():
                try:
                    self.status = "connected"
                    self.client.run_event_loop(self.handle_event, self._event_stop)
                    if self._event_stop.is_set():
                        break
                    reason = "connection_closed"
                    exception_type = ""
                except OneBotError as exc:
                    if self._event_stop.is_set():
                        break
                    reason = getattr(exc, "reason", "network_error")
                    exception_type = getattr(exc, "exception_type", type(exc).__name__)
                except Exception as exc:
                    if self._event_stop.is_set():
                        break
                    reason = "network_error"
                    exception_type = type(exc).__name__
                self.status = "reconnecting"
                self.last_error = "QQ event connection failed"
                delay = self.reconnect_delay()
                self._log("error", f"[QQ] websocket_failed reason={reason} exception={exception_type}")
                self._log("info", f"[QQ] reconnect_scheduled delay_ms={delay * 1000}")
                if self._event_stop.wait(delay):
                    break
            self.status = "disconnected" if self._event_stop.is_set() else self.status
            self._log("info", "[QQ] event_loop_stopped")

        self._event_thread = threading.Thread(target=run, name="aurora-qq-events", daemon=True)
        self._event_thread.start()
        self._log("info", "[QQ] event_loop_started")
        return True

    def reconnect_delay(self):
        self.reconnect_attempt += 1
        return min(30, 2 ** min(self.reconnect_attempt - 1, 5))

    def _duplicate(self, event_id):
        if not event_id:
            return False
        with self._lock:
            if event_id in self._seen:
                return True
            self._seen[event_id] = True
            while len(self._seen) > self._seen_limit:
                self._seen.popitem(last=False)
        return False

    def handle_event(self, event):
        diagnostics = self._event_diagnostics(event)
        self._log("info", f"[QQ] event_received {self._format_diagnostics(diagnostics)}")
        message, parse_reason = parse_event(event)
        if message is None:
            self._log("info", f"[QQ] event_filtered reason={parse_reason} {self._format_diagnostics(diagnostics, include_ids=False)}")
            return {"accepted": False, "reason": parse_reason}
        self._log("info", f"[QQ] event_parsed message_type={message.message_type} event_id={message.event_id}")
        if self._duplicate(message.event_id):
            self._log("info", "[QQ] event_filtered reason=duplicate")
            return {"accepted": False, "reason": "duplicate"}
        if message.is_group and self.config.group_mentions_only and not message.mentioned_self:
            self._log("info", "[QQ] event_filtered reason=group_not_mentioned")
            return {"accepted": False, "reason": "group_not_mentioned"}
        if not message.is_group and not self.config.private_replies:
            self._log("info", "[QQ] event_filtered reason=private_disabled")
            return {"accepted": False, "reason": "private_disabled"}
        with self._lock:
            self._queues[message.conversation_id].append(message)
            if message.conversation_id not in self._workers:
                self._workers.add(message.conversation_id)
                threading.Thread(target=self._drain, args=(message.conversation_id,), daemon=True).start()
        self._log("info", f"[QQ] message_accepted conversation={message.conversation_id} sender={self._safe_sender(message.sender_id)}")
        return {"accepted": True, "conversation_id": message.conversation_id}

    def _drain(self, conversation_id):
        try:
            while True:
                with self._lock:
                    if not self._queues[conversation_id]:
                        self._workers.discard(conversation_id)
                        return
                    message = self._queues[conversation_id].popleft()
                    session = self.sessions.setdefault(
                        conversation_id,
                        ChatSession(system_context=build_qq_system_context(is_group=message.is_group)),
                    )
                try:
                    started = time.monotonic()
                    reply = ""
                    self._log("info", f"[QQ] generation_start conversation={conversation_id}")
                    session.add_user(message.text)
                    if not callable(self.reply_generator):
                        raise RuntimeError("QQ reply service is unavailable")
                    try:
                        reply = normalize_qq_reply(
                            self.reply_generator(conversation_id, message.text, session)
                        )
                    except Exception:
                        self._log("error", "[QQ] generation_failed reason=model_error")
                        raise
                    self._log("info", f"[QQ] generation_done conversation={conversation_id} reply_length={len(reply)} latency_ms={int((time.monotonic() - started) * 1000)}")
                    if reply:
                        session.add_assistant(reply)
                        self.client.send(message, reply)
                    self.status = "connected"
                except Exception as exc:
                    self.status = "error"
                    self.last_error = "QQ message processing failed"
                    if "reply" in locals() and reply:
                        self._log("error", "[QQ] send_failed reason=action_error")
        finally:
            with self._lock:
                self._workers.discard(conversation_id)

    def wait_idle(self, timeout=5):
        done = threading.Event()
        deadline = __import__("time").monotonic() + timeout
        while __import__("time").monotonic() < deadline:
            with self._lock:
                if not self._workers:
                    done.set()
                    break
            done.wait(0.01)
        return done.is_set()

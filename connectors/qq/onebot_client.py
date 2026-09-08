"""Small OneBot 11 HTTP action client. Event transport is injected by the host."""

import json
import urllib.error
import urllib.request


class OneBotError(RuntimeError):
    def __init__(self, message, *, reason="network_error", exception_type=""):
        super().__init__(message)
        self.reason = reason
        self.exception_type = exception_type


class OneBotClient:
    def __init__(self, http_endpoint, access_token="", *, ws_endpoint="ws://127.0.0.1:3001", opener=None, timeout=8, logger=None):
        self.http_endpoint = str(http_endpoint or "http://127.0.0.1:3000").rstrip("/")
        self.ws_endpoint = str(ws_endpoint or "ws://127.0.0.1:3001").rstrip("/")
        self.access_token = str(access_token or "")
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout
        self.logger = logger
        self.status = "disconnected"
        self._socket = None

    def _action(self, action, params=None):
        if self.logger and action.startswith("send_"):
            self.logger.info(f"[QQ] send_start action={action}")
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        request = urllib.request.Request(
            f"{self.http_endpoint}/{action.lstrip('/')}",
            data=json.dumps(params or {}).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            self.status = "error"
            if self.logger and action.startswith("send_"):
                self.logger.error("[QQ] send_failed reason=action_error")
            raise OneBotError("NapCat action failed") from exc
        if not isinstance(data, dict) or data.get("status") not in {"ok", None} or data.get("retcode", 0) not in {0, None}:
            self.status = "error"
            raise OneBotError("NapCat rejected the action")
        self.status = "connected"
        if self.logger and action.startswith("send_"):
            self.logger.info("[QQ] send_done")
        return data.get("data")

    def test_connection(self):
        self._action("get_status")
        return True

    def run_event_loop(self, on_event, stop_event):
        """Read OneBot events until stopped; websocket-client is a packaged dependency."""
        try:
            import websocket
        except ImportError as exc:
            self.status = "error"
            raise OneBotError("WebSocket runtime is unavailable", reason="dependency_error", exception_type=type(exc).__name__) from exc
        headers = [f"Authorization: Bearer {self.access_token}"] if self.access_token else []
        try:
            # HTTP actions use the short request timeout. The event stream is a
            # long-lived channel and must not fail merely because it is idle.
            socket = websocket.create_connection(self._event_url(), header=headers, timeout=None)
            self._socket = socket
        except Exception as exc:
            self.status = "error"
            reason = "authentication_failed" if getattr(exc, "status_code", None) in {401, 403} else "handshake_failed"
            raise OneBotError("NapCat event connection failed", reason=reason, exception_type=type(exc).__name__) from exc
        self.status = "connected"
        try:
            while not stop_event.is_set():
                try:
                    payload = socket.recv()
                except websocket.WebSocketTimeoutException:
                    if self.logger:
                        self.logger.info("[QQ] websocket_idle_timeout continuing=true")
                    continue
                if not payload:
                    break
                try:
                    event = json.loads(payload)
                except (TypeError, ValueError):
                    continue
                if callable(on_event):
                    on_event(event)
        except websocket.WebSocketConnectionClosedException as exc:
            self.status = "error"
            raise OneBotError("NapCat event connection closed", reason="connection_closed", exception_type=type(exc).__name__) from exc
        except websocket.WebSocketProtocolException as exc:
            self.status = "error"
            raise OneBotError("NapCat event protocol failed", reason="protocol_error", exception_type=type(exc).__name__) from exc
        except OSError as exc:
            self.status = "error"
            raise OneBotError("NapCat event network failed", reason="network_error", exception_type=type(exc).__name__) from exc
        except Exception as exc:
            self.status = "error"
            raise OneBotError("NapCat event connection failed", reason="network_error", exception_type=type(exc).__name__) from exc
        finally:
            try:
                socket.close()
            except Exception:
                pass
            self._socket = None
            if self.status != "error":
                self.status = "disconnected"

    def _event_url(self):
        endpoint = str(getattr(self, "ws_endpoint", "") or "")
        if not endpoint:
            raise OneBotError("WebSocket endpoint is not configured")
        return endpoint.rstrip("/")

    def send_private(self, user_id, message):
        return self._action("send_private_msg", {"user_id": int(user_id), "message": str(message)})

    def send_group(self, group_id, message):
        return self._action("send_group_msg", {"group_id": int(group_id), "message": str(message)})

    def send(self, normalized_message, message):
        if normalized_message.is_group:
            return self.send_group(normalized_message.group_id, message)
        return self.send_private(normalized_message.sender_id, message)

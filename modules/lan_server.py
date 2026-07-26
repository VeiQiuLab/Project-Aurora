"""LAN status and mobile chat prototype server for Project Aurora.

The server exposes a small status summary and, when explicitly enabled,
a LAN-only mobile chat prototype. It does not expose settings, data export,
system commands, file access, or full local data.
"""

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time
import urllib.parse

from modules.version import RELEASE


DEFAULT_LAN_STATUS_PORT = 8765


class _ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False


class _LANStatusHandler(BaseHTTPRequestHandler):
    server_version = "ProjectAuroraLANStatus/2.1.4"

    def log_message(self, format, *args):
        """Suppress console logging for packaged Windows builds."""

    def do_HEAD(self):
        if self.path not in {"/", "/status", "/chat"}:
            self.send_error(404)
            return
        body = (
            self.server.render_mobile_chat_page()
            if self.path == "/chat"
            else self.server.render_status_page()
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/mobile-status":
            result = self.server.handle_mobile_status()
            body = json.dumps(result, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == "/api/mobile-conversations":
            result = self.server.handle_mobile_conversations()
            body = json.dumps(result, ensure_ascii=False).encode("utf-8")
            self.send_response(200 if result.get("ok") else 400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed_path.path == "/api/mobile-conversation":
            query = urllib.parse.parse_qs(parsed_path.query)
            conversation_id = (query.get("id") or query.get("conversation_id") or [""])[0]
            result = self.server.handle_mobile_conversation(conversation_id)
            body = json.dumps(result, ensure_ascii=False).encode("utf-8")
            self.send_response(200 if result.get("ok") else 400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path not in {"/", "/status", "/chat"}:
            self.send_error(404)
            return
        body = (
            self.server.render_mobile_chat_page()
            if self.path == "/chat"
            else self.server.render_status_page()
        ).encode("utf-8")
        if self.path == "/chat" and callable(self.server.event_callback):
            self.server.event_callback("Mobile page opened")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/api/mobile-conversation/new":
            result = self.server.handle_new_mobile_conversation()
            body = json.dumps(result, ensure_ascii=False).encode("utf-8")
            self.send_response(200 if result.get("ok") else 400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path != "/api/mobile-chat":
            self.send_error(405, "Read-only status page.")
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0") or 0), 8192)
        except ValueError:
            length = 0
        raw_body = self.rfile.read(length).decode("utf-8", errors="ignore")
        content_type = str(self.headers.get("Content-Type", "")).lower()
        try:
            if "application/json" in content_type:
                payload = json.loads(raw_body or "{}")
            else:
                form = urllib.parse.parse_qs(raw_body)
                payload = {"message": (form.get("message") or [""])[0]}
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        result = self.server.handle_mobile_chat(
            payload.get("message", ""),
            payload.get("conversation_id") or payload.get("conversationId")
        )
        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200 if result.get("ok") else 400)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):
        self.send_error(405, "Read-only status page.")

    def do_DELETE(self):
        self.send_error(405, "Read-only status page.")


class _LANStatusHTTPServer(_ReusableThreadingHTTPServer):
    def __init__(self, server_address, status_provider, mobile_chat_service=None, event_callback=None):
        super().__init__(server_address, _LANStatusHandler)
        self.status_provider = status_provider
        self.mobile_chat_service = mobile_chat_service
        self.event_callback = event_callback

    def render_status_page(self):
        try:
            status = self.status_provider() if callable(self.status_provider) else {}
        except Exception as error:
            status = {"error": str(error)}
        return render_status_html(status)

    def render_mobile_chat_page(self):
        return render_mobile_chat_html()

    def handle_mobile_chat(self, message, conversation_id=None):
        if callable(self.event_callback):
            self.event_callback("Mobile request received")
        if self.mobile_chat_service is None:
            if callable(self.event_callback):
                self.event_callback("Mobile request blocked")
            return {
                "ok": False,
                "error": "LAN Chat Disabled",
                "message": "LAN Chat Disabled / 局域网聊天已关闭。"
            }
        result = self.mobile_chat_service.handle_request(message, conversation_id=conversation_id)
        if callable(self.event_callback):
            if result.get("ok"):
                self.event_callback("Mobile response generated")
            else:
                if result.get("error") == "Request Timeout":
                    self.event_callback("Mobile request timeout")
                if result.get("stage"):
                    self.event_callback(f"Failure stage: {result.get('stage')}")
                if result.get("reason"):
                    self.event_callback(f"Failure reason: {result.get('reason')}")
                self.event_callback("Mobile failure reason recorded")
                self.event_callback("Mobile error handled")
                self.event_callback("Mobile request blocked")
        return result

    def handle_mobile_status(self):
        if self.mobile_chat_service is None:
            return {
                "remote": False,
                "lan_chat": False,
                "ollama": False,
                "context": False,
                "ai_ready": False,
                "reason": "LAN Chat Disabled"
            }
        try:
            return self.mobile_chat_service.mobile_status()
        except Exception as error:
            return {
                "remote": False,
                "lan_chat": False,
                "ollama": False,
                "context": False,
                "ai_ready": False,
                "reason": str(error)
            }

    def handle_mobile_conversations(self):
        if self.mobile_chat_service is None:
            return {"ok": False, "error": "LAN Chat Disabled", "conversations": []}
        try:
            return self.mobile_chat_service.list_conversations()
        except Exception as error:
            return {"ok": False, "error": "Conversation list failed", "reason": str(error), "conversations": []}

    def handle_mobile_conversation(self, conversation_id):
        if self.mobile_chat_service is None:
            return {"ok": False, "error": "LAN Chat Disabled"}
        try:
            return self.mobile_chat_service.load_conversation(conversation_id)
        except Exception as error:
            return {"ok": False, "error": "Conversation load failed", "reason": str(error)}

    def handle_new_mobile_conversation(self):
        if self.mobile_chat_service is None:
            return {"ok": False, "error": "LAN Chat Disabled"}
        try:
            return self.mobile_chat_service.new_conversation()
        except Exception as error:
            return {"ok": False, "error": "Conversation create failed", "reason": str(error)}


class LANStatusPageServer:
    """Small background HTTP server for the v2.0 read-only status page."""

    def __init__(self):
        self._server = None
        self._thread = None
        self.host = "127.0.0.1"
        self.port = DEFAULT_LAN_STATUS_PORT
        self.last_error = None
        self.started_at = None
        self.mobile_chat_enabled = False

    def is_running(self):
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    def start(
        self,
        host="127.0.0.1",
        port=DEFAULT_LAN_STATUS_PORT,
        status_provider=None,
        mobile_chat_service=None,
        event_callback=None
    ):
        if self.is_running():
            if self._server is not None:
                if mobile_chat_service is not None:
                    self.mobile_chat_enabled = True
                    self._server.mobile_chat_service = mobile_chat_service
                if event_callback is not None:
                    self._server.event_callback = event_callback
            return {
                "ok": True,
                "running": True,
                "message": "LAN server duplicate start blocked.",
                "duplicate": True,
                "host": self.host,
                "port": self.port
            }

        try:
            server = _LANStatusHTTPServer(
                (host, int(port)),
                status_provider or (lambda: {}),
                mobile_chat_service=mobile_chat_service,
                event_callback=event_callback
            )
        except OSError as error:
            self.last_error = friendly_port_error(error)
            return {
                "ok": False,
                "running": False,
                "message": self.last_error,
                "host": host,
                "port": int(port)
            }

        self._server = server
        self.host = host
        self.port = int(server.server_address[1])
        self.last_error = None
        self.started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.mobile_chat_enabled = mobile_chat_service is not None
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        return {
            "ok": True,
            "running": True,
            "message": "LAN Status Page started.",
            "host": self.host,
            "port": self.port
        }

    def stop(self):
        if not self._server:
            return {"ok": True, "running": False, "message": "LAN Status Page is already stopped."}

        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        self.mobile_chat_enabled = False
        try:
            server.shutdown()
            server.server_close()
            if thread is not None:
                thread.join(timeout=2)
            self.last_error = None
        except OSError as error:
            self.last_error = str(error)
            return {"ok": False, "running": False, "message": self.last_error}

        return {"ok": True, "running": False, "message": "LAN Status Page stopped.", "released": True}

    def local_url(self):
        return f"http://127.0.0.1:{self.port}"

    def lan_url(self, lan_address):
        if not lan_address or lan_address == "Unavailable":
            return "No LAN address available."
        return f"http://{lan_address}:{self.port}"

    def mobile_url(self, lan_address):
        if not lan_address or lan_address == "Unavailable":
            return "No LAN address available."
        return f"http://{lan_address}:{self.port}/chat"


def friendly_port_error(error):
    if getattr(error, "errno", None) in {98, 10048}:
        return "Port already in use. / 端口已被占用。请关闭其他 Aurora 实例。"
    return str(error) or "LAN Status Page could not start."


def is_port_available(port, host="127.0.0.1"):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, int(port)))
        return True
    except OSError:
        return False


def render_status_html(status):
    def value(key, default="Offline"):
        return escape(str(status.get(key, default)))

    rows = [
        ("Status", value("status", "Online")),
        ("Version", value("version", RELEASE)),
        ("Ollama", value("ollama")),
        ("Open WebUI", value("openwebui")),
        ("Memory", value("memory", "Available")),
        ("Knowledge", value("knowledge", "Available")),
        ("Persona", value("persona", "Disabled")),
        ("Remote Security", value("remote_security", "Protected")),
    ]
    row_html = "\n".join(
        f"<div class='row'><span>{escape(label)}</span><strong>{item}</strong></div>"
        for label, item in rows
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Project Aurora</title>
  <style>
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #111318;
      color: #f5f7fb;
    }}
    main {{
      max-width: 720px;
      margin: 0 auto;
      padding: 32px 20px;
    }}
    .card {{
      background: #1c2028;
      border: 1px solid #303642;
      border-radius: 22px;
      padding: 24px;
      box-shadow: 0 18px 45px rgba(0,0,0,.28);
    }}
    h1 {{
      margin: 0 0 18px;
      font-size: 30px;
    }}
    .row {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      padding: 13px 0;
      border-bottom: 1px solid #303642;
    }}
    .row:last-child {{
      border-bottom: 0;
    }}
    .note {{
      margin-top: 22px;
      color: #b8c0cc;
      line-height: 1.6;
    }}
  </style>
</head>
<body>
  <main>
    <section class="card">
      <h1>Project Aurora</h1>
      {row_html}
      <p class="note">
        This is a read-only LAN status page. Chat is not available on mobile yet.<br>
        这是只读局域网状态页。暂不支持手机聊天。
      </p>
    </section>
  </main>
</body>
</html>"""


def render_mobile_chat_html():
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Project Aurora Mobile</title>
  <style>
    body {
      margin: 0;
      background: #0f1117;
      color: #f6f7fb;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      -webkit-text-size-adjust: 100%;
      overflow-wrap: anywhere;
    }
    main {
      max-width: 760px;
      margin: 0 auto;
      padding: max(14px, env(safe-area-inset-top)) 14px max(18px, env(safe-area-inset-bottom));
    }
    .card {
      background: #181b22;
      border: 1px solid #2b303b;
      border-radius: 18px;
      padding: 16px;
      min-height: calc(100vh - 40px);
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
    }
    h1 {
      margin: 0;
      font-size: 26px;
      line-height: 1.1;
    }
    .subtle {
      color: #aeb8c7;
      font-size: 13px;
      line-height: 1.45;
    }
    .online {
      color: #89d98b;
      font-weight: 700;
      white-space: nowrap;
    }
    .model {
      margin-top: 4px;
      color: #c9d2e3;
      font-size: 13px;
    }
    .status-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .chip {
      background: #10141c;
      border: 1px solid #303746;
      border-radius: 12px;
      padding: 10px;
      min-width: 0;
    }
    .chip span {
      display: block;
      color: #96a3b8;
      font-size: 12px;
      margin-bottom: 4px;
    }
    .chip strong {
      display: block;
      font-size: 13px;
      font-weight: 700;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .conversation-meta {
      color: #aeb8c7;
      font-size: 12px;
      line-height: 1.45;
      border-top: 1px solid #2b303b;
      border-bottom: 1px solid #2b303b;
      padding: 10px 0;
    }
    .messages {
      flex: 1;
      min-height: 220px;
      max-height: 50vh;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 4px 0;
    }
    .bubble {
      max-width: 86%;
      border-radius: 16px;
      padding: 11px 13px;
      line-height: 1.55;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .bubble.user {
      align-self: flex-end;
      background: #2f6fed;
      color: #fff;
      border-bottom-right-radius: 6px;
    }
    .bubble.assistant {
      align-self: flex-start;
      background: #10141c;
      border: 1px solid #303746;
      color: #f6f7fb;
      border-bottom-left-radius: 6px;
    }
    .time {
      display: block;
      margin-top: 6px;
      font-size: 11px;
      opacity: .68;
    }
    textarea {
      width: 100%;
      min-height: 84px;
      box-sizing: border-box;
      border: 1px solid #3b4250;
      border-radius: 14px;
      padding: 14px;
      background: #11151d;
      color: #fff;
      font-size: 16px;
      resize: vertical;
      -webkit-appearance: none;
      line-height: 1.5;
    }
    button {
      width: 100%;
      margin-top: 10px;
      padding: 14px 16px;
      border: 0;
      border-radius: 14px;
      background: #4f8cff;
      color: #fff;
      font-size: 17px;
      font-weight: 700;
      -webkit-tap-highlight-color: transparent;
    }
    button:disabled {
      opacity: .65;
    }
    .hint {
      color: #aeb8c7;
      font-size: 13px;
      line-height: 1.5;
      margin: 8px 0 0;
    }
    code, pre {
      white-space: pre-wrap;
      word-break: break-word;
    }
    @media (max-width: 480px) {
      h1 { font-size: 24px; }
      .card { border-radius: 16px; padding: 14px; }
      .status-grid { grid-template-columns: 1fr; }
      button { font-size: 16px; }
      .messages { max-height: 46vh; }
    }
  </style>
</head>
<body>
  <main>
    <section class="card">
      <header class="topbar">
        <div>
          <h1>Aurora</h1>
          <div class="model" id="modelStatus">Model: checking...</div>
        </div>
        <div class="online" id="auroraStatus">● Online</div>
      </header>
      <section class="status-grid">
        <div class="chip"><span>Persona</span><strong id="personaStatus">Checking</strong></div>
        <div class="chip"><span>Memory</span><strong id="memoryStatus">Available</strong></div>
        <div class="chip"><span>Knowledge</span><strong id="knowledgeStatus">Available</strong></div>
      </section>
      <div class="conversation-meta">
        <div id="conversationTitle">Conversation: New Conversation</div>
        <div id="conversationId">ID: not saved yet</div>
      </div>
      <section class="messages" id="messages">
        <div class="bubble assistant">Ready.<span class="time">Aurora</span></div>
      </section>
      <textarea id="message" maxlength="2000" placeholder="Message"></textarea>
      <p class="hint">LAN only. 局域网访问。Long responses are shortened for mobile display.</p>
      <button id="send">Send</button>
    </section>
  </main>
  <script>
    const message = document.getElementById("message");
    const send = document.getElementById("send");
    const messages = document.getElementById("messages");
    const auroraStatus = document.getElementById("auroraStatus");
    const modelStatus = document.getElementById("modelStatus");
    const personaStatus = document.getElementById("personaStatus");
    const memoryStatus = document.getElementById("memoryStatus");
    const knowledgeStatus = document.getElementById("knowledgeStatus");
    const conversationTitle = document.getElementById("conversationTitle");
    const conversationId = document.getElementById("conversationId");
    let currentConversationId = "";
    loadMobileStatus();
    send.addEventListener("click", async () => {
      const text = message.value.trim();
      if (!text) {
        addBubble("assistant", "Message is empty.");
        return;
      }
      send.disabled = true;
      addBubble("user", text);
      message.value = "";
      const waiting = addBubble("assistant", "Waiting for Aurora...");
      try {
        const result = await fetch("/api/mobile-chat", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({message: text, conversation_id: currentConversationId})
        });
        const data = await result.json();
        if (data.conversation_id) {
          currentConversationId = data.conversation_id;
        }
        const stage = data.stage ? "\\nStage: " + data.stage : "";
        const reason = data.reason ? "\\nReason: " + data.reason : "";
        const detail = data.detail ? "\\nDetail: " + data.detail : "";
        waiting.innerHTML = renderBasicMarkdown(data.ok ? data.response : ((data.message || data.error || "Request failed.") + stage + reason + detail)) + timeHtml();
        auroraStatus.textContent = data.ok ? "● Online" : "● Online";
        updateConversationMeta(data);
      } catch (error) {
        waiting.innerHTML = renderBasicMarkdown("Request failed. / 请求失败。") + timeHtml();
      } finally {
        send.disabled = false;
      }
    });
    async function loadMobileStatus() {
      try {
        const result = await fetch("/api/mobile-status", {cache: "no-store"});
        const data = await result.json();
        auroraStatus.textContent = data.remote ? "● Online" : "● Remote Disabled";
        modelStatus.textContent = "Model: " + (data.chat_model || data.model || "Unknown");
        personaStatus.textContent = data.context ? "Enabled" : "Unknown";
        memoryStatus.textContent = "Available";
        knowledgeStatus.textContent = "Available";
      } catch (error) {
        auroraStatus.textContent = "● Online";
        modelStatus.textContent = "Model: unavailable";
      }
    }
    function addBubble(role, text) {
      const item = document.createElement("div");
      item.className = "bubble " + role;
      item.innerHTML = renderBasicMarkdown(text) + timeHtml();
      messages.appendChild(item);
      messages.scrollTop = messages.scrollHeight;
      return item;
    }
    function timeHtml() {
      return '<span class="time">' + new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) + '</span>';
    }
    function updateConversationMeta(data) {
      conversationTitle.textContent = "Conversation: New Conversation";
      conversationId.textContent = currentConversationId ? ("ID: " + currentConversationId) : "ID: not saved yet";
    }
    function escapeHtml(text) {
      return String(text || "").replace(/[&<>"']/g, item => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[item]));
    }
    function renderBasicMarkdown(text) {
      let safe = escapeHtml(text);
      safe = safe.replace(/```([\\s\\S]*?)```/g, "<pre><code>$1</code></pre>");
      safe = safe.replace(/`([^`]+)`/g, "<code>$1</code>");
      safe = safe.replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>");
      return safe.replace(/\\n/g, "<br>");
    }
  </script>
</body>
</html>"""

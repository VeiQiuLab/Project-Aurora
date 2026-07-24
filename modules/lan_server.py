"""Read-only LAN status page server for Project Aurora.

The server intentionally exposes only a small status summary. It does not
provide chat, settings, data export, system commands, or full local data.
"""

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import time

from modules.version import RELEASE


DEFAULT_LAN_STATUS_PORT = 8765


class _ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False


class _LANStatusHandler(BaseHTTPRequestHandler):
    server_version = "ProjectAuroraLANStatus/2.0"

    def log_message(self, format, *args):
        """Suppress console logging for packaged Windows builds."""

    def do_HEAD(self):
        if self.path not in {"/", "/status"}:
            self.send_error(404)
            return
        body = self.server.render_status_page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self):
        if self.path not in {"/", "/status"}:
            self.send_error(404)
            return
        body = self.server.render_status_page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.send_error(405, "Read-only status page.")

    def do_PUT(self):
        self.send_error(405, "Read-only status page.")

    def do_DELETE(self):
        self.send_error(405, "Read-only status page.")


class _LANStatusHTTPServer(_ReusableThreadingHTTPServer):
    def __init__(self, server_address, status_provider):
        super().__init__(server_address, _LANStatusHandler)
        self.status_provider = status_provider

    def render_status_page(self):
        try:
            status = self.status_provider() if callable(self.status_provider) else {}
        except Exception as error:
            status = {"error": str(error)}
        return render_status_html(status)


class LANStatusPageServer:
    """Small background HTTP server for the v2.0 read-only status page."""

    def __init__(self):
        self._server = None
        self._thread = None
        self.host = "127.0.0.1"
        self.port = DEFAULT_LAN_STATUS_PORT
        self.last_error = None
        self.started_at = None

    def is_running(self):
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    def start(self, host="127.0.0.1", port=DEFAULT_LAN_STATUS_PORT, status_provider=None):
        if self.is_running():
            return {
                "ok": True,
                "running": True,
                "message": "LAN Status Page is already running.",
                "host": self.host,
                "port": self.port
            }

        try:
            server = _LANStatusHTTPServer((host, int(port)), status_provider or (lambda: {}))
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
        try:
            server.shutdown()
            server.server_close()
            if thread is not None:
                thread.join(timeout=2)
        except OSError as error:
            self.last_error = str(error)
            return {"ok": False, "running": False, "message": self.last_error}

        return {"ok": True, "running": False, "message": "LAN Status Page stopped."}

    def local_url(self):
        return f"http://127.0.0.1:{self.port}"

    def lan_url(self, lan_address):
        if not lan_address or lan_address == "Unavailable":
            return "No LAN address available."
        return f"http://{lan_address}:{self.port}"


def friendly_port_error(error):
    if getattr(error, "errno", None) in {98, 10048}:
        return "Port is already in use."
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

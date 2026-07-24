import socket
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlparse

from modules.settings import settings


DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OPENWEBUI_URL = "http://localhost:8080"


def endpoint_from_url(url, default_host, default_port):
    """Return a host and port from a configured service URL."""

    try:
        parsed = urlparse(str(url))
        host = parsed.hostname or default_host
        port = parsed.port or default_port
        return host, port
    except (TypeError, ValueError):
        return default_host, default_port


def port_open(port, host="127.0.0.1"):
    """Check whether a configured host and port are accepting connections."""

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.5)
            result = connection.connect_ex((host, port))
            return result == 0
    except (OSError, TypeError, ValueError):
        return False


def process_running(name):
    """Check whether a Windows process is running."""

    try:
        output = subprocess.check_output(
            "tasklist",
            text=True,
            encoding="gbk",
            errors="ignore",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )

        return name.lower() in output.lower()

    except (OSError, subprocess.SubprocessError):
        return False


def check_ollama_api(url=DEFAULT_OLLAMA_HOST, timeout=3):
    """Check Ollama's actual tags endpoint, returning status and reason."""
    target = str(url).rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(target, timeout=timeout) as response:
            return {"available": True, "status": "Online", "reason": "API available", "http_status": response.status}
    except urllib.error.HTTPError as error:
        return {"available": False, "status": "Error", "reason": f"HTTP {error.code}", "http_status": error.code}
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as error:
        return {"available": False, "status": "Offline", "reason": str(error)}


def check_http_service(url=DEFAULT_OPENWEBUI_URL, timeout=3):
    """Check whether an HTTP service responds without changing existing checks."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return {"available": True, "status": "Online", "reason": "HTTP available", "http_status": response.status}
    except urllib.error.HTTPError as error:
        return {"available": False, "status": "Error", "reason": f"HTTP {error.code}", "http_status": error.code}
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as error:
        return {"available": False, "status": "Offline", "reason": str(error)}


def check_all():
    ollama_url = settings.get("ollama.host", DEFAULT_OLLAMA_HOST)
    openwebui_url = settings.get(
        "openwebui.host",
        DEFAULT_OPENWEBUI_URL
    )

    ollama_host, ollama_port = endpoint_from_url(
        ollama_url,
        "127.0.0.1",
        11434
    )
    webui_host, webui_port = endpoint_from_url(
        openwebui_url,
        "localhost",
        8080
    )

    status = {
        "ollama": process_running("ollama"),
        "webui": port_open(webui_port, webui_host),
        "api": port_open(ollama_port, ollama_host)
    }

    return status

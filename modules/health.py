import socket
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlparse

from modules.settings import settings
from modules.models import infer_model_capability


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


def check_ollama_diagnostics(url=DEFAULT_OLLAMA_HOST, model="", timeout=3):
    """Return detailed Ollama diagnostics for LAN/mobile chat troubleshooting."""

    target = str(url or DEFAULT_OLLAMA_HOST).rstrip("/")
    chat_model = str(settings.get("chat_model", "qwen3:8b") or "").strip()
    embedding_model = str(settings.get("embedding_model", "nomic-embed-text:latest") or "").strip()
    selected_model = str(model or chat_model or "").strip()
    model_capability = infer_model_capability(selected_model)
    diagnostics = {
        "ollama_url": target,
        "model": selected_model,
        "chat_model": chat_model,
        "embedding_model": embedding_model,
        "model_capability": model_capability,
        "chat_support": model_capability == "Chat Supported",
        "running": False,
        "api_available": False,
        "model_available": False,
        "connection_status": "Unavailable",
        "http_status": None,
        "error_detail": "",
        "available_models": []
    }
    try:
        with urllib.request.urlopen(f"{target}/api/tags", timeout=timeout) as response:
            diagnostics["http_status"] = getattr(response, "status", None)
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        diagnostics["http_status"] = error.code
        diagnostics["error_detail"] = f"HTTP {error.code}"
        diagnostics["connection_status"] = "HTTP Error"
        return diagnostics
    except urllib.error.URLError as error:
        diagnostics["error_detail"] = str(getattr(error, "reason", error))
        diagnostics["connection_status"] = "Connection Failed"
        return diagnostics
    except (OSError, TimeoutError, ValueError) as error:
        diagnostics["error_detail"] = str(error)
        diagnostics["connection_status"] = "Error"
        return diagnostics

    try:
        import json
        data = json.loads(payload)
    except (TypeError, ValueError):
        diagnostics["running"] = True
        diagnostics["connection_status"] = "Invalid Response"
        diagnostics["error_detail"] = "Invalid response"
        return diagnostics

    models = data.get("models", []) if isinstance(data, dict) else []
    names = [
        str(item.get("name") or item.get("model") or "").strip()
        for item in models
        if isinstance(item, dict) and str(item.get("name") or item.get("model") or "").strip()
    ]
    diagnostics["running"] = True
    diagnostics["api_available"] = True
    diagnostics["connection_status"] = "Available"
    diagnostics["available_models"] = names
    selected_model = diagnostics["model"]
    diagnostics["model_capability"] = infer_model_capability(selected_model)
    diagnostics["chat_support"] = diagnostics["model_capability"] == "Chat Supported"
    diagnostics["model_available"] = bool(selected_model and selected_model in names)
    if selected_model and not diagnostics["model_available"]:
        diagnostics["error_detail"] = f"Model unavailable: {selected_model}"
    if selected_model and not diagnostics["chat_support"]:
        diagnostics["error_detail"] = "Model cannot chat. Please select a chat model."
    return diagnostics


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

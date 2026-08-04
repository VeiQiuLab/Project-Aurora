import socket
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlparse

from modules.settings import settings
from modules.models import infer_model_capability


DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OPENWEBUI_URL = "http://localhost:8080"
HEALTH_ORDER = {"Healthy": 0, "Warning": 1, "Error": 2}


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
    """Return detailed local Ollama diagnostics."""

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


def _health_item(name, status="Healthy", message="", details=None):
    return {
        "name": name,
        "status": status,
        "message": str(message or ""),
        "details": details or {}
    }


def _overall_status(items):
    status = "Healthy"
    for item in items or []:
        current = item.get("status", "Healthy")
        if HEALTH_ORDER.get(current, 0) > HEALTH_ORDER.get(status, 0):
            status = current
    return status


def check_startup_health(timeout=3):
    """Return a unified startup health report for Aurora core modules."""

    items = []
    ollama_url = settings.get("ollama.host", DEFAULT_OLLAMA_HOST)
    chat_model = str(settings.get("chat_model", "qwen3:8b") or "").strip()
    embedding_model = str(settings.get("embedding_model", "nomic-embed-text:latest") or "").strip()

    ollama = check_ollama_diagnostics(ollama_url, model=chat_model, timeout=timeout)
    ollama_status = "Healthy" if ollama.get("api_available") else "Error"
    items.append(_health_item(
        "Ollama",
        ollama_status,
        "Ollama API available." if ollama_status == "Healthy" else ollama.get("error_detail", "Ollama unavailable."),
        ollama
    ))
    items.append(_health_item(
        "Chat Model",
        "Healthy" if ollama.get("model_available") and ollama.get("chat_support") else "Warning",
        "Chat model available." if ollama.get("model_available") and ollama.get("chat_support") else ollama.get("error_detail", "Chat model not confirmed."),
        {
            "model": chat_model,
            "available": bool(ollama.get("model_available")),
            "capability": infer_model_capability(chat_model)
        }
    ))
    embedding_available = bool(embedding_model and embedding_model in ollama.get("available_models", []))
    items.append(_health_item(
        "Embedding Model",
        "Healthy" if embedding_available else "Warning",
        "Embedding model available." if embedding_available else "Embedding model not confirmed in Ollama model list.",
        {
            "model": embedding_model,
            "available": embedding_available,
            "capability": infer_model_capability(embedding_model)
        }
    ))

    try:
        from modules.memory import MemoryStore
        memory_store = MemoryStore()
        memories = memory_store.list_memories()
        items.append(_health_item(
            "Memory",
            "Healthy",
            f"Memory store readable. Records: {len(memories)}",
            {"records": len(memories), "path": str(memory_store.file_path)}
        ))
    except Exception as error:
        items.append(_health_item("Memory", "Error", error))

    try:
        from modules.knowledge import KnowledgeStore
        knowledge_store = KnowledgeStore()
        knowledge = knowledge_store.health()
        status = "Healthy"
        if knowledge.get("metadata_errors", 0) or knowledge.get("errors", 0):
            status = "Error"
        elif knowledge.get("missing", 0) or knowledge.get("embedding_needs_reindex", 0):
            status = "Warning"
        items.append(_health_item(
            "Knowledge",
            status,
            f"Knowledge files: {knowledge.get('total', 0)}",
            knowledge
        ))
        vector = knowledge.get("vector_index", {})
        vector_status = "Healthy"
        if vector.get("invalid", 0):
            vector_status = "Error"
        elif not vector.get("exists") or vector.get("missing", 0) or vector.get("stale", 0) or vector.get("orphaned", 0):
            vector_status = "Warning"
        items.append(_health_item(
            "Vector Index",
            vector_status,
            "Vector index healthy." if vector_status == "Healthy" else "Vector index needs attention.",
            vector
        ))
    except Exception as error:
        items.append(_health_item("Knowledge", "Error", error))
        items.append(_health_item("Vector Index", "Error", error))

    try:
        from modules.conversation import ConversationManager
        conversation_manager = ConversationManager()
        conversations = conversation_manager.list_conversations()
        items.append(_health_item(
            "Conversation Store",
            "Healthy",
            f"Conversation store readable. Records: {len(conversations)}",
            {"records": len(conversations), "path": str(conversation_manager.directory)}
        ))
    except Exception as error:
        items.append(_health_item("Conversation Store", "Error", error))

    try:
        from modules.persona import PersonaStore
        persona_store = PersonaStore()
        persona = persona_store.load(update_timestamp=False)
        persona_status = persona_store.status(settings.get("persona.enabled", True), persona)
        items.append(_health_item(
            "Persona",
            "Healthy" if persona_status.get("name") else "Warning",
            "Persona loaded." if persona_status.get("name") else "Persona name missing.",
            persona_status
        ))
    except Exception as error:
        items.append(_health_item("Persona", "Error", error))

    return {
        "status": _overall_status(items),
        "items": items
    }


def system_self_check(timeout=3):
    """Return a compact Healthy / Warning / Error report for stable releases."""

    report = check_startup_health(timeout=timeout)
    return {
        "status": report.get("status", "Error"),
        "healthy": sum(1 for item in report.get("items", []) if item.get("status") == "Healthy"),
        "warnings": sum(1 for item in report.get("items", []) if item.get("status") == "Warning"),
        "errors": sum(1 for item in report.get("items", []) if item.get("status") == "Error"),
        "items": report.get("items", [])
    }


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

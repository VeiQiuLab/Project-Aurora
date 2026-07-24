import webbrowser

from modules.settings import settings


DEFAULT_OPENWEBUI_URL = "http://localhost:8080"


def open_webui():
    """Open the configured Open WebUI address."""

    url = settings.get("openwebui.host", DEFAULT_OPENWEBUI_URL)
    url = str(url).strip() or DEFAULT_OPENWEBUI_URL
    webbrowser.open(url)

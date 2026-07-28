import customtkinter as ctk
import copy
import json
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from tkinter import filedialog, messagebox, StringVar

from modules.version import *
from modules.logger import logger
from modules.credential_storage import CredentialStorageProvider


configuration_file = Path(__file__).resolve().parent / "config" / "settings.json"


def ensure_runtime_directories():
    project_root = Path(__file__).resolve().parent
    for relative_path in ("data", "data/conversations", "data/memory", "data/knowledge", "data/persona", "data/remote", "config", "logs"):
        (project_root / relative_path).mkdir(parents=True, exist_ok=True)


ensure_runtime_directories()


def inspect_configuration_file():
    if not configuration_file.exists():
        return "missing"

    try:
        with configuration_file.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return "invalid"

    required_paths = [
        "app_name",
        "theme",
        "appearance",
        "language",
        "window.width",
        "window.height",
        "ollama.host",
        "ollama.auto_start",
        "openwebui.host",
        "openwebui.auto_start",
        "status.refresh_interval",
        "persona.enabled",
        "knowledge.enabled",
        "knowledge.max_results",
        "knowledge.preview_limit",
        "knowledge.enabled_filter",
        "knowledge.sort_field",
        "knowledge.sort_direction",
        "knowledge.backup_path",
        "knowledge.max_backup_count",
        "context.warning_tokens",
        "context.preview_limit",
        "context.inspector_preview_limit",
        "first_run.completed",
        "remote.enabled",
        "remote.mode",
        "remote.auth_required",
        "remote.authentication_required",
        "remote.auth_enabled",
        "remote.authentication_type",
        "remote.token_configured",
        "remote.last_token_update",
        "remote.credential_storage",
        "remote.secure_storage_configured",
        "remote.secure_storage_available",
        "remote.credential_test_passed",
        "remote.credential_last_check",
        "remote.credential_last_result",
        "remote.credential_command_status",
        "remote.credential_last_operation",
        "remote.credential_operation_result",
        "remote.credential_duration_ms",
        "remote.credential_error_suggestion",
        "remote.last_storage_error",
        "remote.credential_history",
        "remote.credential_steps",
        "remote.network_history",
        "remote.security_history",
        "remote.authentication_history",
        "remote.remote_history",
        "remote.lan_status_page_enabled",
        "remote.lan_status_port",
        "remote.lan_status_user_confirmed",
        "remote.lan_chat_enabled",
        "remote.lan_chat_port",
        "remote.mobile_access_confirmed",
        "remote.mobile_debug_mode",
        "remote.mobile_response_limit",
        "remote.selected_lan_ip",
        "remote.selected_adapter",
        "remote.last_mobile_error",
        "remote.last_mobile_capability",
        "chat_model",
        "embedding_model",
        "mobile_chat_timeout",
        "mobile_debug_mode",
        "mobile_response_limit",
        "network.preferred_interface",
        "network.ignore_virtual_adapter",
        "remote.authentication_configured",
        "remote.lan_ready",
        "remote.ios_access_ready",
        "remote.tailscale_ready",
        "remote.user_confirmed",
        "remote.security_confirmed"
    ]

    for path in required_paths:
        value = data
        for key in path.split("."):
            if not isinstance(value, dict) or key not in value:
                return "missing_fields"
            value = value[key]

    return None


configuration_issue = inspect_configuration_file()

from modules.settings import settings
from modules.settings_controller import SettingsController
from modules.health import check_all, check_ollama_api, check_http_service, system_self_check
from modules.launcher import open_webui
from modules.models import get_model_records, get_models, infer_model_capability
from modules.chat import (
    ChatError,
    ChatSession,
    DEFAULT_SYSTEM_CONTEXT,
    assemble_final_prompt,
    build_context_debug_report,
    build_final_prompt_preview,
    summarize_context_sections,
    stream_chat
)
from modules.conversation import ConversationManager
from modules.memory import MemoryStore
from modules.knowledge import KnowledgeStore
from modules.persona import PersonaStore
from modules.authentication import AuthenticationManager
from modules.remote import RemoteAccessManager
from modules.language import TEXT, set_language as set_legacy_language
from modules.i18n import normalize_language, set_language as set_i18n_language, t
from modules.ui_theme import (
    button_style,
    COLOR_ERROR,
    COLOR_MUTED,
    COLOR_SUCCESS,
    COLOR_WARNING,
    FONT_APP_TITLE,
    FONT_HEADER,
    FONT_NORMAL,
    FONT_NORMAL_BOLD,
    FONT_SECTION,
    FONT_SMALL,
    FONT_SMALL_BOLD,
    FONT_TITLE,
    status_color
)
from modules.lan_server import LANStatusPageServer, DEFAULT_LAN_STATUS_PORT
from modules.mobile_chat import MobileChatService
from modules.search import search_memories, search_conversations
from modules.memory_retrieval import format_memory_context, retrieve_memories
from modules.retrieval import format_knowledge_context, search_knowledge, retrieval_summary
from modules.service_manager import ServiceManager
from widgets.app_shell import AppShell
from widgets.chat_window import ChatWindow
from widgets.conversation_browser import ConversationBrowserWindow
from widgets.first_run_wizard import FirstRunWizard
from widgets.health_window import HealthWindow
from widgets.knowledge_window import KnowledgeWindow
from widgets.memory_window import MemoryWindow
from widgets.models_window import ModelsWindow
from widgets.persona_window import PersonaWindow
from widgets.pages.chat_page import ChatPage
from widgets.pages.home_page import HomePage
from widgets.pages.library_page import LibraryPage
from widgets.pages.memory_page import MemoryPage
from widgets.pages.persona_page import PersonaPage
from widgets.pages.remote_page import RemotePage
from widgets.pages.settings_page import SettingsPage
from widgets.remote_window import RemoteWindow, RemoteDiagnosticsWindow
from widgets.settings_window import SettingsWindow

def apply_language(language):
    normalized = normalize_language(language)
    set_legacy_language(normalized)
    set_i18n_language(normalized)
    return normalized


apply_language(settings.get("language", "zh_CN"))
settings_controller = SettingsController(settings)


appearance = settings.get("appearance", "System")
theme = settings.get("theme", "blue")
if theme not in ["blue", "green", "dark-blue"]:
    theme = "blue"

if appearance.lower() == "system":
    ctk.set_appearance_mode("System")
elif appearance.lower() == "light":
    ctk.set_appearance_mode("Light")
else:
    ctk.set_appearance_mode("Dark")

ctk.set_default_color_theme(theme)


logger.startup()


def ui_button(parent, text, command=None, kind="secondary", **kwargs):
    options = button_style(kind)
    options.update(kwargs)
    return ctk.CTkButton(parent, text=text, command=command, **options)


def configure_status(label, status, text=None):
    label.configure(text=text if text is not None else str(status), text_color=status_color(status))


LANGUAGE_DISPLAY = {
    "zh_CN": "zh_CN",
    "en_US": "English"
}


def language_display(language):
    return LANGUAGE_DISPLAY.get(normalize_language(language), LANGUAGE_DISPLAY["zh_CN"])


def language_code(display):
    value = str(display or "").strip()
    for code, label in LANGUAGE_DISPLAY.items():
        if value == label:
            return code
    return normalize_language(value)


def restore_configuration_defaults():
    defaults = copy.deepcopy(settings.default_settings)
    defaults.setdefault("status", {})["refresh_interval"] = 3
    data = settings.data if isinstance(settings.data, dict) else {}
    data = copy.deepcopy(data)
    changed = False

    def merge_defaults(target, source):
        nonlocal changed

        for key, default_value in source.items():
            if key not in target:
                target[key] = copy.deepcopy(default_value)
                changed = True
            elif isinstance(default_value, dict):
                if not isinstance(target[key], dict):
                    target[key] = copy.deepcopy(default_value)
                    changed = True
                else:
                    merge_defaults(target[key], default_value)

    merge_defaults(data, defaults)

    if changed:
        settings.data = data
        settings.save()

    return changed


configuration_restored = restore_configuration_defaults()

if configuration_issue == "missing":
    logger.info("Configuration missing, restored default settings.")
elif configuration_issue == "invalid":
    logger.info("Configuration invalid, restored default settings.")
elif configuration_issue == "missing_fields" or configuration_restored:
    logger.info("Configuration fields missing, restored default settings.")

logger.info("Loading configuration...")


app = ctk.CTk()
app.title(WINDOW_TITLE)
first_run_required = not bool(settings.get("first_run.completed", False))
if first_run_required:
    app.withdraw()

width = settings.get("window.width", 1200)
height = settings.get("window.height", 760)

app.geometry(f"{width}x{height}")
app.minsize(900, 680)
app.resizable(True, True)

logger.info(f"Window Size: {width} x {height}")

legacy_dashboard_frame = ctk.CTkFrame(app, fg_color="transparent")

title = ctk.CTkLabel(
    legacy_dashboard_frame,
    text=APP_NAME,
    font=FONT_APP_TITLE
)
title.pack(pady=(20, 5))


version = ctk.CTkLabel(
    legacy_dashboard_frame,
    text=f"Version {VERSION} - Build {BUILD}",
    font=FONT_NORMAL
)
version.pack()

status_columns_frame = ctk.CTkFrame(legacy_dashboard_frame, fg_color="transparent")
status_columns_frame.pack(fill="x", padx=20, pady=15)
status_frame = ctk.CTkFrame(status_columns_frame)

status_frame.pack(
    side="left",
    fill="both",
    expand=True,
    padx=(0, 8)
)

status_title = ctk.CTkLabel(
    status_frame,
    text=t("system_status"),
    font=FONT_HEADER
)
status_title.pack(anchor="w", padx=15, pady=(12, 6))

startup_frame = ctk.CTkFrame(status_columns_frame)
startup_frame.pack(
    side="left",
    fill="both",
    expand=True,
    padx=(8, 0)
)

startup_title = ctk.CTkLabel(
    startup_frame,
    text=t("startup_status"),
    font=FONT_HEADER
)
startup_title.pack(anchor="w", padx=15, pady=(12, 6))

startup_status_labels = {}

for startup_item in [
    "Version loaded",
    "Configuration loaded",
    "Logger initialized",
    "Required modules loaded"
]:
    startup_row = ctk.CTkFrame(
        startup_frame,
        fg_color="transparent"
    )
    startup_row.pack(fill="x", padx=15, pady=3)

    ctk.CTkLabel(
        startup_row,
        text=startup_item,
        anchor="w",
        font=FONT_NORMAL
    ).pack(side="left")

    startup_state = ctk.CTkLabel(
        startup_row,
        text=t("ready"),
        font=FONT_SMALL,
        text_color=COLOR_SUCCESS
    )
    startup_state.pack(side="right")
    startup_status_labels[startup_item] = startup_state

status_labels = {}
app_shell = None
models_window = None
health_window = None
settings_window = None
chat_window = None
context_inspector_window = None
memory_window = None
knowledge_window = None
conversation_browser_window = None
persona_window = None
remote_window = None
remote_diagnostics_window = None
active_conversation_id = None
chat_load_conversation_callback = None
pending_conversation_id = None
memory_store = MemoryStore()
knowledge_store = KnowledgeStore()
persona_store = PersonaStore()
remote_manager = RemoteAccessManager()
authentication_manager = AuthenticationManager()
credential_storage_provider = CredentialStorageProvider()
service_manager = ServiceManager()
lan_status_server = LANStatusPageServer()


def get_mobile_chat_model():
    logger.info("Chat model loaded")
    logger.info("Embedding model loaded")
    configured_model = str(settings.get("chat_model", "qwen3:8b") or "").strip()
    if configured_model:
        logger.info(f"Chat model selected: {configured_model}")
    return configured_model


def mobile_chat_logger(event):
    logger.info(event)


mobile_chat_service = MobileChatService(
    model_provider=get_mobile_chat_model,
    remote_manager=remote_manager,
    event_callback=mobile_chat_logger
)


def fetch_ollama_models_from_api(timeout=5):
    host = str(settings.get("ollama.host", "http://127.0.0.1:11434") or "").strip().rstrip("/")
    if not host:
        return {
            "ok": False,
            "models": [],
            "reason": "Ollama host is not configured."
        }
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        return {
            "ok": False,
            "models": [],
            "reason": str(error)
        }

    records = []
    for item in payload.get("models", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("model") or "").strip()
        if not name:
            continue
        records.append({
            "name": name,
            "capability": infer_model_capability(name)
        })
    return {
        "ok": True,
        "models": records,
        "reason": ""
    }


def show_first_run_wizard():
    def current_persona_status():
        persona = persona_store.load(update_timestamp=False)
        return persona_store.status(settings.get("persona.enabled", True), persona)

    def complete_first_run(state, wizard):
        settings.set("chat_model", state["chat_model"])
        settings.set("embedding_model", state["embedding_model"])
        settings.set("first_run.completed", True)
        logger.info("First Run Wizard completed")
        wizard.grab_release()
        wizard.destroy()
        app.deiconify()
        startup_check()
        refresh_recent_logs()
        refresh_status()
        refresh_system_health_center()

    FirstRunWizard(
        app,
        release=RELEASE,
        build=BUILD,
        text=TEXT,
        translate=t,
        settings_get=settings.get,
        model_fetcher=fetch_ollama_models_from_api,
        persona_status_provider=current_persona_status,
        on_complete=complete_first_run,
        logger=logger
    )

status_summary_label = ctk.CTkLabel(
    status_frame,
    text=t("checking"),
    font=FONT_NORMAL_BOLD,
    text_color=COLOR_MUTED
)

dashboard_last_check_label = ctk.CTkLabel(
    status_frame,
    text=f"{t('last_check')}: --",
    font=FONT_SMALL,
    text_color=COLOR_MUTED
)

for name in ["Ollama", "Open WebUI", "API 11434"]:

    row = ctk.CTkFrame(
        status_frame,
        fg_color="transparent"
    )
    row.pack(fill="x", padx=15, pady=4)

    lbl = ctk.CTkLabel(
        row,
        text=f"[ ] {name}",
        anchor="w",
        font=FONT_SECTION
    )
    lbl.pack(side="left")

    state = ctk.CTkLabel(
        row,
        text=t("checking"),
        font=FONT_NORMAL,
        text_color=COLOR_MUTED
    )
    state.pack(side="right")

    status_labels[name] = (lbl, state)

docker_status_labels = {}
for name in ["Docker Desktop", "Docker Engine"]:
    row = ctk.CTkFrame(status_frame, fg_color="transparent")
    row.pack(fill="x", padx=15, pady=2)
    lbl = ctk.CTkLabel(row, text=name, anchor="w", font=FONT_NORMAL)
    lbl.pack(side="left")
    state = ctk.CTkLabel(row, text=t("checking"), font=FONT_SMALL, text_color=COLOR_MUTED)
    state.pack(side="right")
    docker_status_labels[name] = state

status_summary_label.pack(pady=(8, 2))
dashboard_last_check_label.pack(pady=(0, 10))

diagnostic_title = ctk.CTkLabel(
    status_frame,
    text=t("ai_environment_diagnostic"),
    font=FONT_SECTION
)
diagnostic_title.pack(anchor="w", padx=15, pady=(2, 4))
diagnostic_box = ctk.CTkTextbox(status_frame, height=105, wrap="word")
diagnostic_box.pack(fill="x", padx=15, pady=(0, 10))
diagnostic_box.insert("1.0", t("diagnostic_not_started"))
diagnostic_box.configure(state="disabled")
diagnostic_running = False

health_center_frame = ctk.CTkFrame(legacy_dashboard_frame)
health_center_frame.pack(fill="x", padx=20, pady=(0, 8))

health_center_header = ctk.CTkFrame(health_center_frame, fg_color="transparent")
health_center_header.pack(fill="x", padx=15, pady=(12, 6))

ctk.CTkLabel(
    health_center_header,
    text=t("dashboard_health_center"),
    font=FONT_HEADER
).pack(side="left")

health_center_summary = ctk.CTkLabel(
    health_center_header,
    text=t("checking"),
    font=FONT_NORMAL_BOLD,
    text_color=COLOR_MUTED
)
health_center_summary.pack(side="right")

health_center_grid = ctk.CTkFrame(health_center_frame, fg_color="transparent")
health_center_grid.pack(fill="x", padx=15, pady=(0, 8))

for health_column in range(3):
    health_center_grid.grid_columnconfigure(health_column, weight=1)

health_center_labels = {}
health_center_groups = [
    (t("ai_services"), ["Ollama", "Chat Model", "Embedding Model"]),
    (t("memory_knowledge"), ["Memory", "Knowledge", "Vector Index"]),
    (t("system"), ["Conversation Store", "Persona", "Remote"])
]

for column, (group_title, health_names) in enumerate(health_center_groups):
    group_frame = ctk.CTkFrame(health_center_grid)
    group_frame.grid(row=0, column=column, sticky="nsew", padx=5, pady=5)
    ctk.CTkLabel(
        group_frame,
        text=group_title,
        font=FONT_NORMAL_BOLD,
        anchor="w"
    ).pack(anchor="w", padx=12, pady=(10, 6))
    for health_name in health_names:
        row_frame = ctk.CTkFrame(group_frame, fg_color="transparent")
        row_frame.pack(fill="x", padx=12, pady=3)
        display_name = t("conversation") if health_name == "Conversation Store" else health_name
        ctk.CTkLabel(
            row_frame,
            text=display_name,
            font=FONT_SMALL,
            anchor="w"
        ).pack(side="left", fill="x", expand=True)
        value_label = ctk.CTkLabel(
            row_frame,
            text=t("checking"),
            font=FONT_SMALL_BOLD,
            text_color=COLOR_MUTED,
            anchor="e",
            width=78
        )
        value_label.pack(side="right")
        health_center_labels[health_name] = value_label

health_stats_frame = ctk.CTkFrame(health_center_frame, fg_color="transparent")
health_stats_frame.pack(fill="x", padx=15, pady=(0, 12))

health_stat_labels = {}
for stat_name in ["Memory", "Knowledge", "Conversation"]:
    stat_label = ctk.CTkLabel(
        health_stats_frame,
        text=f"{stat_name}: --",
        font=FONT_SMALL,
        text_color=COLOR_MUTED
    )
    stat_label.pack(side="left", padx=(0, 18))
    health_stat_labels[stat_name] = stat_label

health_center_running = False


def health_status_color(status):
    return status_color(status)


def refresh_system_health_center():
    global health_center_running
    if health_center_running:
        return
    health_center_running = True
    health_center_summary.configure(text=t("checking"), text_color=COLOR_MUTED)
    for label in health_center_labels.values():
        label.configure(text=t("checking"), text_color=COLOR_MUTED)

    def run_check():
        try:
            report = system_self_check(timeout=3)
            error_message = ""
        except Exception as error:
            report = {"status": "Error", "items": []}
            error_message = str(error)

        def update_center():
            global health_center_running
            items = {
                item.get("name"): item
                for item in report.get("items", [])
                if isinstance(item, dict)
            }
            for health_name, label in health_center_labels.items():
                item = items.get(health_name, {})
                status = item.get("status", "Warning")
                label.configure(text=status, text_color=health_status_color(status))

            memory_details = items.get("Memory", {}).get("details", {})
            knowledge_details = items.get("Knowledge", {}).get("details", {})
            conversation_details = items.get("Conversation Store", {}).get("details", {})
            health_stat_labels["Memory"].configure(text=f"{t('memory_count')}: {memory_details.get('records', 0)}")
            health_stat_labels["Knowledge"].configure(text=f"{t('knowledge_documents')}: {knowledge_details.get('total', 0)}")
            health_stat_labels["Conversation"].configure(text=f"{t('conversation_count')}: {conversation_details.get('records', 0)}")

            overall = report.get("status", "Error")
            if error_message:
                health_center_summary.configure(text=t("error"), text_color=COLOR_ERROR)
                logger.error(f"Dashboard health center failed: {error_message}")
            else:
                health_center_summary.configure(text=overall, text_color=health_status_color(overall))
                logger.info(f"Dashboard health center refreshed: {overall}")
            health_center_running = False

        try:
            app.after(0, update_center)
        except Exception:
            health_center_running = False

    threading.Thread(target=run_check, daemon=True).start()

showcase_frame = ctk.CTkFrame(legacy_dashboard_frame)
showcase_frame.pack(fill="x", padx=20, pady=(0, 8))

ctk.CTkLabel(
    showcase_frame,
    text=t("showcase"),
    font=FONT_HEADER
).pack(anchor="w", padx=15, pady=(12, 6))

showcase_grid = ctk.CTkFrame(showcase_frame, fg_color="transparent")
showcase_grid.pack(fill="x", padx=15, pady=(0, 12))

for showcase_column in range(5):
    showcase_grid.grid_columnconfigure(showcase_column, weight=1)

showcase_items = [
    (t("local_ai_chat"), t("available_status")),
    (t("memory_system"), t("available_status")),
    (t("knowledge_base"), t("available_status")),
    (t("persona_system"), t("enabled") if settings.get("persona.enabled", True) else t("disabled")),
    (t("remote_security"), t("protected"))
]

for index, (feature_name, feature_status) in enumerate(showcase_items):
    feature_card = ctk.CTkFrame(showcase_grid)
    feature_card.grid(row=0, column=index, sticky="ew", padx=5, pady=5)
    ctk.CTkLabel(
        feature_card,
        text=feature_name,
        font=FONT_SMALL_BOLD
    ).pack(pady=(10, 2))
    ctk.CTkLabel(
        feature_card,
        text=feature_status,
        font=FONT_SMALL,
        text_color=COLOR_SUCCESS
    ).pack(pady=(0, 10))

logger.info("Showcase opened")


def _show_diagnostic(lines):
    diagnostic_box.configure(state="normal")
    diagnostic_box.delete("1.0", "end")
    diagnostic_box.insert("1.0", "\n".join(lines))
    diagnostic_box.configure(state="disabled")


def run_diagnostic():
    global diagnostic_running
    if diagnostic_running:
        return
    diagnostic_running = True
    logger.info("Diagnostic started")
    _show_diagnostic(["Diagnostic running..."])

    def worker():
        logger.info("Ollama API check")
        logger.info("Docker Engine check")
        logger.info("Open WebUI check")
        result = service_manager.diagnose_all(
            settings.get("ollama.host", "http://127.0.0.1:11434"),
            settings.get("openwebui.host", "http://localhost:8080"),
            settings.get("openwebui.container_name", "open-webui")
        )
        lines = ["AI Environment Diagnostic"]
        ollama = result["ollama"]
        docker = result["docker"]
        webui = result["openwebui"]
        lines.append(f"{'OK' if ollama['available'] else 'FAIL'} Ollama API: {ollama['status']} - {ollama['reason']}")
        lines.append(f"{'OK' if docker['engine_ready'] else 'FAIL'} Docker Engine: {docker['status']}")
        lines.append(f"{'OK' if webui['container'] == 'running' else 'FAIL'} Open WebUI Container: {webui['container']}")
        lines.append(f"{'OK' if webui['available'] else 'FAIL'} Open WebUI HTTP: {webui['status']} - {webui['reason']}")
        if not ollama["available"]:
            logger.error("Ollama API unavailable")
        if not docker["engine_ready"]:
            logger.error("Docker Engine unavailable")
        if not webui["available"]:
            logger.error("Open WebUI connection failed")
        logger.info("Diagnostic completed")

        def finish():
            global diagnostic_running
            diagnostic_running = False
            _show_diagnostic(lines)
        app.after(0, finish)

    threading.Thread(target=worker, daemon=True).start()


def start_ollama_manual():
    logger.info("Starting Ollama")
    service_manager.start_ollama(
        settings.get("services.ollama.command", "ollama serve"),
        settings.get("ollama.host", "http://127.0.0.1:11434"),
        callback=lambda event: logger.info("Ollama started") if event == "started" else None
    )


def restart_openwebui_manual():
    container = settings.get("openwebui.container_name", "open-webui")
    url = settings.get("openwebui.host", "http://localhost:8080")
    service_manager.stop_open_webui_docker(container, callback=lambda event: launch_open_webui() if event == "stopped" else None)


def restart_container_manual():
    restart_openwebui_manual()


def launch_open_webui():
    """Open WebUI on demand, starting Docker only when the service is requested."""
    if settings.get("openwebui.type", "docker") != "docker":
        open_webui()
        return

    container = settings.get("openwebui.container_name", "open-webui")
    url = settings.get("openwebui.host", "http://localhost:8080")

    def event(name):
        if name == "starting_docker":
            logger.info("Starting Docker Desktop")
        elif name in {"desktop_started", "docker_started"}:
            logger.info("Docker Desktop started")
        elif name == "waiting_engine":
            logger.info("Waiting Docker Engine")
        elif name == "engine_ready":
            logger.info("Docker Engine ready")
        elif name in {"starting_container", "container_started"}:
            logger.info("Starting Open WebUI")
        elif name in {"started", "online"}:
            logger.info("Open WebUI started")
            app.after(0, open_webui)
        elif name == "engine_timeout":
            logger.error("Docker Engine timeout")
        elif name in {"docker_unavailable", "command_not_found", "docker_start_failed", "path_not_found", "container_not_found", "container_start_failed", "timeout"}:
            logger.error(f"Open WebUI start failed: {name}")

    service_manager.start_open_webui_docker_with_engine(
        container, url,
        docker_command=settings.get("services.docker.start_command", "docker desktop start"),
        docker_path=settings.get("services.docker.path", r"C:\Program Files\Docker\Docker\Docker Desktop.exe"),
        engine_timeout=settings.get("services.docker.startup_timeout", 60),
        callback=event
    )


def close_open_webui():
    """Stop the Open WebUI container and optionally Docker Desktop."""
    if settings.get("openwebui.type", "docker") != "docker":
        logger.info("Stopping Open WebUI")
        return
    logger.info("Stopping Open WebUI")

    def event(name):
        if name == "stopping_container":
            logger.info("Stopping Open WebUI container")
        elif name == "stopped":
            logger.info("Open WebUI stopped")
            if settings.get("openwebui.quit_docker_on_close", False):
                logger.info("Stopping Docker")
                service_manager.stop_docker_desktop(
                    settings.get("services.docker.stop_command", "docker desktop stop")
                )
        elif name in {"stop_failed", "docker_unavailable", "not_found"}:
            logger.error(f"Open WebUI stop failed: {name}")

    service_manager.stop_open_webui_docker(
        settings.get("openwebui.container_name", "open-webui"), callback=event
    )


def show_models_legacy():
    logger.info("Open model list")

    models = get_models()

    messagebox.showinfo(
        t("model_list_title"),
        models
    )


def show_models():
    global models_window

    logger.info("Open model list")

    if models_window is not None and models_window.winfo_exists():
        models_window.focus()
        models_window.lift()
        return

    def clear_models_window():
        global models_window
        models_window = None

    models_window = ModelsWindow(
        app,
        text=TEXT,
        translate=t,
        logger=logger,
        model_fetcher=get_model_records,
        settings_get=settings.get,
        on_close=clear_models_window
    )

def build_context_sections(memories=None, knowledge_items=None, persona=None, conversation_messages=None):
    memory_text = format_memory_context(memories)
    knowledge_text = format_knowledge_context(knowledge_items)
    persona_text = persona_store.build_context(persona) if persona else ""
    conversation_lines = []
    for message in conversation_messages or []:
        role = message.get("role", "")
        if role == "system":
            continue
        content = str(message.get("content", "")).strip()
        if content:
            conversation_lines.append(f"{role}: {content}")
    conversation_text = "\n\n".join(conversation_lines)
    return [
        {
            "name": "System Context",
            "enabled": True,
            "content": DEFAULT_SYSTEM_CONTEXT
        },
        {
            "name": "Persona",
            "enabled": bool(persona_text),
            "content": persona_text
        },
        {
            "name": "Memory",
            "enabled": bool(memory_text),
            "content": memory_text
        },
        {
            "name": "Knowledge",
            "enabled": bool(knowledge_text),
            "content": knowledge_text
        },
        {
            "name": "Conversation Context",
            "enabled": bool(conversation_text),
            "content": conversation_text
        }
    ]


def build_memory_context(memories=None, knowledge_items=None, persona=None):
    lines = []
    for section in build_context_sections(memories, knowledge_items, persona)[:4]:
        content = section.get("content", "")
        if content:
            lines.append(content)
    return "\n\n".join(lines)


def build_prompt_preview_text(prompt="", memories=None, knowledge_items=None, persona=None, conversation_messages=None):
    sections = build_context_sections(memories, knowledge_items, persona, conversation_messages)
    if prompt:
        sections.append({
            "name": "Current User Prompt",
            "enabled": True,
            "content": prompt
        })
    return build_final_prompt_preview(
        sections,
        warning_tokens=settings.get("context.warning_tokens", 6000),
        preview_limit=settings.get("context.preview_limit", 4000)
    )


def build_context_inspector_payload(prompt="", memories=None, knowledge_items=None, persona=None, conversation_messages=None, build_duration_ms=0):
    sections = build_context_sections(memories, knowledge_items, persona, conversation_messages)
    if prompt:
        sections.append({
            "name": "Current User Prompt",
            "enabled": True,
            "content": prompt
        })
    summary = summarize_context_sections(
        sections,
        warning_tokens=settings.get("context.warning_tokens", 6000)
    )
    return {
        "generated_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "build_duration_ms": int(build_duration_ms),
        "sections": sections,
        "summary": summary,
        "final_prompt": assemble_final_prompt(sections)
    }


def show_context_inspector(payload, parent_window=None):
    global context_inspector_window

    if context_inspector_window is not None and context_inspector_window.winfo_exists():
        context_inspector_window.destroy()

    context_inspector_window = ctk.CTkToplevel(parent_window or app)
    context_inspector_window.title("Context Inspector")
    context_inspector_window.geometry("980x760")
    context_inspector_window.minsize(760, 560)
    context_inspector_window.transient(parent_window or app)
    logger.info("Context inspector opened")

    summary = payload.get("summary", {})
    sections = summary.get("sections", [])

    header = ctk.CTkFrame(context_inspector_window, fg_color="transparent")
    header.pack(fill="x", padx=25, pady=(20, 10))
    ctk.CTkLabel(
        header,
        text="Final Chat Context",
        font=("Microsoft YaHei", 22, "bold")
    ).pack(anchor="w")
    ctk.CTkLabel(
        header,
        text=(
            f"Generated: {payload.get('generated_time', '')} | "
            f"Build Time: {payload.get('build_duration_ms', 0)}ms | "
            f"Total: {summary.get('total_characters', 0)} chars | "
            f"Tokens: {summary.get('total_tokens', 0)}"
        ),
        font=("Microsoft YaHei", 12),
        text_color="gray"
    ).pack(anchor="w", pady=(4, 0))

    status_frame = ctk.CTkFrame(context_inspector_window)
    status_frame.pack(fill="x", padx=25, pady=(0, 10))
    status_line = "    ".join(
        f"{item.get('name', 'Context')} {'ON' if item.get('enabled') else 'OFF'}"
        for item in sections
    )
    ctk.CTkLabel(
        status_frame,
        text=status_line,
        font=("Microsoft YaHei", 12),
        anchor="w"
    ).pack(fill="x", padx=12, pady=10)

    if summary.get("warning"):
        warning_frame = ctk.CTkFrame(context_inspector_window, fg_color="#3A2A1A")
        warning_frame.pack(fill="x", padx=25, pady=(0, 10))
        ctk.CTkLabel(
            warning_frame,
            text="Context size warning.\n" + "\n".join(summary.get("warning_reasons", [])),
            font=("Microsoft YaHei", 12),
            text_color="#FFD27F",
            anchor="w",
            justify="left"
        ).pack(fill="x", padx=12, pady=10)
        logger.info("Context size warning")

    content_frame = ctk.CTkScrollableFrame(context_inspector_window)
    content_frame.pack(fill="both", expand=True, padx=25, pady=(0, 12))

    try:
        preview_limit = max(500, int(settings.get("context.inspector_preview_limit", settings.get("context.preview_limit", 4000))))
    except (TypeError, ValueError):
        preview_limit = 4000

    collapsed = {}

    def add_section(record):
        name = record.get("name", "Context")
        collapsed[name] = False
        outer = ctk.CTkFrame(content_frame)
        outer.pack(fill="x", padx=8, pady=8)

        body = ctk.CTkFrame(outer, fg_color="transparent")

        def toggle():
            collapsed[name] = not collapsed[name]
            marker = "\u25b6" if collapsed[name] else "\u25bc"
            title_button.configure(text=f"{marker} {name}")
            if collapsed[name]:
                body.pack_forget()
            else:
                body.pack(fill="x", padx=12, pady=(0, 12))

        title_button = ui_button(
            outer,
            text=f"\u25bc {name}",
            anchor="w",
            command=toggle
        )
        title_button.pack(fill="x", padx=10, pady=(10, 6))

        meta = (
            f"{t('status')}: {t('enabled') if record.get('enabled') else t('disabled')}\n"
            f"{t('characters')}: {record.get('characters', 0)}\n"
            f"{t('tokens')}: {record.get('tokens', 0)}"
        )
        ctk.CTkLabel(
            body,
            text=meta,
            font=FONT_SMALL,
            text_color=COLOR_MUTED,
            anchor="w",
            justify="left"
        ).pack(anchor="w", pady=(0, 6))

        content = str(record.get("content", "") or "")
        if len(content) > preview_limit:
            content = content[:preview_limit] + f"\n\n[{t('context_preview_truncated')}]"
        if not content.strip():
            content = f"[{t('no_content')}]"
        text_box = ctk.CTkTextbox(body, height=150, wrap="word")
        text_box.pack(fill="x")
        text_box.insert("1.0", content)
        text_box.configure(state="disabled")
        body.pack(fill="x", padx=12, pady=(0, 12))

    for section in sections:
        add_section(section)

    bottom = ctk.CTkFrame(context_inspector_window, fg_color="transparent")
    bottom.pack(fill="x", padx=25, pady=(0, 20))

    status_label = ctk.CTkLabel(bottom, text="", font=FONT_SMALL, text_color=COLOR_MUTED)
    status_label.pack(side="left", padx=(0, 10))

    def copy_final_prompt():
        try:
            context_inspector_window.clipboard_clear()
            context_inspector_window.clipboard_append(payload.get("final_prompt", ""))
            status_label.configure(text=t("final_prompt_copied"), text_color=COLOR_SUCCESS)
            logger.info("Final prompt copied")
        except Exception as error:
            status_label.configure(text=t("copy_failed"), text_color=COLOR_ERROR)
            logger.error(f"Final prompt copy failed: {error}")

    def close_context_inspector():
        global context_inspector_window
        context_inspector_window.destroy()
        context_inspector_window = None

    ui_button(bottom, text=t("copy_final_prompt"), command=copy_final_prompt).pack(side="right", padx=(6, 0))
    ui_button(bottom, text=t("close"), command=close_context_inspector).pack(side="right", padx=6)
    context_inspector_window.protocol("WM_DELETE_WINDOW", close_context_inspector)


def show_chat():
    global active_conversation_id, chat_load_conversation_callback, chat_window, pending_conversation_id

    if chat_window is not None and chat_window.winfo_exists():
        chat_window.focus()
        chat_window.lift()
        return

    logger.info("Chat started")

    def initial_chat_context():
        initial_persona = persona_store.load() if settings.get("persona.enabled", True) else None
        if initial_persona:
            logger.info("Persona loaded")
            logger.info("Persona loaded timestamp updated")
        else:
            logger.info("Persona disabled")
        return build_memory_context(persona=initial_persona)

    def prepare_chat_prompt_context(prompt, conversation_messages, debug_enabled=False):
        logger.info("Memory retrieval started")
        try:
            max_injection = max(1, int(settings.get("memory.max_injection", 5)))
            min_importance = max(0, float(settings.get("memory.min_importance", 0)))
        except (TypeError, ValueError):
            max_injection, min_importance = 5, 0
        matched_memories = retrieve_memories(
            prompt,
            memory_store.list_memories(),
            max_results=max_injection,
            min_importance=min_importance
        )
        logger.info(f"Memory matched: {len(matched_memories)}")

        matched_knowledge = []
        active_persona = None
        if settings.get("persona.enabled", True):
            active_persona = persona_store.load()
            logger.info("Persona enabled")
            logger.info("Persona loaded timestamp updated")
        else:
            logger.info("Persona disabled")

        if settings.get("knowledge.enabled", True):
            logger.info("Knowledge search started")
            try:
                max_knowledge = max(0, int(settings.get("knowledge.max_results", 3)))
            except (TypeError, ValueError):
                max_knowledge = 3
            knowledge_items = knowledge_store.list_items()
            matched_knowledge = knowledge_store.retrieve(prompt, max_results=max_knowledge)
            disabled_matches = retrieval_summary(
                prompt,
                knowledge_items,
                max_results=max_knowledge,
                knowledge_enabled=settings.get("knowledge.enabled", True)
            ).get("results", [])
            if any((not item.get("enabled")) and (not item.get("injected")) for item in disabled_matches):
                logger.info("Knowledge skipped disabled file")
            if any(item.get("status") == "Missing File" for item in disabled_matches):
                logger.info("Knowledge skipped missing file")
            if any(item.get("status") not in {"OK", "Missing File"} for item in disabled_matches):
                logger.info("Knowledge skipped invalid file")
            logger.info(f"Knowledge matched: {len(matched_knowledge)}")

        if matched_memories:
            logger.info("Memory injected")
        if matched_knowledge:
            logger.info("Knowledge injected")

        debug_text = ""
        if debug_enabled:
            debug_text, warning, _tokens = build_context_debug_report(
                build_context_sections(matched_memories, matched_knowledge, active_persona, conversation_messages),
                warning_tokens=settings.get("context.warning_tokens", 6000)
            )
            if warning:
                logger.info("Context size warning")

        return {
            "system_context": build_memory_context(matched_memories, matched_knowledge, active_persona),
            "debug_text": debug_text
        }

    def build_chat_context_preview(prompt, conversation_messages):
        started_at = time.perf_counter()
        try:
            max_injection = max(1, int(settings.get("memory.max_injection", 5)))
            min_importance = max(0, float(settings.get("memory.min_importance", 0)))
        except (TypeError, ValueError):
            max_injection, min_importance = 5, 0
        memories = retrieve_memories(
            prompt,
            memory_store.list_memories(),
            max_results=max_injection,
            min_importance=min_importance
        ) if prompt else []
        active_persona = persona_store.load() if settings.get("persona.enabled", True) else None
        if active_persona:
            logger.info("Persona loaded timestamp updated")
        knowledge_items = []
        if prompt and settings.get("knowledge.enabled", True):
            try:
                max_knowledge = max(0, int(settings.get("knowledge.max_results", 3)))
            except (TypeError, ValueError):
                max_knowledge = 3
            knowledge_items = knowledge_store.retrieve(prompt, max_results=max_knowledge)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return build_context_inspector_payload(
            prompt,
            memories,
            knowledge_items,
            active_persona,
            conversation_messages,
            build_duration_ms=duration_ms
        )

    def set_active_conversation(value):
        global active_conversation_id
        active_conversation_id = value

    def register_chat_load_callback(callback):
        global chat_load_conversation_callback
        chat_load_conversation_callback = callback

    def clear_chat_window():
        global chat_window
        chat_window = None

    chat_window = ChatWindow(
        app,
        text=TEXT,
        translate=t,
        logger=logger,
        settings=settings,
        conversation_manager=ConversationManager(),
        initial_context_provider=initial_chat_context,
        model_records_provider=get_model_records,
        model_capability_provider=infer_model_capability,
        prepare_prompt_context_callback=prepare_chat_prompt_context,
        stream_chat_callback=stream_chat,
        context_preview_builder=build_chat_context_preview,
        context_preview_callback=show_context_inspector,
        get_active_conversation_id=lambda: active_conversation_id,
        set_active_conversation_id=set_active_conversation,
        register_load_callback=register_chat_load_callback,
        on_close=clear_chat_window
    )

    if pending_conversation_id:
        pending_id = pending_conversation_id
        pending_conversation_id = None
        chat_window.after(0, lambda: chat_window.load_conversation_by_id(pending_id))

def show_conversation_browser():
    global conversation_browser_window, pending_conversation_id, active_conversation_id
    if conversation_browser_window is not None and conversation_browser_window.winfo_exists():
        conversation_browser_window.focus()
        conversation_browser_window.lift()
        return

    def clear_conversation_browser_window():
        global conversation_browser_window
        conversation_browser_window = None

    def clear_active_conversation():
        global active_conversation_id
        active_conversation_id = None

    def continue_browser_conversation(conversation_id):
        global pending_conversation_id
        if callable(chat_load_conversation_callback):
            chat_load_conversation_callback(conversation_id)
        else:
            pending_conversation_id = conversation_id
            show_chat()
        if chat_window is not None and chat_window.winfo_exists():
            chat_window.focus()
            chat_window.lift()

    conversation_browser_window = ConversationBrowserWindow(
        app,
        conversation_manager=ConversationManager(),
        text=TEXT,
        translate=t,
        logger=logger,
        get_active_conversation_id=lambda: active_conversation_id,
        clear_active_conversation_id=clear_active_conversation,
        continue_conversation_callback=continue_browser_conversation,
        on_close=clear_conversation_browser_window
    )

def show_memory():
    global memory_window
    if memory_window is not None and memory_window.winfo_exists():
        memory_window.focus()
        memory_window.lift()
        return

    logger.info("Memory window opened")

    def clear_memory_window():
        global memory_window
        memory_window = None

    memory_window = MemoryWindow(
        app,
        memory_store=memory_store,
        search_memories=search_memories,
        text=TEXT,
        translate=t,
        logger=logger,
        on_close=clear_memory_window
    )

def show_knowledge():
    global knowledge_window
    if knowledge_window is not None and knowledge_window.winfo_exists():
        knowledge_window.focus()
        knowledge_window.lift()
        return

    logger.info("Knowledge loaded")

    def clear_knowledge_window():
        global knowledge_window
        knowledge_window = None

    knowledge_window = KnowledgeWindow(
        app,
        knowledge_store=knowledge_store,
        settings=settings,
        text=TEXT,
        translate=t,
        logger=logger,
        version=VERSION,
        retrieval_summary=retrieval_summary,
        on_close=clear_knowledge_window
    )

def build_persona_final_prompt_preview(prompt, persona_data):
    try:
        max_injection = max(1, int(settings.get("memory.max_injection", 5)))
        min_importance = max(0, float(settings.get("memory.min_importance", 0)))
    except (TypeError, ValueError):
        max_injection, min_importance = 5, 0
    memories = retrieve_memories(
        prompt,
        memory_store.list_memories(),
        max_results=max_injection,
        min_importance=min_importance
    ) if prompt else []
    knowledge_items = []
    if prompt and settings.get("knowledge.enabled", True):
        try:
            max_knowledge = max(0, int(settings.get("knowledge.max_results", 3)))
        except (TypeError, ValueError):
            max_knowledge = 3
        knowledge_items = knowledge_store.retrieve(prompt, max_results=max_knowledge)
    active_persona = persona_data if settings.get("persona.enabled", True) else None
    text, warning, _total_tokens = build_prompt_preview_text(
        prompt,
        memories,
        knowledge_items,
        active_persona,
        []
    )
    return text, warning


def show_persona():
    global persona_window
    if persona_window is not None and persona_window.winfo_exists():
        persona_window.focus()
        persona_window.lift()
        return

    logger.info("Persona loaded")
    logger.info("Persona loaded timestamp updated")

    def clear_persona_window():
        global persona_window
        persona_window = None

    persona_window = PersonaWindow(
        app,
        persona_store=persona_store,
        settings=settings,
        text=TEXT,
        translate=t,
        logger=logger,
        final_prompt_preview_callback=build_persona_final_prompt_preview,
        on_close=clear_persona_window
    )

def show_remote_access():
    global remote_window
    if remote_window is not None and remote_window.winfo_exists():
        remote_window.focus()
        remote_window.lift()
        return

    def lan_status_snapshot():
        try:
            service_status = check_all()
        except Exception:
            service_status = {"ollama": False, "webui": False, "api": False}
        return {
            "status": "Online",
            "version": RELEASE,
            "ollama": "Ready" if service_status.get("ollama") or service_status.get("api") else "Offline",
            "openwebui": "Ready" if service_status.get("webui") else "Offline",
            "memory": "Available" if (Path(__file__).resolve().parent / "data" / "memory").exists() else "Offline",
            "knowledge": "Available" if (Path(__file__).resolve().parent / "data" / "knowledge").exists() else "Offline",
            "persona": "Enabled" if settings.get("persona.enabled", True) else "Disabled",
            "remote_security": "Protected"
        }

    def clear_remote_window():
        global remote_window
        remote_window = None

    remote_window = RemoteWindow(
        app,
        remote_manager=remote_manager,
        authentication_manager=authentication_manager,
        credential_storage_provider=credential_storage_provider,
        settings=settings,
        lan_status_server=lan_status_server,
        lan_status_snapshot=lan_status_snapshot,
        mobile_chat_service=mobile_chat_service,
        text=TEXT,
        logger=logger,
        default_lan_status_port=DEFAULT_LAN_STATUS_PORT,
        on_close=clear_remote_window
    )


def show_remote_diagnostics():
    global remote_diagnostics_window
    if remote_diagnostics_window is not None and remote_diagnostics_window.winfo_exists():
        remote_diagnostics_window.focus()
        remote_diagnostics_window.lift()
        return

    logger.info("Remote diagnostics opened")

    def clear_remote_diagnostics_window():
        global remote_diagnostics_window
        remote_diagnostics_window = None

    remote_diagnostics_window = RemoteDiagnosticsWindow(
        app,
        remote_manager=remote_manager,
        credential_storage_provider=credential_storage_provider,
        text=TEXT,
        logger=logger,
        project_root=Path(__file__).resolve().parent,
        on_close=clear_remote_diagnostics_window
    )

def test_settings_service_connection(target_window, service_name, url, callback):
    def run_check():
        started_at = time.perf_counter()
        connected = False
        reason = ""

        try:
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                reason = "Invalid URL"
            else:
                with urllib.request.urlopen(url, timeout=3):
                    connected = True
        except urllib.error.HTTPError:
            connected = True
        except (socket.timeout, TimeoutError):
            reason = t("timeout")
        except ConnectionRefusedError:
            reason = t("connection_refused")
        except urllib.error.URLError as error:
            if isinstance(error.reason, socket.timeout):
                reason = t("timeout")
            elif isinstance(error.reason, ConnectionRefusedError):
                reason = t("connection_refused")
            else:
                reason = t("connection_error")
        except (OSError, ValueError):
            reason = t("connection_error")

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        if connected:
            logger.info(f"{service_name} connected ({elapsed_ms}ms)")
        else:
            logger.info(f"{service_name} connection failed: {reason}")

        def update_result():
            try:
                if target_window is None or not target_window.winfo_exists():
                    return
                callback(connected, elapsed_ms, reason)
            except Exception:
                return

        try:
            target_window.after(0, update_result)
        except Exception:
            return

    logger.info(f"Testing {service_name} connection...")
    threading.Thread(target=run_check, daemon=True).start()


actions_frame = ctk.CTkScrollableFrame(legacy_dashboard_frame, height=250)
actions_frame.pack(fill="x", padx=20, pady=(0, 8))


action_title = ctk.CTkLabel(
    actions_frame,
    text=t("quick_actions"),
    font=FONT_HEADER
)
action_title.pack(anchor="w", padx=15, pady=(5, 10))


btn1 = ui_button(
    actions_frame,
    text=t("open_webui"),
    command=launch_open_webui,
    kind="primary"
)
btn1.pack(fill="x", padx=40, pady=8)


btn_diagnostic = ui_button(
    actions_frame,
    text=t("runtime_environment_diagnostics"),
    command=run_diagnostic
)
btn_diagnostic.pack(fill="x", padx=40, pady=8)


btn_start_ollama = ui_button(
    actions_frame,
    text=t("start_ollama"),
    command=start_ollama_manual,
    kind="primary"
)
btn_start_ollama.pack(fill="x", padx=40, pady=8)


btn_restart_webui = ui_button(
    actions_frame,
    text=t("restart_openwebui"),
    command=restart_openwebui_manual
)
btn_restart_webui.pack(fill="x", padx=40, pady=8)


btn_restart_container = ui_button(
    actions_frame,
    text=t("restart_container"),
    command=restart_container_manual
)
btn_restart_container.pack(fill="x", padx=40, pady=8)


btn_close_webui = ui_button(
    actions_frame,
    text=t("close_openwebui"),
    command=close_open_webui,
    kind="danger"
)
btn_close_webui.pack(fill="x", padx=40, pady=8)


btn2 = ui_button(
    actions_frame,
    text=t("models"),
    command=show_models
)
btn2.pack(fill="x", padx=40, pady=8)


btn_chat = ui_button(
    actions_frame,
    text=t("chat"),
    command=show_chat,
    kind="primary"
)
btn_chat.pack(fill="x", padx=40, pady=8)


btn_conversation_browser = ui_button(
    actions_frame,
    text=t("conversation_browser"),
    command=show_conversation_browser
)
btn_conversation_browser.pack(fill="x", padx=40, pady=8)


btn_memory = ui_button(
    actions_frame,
    text=t("memory"),
    command=show_memory
)
btn_memory.pack(fill="x", padx=40, pady=8)


btn_persona = ui_button(
    actions_frame,
    text=t("persona"),
    command=show_persona
)
btn_persona.pack(fill="x", padx=40, pady=8)


btn_knowledge = ui_button(
    actions_frame,
    text=t("knowledge_base"),
    command=show_knowledge
)
btn_knowledge.pack(fill="x", padx=40, pady=8)


btn_remote = ui_button(
    actions_frame,
    text=t("remote_access"),
    command=show_remote_access
)
btn_remote.pack(fill="x", padx=40, pady=8)


btn_remote_diagnostics = ui_button(
    actions_frame,
    text=t("remote_diagnostics"),
    command=show_remote_diagnostics
)
btn_remote_diagnostics.pack(fill="x", padx=40, pady=8)


def show_settings():
    global settings_window

    if settings_window is not None and settings_window.winfo_exists():
        settings_window.focus()
        settings_window.lift()
        return

    logger.info("Open Settings")

    def clear_settings_window():
        global settings_window
        settings_window = None

    settings_window = SettingsWindow(
        app,
        settings=settings,
        controller=settings_controller,
        text=TEXT,
        translate=t,
        language_display=language_display,
        language_code=language_code,
        apply_language=apply_language,
        refresh_main_texts=refresh_main_texts,
        logger=logger,
        persona_status_provider=lambda: persona_store.status(
            settings.get("persona.enabled", True),
            persona_store.load(update_timestamp=False)
        ),
        health_report_provider=lambda: system_self_check(timeout=2),
        service_test_callback=lambda service_name, url, callback: test_settings_service_connection(
            settings_window,
            service_name,
            url,
            callback
        ),
        model_capability_provider=infer_model_capability,
        on_close=clear_settings_window
    )


settings_button = ui_button(
    actions_frame,
    text=t("settings"),
    command=show_settings
)
settings_button.pack(fill="x", padx=40, pady=8)


def refresh_main_texts():
    status_title.configure(text=t("system_status"))
    startup_title.configure(text=t("startup_status"))
    action_title.configure(text=t("quick_actions"))
    btn1.configure(text=t("open_webui"))
    btn_diagnostic.configure(text=t("runtime_environment_diagnostics"))
    btn_start_ollama.configure(text=t("start_ollama"))
    btn_restart_webui.configure(text=t("restart_openwebui"))
    btn_restart_container.configure(text=t("restart_container"))
    btn_close_webui.configure(text=t("close_openwebui"))
    btn2.configure(text=t("models"))
    btn_chat.configure(text=t("chat"))
    btn_conversation_browser.configure(text=t("conversation_browser"))
    btn_memory.configure(text=t("memory"))
    btn_persona.configure(text=t("persona"))
    btn_knowledge.configure(text=t("knowledge_base"))
    btn_remote.configure(text=t("remote_access"))
    btn_remote_diagnostics.configure(text=t("remote_diagnostics"))
    settings_button.configure(text=t("settings"))


def health_check_legacy():
    logger.info("Health check")

    status = check_all()

    result = []

    for name, ok in status.items():
        if ok:
            result.append(f"OK {name}")
        else:
            result.append(f"Offline {name}")

    messagebox.showinfo(
        "Health Check",
        "\n".join(result)
    )


def health_check():
    global health_window

    if health_window is not None and health_window.winfo_exists():
        health_window.focus()
        health_window.lift()
        return

    logger.info("Open Health Dashboard")

    def clear_health_window():
        global health_window
        health_window = None

    health_window = HealthWindow(
        app,
        text=TEXT,
        translate=t,
        logger=logger,
        system_self_check=system_self_check,
        on_close=clear_health_window
    )

def show_about():
    messagebox.showinfo(
        t("about_title"),
        f"{APP_NAME}\n\n"
        f"Version: v{VERSION}\n"
        f"Build: {BUILD}\n\n"
        f"{t('a_personal_local_ai_assistant')}\n\n"
        f"{t('core_features')}:\n"
        f"- Local AI Chat\n"
        f"- Memory System\n"
        f"- Knowledge Base\n"
        f"- Persona System\n"
        f"- Context Inspector\n"
        f"- Remote Security Framework\n"
        f"- LAN Status Page"
    )


def shutdown_app():
    if lan_status_server.is_running():
        result = lan_status_server.stop()
        if result.get("released"):
            logger.info("LAN server port released")
        logger.info("LAN status page stopped")
        logger.info("Mobile chat stopped")
    app.destroy()


btn3 = ui_button(
    actions_frame,
    text=t("health"),
    command=health_check
)
btn3.pack(fill="x", padx=40, pady=8)


btn4 = ui_button(
    actions_frame,
    text=t("about"),
    command=show_about
)
btn4.pack(fill="x", padx=40, pady=8)


btn5 = ui_button(
    actions_frame,
    text=t("exit"),
    command=shutdown_app,
    kind="danger"
)
btn5.pack(fill="x", padx=40, pady=8)


recent_log_title = ctk.CTkLabel(
    legacy_dashboard_frame,
    text=t("recent_log"),
    font=FONT_HEADER
)
recent_log_title.pack(anchor="w", padx=35, pady=(5, 10))

recent_log_box = ctk.CTkTextbox(
    legacy_dashboard_frame,
    height=130,
    wrap="none"
)
recent_log_box.pack(fill="both", expand=True, padx=40, pady=(0, 20))
recent_log_box.configure(state="disabled")


def refresh_recent_logs():

    recent_log_box.configure(state="normal")
    recent_log_box.delete("1.0", "end")
    recent_log_box.insert(
        "1.0",
        logger.get_recent_logs_text() or t("no_logs")
    )
    recent_log_box.configure(state="disabled")

    app.after(1000, refresh_recent_logs)


status_check_running = False


def refresh_status():
    global status_check_running
    if status_check_running:
        return
    status_check_running = True

    def run_check():
        try:
            result = check_all()
            result["docker"] = service_manager.docker_engine_ready()
            result["docker_desktop"] = service_manager.docker_desktop_running()
            ollama_diag = service_manager.diagnose_ollama(
                settings.get("ollama.host", "http://127.0.0.1:11434")
            )
            webui_diag = service_manager.diagnose_openwebui(
                settings.get("openwebui.container_name", "open-webui"),
                settings.get("openwebui.host", "http://localhost:8080")
            )
            result["ollama"] = ollama_diag["available"]
            result["webui"] = webui_diag["available"]
        except Exception as error:
            logger.error(f"Status check failed: {error}")
            result = {"ollama": False, "webui": False, "api": False, "docker": False, "docker_desktop": False}

        def finish_check():
            global status_check_running
            status_check_running = False
            apply_status(result)

        app.after(0, finish_check)

    threading.Thread(target=run_check, daemon=True).start()


def apply_status(status):

    mapping = {
        "Ollama": status["ollama"],
        "Open WebUI": status["webui"],
        "API 11434": status["api"]
    }

    endpoints = {
        "Ollama": ServiceManager.endpoint(settings.get("ollama.host", "http://127.0.0.1:11434")),
        "Open WebUI": ServiceManager.endpoint(settings.get("openwebui.host", "http://localhost:8080")),
        "API 11434": ServiceManager.endpoint(settings.get("ollama.host", "http://127.0.0.1:11434"), default_port=11434)
    }

    for name, online in mapping.items():

        label, state = status_labels[name]
        host, port = endpoints[name]
        display_name = f"{name} ({host}:{port})"

        if online:
            label.configure(text=f"[{t('status_ok_short')}] {name}")
            state.configure(
                text=t("online"),
                text_color=COLOR_SUCCESS
            )
        else:
            label.configure(text=f"[{t('status_off_short')}] {name}")
            state.configure(
                text=t("offline"),
                text_color=COLOR_ERROR
            )
        status_prefix = t("status_ok_short") if online else t("status_off_short")
        label.configure(text=f"[{status_prefix}] {display_name}")

    online_count = sum(mapping.values())
    if online_count == len(mapping):
        status_summary_label.configure(
            text=t("all_ready"),
            text_color=COLOR_SUCCESS
        )
    else:
        status_summary_label.configure(
            text=f"{online_count} / {len(mapping)} services online",
            text_color=COLOR_WARNING
        )

    dashboard_last_check_label.configure(
        text=(
            f"{t('last_check')}: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ),
        text_color=COLOR_MUTED
    )

    docker_ready = bool(status.get("docker", False))
    docker_desktop = bool(status.get("docker_desktop", docker_ready))
    if "Docker Desktop" in docker_status_labels:
        docker_status_labels["Docker Desktop"].configure(
            text=t("online") if docker_desktop else t("offline"),
            text_color=COLOR_SUCCESS if docker_desktop else COLOR_ERROR
        )
        docker_status_labels["Docker Engine"].configure(
            text=t("ready") if docker_ready else t("not_ready"),
            text_color=COLOR_SUCCESS if docker_ready else COLOR_ERROR
        )

    try:
        refresh_interval = float(
            settings.get("status.refresh_interval", 3)
        )
        refresh_interval = max(refresh_interval, 0.1)
    except (TypeError, ValueError):
        refresh_interval = 3

    app.after(int(refresh_interval * 1000), refresh_status)


def startup_check():
    startup_started = time.perf_counter()
    logger.info("Startup Check started")
    logger.info("Project Aurora Startup Check")
    project_root = Path(__file__).resolve().parent
    required_paths = [
        project_root / "main.py",
        project_root / "modules" / "version.py",
        project_root / "modules" / "settings.py",
        project_root / "modules" / "knowledge.py",
        project_root / "modules" / "retrieval.py",
        project_root / "modules" / "persona.py",
        project_root / "config" / "settings.json"
    ]
    missing = [str(path.name) for path in required_paths if not path.exists()]
    if missing:
        logger.warning(f"Startup files missing: {', '.join(missing)}")
    else:
        logger.info("Required files available")
    logger.info("Configuration file available" if configuration_file.exists() else "Configuration file missing")
    logger.info("Version loaded")
    logger.info("Configuration loaded")
    logger.info("Logger initialized")
    logger.info("Required modules loaded")

    def check_services():
        service_started = time.perf_counter()
        try:
            status = check_all()
        except Exception as error:
            logger.error(f"Startup service check failed: {error}")
            logger.info(
                f"Service check duration: {int((time.perf_counter() - service_started) * 1000)}ms"
            )
            logger.info(
                f"Startup Check finished: {int((time.perf_counter() - startup_started) * 1000)}ms"
            )
            return

        ollama_connected = status.get("ollama", False) or status.get("api", False)
        if ollama_connected:
            logger.info("Ollama connected")
        else:
            logger.info("Ollama unavailable")
            if settings.get("ollama.auto_start", False):
                def ollama_event(event):
                    if event == "starting":
                        logger.info("Starting Ollama")
                    elif event == "started":
                        logger.info("Ollama started")
                        app.after(0, refresh_status)
                    elif event == "command_not_found":
                        logger.error("Ollama start failed: command not found")
                    elif event == "failed":
                        logger.error("Ollama start failed")

                service_manager.start_ollama(
                    settings.get("services.ollama.command", "ollama serve"),
                    settings.get("ollama.host", "http://127.0.0.1:11434"),
                    callback=ollama_event
                )

        if status.get("webui", False):
            logger.info("Open WebUI connected")
        else:
            logger.info("Open WebUI unavailable")
            if settings.get("openwebui.auto_start", False):
                def service_event(event):
                    if event == "starting":
                        logger.info("Starting Open WebUI")
                    elif event == "starting_container":
                        logger.info("Starting Open WebUI container")
                    elif event == "started":
                        logger.info("Open WebUI started")
                        app.after(0, refresh_status)
                    elif event == "container_started":
                        logger.info("Open WebUI container started")
                    elif event == "docker_unavailable":
                        logger.error("Open WebUI start failed: Docker Desktop unavailable")
                    elif event == "container_not_found":
                        logger.error("Open WebUI start failed: container not found")
                    elif event == "container_start_failed":
                        logger.error("Docker container start failed")
                    elif event == "timeout":
                        logger.error("Open WebUI start failed: port timeout")
                    elif event == "command_not_found":
                        logger.error("Open WebUI start failed: command not found")
                    elif event == "failed":
                        logger.error("Open WebUI start failed")

                if settings.get("openwebui.type", "docker") == "docker" and settings.get("services.docker.auto_start", True):
                    def docker_event(event):
                        if event == "starting_docker":
                            logger.info("Starting Docker Desktop")
                        elif event == "desktop_started":
                            logger.info("Docker Desktop started")
                        elif event == "waiting_engine":
                            logger.info("Waiting Docker Engine")
                        elif event == "engine_ready":
                            logger.info("Docker Engine ready")
                        elif event == "engine_timeout":
                            logger.error("Docker Engine timeout")
                        service_event(event)

                    service_manager.start_open_webui_docker_with_engine(
                        settings.get("openwebui.container_name", "open-webui"),
                        settings.get("openwebui.host", "http://localhost:8080"),
                        docker_command=settings.get("services.docker.start_command", "docker desktop start"),
                        docker_path=settings.get("services.docker.path", r"C:\Program Files\Docker\Docker\Docker Desktop.exe"),
                        engine_timeout=settings.get("services.docker.startup_timeout", 60),
                        callback=docker_event
                    )
                elif settings.get("openwebui.type", "docker") == "docker":
                    logger.info("Docker skipped (Open WebUI disabled)")
                else:
                    service_manager.start_open_webui(
                        settings.get("services.openwebui.command", "open-webui serve"),
                        settings.get("openwebui.host", "http://localhost:8080"),
                        callback=service_event
                    )
            else:
                logger.info("Docker skipped (Open WebUI disabled)")
        try:
            credential_status = credential_storage_provider.check_available()
            remote_manager.update_credential_diagnostics(credential_status)
            remote_manager.record_diagnostic_history()
            logger.info("Startup Diagnostic:")
            logger.info(f"Ollama: {'Ready' if ollama_connected else 'Offline'}")
            logger.info(f"Open WebUI: {'Ready' if status.get('webui', False) else 'Offline'}")
            logger.info(f"Remote: {'Enabled' if settings.get('remote.enabled', False) else 'Disabled'}")
            logger.info(f"Credential Storage: {'Available' if credential_status.get('available') else 'Unavailable'}")
            logger.info("Startup diagnostic completed")
        except Exception as error:
            logger.error(f"Startup diagnostic failed: {error}")
        logger.info(
            f"Service check duration: {int((time.perf_counter() - service_started) * 1000)}ms"
        )
        logger.info(
            f"Startup Check finished: {int((time.perf_counter() - startup_started) * 1000)}ms"
        )

    threading.Thread(target=check_services, daemon=True).start()


def navigate_app_shell(page_name):
    if app_shell is not None:
        app_shell.navigate(page_name)


def app_shell_home_status_provider():
    memory_count = 0
    knowledge_count = 0
    persona_name = "--"
    try:
        memory_count = len(memory_store.list_memories())
    except Exception as error:
        logger.error(f"AppShell memory status failed: {error}")
    try:
        knowledge_health = knowledge_store.health()
        knowledge_count = knowledge_health.get("total", 0)
    except Exception as error:
        logger.error(f"AppShell knowledge status failed: {error}")
    try:
        persona_status = persona_store.status(
            settings.get("persona.enabled", True),
            persona_store.load(update_timestamp=False)
        )
        persona_name = persona_status.get("name", "--")
    except Exception as error:
        logger.error(f"AppShell persona status failed: {error}")

    remote_enabled = settings.get("remote.enabled", False)
    chat_model = settings.get("chat_model", "")
    return {
        "overall": "healthy",
        "summary": t("app_shell_ready"),
        "ai_runtime": {
            "status": "healthy" if chat_model else "warning",
            "text": t("ready") if chat_model else t("missing"),
            "detail": chat_model or "--"
        },
        "memory": {
            "status": "healthy",
            "text": t("ready"),
            "detail": f"{t('memory_count')}: {memory_count}"
        },
        "knowledge": {
            "status": "healthy",
            "text": t("ready"),
            "detail": f"{t('knowledge_documents')}: {knowledge_count}"
        },
        "persona": {
            "status": "enabled" if settings.get("persona.enabled", True) else "disabled",
            "text": t("enabled") if settings.get("persona.enabled", True) else t("disabled"),
            "detail": persona_name
        },
        "remote": {
            "status": "enabled" if remote_enabled else "disabled",
            "text": t("enabled") if remote_enabled else t("disabled"),
            "detail": t("remote")
        }
    }


def app_shell_library_status_provider():
    try:
        health = knowledge_store.health()
        vector_health = health.get("vector_index", {})
        index_exists = bool(vector_health.get("exists"))
        return {
            "status": "healthy" if settings.get("knowledge.enabled", True) else "disabled",
            "text": t("enabled") if settings.get("knowledge.enabled", True) else t("disabled"),
            "documents": health.get("total", 0),
            "retrieval": t("ready") if settings.get("knowledge.enabled", True) else t("disabled"),
            "retrieval_state": "healthy" if settings.get("knowledge.enabled", True) else "disabled",
            "index": t("available") if index_exists else t("missing"),
            "index_state": "healthy" if index_exists else "warning"
        }
    except Exception as error:
        logger.error(f"AppShell library status failed: {error}")
        return {"status": "error", "text": str(error)}


def app_shell_memory_status_provider():
    try:
        memories = memory_store.list_memories()
        return {
            "status": "healthy",
            "text": t("available"),
            "total": len(memories),
            "recent": min(len(memories), 5)
        }
    except Exception as error:
        logger.error(f"AppShell memory status failed: {error}")
        return {"status": "error", "text": str(error)}


def app_shell_persona_status_provider():
    try:
        persona = persona_store.load(update_timestamp=False)
        status = persona_store.status(settings.get("persona.enabled", True), persona)
        status.update({
            "description": persona.get("description", ""),
            "style": persona.get("style", "")
        })
        return status
    except Exception as error:
        logger.error(f"AppShell persona status failed: {error}")
        return {"status": "error", "text": str(error)}


def app_shell_remote_status_provider():
    remote_enabled = settings.get("remote.enabled", False)
    auth_configured = settings.get("remote.authentication_configured", False)
    security_confirmed = settings.get("remote.security_confirmed", False)
    return {
        "status": "enabled" if remote_enabled else "disabled",
        "text": t("enabled") if remote_enabled else t("disabled"),
        "remote": t("enabled") if remote_enabled else t("disabled"),
        "authentication": t("configured") if auth_configured else t("not_configured"),
        "safety": t("confirmed") if security_confirmed else t("not_confirmed"),
        "devices": t("not_available_this_version"),
        "security_policy": t("configured"),
        "access_control": t("configured")
    }


def app_shell_settings_status_provider():
    return {
        "status": "healthy",
        "text": t("settings_page_reuse_note")
    }


def app_shell_conversation_provider():
    try:
        return ConversationManager().list_conversations()
    except Exception as error:
        logger.error(f"AppShell conversation list failed: {error}")
        return []


def create_app_shell():
    global app_shell
    if app_shell is not None:
        return app_shell

    page_builders = {
        "home": lambda parent: HomePage(
            parent,
            translate=t,
            status_provider=app_shell_home_status_provider,
            quick_actions={
                "new_chat": lambda: navigate_app_shell("chat"),
                "open_library": lambda: navigate_app_shell("library"),
                "settings": lambda: navigate_app_shell("settings")
            },
            logger=logger
        ),
        "chat": lambda parent: ChatPage(
            parent,
            translate=t,
            open_chat_callback=show_chat,
            new_chat_callback=show_chat,
            conversation_provider=app_shell_conversation_provider,
            model_provider=lambda: settings.get("chat_model", ""),
            logger=logger
        ),
        "library": lambda parent: LibraryPage(
            parent,
            translate=t,
            open_knowledge_callback=show_knowledge,
            knowledge_status_provider=app_shell_library_status_provider,
            logger=logger
        ),
        "memory": lambda parent: MemoryPage(
            parent,
            translate=t,
            open_memory_callback=show_memory,
            memory_status_provider=app_shell_memory_status_provider,
            logger=logger
        ),
        "persona": lambda parent: PersonaPage(
            parent,
            translate=t,
            open_persona_callback=show_persona,
            persona_status_provider=app_shell_persona_status_provider,
            logger=logger
        ),
        "remote": lambda parent: RemotePage(
            parent,
            translate=t,
            open_remote_callback=show_remote_access,
            open_diagnostics_callback=show_remote_diagnostics,
            remote_status_provider=app_shell_remote_status_provider,
            logger=logger
        ),
        "settings": lambda parent: SettingsPage(
            parent,
            translate=t,
            open_settings_callback=show_settings,
            settings_status_provider=app_shell_settings_status_provider,
            logger=logger
        )
    }

    try:
        legacy_dashboard_frame.pack_forget()
    except Exception:
        pass

    app_shell = AppShell(
        app,
        app_name=APP_NAME,
        translate=t,
        page_builders=page_builders,
        on_page_change=lambda page_name: logger.info(f"AppShell page opened: {page_name}")
    )
    app_shell.pack(fill="both", expand=True)
    logger.info("AppShell initialized")
    return app_shell


logger.info("Application started")

app.protocol("WM_DELETE_WINDOW", shutdown_app)

create_app_shell()

if first_run_required:
    app.after(100, show_first_run_wizard)
else:
    startup_check()
    refresh_recent_logs()
    refresh_status()
    refresh_system_health_center()

app.mainloop()

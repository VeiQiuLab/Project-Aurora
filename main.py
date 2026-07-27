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
from modules.language import TEXT, set_language
from modules.lan_server import LANStatusPageServer, DEFAULT_LAN_STATUS_PORT
from modules.mobile_chat import MobileChatService
from modules.search import search_memories, search_conversations
from modules.memory_retrieval import format_memory_context, retrieve_memories
from modules.retrieval import format_knowledge_context, search_knowledge, retrieval_summary
from modules.service_manager import ServiceManager

set_language(settings.get("language", "English"))


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

width = settings.get("window.width", 520)
height = settings.get("window.height", 560)

app.geometry(f"{width}x{height}")
app.minsize(520, 560)
app.resizable(True, True)

logger.info(f"Window Size: {width} x {height}")


title = ctk.CTkLabel(
    app,
    text=APP_NAME,
    font=("Microsoft YaHei", 24, "bold")
)
title.pack(pady=(20, 5))


version = ctk.CTkLabel(
    app,
    text=f"Version {VERSION} - Build {BUILD}",
    font=("Microsoft YaHei", 14)
)
version.pack()


status_frame = ctk.CTkFrame(app)
status_columns_frame = ctk.CTkFrame(app, fg_color="transparent")
status_columns_frame.pack(fill="x", padx=20, pady=15)

status_frame.pack(
    side="left",
    fill="both",
    expand=True,
    padx=(0, 8)
)

status_title = ctk.CTkLabel(
    status_frame,
    text=TEXT["system_status"],
    font=("Microsoft YaHei", 16, "bold")
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
    text=TEXT["startup_status"],
    font=("Microsoft YaHei", 16, "bold")
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
        font=("Microsoft YaHei", 13)
    ).pack(side="left")

    startup_state = ctk.CTkLabel(
        startup_row,
        text=TEXT["ready"],
        font=("Microsoft YaHei", 12),
        text_color="#32CD32"
    )
    startup_state.pack(side="right")
    startup_status_labels[startup_item] = startup_state

status_labels = {}
models_window = None
health_window = None
settings_window = None
chat_window = None
context_inspector_window = None
memory_window = None
knowledge_window = None
persona_window = None
remote_window = None
remote_diagnostics_window = None
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
    wizard = ctk.CTkToplevel(app)
    wizard.title("Project Aurora First Run")
    wizard.geometry("620x520")
    wizard.minsize(560, 480)
    wizard.protocol("WM_DELETE_WINDOW", lambda: None)
    wizard.grab_set()

    state = {
        "step": 0,
        "models": [],
        "ollama_ok": False,
        "chat_model": str(settings.get("chat_model", "qwen3:8b") or "qwen3:8b"),
        "embedding_model": str(settings.get("embedding_model", "nomic-embed-text:latest") or "nomic-embed-text:latest")
    }

    container = ctk.CTkFrame(wizard)
    container.pack(fill="both", expand=True, padx=24, pady=24)

    title_label = ctk.CTkLabel(container, text="", font=("Microsoft YaHei", 24, "bold"))
    title_label.pack(anchor="w", pady=(4, 10))

    content_frame = ctk.CTkFrame(container, fg_color="transparent")
    content_frame.pack(fill="both", expand=True)

    nav_frame = ctk.CTkFrame(container, fg_color="transparent")
    nav_frame.pack(fill="x", pady=(16, 0))

    back_button = ctk.CTkButton(nav_frame, text="Back", width=100)
    back_button.pack(side="left")
    next_button = ctk.CTkButton(nav_frame, text="Next", width=120)
    next_button.pack(side="right")

    def clear_content():
        for child in content_frame.winfo_children():
            child.destroy()

    def text_row(text, color="gray", size=14):
        label = ctk.CTkLabel(content_frame, text=text, font=("Microsoft YaHei", size), text_color=color, anchor="w", justify="left")
        label.pack(fill="x", pady=6)
        return label

    def refresh_nav():
        back_button.configure(state="normal" if state["step"] > 0 else "disabled")
        next_button.configure(text="Finish" if state["step"] == 5 else "Next")

    def load_models_async(status_label=None):
        def run():
            result = fetch_ollama_models_from_api()

            def finish():
                state["ollama_ok"] = bool(result.get("ok"))
                state["models"] = result.get("models", [])
                if status_label is not None:
                    if result.get("ok"):
                        status_label.configure(text=f"OK | Models: {len(state['models'])}", text_color="#32CD32")
                    else:
                        status_label.configure(text=f"Not detected | {result.get('reason', '')}", text_color="red")

            try:
                wizard.after(0, finish)
            except Exception:
                return

        threading.Thread(target=run, daemon=True).start()

    def choose_model_step(kind):
        clear_content()
        is_chat = kind == "chat"
        title_label.configure(text="Step 3 - Chat Model" if is_chat else "Step 4 - Embedding Model")
        text_row("Read Ollama /api/tags and select the model used for chat or embeddings.")
        candidates = [
            item["name"]
            for item in state["models"]
            if (item.get("capability") == "Chat Supported") == is_chat
        ]
        if not candidates:
            candidates = [item["name"] for item in state["models"]]
        current = state["chat_model"] if is_chat else state["embedding_model"]
        if current and current not in candidates:
            candidates.insert(0, current)
        values = candidates or [current or "No models available"]
        selected = StringVar(value=current if current in values else values[0])
        menu = ctk.CTkOptionMenu(content_frame, values=values, variable=selected, width=360)
        menu.pack(anchor="w", pady=12)

        def remember_choice(*_args):
            if is_chat:
                state["chat_model"] = selected.get()
            else:
                state["embedding_model"] = selected.get()

        selected.trace_add("write", remember_choice)
        remember_choice()

    def render():
        clear_content()
        step = state["step"]
        if step == 0:
            title_label.configure(text="Welcome to Project Aurora")
            ctk.CTkLabel(content_frame, text="Aurora", font=("Microsoft YaHei", 42, "bold")).pack(anchor="w", pady=(12, 6))
            text_row(f"Version: {RELEASE} | Build: {BUILD}", "#32CD32")
            text_row("Welcome to Project Aurora. This wizard completes the basic local AI setup for first launch.", size=15)
        elif step == 1:
            title_label.configure(text="Step 2 - Detect Ollama")
            text_row("Detect the local Ollama service status.")
            status_label = text_row("Checking Ollama...", "gray", 16)
            load_models_async(status_label)
        elif step == 2:
            choose_model_step("chat")
        elif step == 3:
            choose_model_step("embedding")
        elif step == 4:
            title_label.configure(text="Step 5 - Persona")
            persona = persona_store.load(update_timestamp=False)
            persona_status = persona_store.status(settings.get("persona.enabled", True), persona)
            text_row(f"Current Persona: {persona_status.get('name', 'Aurora')}", "#32CD32", 16)
            text_row(f"Rules: {persona_status.get('rules_count', 0)}")
            text_row(f"Enabled: {'Yes' if persona_status.get('enabled') else 'No'}")
        else:
            title_label.configure(text="Step 6 - Complete")
            text_row("Aurora is ready.", "#32CD32", 18)
            text_row(f"Chat Model: {state['chat_model']}")
            text_row(f"Embedding Model: {state['embedding_model']}")
            text_row("Click Finish to enter the main dashboard.")
        refresh_nav()

    def next_step():
        if state["step"] >= 5:
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
            return
        state["step"] += 1
        render()

    def prev_step():
        if state["step"] > 0:
            state["step"] -= 1
            render()

    back_button.configure(command=prev_step)
    next_button.configure(command=next_step)
    logger.info("First Run Wizard opened")
    render()

status_summary_label = ctk.CTkLabel(
    status_frame,
    text=TEXT["checking"],
    font=("Microsoft YaHei", 13, "bold"),
    text_color="gray"
)

dashboard_last_check_label = ctk.CTkLabel(
    status_frame,
    text=f"{TEXT['last_check']}: --",
    font=("Microsoft YaHei", 12),
    text_color="gray"
)

for name in ["Ollama", "Open WebUI", "API 11434"]:

    row = ctk.CTkFrame(
        status_frame,
        fg_color="transparent"
    )
    row.pack(fill="x", padx=15, pady=4)

    lbl = ctk.CTkLabel(
        row,
        text=f"鈿?{name}",
        anchor="w",
        font=("Microsoft YaHei", 15)
    )
    lbl.pack(side="left")

    state = ctk.CTkLabel(
        row,
        text=TEXT["checking"],
        font=("Microsoft YaHei", 13),
        text_color="gray"
    )
    state.pack(side="right")

    status_labels[name] = (lbl, state)

docker_status_labels = {}
for name in ["Docker Desktop", "Docker Engine"]:
    row = ctk.CTkFrame(status_frame, fg_color="transparent")
    row.pack(fill="x", padx=15, pady=2)
    lbl = ctk.CTkLabel(row, text=name, anchor="w", font=("Microsoft YaHei", 13))
    lbl.pack(side="left")
    state = ctk.CTkLabel(row, text=TEXT["checking"], font=("Microsoft YaHei", 12), text_color="gray")
    state.pack(side="right")
    docker_status_labels[name] = state

status_summary_label.pack(pady=(8, 2))
dashboard_last_check_label.pack(pady=(0, 10))

diagnostic_title = ctk.CTkLabel(
    status_frame,
    text="AI Environment Diagnostic",
    font=("Microsoft YaHei", 15, "bold")
)
diagnostic_title.pack(anchor="w", padx=15, pady=(2, 4))
diagnostic_box = ctk.CTkTextbox(status_frame, height=105, wrap="word")
diagnostic_box.pack(fill="x", padx=15, pady=(0, 10))
diagnostic_box.insert("1.0", "Diagnostic not started")
diagnostic_box.configure(state="disabled")
diagnostic_running = False

health_center_frame = ctk.CTkFrame(app)
health_center_frame.pack(fill="x", padx=20, pady=(0, 8))

health_center_header = ctk.CTkFrame(health_center_frame, fg_color="transparent")
health_center_header.pack(fill="x", padx=15, pady=(12, 6))

ctk.CTkLabel(
    health_center_header,
    text="Dashboard Health Center",
    font=("Microsoft YaHei", 16, "bold")
).pack(side="left")

health_center_summary = ctk.CTkLabel(
    health_center_header,
    text="Checking...",
    font=("Microsoft YaHei", 13, "bold"),
    text_color="gray"
)
health_center_summary.pack(side="right")

health_center_grid = ctk.CTkFrame(health_center_frame, fg_color="transparent")
health_center_grid.pack(fill="x", padx=15, pady=(0, 8))

for health_column in range(3):
    health_center_grid.grid_columnconfigure(health_column, weight=1)

health_center_labels = {}
health_center_names = [
    "Ollama",
    "Chat Model",
    "Embedding Model",
    "Persona",
    "Memory",
    "Knowledge",
    "Vector Index",
    "Conversation Store",
    "Remote"
]

for index, health_name in enumerate(health_center_names):
    row = index // 3
    column = index % 3
    item_frame = ctk.CTkFrame(health_center_grid)
    item_frame.grid(row=row, column=column, sticky="ew", padx=5, pady=5)
    ctk.CTkLabel(
        item_frame,
        text="Conversation" if health_name == "Conversation Store" else health_name,
        font=("Microsoft YaHei", 13),
        anchor="w"
    ).pack(anchor="w", padx=10, pady=(8, 2))
    value_label = ctk.CTkLabel(
        item_frame,
        text="Checking",
        font=("Microsoft YaHei", 12, "bold"),
        text_color="gray"
    )
    value_label.pack(anchor="w", padx=10, pady=(0, 8))
    health_center_labels[health_name] = value_label

health_stats_frame = ctk.CTkFrame(health_center_frame, fg_color="transparent")
health_stats_frame.pack(fill="x", padx=15, pady=(0, 12))

health_stat_labels = {}
for stat_name in ["Memory", "Knowledge", "Conversation"]:
    stat_label = ctk.CTkLabel(
        health_stats_frame,
        text=f"{stat_name}: --",
        font=("Microsoft YaHei", 12),
        text_color="gray"
    )
    stat_label.pack(side="left", padx=(0, 18))
    health_stat_labels[stat_name] = stat_label

health_center_running = False


def health_status_color(status):
    if status == "Healthy":
        return "#32CD32"
    if status == "Warning":
        return "orange"
    return "red"


def refresh_system_health_center():
    global health_center_running
    if health_center_running:
        return
    health_center_running = True
    health_center_summary.configure(text="Checking...", text_color="gray")
    for label in health_center_labels.values():
        label.configure(text="Checking", text_color="gray")

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
            health_stat_labels["Memory"].configure(text=f"Memory: {memory_details.get('records', 0)}")
            health_stat_labels["Knowledge"].configure(text=f"Knowledge: {knowledge_details.get('total', 0)}")
            health_stat_labels["Conversation"].configure(text=f"Conversation: {conversation_details.get('records', 0)}")

            overall = report.get("status", "Error")
            if error_message:
                health_center_summary.configure(text="Error", text_color="red")
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

showcase_frame = ctk.CTkFrame(app)
showcase_frame.pack(fill="x", padx=20, pady=(0, 8))

ctk.CTkLabel(
    showcase_frame,
    text=TEXT["showcase"],
    font=("Microsoft YaHei", 16, "bold")
).pack(anchor="w", padx=15, pady=(12, 6))

showcase_grid = ctk.CTkFrame(showcase_frame, fg_color="transparent")
showcase_grid.pack(fill="x", padx=15, pady=(0, 12))

for showcase_column in range(5):
    showcase_grid.grid_columnconfigure(showcase_column, weight=1)

showcase_items = [
    (TEXT["local_ai_chat"], TEXT["available_status"]),
    (TEXT["memory_system"], TEXT["available_status"]),
    (TEXT["knowledge_base"], TEXT["available_status"]),
    (TEXT["persona_system"], TEXT["enabled"] if settings.get("persona.enabled", True) else TEXT["disabled"]),
    (TEXT["remote_security"], TEXT["protected"])
]

for index, (feature_name, feature_status) in enumerate(showcase_items):
    feature_card = ctk.CTkFrame(showcase_grid)
    feature_card.grid(row=0, column=index, sticky="ew", padx=5, pady=5)
    ctk.CTkLabel(
        feature_card,
        text=feature_name,
        font=("Microsoft YaHei", 12, "bold")
    ).pack(pady=(10, 2))
    ctk.CTkLabel(
        feature_card,
        text=feature_status,
        font=("Microsoft YaHei", 11),
        text_color="#32CD32"
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
        "妯″瀷鍒楄〃",
        models
    )


def show_models():
    global models_window

    logger.info("Open model list")

    if models_window is not None and models_window.winfo_exists():
        models_window.focus()
        models_window.lift()
        return

    models_window = ctk.CTkToplevel(app)
    models_window.title(TEXT["models"])
    models_window.geometry("820x480")
    models_window.minsize(680, 320)
    models_window.transient(app)

    model_title = ctk.CTkLabel(
        models_window,
        text="Ollama 妯″瀷",
        font=("Microsoft YaHei", 20, "bold")
    )
    model_title.pack(anchor="w", padx=20, pady=(18, 10))

    model_table = ctk.CTkScrollableFrame(models_window)
    model_table.pack(fill="both", expand=True, padx=20, pady=(0, 20))

    columns = [
        (TEXT["name"], "name", 220),
        (TEXT["id"], "model_id", 180),
        (TEXT["size"], "size", 110),
        (TEXT["modified"], "modified", 240)
    ]

    for index, (label, _, width) in enumerate(columns):
        model_table.grid_columnconfigure(index, weight=1)
        ctk.CTkLabel(
            model_table,
            text=label,
            width=width,
            anchor="w",
            font=("Microsoft YaHei", 13, "bold")
        ).grid(row=0, column=index, padx=8, pady=(8, 6), sticky="w")

    records = []

    if records:
        for row_index, record in enumerate(records, start=1):
            for column_index, (_, field, width) in enumerate(columns):
                ctk.CTkLabel(
                    model_table,
                    text=record.get(field, ""),
                    width=width,
                    anchor="w",
                    font=("Microsoft YaHei", 12)
                ).grid(
                    row=row_index,
                    column=column_index,
                    padx=8,
                    pady=6,
                    sticky="w"
                )
    else:
        ctk.CTkLabel(
            model_table,
            text="No Ollama models found.",
            font=("Microsoft YaHei", 13),
            text_color="gray"
        ).grid(row=1, column=0, columnspan=len(columns), padx=8, pady=20)

    def update_model_rows(records):
        if models_window is None or not models_window.winfo_exists():
            return
        for widget in model_table.winfo_children():
            info = widget.grid_info()
            if str(info.get("row", "")) not in {"", "0"}:
                widget.destroy()
        if not records:
            ctk.CTkLabel(
                model_table,
                text=TEXT["no_models"],
                font=("Microsoft YaHei", 13),
                text_color="gray"
            ).grid(row=1, column=0, columnspan=len(columns), padx=8, pady=20)
            return
        for row_index, record in enumerate(records, start=1):
            for column_index, (_, field, width) in enumerate(columns):
                ctk.CTkLabel(
                    model_table, text=record.get(field, ""), width=width,
                    anchor="w", font=("Microsoft YaHei", 12)
                ).grid(row=row_index, column=column_index, padx=8, pady=6, sticky="w")

    def load_model_rows():
        try:
            loaded_records = get_model_records()
        except Exception as error:
            logger.error(f"Model loading failed: {error}")
            loaded_records = []
        app.after(0, lambda: update_model_rows(loaded_records))

    threading.Thread(target=load_model_rows, daemon=True).start()

    def close_models_window():
        global models_window
        models_window.destroy()
        models_window = None

    models_window.protocol("WM_DELETE_WINDOW", close_models_window)


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

        title_button = ctk.CTkButton(
            outer,
            text=f"\u25bc {name}",
            anchor="w",
            command=toggle
        )
        title_button.pack(fill="x", padx=10, pady=(10, 6))

        meta = (
            f"Status: {'Enabled' if record.get('enabled') else 'Disabled'}\n"
            f"Characters: {record.get('characters', 0)}\n"
            f"Tokens: {record.get('tokens', 0)}"
        )
        ctk.CTkLabel(
            body,
            text=meta,
            font=("Microsoft YaHei", 12),
            text_color="gray",
            anchor="w",
            justify="left"
        ).pack(anchor="w", pady=(0, 6))

        content = str(record.get("content", "") or "")
        if len(content) > preview_limit:
            content = content[:preview_limit] + "\n\n[Context preview truncated]"
        if not content.strip():
            content = "[No content]"
        text_box = ctk.CTkTextbox(body, height=150, wrap="word")
        text_box.pack(fill="x")
        text_box.insert("1.0", content)
        text_box.configure(state="disabled")
        body.pack(fill="x", padx=12, pady=(0, 12))

    for section in sections:
        add_section(section)

    bottom = ctk.CTkFrame(context_inspector_window, fg_color="transparent")
    bottom.pack(fill="x", padx=25, pady=(0, 20))

    status_label = ctk.CTkLabel(bottom, text="", font=("Microsoft YaHei", 12), text_color="gray")
    status_label.pack(side="left", padx=(0, 10))

    def copy_final_prompt():
        try:
            context_inspector_window.clipboard_clear()
            context_inspector_window.clipboard_append(payload.get("final_prompt", ""))
            status_label.configure(text="Final Prompt copied.", text_color="#32CD32")
            logger.info("Final prompt copied")
        except Exception as error:
            status_label.configure(text="Copy failed.", text_color="red")
            logger.error(f"Final prompt copy failed: {error}")

    def close_context_inspector():
        global context_inspector_window
        context_inspector_window.destroy()
        context_inspector_window = None

    ctk.CTkButton(bottom, text="Copy Final Prompt", command=copy_final_prompt).pack(side="right", padx=(6, 0))
    ctk.CTkButton(bottom, text=TEXT["close"], command=close_context_inspector).pack(side="right", padx=6)
    context_inspector_window.protocol("WM_DELETE_WINDOW", close_context_inspector)


def show_chat():
    global chat_window

    if chat_window is not None and chat_window.winfo_exists():
        chat_window.focus()
        chat_window.lift()
        return

    logger.info("Chat started")
    chat_window = ctk.CTkToplevel(app)
    chat_window.title(TEXT["chat"])
    chat_window.geometry("900x680")
    chat_window.minsize(720, 560)
    chat_window.transient(app)

    ctk.CTkLabel(
        chat_window,
        text=TEXT["chat"],
        font=("Microsoft YaHei", 22, "bold")
    ).pack(anchor="w", padx=25, pady=(20, 12))

    model_frame = ctk.CTkFrame(chat_window, fg_color="transparent")
    model_frame.pack(fill="x", padx=25, pady=(0, 10))
    ctk.CTkLabel(
        model_frame,
        text=TEXT["model_selector"],
        font=("Microsoft YaHei", 14, "bold")
    ).pack(side="left")

    selected_model = {"name": ""}
    initial_persona = persona_store.load() if settings.get("persona.enabled", True) else None
    if initial_persona:
        logger.info("Persona loaded")
        logger.info("Persona loaded timestamp updated")
    else:
        logger.info("Persona disabled")
    session = ChatSession(build_memory_context(persona=initial_persona))
    conversation_manager = ConversationManager()
    conversation_state = {
        "id": None,
        "created_at": None,
        "title": "New Conversation"
    }
    stream_state = {
        "running": False,
        "stop_event": None
    }
    debug_context_var = ctk.BooleanVar(value=False)

    conversation_frame = ctk.CTkFrame(chat_window, fg_color="transparent")
    conversation_frame.pack(fill="x", padx=25, pady=(0, 10))
    ctk.CTkLabel(
        conversation_frame,
        text=TEXT["conversation_list"],
        font=("Microsoft YaHei", 14, "bold")
    ).pack(side="left")
    conversation_selector = ctk.CTkOptionMenu(
        conversation_frame,
        values=[TEXT["no_conversations"]],
        width=280,
        command=lambda _value: load_conversation()
    )
    conversation_selector.pack(side="right")

    conversation_search_frame = ctk.CTkFrame(chat_window, fg_color="transparent")
    conversation_search_frame.pack(fill="x", padx=25, pady=(0, 8))
    conversation_search_entry = ctk.CTkEntry(conversation_search_frame, placeholder_text="Search conversations")
    conversation_search_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

    def search_conversation_list():
        refresh_conversations(conversation_search_entry.get())
        logger.info("Conversation searched")

    ctk.CTkButton(
        conversation_search_frame,
        text="Search",
        width=80,
        command=search_conversation_list
    ).pack(side="right")

    def select_model(model):
        if model and model not in {"Loading...", "No models available"}:
            if infer_model_capability(model) != "Chat Supported":
                chat_status.configure(text=TEXT["model_cannot_chat"], text_color="red")
                logger.info("Embedding model blocked from chat")
                return
            selected_model["name"] = model
            settings.set("chat_model", model)
            logger.info(f"Chat model selected: {model}")

    model_selector = ctk.CTkOptionMenu(
        model_frame,
        values=["Loading..."],
        width=280,
        command=select_model
    )
    model_selector.set("Loading...")
    model_selector.pack(side="right")

    chat_display = ctk.CTkTextbox(chat_window, wrap="word")
    chat_display.pack(fill="both", expand=True, padx=25, pady=(0, 12))
    chat_display.configure(state="disabled")

    ctk.CTkLabel(
        chat_window,
        text=TEXT["input_box"],
        font=("Microsoft YaHei", 14, "bold")
    ).pack(anchor="w", padx=25, pady=(0, 6))

    input_box = ctk.CTkTextbox(chat_window, height=90, wrap="word")
    input_box.pack(fill="x", padx=25, pady=(0, 10))

    debug_switch = ctk.CTkSwitch(
        chat_window,
        text="鏄剧ず Chat Context 璋冭瘯淇℃伅",
        variable=debug_context_var
    )
    debug_switch.pack(anchor="w", padx=25, pady=(0, 8))

    chat_status = ctk.CTkLabel(
        chat_window,
        text="姝ｅ湪鍔犺浇 Ollama 妯″瀷...",
        font=("Microsoft YaHei", 12),
        text_color="gray"
    )
    chat_status.pack(anchor="w", padx=25, pady=(0, 8))

    def is_open():
        try:
            return chat_window is not None and chat_window.winfo_exists()
        except Exception:
            return False

    def append_text(text):
        chat_display.configure(state="normal")
        chat_display.insert("end", text + "\n\n")
        chat_display.see("end")
        chat_display.configure(state="disabled")

    def append_stream_chunk(chunk):
        if not is_open():
            return
        chat_display.configure(state="normal")
        chat_display.insert("end", chunk)
        chat_display.see("end")
        chat_display.configure(state="disabled")

    conversation_records = []

    def conversation_label(record):
        updated = record.get("updated_at", "").replace("T", " ").replace("+00:00", " UTC")
        return f"{record.get('title', 'New Conversation')}\n{record.get('model', 'Unknown model')}\n{updated}"

    def refresh_conversations(keyword=""):
        nonlocal conversation_records
        if keyword.strip():
            conversation_records = search_conversations(conversation_manager.directory, keyword)
        else:
            conversation_records = conversation_manager.list_conversations()
        labels = [conversation_label(item) for item in conversation_records]
        conversation_selector.configure(values=labels or [TEXT["no_conversations"]])
        conversation_selector.set(labels[0] if labels else TEXT["no_conversations"])

    def render_messages(messages):
        chat_display.configure(state="normal")
        chat_display.delete("1.0", "end")
        for message in messages:
            if message.get("role") == "system":
                continue
            label = "You" if message.get("role") == "user" else "Aurora"
            chat_display.insert("end", f"{label}:\n{message.get('content', '')}\n\n")
        chat_display.see("end")
        chat_display.configure(state="disabled")

    def new_conversation():
        if stream_state["running"]:
            chat_status.configure(text="Please stop generation first.", text_color="orange")
            return
        if len(session.snapshot()) > 1:
            save_conversation(auto=True)
        session.clear()
        conversation_state["id"] = None
        conversation_state["created_at"] = None
        conversation_state["title"] = "New Conversation"
        render_messages(session.snapshot())
        chat_status.configure(text="New conversation.", text_color="gray")
        logger.info("Conversation created")

    def save_conversation(auto=False):
        if stream_state["running"]:
            chat_status.configure(text="Please stop generation before saving.", text_color="orange")
            return
        messages = session.snapshot()
        if len(messages) <= 1:
            chat_status.configure(text="No conversation content to save.", text_color="orange")
            return
        title = conversation_state["title"]
        if title == "New Conversation":
            title = next((m.get("content", "") for m in messages if m.get("role") == "user"), title)
        data = conversation_manager.save(
            conversation_state["id"],
            selected_model["name"],
            messages,
            title=title[:40],
            created_at=conversation_state["created_at"]
        )
        conversation_state["id"] = data["id"]
        conversation_state["created_at"] = data["created_at"]
        conversation_state["title"] = data["title"]
        refresh_conversations()
        chat_status.configure(text="Conversation auto saved." if auto else "Conversation saved.", text_color="#32CD32")
        logger.info("Conversation auto saved" if auto else "Conversation saved")

    def load_conversation():
        if stream_state["running"]:
            chat_status.configure(text="Please stop generation before loading.", text_color="orange")
            return
        selected = conversation_selector.get()
        record = next((item for item in conversation_records if conversation_label(item) == selected), None)
        if record is None:
            return
        try:
            if conversation_state["id"] and len(session.snapshot()) > 1:
                save_conversation(auto=True)
            data = conversation_manager.load(record["id"])
            session.replace(data.get("messages", []))
            conversation_state["id"] = data.get("id")
            conversation_state["created_at"] = data.get("created_at")
            conversation_state["title"] = data.get("title", "New Conversation")
            if data.get("model"):
                selected_model["name"] = data["model"]
                model_selector.set(data["model"])
            render_messages(session.snapshot())
            chat_status.configure(text="Conversation loaded.", text_color="#32CD32")
            logger.info("Conversation loaded")
            logger.info("Conversation switched")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            logger.error(f"Conversation load failed: {error}")
            chat_status.configure(text="Unable to load conversation.", text_color="red")

    def delete_conversation():
        selected = conversation_selector.get()
        record = next((item for item in conversation_records if conversation_label(item) == selected), None)
        if record is None or not messagebox.askyesno("Delete Chat", "Delete selected conversation?", parent=chat_window):
            return
        try:
            conversation_manager.delete(record["id"])
            if conversation_state["id"] == record["id"]:
                new_conversation()
            refresh_conversations()
            chat_status.configure(text="Conversation deleted.", text_color="gray")
            logger.info("Conversation deleted")
        except OSError as error:
            logger.error(f"Conversation delete failed: {error}")

    def rename_conversation():
        if not conversation_state["id"]:
            chat_status.configure(text="Please load a conversation first.", text_color="orange")
            return
        dialog = ctk.CTkInputDialog(text="Enter conversation title:", title=TEXT["rename_chat"])
        title = dialog.get_input()
        if not title or not title.strip():
            return
        try:
            data = conversation_manager.rename(conversation_state["id"], title)
            conversation_state["title"] = data["title"]
            refresh_conversations()
            chat_status.configure(text="Conversation renamed.", text_color="#32CD32")
            logger.info("Conversation renamed")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            logger.error(f"Conversation rename failed: {error}")

    def update_models(records):
        if not is_open():
            return
        names = [
            record.get("name", "")
            for record in records
            if infer_model_capability(record.get("name", "")) == "Chat Supported"
        ]
        names = [name for name in names if name]
        if not names:
            model_selector.configure(values=["No models available"])
            model_selector.set("No models available")
            chat_status.configure(
                text="No Ollama models found. Start Ollama and retry.",
                text_color="orange"
            )
            return
        configured_chat_model = str(settings.get("chat_model", "qwen3:8b") or "").strip()
        selected_name = configured_chat_model if configured_chat_model in names else names[0]
        selected_model["name"] = selected_name
        model_selector.configure(values=names)
        model_selector.set(selected_name)
        chat_status.configure(
            text=f"{len(names)} model(s) available",
            text_color="#32CD32"
        )
        logger.info(f"Chat models loaded: {len(names)}")
        logger.info("Model capability checked")

    def load_models():
        try:
            records = get_model_records()
        except Exception as error:
            logger.error(f"Chat model loading failed: {error}")
            records = []
        try:
            app.after(0, lambda: update_models(records))
        except Exception:
            return

    button_frame = ctk.CTkFrame(chat_window, fg_color="transparent")
    button_frame.pack(fill="x", padx=25, pady=(0, 20))

    def send_prompt():
        model = selected_model["name"].strip()
        prompt = input_box.get("1.0", "end").strip()
        if not model or model in {"Loading...", "No models available"}:
            append_text("Error: No Ollama model is available.")
            return
        if not prompt:
            append_text("Please enter a prompt first.")
            return

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
            matched_knowledge = knowledge_store.retrieve(
                prompt,
                max_results=max_knowledge
            )
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
        session.set_system_context(build_memory_context(matched_memories, matched_knowledge, active_persona))
        if matched_memories:
            logger.info("Memory injected")
        if matched_knowledge:
            logger.info("Knowledge injected")

        if debug_context_var.get():
            debug_text, warning, _tokens = build_context_debug_report(
                build_context_sections(matched_memories, matched_knowledge, active_persona, session.snapshot()),
                warning_tokens=settings.get("context.warning_tokens", 6000)
            )
            if warning:
                logger.info("Context size warning")
            append_text(debug_text)

        append_text(f"You ({model}):\n{prompt}")
        append_text("Aurora:")
        input_box.delete("1.0", "end")
        send_button.configure(state="disabled")
        stop_button.configure(state="normal")
        chat_status.configure(text="绛夊緟 Ollama 鍝嶅簲...", text_color="gray")
        logger.info(f"Streaming started: {model}")
        stream_state["running"] = True
        stream_state["stop_event"] = threading.Event()

        def run_request():
            try:
                def append_chunk(chunk):
                    try:
                        app.after(0, lambda: append_stream_chunk(chunk))
                    except Exception:
                        return

                result = stream_chat(
                    model,
                    prompt,
                    session,
                    append_chunk,
                    stream_state["stop_event"]
                )
                error_message = None
                logger.info(f"Chat request succeeded: {model}")
            except ChatError as error:
                result = "failed"
                error_message = str(error)
                logger.error(f"Chat request failed: {error_message}")
            except Exception as error:
                result = "failed"
                error_message = "Unexpected chat error."
                logger.error(f"Chat request failed: {error}")

            def update_chat():
                if not is_open():
                    return
                if error_message:
                    append_text(f"Error: {error_message}")
                    chat_status.configure(text=error_message, text_color="red")
                elif result == "stopped":
                    append_text("[Generation stopped]")
                    chat_status.configure(text="Generation stopped.", text_color="orange")
                else:
                    chat_status.configure(text="Response received.", text_color="#32CD32")
                stream_state["running"] = False
                stream_state["stop_event"] = None
                send_button.configure(state="normal")
                stop_button.configure(state="disabled")
                if not error_message:
                    save_conversation(auto=True)

            try:
                app.after(0, update_chat)
            except Exception:
                return

        threading.Thread(target=run_request, daemon=True).start()

    def clear_chat():
        if stream_state["running"]:
            chat_status.configure(text="Please stop generation before clearing.", text_color="orange")
            return
        if not messagebox.askyesno("Clear Chat", "Clear current conversation?", parent=chat_window):
            return
        chat_display.configure(state="normal")
        chat_display.delete("1.0", "end")
        chat_display.configure(state="disabled")
        input_box.delete("1.0", "end")
        session.clear()
        chat_status.configure(text="Conversation cleared.", text_color="gray")
        logger.info("Conversation cleared")

    def stop_generation():
        if stream_state["running"] and stream_state["stop_event"] is not None:
            stream_state["stop_event"].set()
            logger.info("Generation stopped")
            chat_status.configure(text="姝ｅ湪鍋滄鐢熸垚...", text_color="orange")
            stop_button.configure(state="disabled")

    def preview_chat_context():
        prompt = input_box.get("1.0", "end").strip()
        chat_status.configure(text="Building Context Inspector...", text_color="gray")
        logger.info("Context preview opened")
        logger.info("Context inspector opened")

        def run_preview():
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
                knowledge_items = knowledge_store.retrieve(
                    prompt,
                    max_results=max_knowledge
                )
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            payload = build_context_inspector_payload(
                prompt,
                memories,
                knowledge_items,
                active_persona,
                session.snapshot(),
                build_duration_ms=duration_ms
            )

            def finish_preview():
                if not is_open():
                    return
                show_context_inspector(payload, chat_window)
                chat_status.configure(text="Context Inspector ready", text_color="#32CD32")
                logger.info("Context generated")
                logger.info("Context build duration recorded")
                logger.info("Final prompt preview generated")
                if payload.get("summary", {}).get("warning"):
                    logger.info("Context size warning")

            try:
                app.after(0, finish_preview)
            except Exception:
                return

        threading.Thread(target=run_preview, daemon=True).start()

    def close_chat_window():
        global chat_window
        chat_window.destroy()
        chat_window = None

    send_button = ctk.CTkButton(
        button_frame,
        text=TEXT["send"],
        command=send_prompt
    )
    send_button.pack(side="left", expand=True, fill="x", padx=(0, 6))

    ctk.CTkButton(
        button_frame,
        text=TEXT["new_chat"],
        command=new_conversation
    ).pack(side="left", expand=True, fill="x", padx=6)

    ctk.CTkButton(
        button_frame,
        text=TEXT["save_chat"],
        command=save_conversation
    ).pack(side="left", expand=True, fill="x", padx=6)

    ctk.CTkButton(
        button_frame,
        text=TEXT["rename_chat"],
        command=rename_conversation
    ).pack(side="left", expand=True, fill="x", padx=6)

    stop_button = ctk.CTkButton(
        button_frame,
        text=TEXT["stop_generate"],
        command=stop_generation,
        state="disabled"
    )
    stop_button.pack(side="left", expand=True, fill="x", padx=6)

    ctk.CTkButton(
        button_frame,
        text=TEXT["clear"],
        command=clear_chat
    ).pack(side="left", expand=True, fill="x", padx=6)

    ctk.CTkButton(
        button_frame,
        text=TEXT["delete_chat"],
        command=delete_conversation
    ).pack(side="left", expand=True, fill="x", padx=6)

    ctk.CTkButton(
        button_frame,
        text="Context Inspector",
        command=preview_chat_context
    ).pack(side="left", expand=True, fill="x", padx=6)

    ctk.CTkButton(
        button_frame,
        text=TEXT["close"],
        command=close_chat_window
    ).pack(side="left", expand=True, fill="x", padx=(6, 0))

    chat_window.protocol("WM_DELETE_WINDOW", close_chat_window)
    refresh_conversations()
    threading.Thread(target=load_models, daemon=True).start()


def show_memory():
    global memory_window
    if memory_window is not None and memory_window.winfo_exists():
        memory_window.focus()
        memory_window.lift()
        return

    logger.info("Memory window opened")
    memory_window = ctk.CTkToplevel(app)
    memory_window.title(TEXT["memory"])
    memory_window.geometry("760x600")
    memory_window.minsize(620, 480)
    memory_window.transient(app)
    store = memory_store
    records = []
    selected_id = {"value": None}

    ctk.CTkLabel(memory_window, text=TEXT["memory"], font=("Microsoft YaHei", 22, "bold")).pack(
        anchor="w", padx=25, pady=(20, 12)
    )
    list_box = ctk.CTkOptionMenu(memory_window, values=["No memories available"], width=680)
    list_box.pack(fill="x", padx=25, pady=(0, 12))

    memory_search_frame = ctk.CTkFrame(memory_window, fg_color="transparent")
    memory_search_frame.pack(fill="x", padx=25, pady=(0, 10))
    memory_search_entry = ctk.CTkEntry(memory_search_frame, placeholder_text="Search memories")
    memory_search_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

    form = ctk.CTkFrame(memory_window, fg_color="transparent")
    form.pack(fill="both", expand=True, padx=25)
    ctk.CTkLabel(form, text=TEXT["type"]).pack(anchor="w")
    type_box = ctk.CTkOptionMenu(form, values=["preference", "fact", "project", "temporary"])
    type_box.set("fact")
    type_box.pack(fill="x", pady=(2, 10))
    ctk.CTkLabel(form, text=TEXT["content"]).pack(anchor="w")
    content_box = ctk.CTkTextbox(form, height=120, wrap="word")
    content_box.pack(fill="both", expand=True, pady=(2, 10))
    ctk.CTkLabel(form, text=TEXT["importance"]).pack(anchor="w")
    importance_box = ctk.CTkOptionMenu(form, values=["low", "normal", "high"])
    importance_box.set("normal")
    importance_box.pack(fill="x", pady=(2, 12))
    enabled_var = ctk.BooleanVar(value=True)
    enabled_switch = ctk.CTkSwitch(form, text="Enable Memory", variable=enabled_var, command=lambda: toggle_memory())
    enabled_switch.pack(anchor="w", pady=(0, 10))
    status = ctk.CTkLabel(form, text="", text_color="gray")
    status.pack(anchor="w", pady=(0, 8))

    def search_memory_list():
        refresh_memory_list(memory_search_entry.get())
        logger.info("Memory searched")

    ctk.CTkButton(memory_search_frame, text="Search", width=80, command=search_memory_list).pack(side="right")

    memory_filter_frame = ctk.CTkFrame(memory_window, fg_color="transparent")
    memory_filter_frame.pack(fill="x", padx=25, pady=(0, 10))
    type_filter = ctk.CTkOptionMenu(memory_filter_frame, values=["All Types", "preference", "fact", "project", "temporary"], width=150)
    type_filter.set("All Types")
    type_filter.pack(side="left", padx=(0, 6))
    importance_filter = ctk.CTkOptionMenu(memory_filter_frame, values=["All Importance", "low", "normal", "high"], width=150)
    importance_filter.set("All Importance")
    importance_filter.pack(side="left", padx=6)
    enabled_filter = ctk.CTkOptionMenu(memory_filter_frame, values=["All Status", "Enabled", "Disabled"], width=120)
    enabled_filter.set("All Status")
    enabled_filter.pack(side="left", padx=6)

    def refresh_memory_list(keyword=""):
        nonlocal records
        selected_type = type_filter.get()
        selected_importance = importance_filter.get()
        selected_enabled = enabled_filter.get()
        records = search_memories(
            store.list_memories(),
            keyword,
            memory_type=None if selected_type == "All Types" else selected_type,
            importance=None if selected_importance == "All Importance" else selected_importance,
            enabled=None if selected_enabled == "All Status" else selected_enabled == "Enabled"
        )
        logger.info(f"Memory loaded: {len(records)}")
        labels = [
            f"{item.get('type', 'fact')} | {item.get('content', '')[:45]} | "
            f"{item.get('importance', 'normal')} | "
            f"{'Enabled' if item.get('enabled', True) else 'Disabled'} | "
            f"{item.get('updated_time', '').replace('T', ' ')}"
            for item in records
        ]
        list_box.configure(values=labels or ["No memories available"])
        list_box.set(labels[0] if labels else "No memories available")

    def apply_memory_filters(_value=None):
        refresh_memory_list(memory_search_entry.get())

    type_filter.configure(command=apply_memory_filters)
    importance_filter.configure(command=apply_memory_filters)
    enabled_filter.configure(command=apply_memory_filters)

    def select_memory(value):
        index = list_box.cget("values").index(value) if value in list_box.cget("values") else -1
        if index < 0 or index >= len(records):
            selected_id["value"] = None
            return
        item = records[index]
        selected_id["value"] = item.get("id")
        type_box.set(item.get("type", "fact"))
        importance_box.set(item.get("importance", "normal"))
        enabled_var.set(bool(item.get("enabled", True)))
        content_box.delete("1.0", "end")
        content_box.insert("1.0", item.get("content", ""))

    list_box.configure(command=select_memory)

    def clear_form():
        selected_id["value"] = None
        type_box.set("fact")
        importance_box.set("normal")
        enabled_var.set(True)
        content_box.delete("1.0", "end")

    def save_memory():
        content = content_box.get("1.0", "end").strip()
        if not content:
            status.configure(text="Please enter memory content.", text_color="orange")
            return
        if selected_id["value"]:
            store.update(selected_id["value"], type_box.get(), content, importance_box.get())
            store.set_enabled(selected_id["value"], enabled_var.get())
            logger.info("Memory updated")
            status.configure(text="Memory updated.", text_color="#32CD32")
        else:
            store.create(type_box.get(), content, importance_box.get())
            logger.info("Memory created")
            status.configure(text="Memory created.", text_color="#32CD32")
        clear_form()
        refresh_memory_list()

    def toggle_memory():
        if not selected_id["value"]:
            return
        store.set_enabled(selected_id["value"], enabled_var.get())
        logger.info("Memory enabled changed")
        status.configure(text="Memory status updated.", text_color="#32CD32")
        refresh_memory_list(memory_search_entry.get())

    def delete_memory():
        if not selected_id["value"]:
            return
        if not messagebox.askyesno("Delete Memory", "Delete selected memory?", parent=memory_window):
            return
        store.delete(selected_id["value"])
        logger.info("Memory deleted")
        status.configure(text="Memory deleted.", text_color="gray")
        clear_form()
        refresh_memory_list()

    def export_memory():
        target = filedialog.asksaveasfilename(
            title="瀵煎嚭璁板繂",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            parent=memory_window
        )
        if not target:
            return
        try:
            Path(target).write_text(
                json.dumps(store.list_memories(), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.info("Memory exported")
            status.configure(text="Memory exported.", text_color="#32CD32")
        except (OSError, TypeError) as error:
            logger.error(f"Memory export failed: {error}")
            status.configure(text="Memory export failed.", text_color="red")

    def import_memory():
        source = filedialog.askopenfilename(
            title="瀵煎叆璁板繂",
            filetypes=[("JSON", "*.json")],
            parent=memory_window
        )
        if not source:
            return
        try:
            imported = json.loads(Path(source).read_text(encoding="utf-8"))
            if not isinstance(imported, list):
                raise ValueError("Invalid memory format")
            added = store.merge(imported)
            refresh_memory_list(memory_search_entry.get())
            logger.info("Memory imported")
            status.configure(text=f"Imported {added} memory record(s).", text_color="#32CD32")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            logger.error(f"Memory import failed: {error}")
            status.configure(text="Invalid memory file format. Import failed.", text_color="red")

    buttons = ctk.CTkFrame(memory_window, fg_color="transparent")
    buttons.pack(fill="x", padx=25, pady=(0, 20))
    ctk.CTkButton(buttons, text=TEXT["add"], command=clear_form).pack(side="left", expand=True, fill="x", padx=(0, 6))
    ctk.CTkButton(buttons, text=TEXT["save"], command=save_memory).pack(side="left", expand=True, fill="x", padx=6)
    ctk.CTkButton(buttons, text=TEXT["delete"], command=delete_memory).pack(side="left", expand=True, fill="x", padx=6)
    ctk.CTkButton(buttons, text="瀵煎嚭璁板繂", command=export_memory).pack(side="left", expand=True, fill="x", padx=6)
    ctk.CTkButton(buttons, text="瀵煎叆璁板繂", command=import_memory).pack(side="left", expand=True, fill="x", padx=6)

    def close_memory():
        global memory_window
        memory_window.destroy()
        memory_window = None

    ctk.CTkButton(buttons, text=TEXT["close"], command=close_memory).pack(side="left", expand=True, fill="x", padx=(6, 0))
    memory_window.protocol("WM_DELETE_WINDOW", close_memory)
    refresh_memory_list()


def show_knowledge():
    global knowledge_window
    if knowledge_window is not None and knowledge_window.winfo_exists():
        knowledge_window.focus()
        knowledge_window.lift()
        return

    logger.info("Knowledge loaded")
    knowledge_window = ctk.CTkToplevel(app)
    knowledge_window.title("Knowledge Base")
    knowledge_window.geometry("900x760")
    knowledge_window.minsize(760, 640)
    knowledge_window.transient(app)

    ctk.CTkLabel(
        knowledge_window,
        text="Knowledge Base",
        font=("Microsoft YaHei", 22, "bold")
    ).pack(anchor="w", padx=25, pady=(20, 12))

    search_frame = ctk.CTkFrame(knowledge_window, fg_color="transparent")
    search_frame.pack(fill="x", padx=25, pady=(0, 10))

    search_entry = ctk.CTkEntry(search_frame, placeholder_text="Search knowledge")
    search_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

    enabled_filter = ctk.CTkOptionMenu(
        search_frame,
        values=["All", "Enabled", "Disabled", "Error"],
        width=130
    )
    stored_filter = settings.get("knowledge.enabled_filter", "All")
    if stored_filter == "Enabled Only":
        stored_filter = "Enabled"
    elif stored_filter == "Disabled Only":
        stored_filter = "Disabled"
    if stored_filter not in {"All", "Enabled", "Disabled", "Error"}:
        stored_filter = "All"
    enabled_filter.set(stored_filter)
    enabled_filter.pack(side="left", padx=(0, 6))

    stats_label = ctk.CTkLabel(
        knowledge_window,
        text="",
        font=("Microsoft YaHei", 12),
        text_color="gray"
    )
    stats_label.pack(anchor="w", padx=25, pady=(0, 8))

    index_status_label = ctk.CTkLabel(
        knowledge_window,
        text="",
        font=("Microsoft YaHei", 12),
        text_color="gray"
    )
    index_status_label.pack(anchor="w", padx=25, pady=(0, 8))

    list_box = ctk.CTkOptionMenu(knowledge_window, values=["No knowledge files available"], width=680)
    list_box.pack(fill="x", padx=25, pady=(0, 12))

    detail_box = ctk.CTkTextbox(knowledge_window, height=250, wrap="word")
    detail_box.pack(fill="both", expand=True, padx=25, pady=(0, 10))
    detail_box.configure(state="disabled")

    preview_search_frame = ctk.CTkFrame(knowledge_window, fg_color="transparent")
    preview_search_frame.pack(fill="x", padx=25, pady=(0, 10))
    preview_search_entry = ctk.CTkEntry(preview_search_frame, placeholder_text="Search in Preview")
    preview_search_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
    preview_search_label = ctk.CTkLabel(
        preview_search_frame,
        text="Matches: 0",
        font=("Microsoft YaHei", 12),
        text_color="gray"
    )
    preview_search_label.pack(side="left", padx=(0, 6))

    knowledge_records = []
    visible_records = []
    backup_records = []
    selected_record = {"record": None}
    selected_backup = {"record": None}
    current_keyword = {"value": ""}
    preview_state = {"content": "", "matches": [], "current": -1, "keyword": ""}

    def format_size(size):
        try:
            value = int(size)
        except (TypeError, ValueError):
            value = 0
        if value >= 1024 * 1024:
            return f"{value / 1024 / 1024:.1f} MB"
        if value >= 1024:
            return f"{value / 1024:.1f} KB"
        return f"{value} B"

    def knowledge_label(record):
        status = {
            "OK": "OK",
            "Missing File": "Missing File",
            "Invalid Knowledge File": "Invalid Knowledge File",
            "Read Error": "Read Error"
        }.get(record.get("status", "OK"), "Read Error")
        enabled_text = status if status != "OK" else ("Enabled" if record.get("enabled", True) else "Disabled")
        embedding_state = knowledge_store.embedding_state(record)
        embedding_text = embedding_state.get("status", record.get("embedding_status", "Not Indexed"))
        vector_text = "Ready" if embedding_state.get("has_embedding") and not embedding_state.get("stale") else embedding_text
        return (
            f"{record.get('file_name', 'Unknown')}\n"
            f"{record.get('file_type', '').upper()} | "
            f"{format_size(record.get('file_size', 0))} | "
            f"{enabled_text} | "
            f"Embedding: {embedding_text} | "
            f"Vector: {vector_text} | "
            f"{record.get('added_time', '')} | "
            f"Updated: {record.get('updated_time', '')}"
        )

    def backup_label(record):
        return (
            f"{record.get('name', 'Unknown')}\n"
            f"Created: {record.get('created_time', '') or 'Unknown'} | "
            f"Version: {record.get('app_version', record.get('backup_version', 'Unknown'))} | "
            f"Size: {format_size(record.get('file_size', 0))} | "
            f"Status: {record.get('status', 'OK')}"
        )

    def set_detail(text):
        detail_box.configure(state="normal")
        detail_box.delete("1.0", "end")
        detail_box.insert("end", text)
        detail_box.configure(state="disabled")

    def show_detail(record):
        if record:
            selected_record["record"] = record
            enabled_text = "Yes" if record.get("enabled", True) else "No"
            embedding_state = knowledge_store.embedding_state(record)
            vector_text = "Ready" if embedding_state.get("has_embedding") and not embedding_state.get("stale") else embedding_state.get("status", "Not Indexed")
            set_detail(
                f"File: {record.get('file_name', '')}\n"
                f"Type: {record.get('file_type', '')}\n"
                f"Size: {format_size(record.get('file_size', 0))}\n"
                f"Added: {record.get('added_time', '')}\n"
                f"Updated: {record.get('updated_time', '')}\n"
                f"Characters: {record.get('character_count', len(str(record.get('content', ''))))}\n"
                f"Retrievable: {'Yes' if knowledge_store.valid_for_retrieval(record) else 'No'}\n"
                f"Enabled: {enabled_text}\n"
                f"Status: {record.get('status', 'OK')}\n"
                f"Embedding Status: {embedding_state.get('status', record.get('embedding_status', 'Not Indexed'))}\n"
                f"Embedding Model: {record.get('embedding_model', '') or 'None'}\n"
                f"Embedding Updated: {record.get('embedding_updated_time', '') or 'Never'}\n"
                f"Embedding Dimensions: {record.get('embedding_dimensions', 0)}\n"
                f"Vector Index Status: {vector_text}\n"
                f"Needs Reindex: {'Yes' if embedding_state.get('needs_reindex') else 'No'}\n"
                f"Index Reason: {embedding_state.get('reason', '') or 'OK'}\n"
                f"Source Path: {record.get('source_path', '') or 'Unknown'}\n"
                f"Stored Path: {record.get('stored_path', '')}\n\n"
                "Click Preview to load a limited content preview."
            )
        else:
            selected_record["record"] = None
            set_detail("No knowledge file selected.")

    def update_stats(records):
        stats = knowledge_store.health()
        index_health = stats.get("vector_index", {})
        stats_label.configure(
            text=(
                f"Knowledge Enabled: {'Yes' if settings.get('knowledge.enabled', True) else 'No'} | "
                f"Total: {stats['total']} | TXT: {stats['txt']} | "
                f"Markdown: {stats['md']} | PDF: {stats['pdf']} | "
                f"Enabled: {stats['enabled']} | Disabled: {stats['disabled']} | "
                f"Retrievable: {stats['retrievable']} | "
                f"Indexed: {stats.get('embedding_indexed', 0)} | "
                f"Stale: {stats.get('embedding_stale', 0)} | "
                f"Needs Reindex: {stats.get('embedding_needs_reindex', 0)}"
            )
        )
        index_status_label.configure(
            text=(
                f"Vector Index: {'Present' if index_health.get('exists') else 'Missing'} | "
                f"Entries: {index_health.get('entries', 0)} | "
                f"Indexed: {index_health.get('indexed', 0)} | "
                f"Missing: {index_health.get('missing', 0)} | "
                f"Invalid: {index_health.get('invalid', 0)} | "
                f"Orphaned: {index_health.get('orphaned', 0)} | "
                f"Updated: {index_health.get('updated_time', '') or 'Never'}"
            )
        )

    def filter_records(records, keyword):
        keyword = keyword.strip().casefold()
        selected_filter = enabled_filter.get()
        filtered = []
        for item in records:
            enabled = bool(item.get("enabled", True))
            status = str(item.get("status", "OK"))
            if selected_filter == "Enabled" and (not enabled or status != "OK"):
                continue
            if selected_filter == "Disabled" and enabled:
                continue
            if selected_filter == "Error" and status == "OK":
                continue
            if keyword and not (
                keyword in str(item.get("file_name", "")).casefold()
                or keyword in str(item.get("file_type", "")).casefold()
                or keyword in str(item.get("content", "")).casefold()
            ):
                continue
            filtered.append(item)
        return filtered

    def sort_records(records):
        field = sort_field.get()
        reverse = sort_direction.get() == "Descending"

        def sort_key(item):
            if field == "File Name":
                return str(item.get("file_name", "")).casefold()
            if field == "File Type":
                return str(item.get("file_type", "")).casefold()
            if field == "File Size":
                return int(item.get("file_size", 0) or 0)
            if field == "Added Time":
                return str(item.get("added_time", ""))
            if field == "Characters":
                return int(item.get("character_count", 0) or 0)
            if field == "Enabled":
                return 1 if item.get("enabled", True) else 0
            return str(item.get("updated_time", ""))

        return sorted(records, key=sort_key, reverse=reverse)

    def refresh_knowledge_list():
        set_detail("Loading knowledge files...")

        def load_records():
            try:
                loaded_records = knowledge_store.list_items()
                filtered_records = filter_records(loaded_records, current_keyword["value"])
                error_message = None
            except Exception as error:
                loaded_records = []
                filtered_records = []
                error_message = str(error)

            def update_records():
                nonlocal knowledge_records, visible_records
                if knowledge_window is None or not knowledge_window.winfo_exists():
                    return
                if error_message:
                    set_detail(f"Knowledge load failed: {error_message}")
                    logger.error(f"Knowledge load failed: {error_message}")
                    return
                knowledge_records = loaded_records
                visible_records = sort_records(filtered_records)
                labels = [knowledge_label(item) for item in visible_records]
                list_box.configure(values=labels or ["No knowledge files available"])
                list_box.set(labels[0] if labels else "No knowledge files available")
                update_stats(knowledge_records)
                search_text = current_keyword["value"] or "None"
                search_result_label.configure(
                    text=(
                        f"Search: {search_text} | Filter: {enabled_filter.get()} | "
                        f"Results: {len(visible_records)} / {len(knowledge_records)}"
                    )
                )
                show_detail(visible_records[0] if visible_records else None)
                logger.info(f"Knowledge loaded: {len(knowledge_records)}")

            try:
                knowledge_window.after(0, update_records)
            except Exception:
                return

        threading.Thread(target=load_records, daemon=True).start()

    def select_knowledge(value):
        record = next((item for item in visible_records if knowledge_label(item) == value), None)
        show_detail(record)

    list_box.configure(command=select_knowledge)

    def search_knowledge_list():
        current_keyword["value"] = search_entry.get().strip()
        settings.set("knowledge.enabled_filter", enabled_filter.get())
        refresh_knowledge_list()
        logger.info("Knowledge searched")

    def clear_search():
        search_entry.delete(0, "end")
        current_keyword["value"] = ""
        enabled_filter.set("All")
        settings.set("knowledge.enabled_filter", "All")
        refresh_knowledge_list()
        logger.info("Knowledge search cleared")

    ctk.CTkButton(search_frame, text="Search", width=90, command=search_knowledge_list).pack(side="left", padx=(0, 6))
    ctk.CTkButton(search_frame, text="Clear Search", width=110, command=clear_search).pack(side="left")

    sort_frame = ctk.CTkFrame(knowledge_window, fg_color="transparent")
    sort_frame.pack(fill="x", padx=25, pady=(0, 8))
    sort_field = ctk.CTkOptionMenu(
        sort_frame,
        values=["Updated Time", "File Name", "File Type", "File Size", "Added Time", "Characters", "Enabled"],
        width=160
    )
    sort_field.set(settings.get("knowledge.sort_field", "Updated Time"))
    sort_field.pack(side="left", padx=(0, 6))
    sort_direction = ctk.CTkOptionMenu(sort_frame, values=["Descending", "Ascending"], width=130)
    sort_direction.set(settings.get("knowledge.sort_direction", "Descending"))
    sort_direction.pack(side="left", padx=(0, 6))
    search_result_label = ctk.CTkLabel(sort_frame, text="", font=("Microsoft YaHei", 12), text_color="gray")
    search_result_label.pack(side="left", padx=(8, 0))

    def change_enabled_filter(_value):
        settings.set("knowledge.enabled_filter", enabled_filter.get())
        refresh_knowledge_list()

    enabled_filter.configure(command=change_enabled_filter)

    def sort_knowledge_list(_value=None):
        settings.set("knowledge.sort_field", sort_field.get())
        settings.set("knowledge.sort_direction", sort_direction.get())
        refresh_knowledge_list()
        logger.info("Knowledge list sorted")

    sort_field.configure(command=sort_knowledge_list)
    sort_direction.configure(command=sort_knowledge_list)

    def add_knowledge():
        file_path = filedialog.askopenfilename(
            parent=knowledge_window,
            title="Add Knowledge",
            filetypes=[
                ("Knowledge files", "*.txt *.md *.pdf"),
                ("Text files", "*.txt"),
                ("Markdown files", "*.md"),
                ("PDF files", "*.pdf")
            ]
        )
        if not file_path:
            return
        set_detail("Adding knowledge file...")

        def run_add():
            try:
                knowledge_store.add_file(file_path)
                error_message = None
            except (OSError, ValueError) as error:
                error_message = str(error)

            def finish_add():
                if knowledge_window is None or not knowledge_window.winfo_exists():
                    return
                if error_message:
                    logger.error(f"Knowledge add failed: {error_message}")
                    messagebox.showerror("Knowledge Base", error_message, parent=knowledge_window)
                    return
                refresh_knowledge_list()
                logger.info("Knowledge added")

            try:
                knowledge_window.after(0, finish_add)
            except Exception:
                return

        threading.Thread(target=run_add, daemon=True).start()

    def delete_knowledge():
        selected = list_box.get()
        record = next((item for item in knowledge_records if knowledge_label(item) == selected), None)
        if record is None:
            return
        if not messagebox.askyesno("Delete Knowledge", "Delete selected knowledge file?", parent=knowledge_window):
            return
        try:
            knowledge_store.delete(record["id"])
            refresh_knowledge_list()
            logger.info("Knowledge deleted")
        except (OSError, KeyError) as error:
            logger.error(f"Knowledge delete failed: {error}")
            messagebox.showerror("Knowledge Base", str(error), parent=knowledge_window)

    def toggle_knowledge_enabled():
        record = selected_record["record"]
        if record is None:
            set_detail("No knowledge file selected.")
            return
        new_value = not bool(record.get("enabled", True))
        try:
            updated = knowledge_store.set_enabled(record["id"], new_value)
            selected_record["record"] = updated
            refresh_knowledge_list()
            logger.info("Knowledge enabled" if new_value else "Knowledge disabled")
        except (OSError, KeyError) as error:
            logger.error(f"Knowledge enabled change failed: {error}")
            messagebox.showerror("Knowledge Base", str(error), parent=knowledge_window)

    def backup_directory():
        configured = Path(str(settings.get("knowledge.backup_path", "data/knowledge/backups")))
        if configured.is_absolute():
            return configured
        return Path(__file__).resolve().parent / configured

    def refresh_backup_history():
        nonlocal backup_records
        backup_records = knowledge_store.list_backups(backup_directory())
        labels = [backup_label(item) for item in backup_records]
        backup_selector.configure(values=labels or ["No backups available"])
        backup_selector.set(labels[0] if labels else "No backups available")
        selected_backup["record"] = backup_records[0] if backup_records else None

    def select_backup(value):
        selected_backup["record"] = next(
            (item for item in backup_records if backup_label(item) == value),
            None
        )

    def knowledge_config_snapshot():
        return {
            "enabled": settings.get("knowledge.enabled", True),
            "max_results": settings.get("knowledge.max_results", 3),
            "preview_limit": settings.get("knowledge.preview_limit", 5000),
            "sort_field": settings.get("knowledge.sort_field", "Updated Time"),
            "sort_direction": settings.get("knowledge.sort_direction", "Descending"),
            "backup_path": settings.get("knowledge.backup_path", "data/knowledge/backups"),
            "max_backup_count": settings.get("knowledge.max_backup_count", 10)
        }

    def restore_knowledge_config(config):
        for key in (
            "enabled",
            "max_results",
            "preview_limit",
            "sort_field",
            "sort_direction",
            "backup_path",
            "max_backup_count"
        ):
            if key in config:
                settings.set(f"knowledge.{key}", config[key])

    def create_knowledge_backup():
        set_detail("Creating Knowledge backup...")

        def run_create_backup():
            try:
                result = knowledge_store.create_backup(
                    backup_directory(),
                    config=knowledge_config_snapshot(),
                    app_version=VERSION,
                    max_backup_count=settings.get("knowledge.max_backup_count", 10)
                )
                error_message = None
            except Exception as error:
                result = {}
                error_message = str(error)

            def finish_create_backup():
                if knowledge_window is None or not knowledge_window.winfo_exists():
                    return
                if error_message:
                    set_detail(f"Knowledge backup create failed: {error_message}")
                    logger.error(f"Knowledge backup create failed: {error_message}")
                    return
                refresh_backup_history()
                cleanup_note = (
                    "\nBackup count exceeds max_backup_count. Consider deleting old backups."
                    if result.get("cleanup_required") else ""
                )
                set_detail(
                    "Knowledge backup created\n\n"
                    f"File: {result.get('path', '')}\n"
                    f"Backup Count: {result.get('backup_count', 0)} / {result.get('max_backup_count', 10)}"
                    f"{cleanup_note}"
                )
                logger.info("Knowledge backup created")

            try:
                knowledge_window.after(0, finish_create_backup)
            except Exception:
                return

        threading.Thread(target=run_create_backup, daemon=True).start()

    def delete_knowledge_backup():
        record = selected_backup["record"]
        if record is None:
            set_detail("No backup selected.")
            return
        if not messagebox.askyesno("Delete Backup", "Delete selected Knowledge backup?", parent=knowledge_window):
            return
        set_detail("Deleting Knowledge backup...")

        def run_delete_backup():
            try:
                deleted = knowledge_store.delete_backup(record["path"])
                error_message = None
            except Exception as error:
                deleted = ""
                error_message = str(error)

            def finish_delete_backup():
                if knowledge_window is None or not knowledge_window.winfo_exists():
                    return
                if error_message:
                    set_detail(f"Knowledge backup delete failed: {error_message}")
                    logger.error(f"Knowledge backup delete failed: {error_message}")
                    return
                refresh_backup_history()
                set_detail(f"Knowledge backup deleted:\n{deleted}")
                logger.info("Knowledge backup deleted")

            try:
                knowledge_window.after(0, finish_delete_backup)
            except Exception:
                return

        threading.Thread(target=run_delete_backup, daemon=True).start()

    def restore_knowledge_backup():
        record = selected_backup["record"]
        if record is None:
            set_detail("No backup selected.")
            return
        if record.get("status") != "OK":
            set_detail(record.get("status", "Invalid backup format."))
            logger.error("Knowledge backup restore failed")
            return
        if not messagebox.askyesno("Restore Backup", "Restore selected Knowledge backup?", parent=knowledge_window):
            return
        set_detail("Restoring Knowledge backup...")

        def run_restore_backup():
            try:
                result = knowledge_store.import_backup(record["path"], current_version=VERSION)
                restore_knowledge_config(result.get("config", {}))
                error_message = None
            except ValueError as error:
                result = {}
                error_message = str(error)
            except Exception as error:
                result = {}
                error_message = f"Invalid backup format. {error}"

            def finish_restore_backup():
                if knowledge_window is None or not knowledge_window.winfo_exists():
                    return
                if error_message:
                    set_detail(error_message)
                    logger.error("Knowledge backup restore failed")
                    return
                refresh_knowledge_list()
                refresh_backup_history()
                migration_note = ""
                if result.get("migration_required"):
                    migration_note = "\nBackup migration may be required."
                    logger.info("Knowledge backup migration required")
                set_detail(
                    "Knowledge backup restored\n\n"
                    f"Imported: {result.get('imported', 0)} file(s)\n"
                    f"Current Version: {result.get('current_version', VERSION)}\n"
                    f"Backup Version: {result.get('app_version', 'Unknown')}"
                    f"{migration_note}"
                )
                logger.info("Knowledge backup restored")

            try:
                knowledge_window.after(0, finish_restore_backup)
            except Exception:
                return

        threading.Thread(target=run_restore_backup, daemon=True).start()

    def export_knowledge():
        default_dir = backup_directory()
        default_dir.mkdir(parents=True, exist_ok=True)
        target = filedialog.asksaveasfilename(
            parent=knowledge_window,
            title="Export Knowledge",
            initialdir=str(default_dir),
            initialfile="Aurora_Knowledge_Backup.json",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")]
        )
        if not target:
            return
        set_detail("Exporting Knowledge...")

        def run_export():
            try:
                output = knowledge_store.export_backup(
                    target,
                    config=knowledge_config_snapshot(),
                    app_version=VERSION
                )
                error_message = None
            except Exception as error:
                output = None
                error_message = str(error)

            def finish_export():
                if knowledge_window is None or not knowledge_window.winfo_exists():
                    return
                if error_message:
                    set_detail(f"Knowledge export failed: {error_message}")
                    logger.error(f"Knowledge export failed: {error_message}")
                    return
                refresh_backup_history()
                set_detail(f"Knowledge exported:\n{output}")
                logger.info("Knowledge exported")

            try:
                knowledge_window.after(0, finish_export)
            except Exception:
                return

        threading.Thread(target=run_export, daemon=True).start()

    def import_knowledge():
        source = filedialog.askopenfilename(
            parent=knowledge_window,
            title="Import Knowledge",
            filetypes=[("JSON", "*.json")]
        )
        if not source:
            return
        set_detail("Importing Knowledge...")

        def run_import():
            try:
                result = knowledge_store.import_backup(source, current_version=VERSION)
                restore_knowledge_config(result.get("config", {}))
                error_message = None
            except ValueError as error:
                result = None
                error_message = str(error)
            except Exception as error:
                result = None
                error_message = f"Invalid knowledge backup file. {error}"

            def finish_import():
                if knowledge_window is None or not knowledge_window.winfo_exists():
                    return
                if error_message:
                    set_detail(error_message)
                    logger.error(f"Knowledge import failed: {error_message}")
                    return
                refresh_knowledge_list()
                refresh_backup_history()
                migration_note = "\nBackup migration may be required." if result.get("migration_required") else ""
                if result.get("migration_required"):
                    logger.info("Knowledge backup migration required")
                set_detail(f"Knowledge imported: {result.get('imported', 0)} file(s){migration_note}")
                logger.info("Knowledge imported")

            try:
                knowledge_window.after(0, finish_import)
            except Exception:
                return

        threading.Thread(target=run_import, daemon=True).start()

    def health_check_knowledge():
        set_detail("Checking Knowledge Health...")

        def run_health():
            try:
                health = knowledge_store.health_with_backups(backup_directory())
                error_message = None
            except Exception as error:
                health = {}
                error_message = str(error)

            def finish_health():
                if knowledge_window is None or not knowledge_window.winfo_exists():
                    return
                if error_message:
                    set_detail(f"Knowledge health check failed: {error_message}")
                    logger.error(f"Knowledge health check failed: {error_message}")
                    return
                set_detail(
                    "Knowledge Health\n\n"
                    f"Total Files: {health.get('total', 0)}\n"
                    f"Enabled Files: {health.get('enabled', 0)}\n"
                    f"Disabled Files: {health.get('disabled', 0)}\n"
                    f"TXT Files: {health.get('txt', 0)}\n"
                    f"Markdown Files: {health.get('md', 0)}\n"
                    f"PDF Files: {health.get('pdf', 0)}\n"
                    f"Retrievable Files: {health.get('retrievable', 0)}\n"
                    f"Total Characters: {health.get('characters', 0)}\n"
                    f"Missing Files: {health.get('missing', 0)}\n"
                    f"Metadata Errors: {health.get('metadata_errors', 0)}\n"
                    f"Embedding Indexed: {health.get('embedding_indexed', 0)}\n"
                    f"Embedding Not Indexed: {health.get('embedding_not_indexed', 0)}\n"
                    f"Embedding Stale: {health.get('embedding_stale', 0)}\n"
                    f"Embedding Invalid: {health.get('embedding_invalid', 0)}\n"
                    f"Embedding Needs Reindex: {health.get('embedding_needs_reindex', 0)}\n"
                    f"Vector Index Entries: {health.get('vector_index', {}).get('entries', 0)}\n"
                    f"Vector Index Missing: {health.get('vector_index', {}).get('missing', 0)}\n"
                    f"Vector Index Stale: {health.get('vector_index', {}).get('stale', 0)}\n"
                    f"Vector Index Invalid: {health.get('vector_index', {}).get('invalid', 0)}\n"
                    f"Vector Index Orphaned: {health.get('vector_index', {}).get('orphaned', 0)}\n"
                    f"Backups: {health.get('backup_count', 0)}\n"
                    f"Last Backup: {health.get('last_backup_time', 'None')}\n"
                    f"Latest Backup Version: {health.get('latest_backup_version', 'None')}"
                )
                logger.info("Knowledge health checked")

            try:
                knowledge_window.after(0, finish_health)
            except Exception:
                return

        threading.Thread(target=run_health, daemon=True).start()

    def show_index_status():
        set_detail("Checking Vector Index...")

        def run_index_health():
            try:
                records = knowledge_store.list_items()
                health = knowledge_store.vector_index_health(records)
                error_message = None
            except Exception as error:
                records = []
                health = {}
                error_message = str(error)

            def finish_index_health():
                if knowledge_window is None or not knowledge_window.winfo_exists():
                    return
                if error_message:
                    set_detail(f"Vector index check failed: {error_message}")
                    logger.error(f"Knowledge vector index check failed: {error_message}")
                    return
                set_detail(
                    "Vector Index Status\n\n"
                    f"Knowledge Enabled: {'Yes' if settings.get('knowledge.enabled', True) else 'No'}\n"
                    f"Documents: {len(records)}\n"
                    f"Index File: {health.get('path', '')}\n"
                    f"Exists: {'Yes' if health.get('exists') else 'No'}\n"
                    f"Format: {health.get('format', '')}\n"
                    f"Version: {health.get('version', '')}\n"
                    f"Updated: {health.get('updated_time', '') or 'Never'}\n"
                    f"Entries: {health.get('entries', 0)}\n"
                    f"Indexed: {health.get('indexed', 0)}\n"
                    f"Missing: {health.get('missing', 0)}\n"
                    f"Stale: {health.get('stale', 0)}\n"
                    f"Invalid: {health.get('invalid', 0)}\n"
                    f"Orphaned: {health.get('orphaned', 0)}\n"
                    f"Needs Reindex: {health.get('needs_reindex', 0)}"
                )
                logger.info("Knowledge vector index checked")

            try:
                knowledge_window.after(0, finish_index_health)
            except Exception:
                return

        threading.Thread(target=run_index_health, daemon=True).start()

    def rebuild_vector_index():
        if not messagebox.askyesno("Rebuild Vector Index", "Rebuild Knowledge vector index now?", parent=knowledge_window):
            return
        set_detail("Rebuilding Vector Index...")

        def run_rebuild():
            try:
                result = knowledge_store.build_vector_index()
                health = knowledge_store.vector_index_health()
                error_message = None
            except Exception as error:
                result = {}
                health = {}
                error_message = str(error)

            def finish_rebuild():
                if knowledge_window is None or not knowledge_window.winfo_exists():
                    return
                if error_message:
                    set_detail(f"Vector index rebuild failed: {error_message}")
                    logger.error(f"Knowledge vector index rebuild failed: {error_message}")
                    return
                refresh_knowledge_list()
                set_detail(
                    "Vector Index Rebuilt\n\n"
                    f"Indexed: {result.get('indexed', 0)}\n"
                    f"Errors: {len(result.get('errors', []))}\n"
                    f"Index File: {result.get('index_file', '')}\n"
                    f"Entries: {health.get('entries', 0)}\n"
                    f"Needs Reindex: {health.get('needs_reindex', 0)}"
                )
                logger.info("Knowledge vector index rebuilt")

            try:
                knowledge_window.after(0, finish_rebuild)
            except Exception:
                return

        threading.Thread(target=run_rebuild, daemon=True).start()

    def repair_knowledge_metadata():
        set_detail("Repairing Knowledge Metadata...")

        def run_repair():
            try:
                result = knowledge_store.repair_metadata()
                error_message = None
            except Exception as error:
                result = {}
                error_message = str(error)

            def finish_repair():
                if knowledge_window is None or not knowledge_window.winfo_exists():
                    return
                if error_message:
                    set_detail(f"Knowledge repair failed: {error_message}")
                    logger.error("Knowledge repair failed")
                    return
                refresh_knowledge_list()
                set_detail(
                    "Knowledge metadata repaired\n\n"
                    f"Records repaired: {result.get('repaired', 0)}\n"
                    f"Errors: {len(result.get('errors', []))}"
                )
                logger.info("Knowledge metadata repaired")
                logger.info("Knowledge repair completed")

            try:
                knowledge_window.after(0, finish_repair)
            except Exception:
                return

        threading.Thread(target=run_repair, daemon=True).start()

    def preview_knowledge():
        record = selected_record["record"]
        if record is None:
            set_detail("No knowledge file selected.")
            return
        set_detail("Loading preview...")

        def run_preview():
            try:
                preview = knowledge_store.preview_details(
                    record["id"],
                    limit=settings.get("knowledge.preview_limit", 5000)
                )
            except (OSError, KeyError) as error:
                preview = {
                    "file_name": record.get("file_name", ""),
                    "file_type": record.get("file_type", ""),
                    "character_count": 0,
                    "preview_count": 0,
                    "truncated": False,
                    "content": f"Preview failed: {error}"
                }

            def update_preview():
                if knowledge_window is None or not knowledge_window.winfo_exists():
                    return
                preview_state["content"] = preview.get("content", "")
                preview_state["matches"] = []
                preview_state["current"] = -1
                preview_state["keyword"] = ""
                preview_search_label.configure(text="Matches: 0")
                truncated_note = "\nContent preview truncated." if preview.get("truncated") else ""
                set_detail(
                    f"Preview: {preview.get('file_name', '')}\n"
                    f"Type: {preview.get('file_type', '')}\n"
                    f"Characters: {preview.get('character_count', 0)}\n"
                    f"Preview Characters: {preview.get('preview_count', 0)}\n"
                    f"Truncated: {'Yes' if preview.get('truncated') else 'No'}"
                    f"{truncated_note}\n\n"
                    f"{preview.get('content', '')}"
                )
                logger.info("Knowledge preview opened")

            try:
                knowledge_window.after(0, update_preview)
            except Exception:
                return

        threading.Thread(target=run_preview, daemon=True).start()

    def show_preview_match():
        matches = preview_state["matches"]
        current = preview_state["current"]
        if not matches or current < 0:
            preview_search_label.configure(text="Matches: 0")
            return
        position = matches[current]
        preview_search_label.configure(
            text=f"Matches: {len(matches)} | Current: {current + 1} / {len(matches)} | Position: {position}"
        )

    def search_preview_content():
        keyword = preview_search_entry.get().strip()
        preview_state["keyword"] = keyword
        preview_state["matches"] = knowledge_store.search_preview(preview_state["content"], keyword)
        preview_state["current"] = 0 if preview_state["matches"] else -1
        show_preview_match()
        logger.info("Knowledge preview searched")

    def next_preview_match():
        if not preview_state["matches"]:
            show_preview_match()
            return
        preview_state["current"] = (preview_state["current"] + 1) % len(preview_state["matches"])
        show_preview_match()
        logger.info("Knowledge preview next match")

    def clear_preview_search():
        preview_search_entry.delete(0, "end")
        preview_state["matches"] = []
        preview_state["current"] = -1
        preview_state["keyword"] = ""
        preview_search_label.configure(text="Matches: 0")
        logger.info("Knowledge preview search cleared")

    ctk.CTkButton(preview_search_frame, text="Search", width=85, command=search_preview_content).pack(side="left", padx=(0, 6))
    ctk.CTkButton(preview_search_frame, text="Next Match", width=105, command=next_preview_match).pack(side="left", padx=(0, 6))
    ctk.CTkButton(preview_search_frame, text="Clear", width=75, command=clear_preview_search).pack(side="left")

    retrieval_frame = ctk.CTkFrame(knowledge_window, fg_color="transparent")
    retrieval_frame.pack(fill="x", padx=25, pady=(0, 10))
    retrieval_entry = ctk.CTkEntry(retrieval_frame, placeholder_text="Test retrieval prompt")
    retrieval_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

    def test_retrieval():
        prompt = retrieval_entry.get().strip()
        if not prompt:
            set_detail("Please enter a test prompt.")
            return
        set_detail("Testing retrieval...")

        def run_test():
            try:
                max_results = max(0, int(settings.get("knowledge.max_results", 3)))
            except (TypeError, ValueError):
                max_results = 3
            items = knowledge_store.list_items()
            summary = retrieval_summary(
                prompt,
                items,
                max_results=max_results,
                knowledge_enabled=settings.get("knowledge.enabled", True)
            )

            def update_result():
                if knowledge_window is None or not knowledge_window.winfo_exists():
                    return
                results = summary.get("results", [])
                lines = [
                    "Summary",
                    f"Prompt: {summary.get('prompt', '')}",
                    f"Knowledge Enabled: {'Yes' if summary.get('knowledge_enabled') else 'No'}",
                    f"Maximum Knowledge Results: {summary.get('max_results', 0)}",
                    f"Matched Count: {summary.get('matched_count', 0)}",
                    f"Injected Count: {summary.get('injected_count', 0)}",
                    ""
                ]
                if not summary.get("knowledge_enabled"):
                    lines.append("Knowledge Retrieval is disabled in Settings.")
                elif not summary.get("enabled_available"):
                    lines.append("No enabled knowledge files available.")
                elif not results:
                    lines.append("No knowledge matched this prompt.")
                else:
                    lines.append("Matched:")
                    for item in results:
                        lines.append(f"\n{item.get('file_name', 'Unknown')}")
                        lines.append(f"Enabled: {'Yes' if item.get('enabled') else 'No'}")
                        lines.append(f"Status: {item.get('status', 'OK')}")
                        lines.append(f"Score: {item.get('score', 0)}")
                        lines.append(f"Matched Keywords: {', '.join(item.get('keywords', [])) or 'None'}")
                        if item.get("line"):
                            lines.append(f"Line: {item.get('line')}")
                        lines.append(f"Character Range: {item.get('start', 0)} - {item.get('end', 0)}")
                        lines.append(f"Snippet:\n{item.get('snippet', '') or 'No text snippet available.'}")
                        lines.append(f"Injected: {'Yes' if item.get('injected') else 'No'}")
                        if not item.get("enabled"):
                            lines.append("Status: skipped disabled file")
                            logger.info("Knowledge skipped disabled file")
                        elif item.get("status") == "Missing File":
                            lines.append("Status: skipped missing file")
                            logger.info("Knowledge skipped missing file")
                        elif item.get("status") != "OK":
                            lines.append("Status: skipped invalid file")
                            logger.info("Knowledge skipped invalid file")
                set_detail("\n".join(lines))
                logger.info("Knowledge retrieval tested")
                logger.info("Knowledge retrieval explained")

            try:
                knowledge_window.after(0, update_result)
            except Exception:
                return

        threading.Thread(target=run_test, daemon=True).start()

    ctk.CTkButton(retrieval_frame, text="Test Retrieval", width=120, command=test_retrieval).pack(side="left")

    maintenance_frame = ctk.CTkFrame(knowledge_window, fg_color="transparent")
    maintenance_frame.pack(fill="x", padx=25, pady=(0, 10))
    ctk.CTkButton(maintenance_frame, text="Create Backup", command=create_knowledge_backup).pack(side="left", expand=True, fill="x", padx=(0, 6))
    ctk.CTkButton(maintenance_frame, text="Export", command=export_knowledge).pack(side="left", expand=True, fill="x", padx=6)
    ctk.CTkButton(maintenance_frame, text="Import", command=import_knowledge).pack(side="left", expand=True, fill="x", padx=6)
    ctk.CTkButton(maintenance_frame, text="Health Check", command=health_check_knowledge).pack(side="left", expand=True, fill="x", padx=6)
    ctk.CTkButton(maintenance_frame, text="Repair Metadata", command=repair_knowledge_metadata).pack(side="left", expand=True, fill="x", padx=(6, 0))

    index_frame = ctk.CTkFrame(knowledge_window, fg_color="transparent")
    index_frame.pack(fill="x", padx=25, pady=(0, 10))
    ctk.CTkButton(index_frame, text="Index Status", command=show_index_status).pack(side="left", expand=True, fill="x", padx=(0, 6))
    ctk.CTkButton(index_frame, text="Rebuild Index", command=rebuild_vector_index).pack(side="left", expand=True, fill="x", padx=6)

    backup_frame = ctk.CTkFrame(knowledge_window, fg_color="transparent")
    backup_frame.pack(fill="x", padx=25, pady=(0, 10))
    backup_selector = ctk.CTkOptionMenu(
        backup_frame,
        values=["No backups available"],
        width=500,
        command=select_backup
    )
    backup_selector.pack(side="left", fill="x", expand=True, padx=(0, 6))
    ctk.CTkButton(backup_frame, text="Restore Backup", width=130, command=restore_knowledge_backup).pack(side="left", padx=(0, 6))
    ctk.CTkButton(backup_frame, text="Delete Backup", width=120, command=delete_knowledge_backup).pack(side="left")

    buttons = ctk.CTkFrame(knowledge_window, fg_color="transparent")
    buttons.pack(fill="x", padx=25, pady=(0, 20))

    ctk.CTkButton(buttons, text="Add Knowledge", command=add_knowledge).pack(side="left", expand=True, fill="x", padx=(0, 6))
    ctk.CTkButton(buttons, text="Delete Knowledge", command=delete_knowledge).pack(side="left", expand=True, fill="x", padx=6)
    ctk.CTkButton(buttons, text="Toggle Enabled", command=toggle_knowledge_enabled).pack(side="left", expand=True, fill="x", padx=6)
    ctk.CTkButton(buttons, text="Preview", command=preview_knowledge).pack(side="left", expand=True, fill="x", padx=6)
    ctk.CTkButton(buttons, text="Refresh", command=refresh_knowledge_list).pack(side="left", expand=True, fill="x", padx=6)

    def close_knowledge():
        global knowledge_window
        knowledge_window.destroy()
        knowledge_window = None

    ctk.CTkButton(buttons, text=TEXT["close"], command=close_knowledge).pack(side="left", expand=True, fill="x", padx=(6, 0))
    knowledge_window.protocol("WM_DELETE_WINDOW", close_knowledge)
    refresh_knowledge_list()
    refresh_backup_history()


def show_persona():
    global persona_window
    if persona_window is not None and persona_window.winfo_exists():
        persona_window.focus()
        persona_window.lift()
        return

    persona = persona_store.load()
    logger.info("Persona loaded")
    logger.info("Persona loaded timestamp updated")
    persona_state = {
        "last_loaded_time": persona.get("last_loaded_time", "Never loaded."),
        "last_updated_time": persona.get("last_updated_time", "Never loaded.")
    }
    persona_window = ctk.CTkToplevel(app)
    persona_window.title(TEXT["persona"])
    persona_window.geometry("860x720")
    persona_window.minsize(720, 560)
    persona_window.transient(app)

    ctk.CTkLabel(
        persona_window,
        text=TEXT["persona"],
        font=("Microsoft YaHei", 22, "bold")
    ).pack(anchor="w", padx=25, pady=(20, 12))

    persona_status_label = ctk.CTkLabel(
        persona_window,
        text="",
        font=("Microsoft YaHei", 12),
        text_color="gray"
    )
    persona_status_label.pack(anchor="w", padx=25, pady=(0, 8))

    content = ctk.CTkScrollableFrame(persona_window)
    content.pack(fill="both", expand=True, padx=25, pady=(0, 12))

    def add_label(text):
        ctk.CTkLabel(
            content,
            text=text,
            font=("Microsoft YaHei", 13, "bold")
        ).pack(anchor="w", padx=10, pady=(10, 4))

    add_label(TEXT["persona_name"])
    name_entry = ctk.CTkEntry(content)
    name_entry.pack(fill="x", padx=10, pady=(0, 6))
    name_entry.insert(0, persona.get("name", "Aurora"))

    add_label(TEXT["persona_description"])
    description_box = ctk.CTkTextbox(content, height=80, wrap="word")
    description_box.pack(fill="x", padx=10, pady=(0, 6))
    description_box.insert("1.0", persona.get("description", ""))

    add_label(TEXT["persona_style"])
    style_box = ctk.CTkTextbox(content, height=80, wrap="word")
    style_box.pack(fill="x", padx=10, pady=(0, 6))
    style_box.insert("1.0", persona.get("style", ""))

    add_label(TEXT["persona_rules"])
    rules_box = ctk.CTkTextbox(content, height=160, wrap="word")
    rules_box.pack(fill="both", expand=True, padx=10, pady=(0, 6))
    rules_box.insert("1.0", "\n".join(persona.get("rules", [])))

    character_label = ctk.CTkLabel(content, text="", font=("Microsoft YaHei", 12), text_color="gray")
    character_label.pack(anchor="w", padx=10, pady=(0, 6))

    add_label("Test Persona")
    test_prompt_entry = ctk.CTkEntry(content, placeholder_text="杈撳叆娴嬭瘯 Prompt")
    test_prompt_entry.pack(fill="x", padx=10, pady=(0, 6))

    preview_box = ctk.CTkTextbox(content, height=180, wrap="word")
    preview_box.pack(fill="both", expand=True, padx=10, pady=(0, 6))
    preview_box.insert("1.0", "")
    preview_box.configure(state="disabled")

    status_label = ctk.CTkLabel(
        persona_window,
        text="",
        font=("Microsoft YaHei", 12),
        text_color="gray"
    )
    status_label.pack(anchor="w", padx=25, pady=(0, 8))

    def load_persona_into_fields(data):
        persona_state["last_loaded_time"] = data.get("last_loaded_time", persona_state["last_loaded_time"])
        persona_state["last_updated_time"] = data.get("last_updated_time", persona_state["last_updated_time"])
        name_entry.delete(0, "end")
        name_entry.insert(0, data.get("name", "Aurora"))
        description_box.delete("1.0", "end")
        description_box.insert("1.0", data.get("description", ""))
        style_box.delete("1.0", "end")
        style_box.insert("1.0", data.get("style", ""))
        rules_box.delete("1.0", "end")
        rules_box.insert("1.0", "\n".join(data.get("rules", [])))
        update_persona_status()

    def current_persona_from_fields():
        return {
            "name": name_entry.get().strip(),
            "description": description_box.get("1.0", "end").strip(),
            "style": style_box.get("1.0", "end").strip(),
            "rules": [
                line.strip()
                for line in rules_box.get("1.0", "end").splitlines()
                if line.strip()
            ],
            "last_loaded_time": persona_state.get("last_loaded_time", "Never loaded."),
            "last_updated_time": persona_state.get("last_updated_time", "Never loaded.")
        }

    def set_preview(text):
        preview_box.configure(state="normal")
        preview_box.delete("1.0", "end")
        preview_box.insert("1.0", text)
        preview_box.configure(state="disabled")

    def update_persona_status():
        data = current_persona_from_fields()
        status = persona_store.status(settings.get("persona.enabled", True), data)
        persona_status_label.configure(
            text=(
                f"Current Status: Persona: {'Enabled' if status['enabled'] else 'Disabled'} | "
                f"Name: {status['name']} | Rules Count: {status['rules_count']} | "
                f"Last Loaded: {status['last_loaded_time']} | Last Updated: {status['last_updated_time']}"
            )
        )
        character_label.configure(
            text=(
                f"Characters: name {len(data.get('name', ''))}, "
                f"description {len(data.get('description', ''))}, "
                f"style {len(data.get('style', ''))}, "
                f"rules {sum(len(rule) for rule in data.get('rules', []))}"
            )
        )

    def validate_current_persona():
        data = current_persona_from_fields()
        persona_store.validate(data)
        return data

    def save_persona():
        try:
            data = validate_current_persona()
            data = persona_store.save(data)
            persona_state["last_loaded_time"] = data.get("last_loaded_time", persona_state["last_loaded_time"])
            persona_state["last_updated_time"] = data.get("last_updated_time", persona_state["last_updated_time"])
            update_persona_status()
            status_label.configure(text="\u4eba\u683c\u5df2\u4fdd\u5b58", text_color="#32CD32")
            logger.info("Persona updated")
        except ValueError as error:
            status_label.configure(text=str(error), text_color="red")
            logger.info("Persona validation failed")
        except Exception as error:
            status_label.configure(text="Invalid Persona format.", text_color="red")
            logger.error(f"Persona update failed: {error}")

    def reset_persona():
        if not messagebox.askyesno(TEXT["persona"], "\u662f\u5426\u6062\u590d\u9ed8\u8ba4 Persona\uff1f", parent=persona_window):
            return
        data = persona_store.reset()
        persona_state["last_loaded_time"] = data.get("last_loaded_time", persona_state["last_loaded_time"])
        persona_state["last_updated_time"] = data.get("last_updated_time", persona_state["last_updated_time"])
        load_persona_into_fields(data)
        status_label.configure(text="\u5df2\u6062\u590d\u9ed8\u8ba4 Persona", text_color="#32CD32")
        logger.info("Persona reset")

    def edit_persona():
        status_label.configure(text="\u53ef\u7f16\u8f91 Persona", text_color="gray")
        update_persona_status()

    def add_rule():
        rules_box.insert("end", "\n")
        update_persona_status()
        logger.info("Persona rules updated")

    def delete_rule():
        lines = [
            line for line in rules_box.get("1.0", "end").splitlines()
            if line.strip()
        ]
        if lines:
            lines.pop()
        rules_box.delete("1.0", "end")
        rules_box.insert("1.0", "\n".join(lines))
        update_persona_status()
        logger.info("Persona rules updated")

    def preview_persona_prompt():
        set_preview("Loading Persona preview...")

        def run_preview():
            try:
                data = validate_current_persona()
                text = persona_store.preview_prompt(data)
                error_message = None
            except Exception as error:
                text = ""
                error_message = str(error)

            def finish_preview():
                if persona_window is None or not persona_window.winfo_exists():
                    return
                if error_message:
                    set_preview(error_message)
                    logger.info("Persona validation failed")
                    return
                set_preview(text)
                logger.info("Persona preview opened")

            try:
                persona_window.after(0, finish_preview)
            except Exception:
                return

        threading.Thread(target=run_preview, daemon=True).start()

    def test_persona_prompt():
        set_preview("Testing Persona...")

        def run_test():
            try:
                data = validate_current_persona()
                text = persona_store.test_prompt(test_prompt_entry.get().strip(), data)
                error_message = None
            except Exception as error:
                text = ""
                error_message = str(error)

            def finish_test():
                if persona_window is None or not persona_window.winfo_exists():
                    return
                if error_message:
                    set_preview(error_message)
                    logger.info("Persona validation failed")
                    return
                set_preview(text)
                logger.info("Persona tested")

            try:
                persona_window.after(0, finish_test)
            except Exception:
                return

        threading.Thread(target=run_test, daemon=True).start()

    def preview_final_prompt():
        set_preview("Building Final Chat Context Preview...")
        logger.info("Context preview opened")

        def run_final_preview():
            try:
                data = validate_current_persona()
                prompt = test_prompt_entry.get().strip()
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
                    knowledge_items = knowledge_store.retrieve(
                        prompt,
                        max_results=max_knowledge
                    )
                active_persona = data if settings.get("persona.enabled", True) else None
                text, warning, _total_tokens = build_prompt_preview_text(
                    prompt,
                    memories,
                    knowledge_items,
                    active_persona,
                    []
                )
                error_message = None
            except Exception as error:
                text = ""
                warning = False
                error_message = str(error)

            def finish_final_preview():
                if persona_window is None or not persona_window.winfo_exists():
                    return
                if error_message:
                    set_preview(error_message)
                    logger.info("Persona validation failed")
                    return
                set_preview(text)
                logger.info("Final prompt preview generated")
                logger.info("Knowledge retrieval explained")
                if warning:
                    logger.info("Context size warning")

            try:
                persona_window.after(0, finish_final_preview)
            except Exception:
                return

        threading.Thread(target=run_final_preview, daemon=True).start()

    buttons = ctk.CTkFrame(persona_window, fg_color="transparent")
    buttons.pack(fill="x", padx=25, pady=(0, 20))
    ctk.CTkButton(buttons, text=TEXT["edit_persona"], command=edit_persona).pack(side="left", expand=True, fill="x", padx=(0, 6))
    ctk.CTkButton(buttons, text=TEXT["save_persona"], command=save_persona).pack(side="left", expand=True, fill="x", padx=6)
    ctk.CTkButton(buttons, text=TEXT["reset_persona"], command=reset_persona).pack(side="left", expand=True, fill="x", padx=6)
    ctk.CTkButton(buttons, text="Add Rule", command=add_rule).pack(side="left", expand=True, fill="x", padx=6)
    ctk.CTkButton(buttons, text="Delete Rule", command=delete_rule).pack(side="left", expand=True, fill="x", padx=6)

    preview_buttons = ctk.CTkFrame(persona_window, fg_color="transparent")
    preview_buttons.pack(fill="x", padx=25, pady=(0, 12))
    ctk.CTkButton(preview_buttons, text="Preview Persona Prompt", command=preview_persona_prompt).pack(side="left", expand=True, fill="x", padx=(0, 6))
    ctk.CTkButton(preview_buttons, text="Test Persona", command=test_persona_prompt).pack(side="left", expand=True, fill="x", padx=6)
    ctk.CTkButton(preview_buttons, text="Preview Final Prompt", command=preview_final_prompt).pack(side="left", expand=True, fill="x", padx=6)

    def close_persona():
        global persona_window
        persona_window.destroy()
        persona_window = None

    ctk.CTkButton(buttons, text=TEXT["close"], command=close_persona).pack(side="left", expand=True, fill="x", padx=(6, 0))
    persona_window.protocol("WM_DELETE_WINDOW", close_persona)
    update_persona_status()


def show_remote_access():
    global remote_window
    if remote_window is not None and remote_window.winfo_exists():
        remote_window.focus()
        remote_window.lift()
        return

    logger.info("Remote configuration loaded")
    authentication_manager.load()
    logger.info("Authentication configuration loaded")
    logger.info("Authentication framework initialized")
    logger.info("Credential diagnostics opened")
    remote_manager.update(
        enabled=settings.get("remote.enabled", False),
        mode=settings.get("remote.mode", "local"),
        auth_required=settings.get("remote.auth_required", True),
        auth_enabled=settings.get("remote.auth_enabled", False),
        authentication_type=settings.get("remote.authentication_type", "none"),
        token_configured=settings.get("remote.token_configured", False),
        credential_storage=settings.get("remote.credential_storage", "windows_credential_manager"),
        secure_storage_configured=settings.get("remote.secure_storage_configured", False),
        secure_storage_available=settings.get("remote.secure_storage_available", False),
        credential_test_passed=settings.get("remote.credential_test_passed", False),
        credential_last_check=settings.get("remote.credential_last_check", None),
        credential_last_result=settings.get("remote.credential_last_result", None),
        credential_command_status=settings.get("remote.credential_command_status", "Unavailable"),
        credential_last_operation=settings.get("remote.credential_last_operation", None),
        credential_operation_result=settings.get("remote.credential_operation_result", None),
        credential_duration_ms=settings.get("remote.credential_duration_ms", 0),
        credential_error_suggestion=settings.get("remote.credential_error_suggestion", None),
        last_storage_error=settings.get("remote.last_storage_error", None),
        credential_history=settings.get("remote.credential_history", []),
        credential_steps=settings.get("remote.credential_steps", []),
        network_history=settings.get("remote.network_history", []),
        security_history=settings.get("remote.security_history", []),
        authentication_history=settings.get("remote.authentication_history", []),
        remote_history=settings.get("remote.remote_history", []),
        lan_status_page_enabled=settings.get("remote.lan_status_page_enabled", False),
        lan_status_port=settings.get("remote.lan_status_port", DEFAULT_LAN_STATUS_PORT),
        lan_status_user_confirmed=settings.get("remote.lan_status_user_confirmed", False),
        lan_chat_enabled=settings.get("remote.lan_chat_enabled", False),
        lan_chat_port=settings.get("remote.lan_chat_port", DEFAULT_LAN_STATUS_PORT),
        mobile_access_confirmed=settings.get("remote.mobile_access_confirmed", False),
        mobile_chat_timeout=settings.get("mobile_chat_timeout", 60),
        mobile_debug_mode=settings.get("mobile_debug_mode", False),
        mobile_response_limit=settings.get("mobile_response_limit", 12000),
        selected_lan_ip=settings.get("remote.selected_lan_ip", ""),
        selected_adapter=settings.get("remote.selected_adapter", ""),
        last_mobile_error=settings.get("remote.last_mobile_error", ""),
        last_mobile_stage=settings.get("remote.last_mobile_stage", ""),
        last_mobile_status=settings.get("remote.last_mobile_status", ""),
        last_mobile_duration_ms=settings.get("remote.last_mobile_duration_ms", 0),
        last_mobile_model=settings.get("remote.last_mobile_model", ""),
        last_mobile_capability=settings.get("remote.last_mobile_capability", ""),
        last_mobile_ollama_url=settings.get("remote.last_mobile_ollama_url", ""),
        last_mobile_client=settings.get("remote.last_mobile_client", ""),
        last_mobile_time=settings.get("remote.last_mobile_time", ""),
        authentication_configured=settings.get("remote.authentication_configured", False),
        lan_ready=settings.get("remote.lan_ready", False),
        ios_access_ready=settings.get("remote.ios_access_ready", False),
        tailscale_ready=settings.get("remote.tailscale_ready", False),
        user_confirmed=settings.get("remote.user_confirmed", False),
        security_confirmed=settings.get("remote.security_confirmed", False)
    )
    remote_window = ctk.CTkToplevel(app)
    remote_window.title(TEXT["remote_access"])
    remote_window.geometry("760x680")
    remote_window.minsize(620, 520)
    remote_window.transient(app)

    ctk.CTkLabel(
        remote_window,
        text=TEXT["remote_access"],
        font=("Microsoft YaHei", 22, "bold")
    ).pack(anchor="w", padx=25, pady=(20, 12))

    status_label = ctk.CTkLabel(
        remote_window,
        text=TEXT["checking"],
        font=("Microsoft YaHei", 12),
        text_color="gray"
    )
    status_label.pack(anchor="w", padx=25, pady=(0, 10))

    content = ctk.CTkScrollableFrame(remote_window)
    content.pack(fill="both", expand=True, padx=25, pady=(0, 12))
    rows = {}

    def add_status_row(key, label):
        row = ctk.CTkFrame(content, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=8)
        ctk.CTkLabel(
            row,
            text=label,
            font=("Microsoft YaHei", 13, "bold"),
            anchor="w"
        ).pack(side="left")
        value = ctk.CTkLabel(
            row,
            text="--",
            font=("Microsoft YaHei", 13),
            anchor="e"
        )
        value.pack(side="right")
        rows[key] = value

    add_status_row("local_address", TEXT["local_address"])
    add_status_row("lan_address", TEXT["lan_address"])
    add_status_row("selected_adapter", TEXT["selected_network_adapter"])
    add_status_row("selected_lan_ip", TEXT["selected_lan_ip"])
    add_status_row("rejected_interfaces", TEXT["rejected_interfaces"])
    add_status_row("network_available", TEXT["network_available"])
    add_status_row("remote_status", TEXT["remote_status"])
    add_status_row("security_status", TEXT["security_status"])
    add_status_row("mode", TEXT["remote_mode"])

    def add_section_title(text):
        ctk.CTkLabel(
            content,
            text=text,
            font=("Microsoft YaHei", 15, "bold"),
            anchor="w"
        ).pack(anchor="w", padx=15, pady=(16, 6))

    safety_frame = ctk.CTkFrame(content, fg_color="#3A1F1F")
    safety_frame.pack(fill="x", padx=15, pady=(10, 8))
    ctk.CTkLabel(
        safety_frame,
        text=TEXT["do_not_expose_warning"],
        font=("Microsoft YaHei", 13, "bold"),
        text_color="#FFB3B3",
        anchor="w",
        justify="left"
    ).pack(fill="x", padx=12, pady=10)

    add_section_title(TEXT["safety_gate"])
    safety_warning_box = ctk.CTkTextbox(content, height=90, wrap="word")
    safety_warning_box.pack(fill="x", padx=15, pady=(4, 8))
    safety_warning_box.insert("1.0", f"{TEXT['remote_safety_check']}\n\n{TEXT['remote_access_warning']}")
    safety_warning_box.configure(state="disabled")
    for key, label in (
        ("gate_network", TEXT["network"]),
        ("gate_lan", TEXT["lan"]),
        ("gate_auth_required", TEXT["required"]),
        ("gate_auth_configured", TEXT["configured"]),
        ("gate_security_confirmed", TEXT["security_confirmation"]),
        ("gate_overall", TEXT["overall"]),
    ):
        add_status_row(key, label)

    add_section_title(TEXT["lan_ios_readiness"])
    for key, label in (
        ("ios_same_wifi_status", TEXT["ios_same_wifi_status"]),
        ("tailscale_readiness", TEXT["tailscale_readiness"]),
        ("remote_safety_status", TEXT["remote_safety_status"]),
        ("local_preview", TEXT["local_preview"]),
        ("lan_preview", TEXT["lan_preview"]),
    ):
        add_status_row(key, label)

    ios_note_box = ctk.CTkTextbox(content, height=90, wrap="word")
    ios_note_box.pack(fill="x", padx=15, pady=(4, 8))
    ios_note_box.insert("1.0", f"{TEXT['iphone_same_wifi_access']}:\n{TEXT['iphone_same_wifi_note']}")
    ios_note_box.configure(state="disabled")

    add_section_title(TEXT["ios_compatibility"])
    for key, label in (
        ("ios_safari_supported", TEXT["safari_supported"]),
        ("ios_android_required", TEXT["android_required"]),
        ("ios_same_wifi_access", TEXT["same_wifi_access"]),
        ("ios_cellular_access", TEXT["cellular_access"]),
    ):
        add_status_row(key, label)

    add_section_title(TEXT["tailscale_readiness"])
    add_status_row("tailscale_status", TEXT["tailscale_readiness"])

    tailscale_note_box = ctk.CTkTextbox(content, height=70, wrap="word")
    tailscale_note_box.pack(fill="x", padx=15, pady=(4, 8))
    tailscale_note_box.insert("1.0", TEXT["tailscale_note"])
    tailscale_note_box.configure(state="disabled")

    add_section_title(TEXT["lan_access_preparation"])
    checklist_box = ctk.CTkTextbox(content, height=130, wrap="word")
    checklist_box.pack(fill="x", padx=15, pady=(4, 8))
    checklist_box.configure(state="disabled")

    add_section_title(TEXT["lan_status_page"])
    for key, label in (
        ("lan_status_state", TEXT["status"]),
        ("lan_status_local_url", TEXT["local_url"]),
        ("lan_status_lan_url", TEXT["lan_url"]),
    ):
        add_status_row(key, label)

    add_section_title(TEXT["lan_chat"])
    for key, label in (
        ("lan_chat_state", TEXT["status"]),
        ("lan_chat_url", TEXT["mobile_url"]),
        ("lan_chat_confirmation", TEXT["mobile_access_confirmation"]),
    ):
        add_status_row(key, label)

    add_section_title(TEXT["ai_configuration"])
    for key, label in (
        ("ai_chat_model", TEXT["chat_model"]),
        ("ai_embedding_model", TEXT["embedding_model"]),
        ("ai_model_capability", TEXT["model_capability"]),
        ("ai_mobile_chat_ready", TEXT["mobile_chat"]),
    ):
        add_status_row(key, label)

    add_section_title(TEXT["mobile_debug_panel"])
    for key, label in (
        ("mobile_debug_client", TEXT["client"]),
        ("mobile_debug_stage", TEXT["stage"]),
        ("mobile_debug_status", TEXT["status"]),
        ("mobile_debug_duration", TEXT["duration"]),
        ("mobile_debug_model", TEXT["model_name"]),
        ("mobile_debug_capability", TEXT["model_capability"]),
        ("mobile_debug_ollama_url", TEXT["ollama_url"]),
        ("mobile_debug_error", TEXT["error"]),
    ):
        add_status_row(key, label)

    firewall_notice_box = ctk.CTkTextbox(content, height=70, wrap="word")
    firewall_notice_box.pack(fill="x", padx=15, pady=(4, 8))
    firewall_notice_box.insert("1.0", TEXT["firewall_notice"])
    firewall_notice_box.configure(state="disabled")
    logger.info("Firewall notice displayed")

    add_section_title(TEXT["iphone_same_wifi_test"])
    iphone_guide_box = ctk.CTkTextbox(content, height=110, wrap="word")
    iphone_guide_box.pack(fill="x", padx=15, pady=(4, 8))
    iphone_guide_box.insert("1.0", TEXT["iphone_same_wifi_steps"])
    iphone_guide_box.configure(state="disabled")

    add_section_title(TEXT["security_checklist"])
    for key, label in (
        ("security_remote_access", TEXT["remote_access_label"]),
        ("security_current_mode", TEXT["current_mode"]),
        ("security_authentication", TEXT["authentication"]),
        ("security_public_exposure", TEXT["public_exposure"]),
        ("security_firewall", TEXT["firewall"]),
    ):
        add_status_row(key, label)

    add_section_title(TEXT["remote_health"])
    for key, label in (
        ("health_network", TEXT["network"]),
        ("health_local_access", TEXT["local_access"]),
        ("health_lan_access", TEXT["lan_access"]),
        ("health_lan_readiness", TEXT["lan_readiness"]),
        ("health_ios_access", TEXT["ios_access"]),
        ("health_cellular_access", TEXT["cellular_access"]),
        ("health_security", TEXT["security"]),
    ):
        add_status_row(key, label)

    add_section_title(TEXT["authentication_status"])
    add_status_row("auth_required", TEXT["required"])
    add_status_row("auth_configured", TEXT["configured"])

    add_section_title(TEXT["authentication"])
    for key, label in (
        ("auth_required_detail", TEXT["authentication_required"]),
        ("auth_status_detail", TEXT["authentication_status"]),
        ("auth_type_detail", TEXT["authentication_type"]),
        ("token_status_detail", TEXT["token_status"]),
        ("token_configured_detail", TEXT["configured"]),
        ("token_last_updated_detail", TEXT["token_last_updated"]),
    ):
        add_status_row(key, label)

    auth_note_box = ctk.CTkTextbox(content, height=85, wrap="word")
    auth_note_box.pack(fill="x", padx=15, pady=(4, 8))
    auth_note_box.insert(
        "1.0",
        (
            f"{TEXT['authentication_type']}:\n"
            f"{TEXT['none']}\n"
            f"{TEXT['token_auth_future']}\n"
            f"{TEXT['password_auth_future']}\n\n"
            f"{TEXT['auth_secrets_plaintext_warning']}"
        )
    )
    auth_note_box.configure(state="disabled")

    add_section_title(TEXT["token_authentication"])
    for key, label in (
        ("token_auth_status", TEXT["token_status"]),
        ("token_auth_configured", TEXT["configured"]),
        ("token_auth_last_updated", TEXT["token_last_updated"]),
        ("auth_readiness_required", TEXT["required"]),
        ("auth_readiness_token", TEXT["token"]),
        ("auth_readiness_storage", TEXT["storage"]),
        ("auth_readiness_security", TEXT["security"]),
        ("auth_readiness_overall", TEXT["overall"]),
    ):
        add_status_row(key, label)

    token_note_box = ctk.CTkTextbox(content, height=95, wrap="word")
    token_note_box.pack(fill="x", padx=15, pady=(4, 8))
    token_note_box.insert(
        "1.0",
        (
            f"{TEXT['token_setup_note']}\n\n"
            f"{TEXT['never_share_token']}\n"
            f"{TEXT['store_credentials_securely']}"
        )
    )
    token_note_box.configure(state="disabled")

    add_section_title(TEXT["credential_storage"])
    for key, label in (
        ("credential_storage_status", TEXT["storage_status"]),
        ("credential_secure_configured", TEXT["secure_storage_configured"]),
        ("credential_storage_type", TEXT["storage_type"]),
    ):
        add_status_row(key, label)

    credential_note_box = ctk.CTkTextbox(content, height=125, wrap="word")
    credential_note_box.pack(fill="x", padx=15, pady=(4, 8))
    credential_note_box.insert(
        "1.0",
        (
            f"{TEXT['recommended']}:\n"
            f"{TEXT['windows_credential_manager']}\n\n"
            f"{TEXT['future_option']}:\n"
            f"{TEXT['encrypted_local_storage']}\n\n"
            f"{TEXT['not_recommended']}:\n"
            f"{TEXT['plain_text_file']}\n\n"
            f"{TEXT['auth_secrets_plaintext_warning']}"
        )
    )
    credential_note_box.configure(state="disabled")

    add_section_title(TEXT["credential_storage_provider"])
    for key, label in (
        ("credential_provider", TEXT["provider"]),
        ("credential_provider_status", TEXT["status"]),
        ("credential_test_status", TEXT["test_status"]),
        ("credential_last_check", TEXT["last_check_time"]),
    ):
        add_status_row(key, label)

    provider_note_box = ctk.CTkTextbox(content, height=70, wrap="word")
    provider_note_box.pack(fill="x", padx=15, pady=(4, 8))
    provider_note_box.insert("1.0", TEXT["windows_credential_manager_note"])
    provider_note_box.configure(state="disabled")

    add_section_title(TEXT["credential_storage_diagnostics"])
    for key, label in (
        ("diagnostic_provider", TEXT["provider"]),
        ("diagnostic_storage_status", TEXT["storage_status"]),
        ("diagnostic_availability", TEXT["availability"]),
        ("diagnostic_command_status", TEXT["command_status"]),
        ("diagnostic_last_check", TEXT["last_check_time"]),
        ("diagnostic_last_result", TEXT["last_result"]),
        ("diagnostic_last_error", TEXT["last_error"]),
        ("diagnostic_last_operation", TEXT["last_operation"]),
        ("diagnostic_operation_result", TEXT["operation_result"]),
        ("diagnostic_duration", TEXT["duration"]),
        ("diagnostic_suggestion", TEXT["suggestion"]),
    ):
        add_status_row(key, label)

    credential_steps_box = ctk.CTkTextbox(content, height=105, wrap="word")
    credential_steps_box.pack(fill="x", padx=15, pady=(4, 8))
    credential_steps_box.configure(state="disabled")

    add_section_title(TEXT["credential_history"])
    credential_history_box = ctk.CTkTextbox(content, height=145, wrap="word")
    credential_history_box.pack(fill="x", padx=15, pady=(4, 8))
    credential_history_box.configure(state="disabled")

    add_section_title(TEXT["credential_security"])
    for key, label in (
        ("credential_no_plain_text", TEXT["no_plain_text_storage"]),
        ("credential_framework_ready", TEXT["authentication_framework_ready"]),
        ("credential_secure_missing", TEXT["secure_storage_not_configured"]),
    ):
        add_status_row(key, label)

    add_section_title(TEXT["listening_ports"])
    add_status_row("listening_ports", TEXT["listening_ports"])

    hint_box = ctk.CTkTextbox(remote_window, height=80, wrap="word")
    hint_box.pack(fill="x", padx=25, pady=(0, 12))
    hint_box.insert(
        "1.0",
        (
            f"{TEXT['security_status']}:\n"
            f"{TEXT['local_only']}\n\n"
            f"{TEXT['auth_required_hint']}\n\n"
            f"{TEXT['local_only_description']}\n"
            f"{TEXT['lan_only_description']}\n"
            f"{TEXT['secure_remote_description']}\n\n"
            f"{TEXT['authentication_not_configured_hint']}"
        )
    )
    hint_box.configure(state="disabled")

    def update_remote_rows(status):
        config = status.get("config", {})
        network = status.get("network", {})
        security = status.get("security", {})
        health = status.get("health", {})
        url_preview = status.get("url_preview", {})
        ios = status.get("ios_compatibility", {})
        tailscale = status.get("tailscale", {})
        lan_checklist = status.get("lan_checklist", [])
        lan_status = status.get("lan_status", {})
        lan_chat = status.get("lan_chat", {})
        mobile_debug = status.get("mobile_debug", {})
        safety_gate = status.get("safety_gate", {})
        auth_status = status.get("authentication", {})
        readiness = safety_gate.get("readiness", {})
        enabled = bool(config.get("enabled", False))
        network_available = bool(network.get("network_available", False))
        auth_required = bool(config.get("auth_required", True))
        auth_configured = bool(auth_status.get("configured", config.get("authentication_configured", False)))
        ports = security.get("listening_ports", [])
        rows["local_address"].configure(text=network.get("local_address", "127.0.0.1"))
        rows["lan_address"].configure(text=network.get("lan_address", TEXT["unavailable"]))
        rows["selected_adapter"].configure(text=network.get("selected_adapter", TEXT["unavailable"]))
        rows["selected_lan_ip"].configure(text=network.get("selected_lan_ip", TEXT["unavailable"]) or TEXT["unavailable"])
        rejected = network.get("ignored_virtual_adapters", [])
        rows["rejected_interfaces"].configure(text=", ".join(rejected) if rejected else TEXT["none"])
        rows["network_available"].configure(text=TEXT["yes"] if network_available else TEXT["no"])
        rows["remote_status"].configure(text=TEXT["ready"] if enabled and network_available else TEXT["disabled"])
        rows["security_status"].configure(text=TEXT["auth_required_hint"] if enabled else TEXT["local_only"])
        rows["mode"].configure(text=TEXT["local_only"])
        rows["gate_network"].configure(text=TEXT["ready"] if readiness.get("network") == "Ready" else TEXT["not_ready"])
        rows["gate_lan"].configure(text=TEXT["ready"] if readiness.get("lan") == "Ready" else TEXT["not_ready"])
        rows["gate_auth_required"].configure(text=TEXT["ready"] if safety_gate.get("checks", {}).get("authentication_required") else TEXT["missing"])
        rows["gate_auth_configured"].configure(text=TEXT["ready"] if readiness.get("authentication") == "Ready" else TEXT["missing"])
        rows["gate_security_confirmed"].configure(text=TEXT["confirmed"] if readiness.get("security") == "Confirmed" else TEXT["not_confirmed"])
        rows["gate_overall"].configure(text=TEXT["ready"] if readiness.get("overall") == "Ready" else TEXT["blocked"])
        rows["ios_same_wifi_status"].configure(text=TEXT["future_supported"])
        rows["tailscale_readiness"].configure(text=TEXT["future_supported"])
        rows["remote_safety_status"].configure(text=TEXT["safe"] if not enabled else TEXT["warning"])
        rows["local_preview"].configure(text=url_preview.get("local_preview", TEXT["port_not_configured"]))
        rows["lan_preview"].configure(text=url_preview.get("lan_preview", TEXT["port_not_configured"]))
        lan_urls = lan_status.get("urls", remote_manager.lan_status_urls())
        rows["lan_status_state"].configure(text=TEXT["running"] if lan_status_server.is_running() else TEXT["stopped"])
        rows["lan_status_local_url"].configure(text=lan_urls.get("local_url", f"http://127.0.0.1:{DEFAULT_LAN_STATUS_PORT}"))
        rows["lan_status_lan_url"].configure(text=lan_urls.get("lan_url", TEXT["no_lan_address"]))
        lan_chat_urls = lan_chat.get("urls", remote_manager.lan_chat_urls())
        rows["lan_chat_state"].configure(
            text=TEXT["running"] if lan_status_server.is_running() and lan_status_server.mobile_chat_enabled else TEXT["disabled"]
        )
        rows["lan_chat_url"].configure(text=lan_chat_urls.get("mobile_url", TEXT["no_lan_address"]))
        rows["lan_chat_confirmation"].configure(text=TEXT["confirmed"] if lan_chat.get("mobile_access_confirmed") else TEXT["not_confirmed"])
        chat_model = str(settings.get("chat_model", "qwen3:8b") or "").strip()
        embedding_model = str(settings.get("embedding_model", "nomic-embed-text:latest") or "").strip()
        chat_capability = infer_model_capability(chat_model)
        rows["ai_chat_model"].configure(text=chat_model)
        rows["ai_embedding_model"].configure(text=embedding_model)
        rows["ai_model_capability"].configure(text=chat_capability)
        rows["ai_mobile_chat_ready"].configure(text=TEXT["ready"] if chat_capability == "Chat Supported" else TEXT["error"])
        rows["mobile_debug_client"].configure(text=mobile_debug.get("client") or "iPhone Safari")
        rows["mobile_debug_stage"].configure(text=mobile_debug.get("stage") or "--")
        rows["mobile_debug_status"].configure(text=mobile_debug.get("status") or "--")
        rows["mobile_debug_duration"].configure(text=f"{mobile_debug.get('duration_ms', 0)}ms")
        rows["mobile_debug_model"].configure(text=mobile_debug.get("model") or "--")
        rows["mobile_debug_capability"].configure(text=mobile_debug.get("capability") or infer_model_capability(mobile_debug.get("model") or chat_model))
        rows["mobile_debug_ollama_url"].configure(text=mobile_debug.get("ollama_url") or settings.get("ollama.host", "--"))
        rows["mobile_debug_error"].configure(text=mobile_debug.get("error") or TEXT["none"])
        rows["ios_safari_supported"].configure(text=TEXT["yes"] if ios.get("safari_supported") == "Yes" else TEXT["no"])
        rows["ios_android_required"].configure(text=TEXT["yes"] if ios.get("android_required") == "Yes" else TEXT["no"])
        rows["ios_same_wifi_access"].configure(text=TEXT["future_supported"])
        rows["ios_cellular_access"].configure(text=TEXT["requires_secure_tunnel"])
        rows["tailscale_status"].configure(
            text=TEXT["ready"] if tailscale.get("status") == "Ready" else TEXT["future_supported"]
        )
        rows["security_remote_access"].configure(text=TEXT["enabled"] if enabled else TEXT["disabled"])
        rows["security_current_mode"].configure(text=TEXT["local_only"])
        rows["security_authentication"].configure(text=TEXT["required"] if auth_required else TEXT["not_configured"])
        rows["security_public_exposure"].configure(text=TEXT["no"])
        rows["security_firewall"].configure(text=TEXT["safe"] if security.get("firewall") == "Safe" else TEXT["unknown"])
        rows["health_network"].configure(text=TEXT["ok"] if health.get("network") == "OK" else TEXT["offline"])
        rows["health_local_access"].configure(text=TEXT["available"] if health.get("local_access") == "Available" else TEXT["unavailable"])
        rows["health_lan_access"].configure(text=TEXT["available"] if health.get("lan_access") == "Available" else TEXT["unavailable"])
        rows["health_lan_readiness"].configure(text=TEXT["ready"] if health.get("lan_readiness") == "Ready" else TEXT["not_ready"])
        rows["health_ios_access"].configure(text=TEXT["ready"] if health.get("ios_access") == "Ready" else TEXT["future_supported"])
        rows["health_cellular_access"].configure(text=TEXT["requires_secure_tunnel"])
        rows["health_security"].configure(text=TEXT["safe"] if health.get("security") == "Safe" else TEXT["warning"])
        rows["auth_required"].configure(text=TEXT["yes"] if auth_required else TEXT["no"])
        rows["auth_configured"].configure(text=TEXT["yes"] if auth_configured else TEXT["no"])
        rows["auth_required_detail"].configure(text=TEXT["yes"] if auth_status.get("required", True) else TEXT["no"])
        rows["auth_status_detail"].configure(text=TEXT["configured"] if auth_status.get("configured") else TEXT["not_configured"])
        rows["auth_type_detail"].configure(text=TEXT["token_authentication"] if auth_status.get("authentication_type") == "token" else TEXT["none"])
        rows["token_status_detail"].configure(text=TEXT["configured"] if auth_status.get("token_configured") else TEXT["not_configured"])
        rows["token_configured_detail"].configure(text=TEXT["yes"] if auth_status.get("token_configured") else TEXT["no"])
        rows["token_last_updated_detail"].configure(text=auth_status.get("last_token_update") or TEXT["never_configured"])
        rows["token_auth_status"].configure(text=TEXT["configured"] if auth_status.get("token_configured") else TEXT["not_configured"])
        rows["token_auth_configured"].configure(text=TEXT["yes"] if auth_status.get("token_configured") else TEXT["no"])
        rows["token_auth_last_updated"].configure(text=auth_status.get("last_token_update") or TEXT["never_configured"])
        readiness_auth = auth_status.get("readiness", {})
        rows["auth_readiness_required"].configure(text=TEXT["yes"])
        rows["auth_readiness_token"].configure(text=TEXT["configured"] if readiness_auth.get("token") == "Configured" else TEXT["missing"])
        rows["auth_readiness_storage"].configure(text=TEXT["available_status"] if readiness_auth.get("storage") == "Available" else TEXT["storage_missing"])
        rows["auth_readiness_security"].configure(text=TEXT["ready"] if readiness_auth.get("security") == "Ready" else TEXT["warning"])
        rows["auth_readiness_overall"].configure(text=TEXT["ready"] if readiness_auth.get("overall") == "Ready" else TEXT["blocked"])
        credential_type = auth_status.get("credential_storage", "none")
        credential_type_text = {
            "none": TEXT["none"],
            "windows_credential_manager": TEXT["windows_credential_manager"],
            "encrypted_local_storage": TEXT["encrypted_local_storage"],
            "plain_text_file": TEXT["plain_text_file"]
        }.get(credential_type, TEXT["unknown"])
        credential_security = auth_status.get("credential_security", {})
        rows["credential_storage_status"].configure(text=TEXT["available_status"] if auth_status.get("storage_status") == "Available" else TEXT["unavailable_status"])
        rows["credential_secure_configured"].configure(text=TEXT["yes"] if auth_status.get("secure_storage_configured") else TEXT["no"])
        rows["credential_storage_type"].configure(text=credential_type_text)
        rows["credential_provider"].configure(text=TEXT["windows_credential_manager"])
        rows["credential_provider_status"].configure(text=TEXT["available_status"] if auth_status.get("secure_storage_available") else TEXT["unavailable_status"])
        rows["credential_test_status"].configure(text=TEXT["passed"] if auth_status.get("credential_test_passed") else TEXT["failed"])
        rows["credential_last_check"].configure(text=auth_status.get("credential_last_check") or "--")
        rows["diagnostic_provider"].configure(text=TEXT["windows_credential_manager"])
        rows["diagnostic_storage_status"].configure(text=TEXT["available_status"] if auth_status.get("storage_status") == "Available" else TEXT["unavailable_status"])
        rows["diagnostic_availability"].configure(text=TEXT["available_status"] if auth_status.get("secure_storage_available") else TEXT["unavailable_status"])
        rows["diagnostic_command_status"].configure(text=TEXT["available_status"] if auth_status.get("credential_command_status") == "Available" else TEXT["unavailable_status"])
        rows["diagnostic_last_check"].configure(text=auth_status.get("credential_last_check") or "--")
        rows["diagnostic_last_result"].configure(text=TEXT["passed"] if auth_status.get("credential_last_result") == "Passed" else TEXT["failed"])
        rows["diagnostic_last_error"].configure(text=auth_status.get("last_storage_error") or TEXT["none"])
        rows["diagnostic_last_operation"].configure(text=auth_status.get("credential_last_operation") or "--")
        rows["diagnostic_operation_result"].configure(text=auth_status.get("credential_operation_result") or "--")
        rows["diagnostic_duration"].configure(text=f"{auth_status.get('credential_duration_ms', 0)}ms")
        rows["diagnostic_suggestion"].configure(text=auth_status.get("credential_error_suggestion") or TEXT["none"])
        rows["credential_no_plain_text"].configure(text=TEXT["yes"] if credential_security.get("no_plain_text_storage") else TEXT["no"])
        rows["credential_framework_ready"].configure(text=TEXT["yes"] if credential_security.get("authentication_framework_ready") else TEXT["no"])
        rows["credential_secure_missing"].configure(text=TEXT["no"] if credential_security.get("secure_storage_configured") else TEXT["secure_storage_not_configured"])
        if ports:
            rows["listening_ports"].configure(
                text=", ".join(f"{item.get('port')} ({TEXT['unknown']})" for item in ports)
            )
        else:
            rows["listening_ports"].configure(text=TEXT["none"])
        checklist_box.configure(state="normal")
        checklist_box.delete("1.0", "end")
        checklist_lines = []
        for item in lan_checklist:
            marker = "\u2713" if item.get("ok") else "\u2717"
            checklist_lines.append(f"{marker} {item.get('label', '')}")
        checklist_box.insert("1.0", "\n".join(checklist_lines))
        checklist_box.configure(state="disabled")
        credential_steps_box.configure(state="normal")
        credential_steps_box.delete("1.0", "end")
        steps = auth_status.get("credential_steps", [])
        if steps:
            credential_steps_box.insert(
                "1.0",
                "\n".join(f"{item.get('step', '')}: {item.get('result', '')}" for item in steps)
            )
        else:
            credential_steps_box.insert("1.0", "--")
        credential_steps_box.configure(state="disabled")
        credential_history_box.configure(state="normal")
        credential_history_box.delete("1.0", "end")
        history = auth_status.get("credential_history", [])
        if history:
            history_lines = [
                f"{item.get('time') or '--'}   {item.get('status') or '--'}   {item.get('result') or '--'}"
                for item in reversed(history[-10:])
            ]
            credential_history_box.insert("1.0", "\n".join(history_lines))
            logger.info("Credential storage history loaded")
        else:
            credential_history_box.insert("1.0", TEXT["no_history"])
        credential_history_box.configure(state="disabled")
        status_label.configure(text=TEXT["ready"], text_color="#32CD32")
        if enabled:
            logger.info("Remote configuration updated")
        else:
            logger.info("Remote access disabled")
        logger.info("Remote status checked")
        logger.info("Chat model loaded")
        logger.info("Embedding model loaded")
        logger.info("Model capability checked")
        if network.get("selected_lan_ip"):
            logger.info("LAN IP selected")
        if network.get("ignored_virtual_adapters"):
            logger.info("Virtual adapter ignored")
        logger.info("Remote security checked")
        logger.info("Remote health checked")
        logger.info("Remote mode displayed")
        logger.info("Remote authentication status checked")
        logger.info("Authentication status checked")
        logger.info("Token status checked")
        logger.info("Token readiness checked")
        logger.info("Credential storage status checked")
        logger.info("Credential security checked")
        logger.info("Credential storage provider checked")
        logger.info("Credential storage diagnostics completed")
        if not auth_status.get("configured"):
            logger.info("Authentication missing")
        if not auth_status.get("token_configured"):
            logger.info("Token configuration missing")
        if auth_status.get("secure_storage_configured"):
            logger.info("Secure storage configured")
        else:
            logger.info("Secure storage missing")
        if auth_status.get("last_storage_error"):
            logger.info("Credential storage error detected")
            logger.info("Error suggestion generated")
        logger.info("LAN readiness checked")
        logger.info("iOS access readiness checked")
        logger.info("LAN preview generated")
        logger.info("Tailscale readiness displayed")
        logger.info("Remote safety warning displayed")
        logger.info("Mobile debug updated")
        if safety_gate.get("ready"):
            logger.info("Remote safety check passed")
        else:
            logger.info("Remote safety check blocked")

    def refresh_remote_status():
        status_label.configure(text=TEXT["checking"], text_color="gray")
        logger.info("Remote safety check started")

        def run_check():
            try:
                provider_status = credential_storage_provider.check_available()
                logger.info("Credential storage command checked")
                remote_config = remote_manager.update_credential_diagnostics(provider_status)
                settings.set("remote.credential_storage", "windows_credential_manager")
                settings.set("remote.secure_storage_available", provider_status.get("available", False))
                settings.set("remote.credential_last_check", provider_status.get("last_check"))
                settings.set("remote.credential_last_result", provider_status.get("last_result"))
                settings.set("remote.credential_command_status", provider_status.get("command_status", "Unavailable"))
                settings.set("remote.credential_last_operation", provider_status.get("last_operation"))
                settings.set("remote.credential_operation_result", provider_status.get("operation_result"))
                settings.set("remote.credential_duration_ms", provider_status.get("duration_ms", 0))
                settings.set("remote.credential_error_suggestion", provider_status.get("suggestion"))
                settings.set("remote.last_storage_error", provider_status.get("last_error"))
                settings.set("remote.credential_history", remote_config.get("credential_history", []))
                settings.set("remote.credential_steps", provider_status.get("steps", []))
                remote_config = remote_manager.record_diagnostic_history()
                settings.set("remote.network_history", remote_config.get("network_history", []))
                settings.set("remote.security_history", remote_config.get("security_history", []))
                settings.set("remote.authentication_history", remote_config.get("authentication_history", []))
                settings.set("remote.remote_history", remote_config.get("remote_history", []))
                assessment = remote_manager.assessment()
                status = assessment["status"]
                network_info = status.get("network", {})
                settings.set("remote.selected_lan_ip", network_info.get("selected_lan_ip", ""))
                settings.set("remote.selected_adapter", network_info.get("selected_adapter", ""))
                status["security"] = assessment["security"]
                status["health"] = assessment["health"]
                status["url_preview"] = assessment["url_preview"]
                status["ios_compatibility"] = assessment["ios_compatibility"]
                status["tailscale"] = assessment["tailscale"]
                status["lan_checklist"] = assessment["lan_checklist"]
                status["lan_status"] = assessment["lan_status"]
                status["lan_chat"] = assessment["lan_chat"]
                status["mobile_debug"] = assessment.get("mobile_debug", {})
                status["safety_gate"] = assessment["safety_gate"]
                status["authentication"] = assessment["authentication"]
                error_message = None
            except Exception as error:
                status = {}
                error_message = str(error)

            def finish_check():
                if remote_window is None or not remote_window.winfo_exists():
                    return
                if error_message:
                    status_label.configure(text=error_message, text_color="red")
                    logger.error(f"Remote status check failed: {error_message}")
                    return
                update_remote_rows(status)

            try:
                remote_window.after(0, finish_check)
            except Exception:
                return

        threading.Thread(target=run_check, daemon=True).start()

    def close_remote_window():
        global remote_window
        remote_window.destroy()
        remote_window = None

    buttons = ctk.CTkScrollableFrame(remote_window, height=118, fg_color="transparent")
    buttons.pack(fill="x", padx=25, pady=(0, 20))
    for column in range(3):
        buttons.grid_columnconfigure(column, weight=1)

    def confirm_remote_security():
        logger.info("Remote safety check started")

        def run_confirm():
            try:
                remote_manager.confirm_security()
                settings.set("remote.security_confirmed", True)
                settings.set("remote.user_confirmed", True)
                error_message = None
            except Exception as error:
                error_message = str(error)

            def finish_confirm():
                if remote_window is None or not remote_window.winfo_exists():
                    return
                if error_message:
                    status_label.configure(text=error_message, text_color="red")
                    logger.error(f"Remote security confirmation failed: {error_message}")
                    return
                status_label.configure(text=TEXT["confirmed"], text_color="#32CD32")
                logger.info("Remote security confirmation updated")
                refresh_remote_status()

            try:
                remote_window.after(0, finish_confirm)
            except Exception:
                return

        threading.Thread(target=run_confirm, daemon=True).start()

    def setup_token_placeholder():
        logger.info("Token setup opened")

        def run_setup():
            try:
                authentication_manager.setup_token_placeholder(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                error_message = None
            except Exception as error:
                error_message = str(error)

            def finish_setup():
                if remote_window is None or not remote_window.winfo_exists():
                    return
                if error_message:
                    status_label.configure(text=error_message, text_color="red")
                    logger.error(f"Token setup failed: {error_message}")
                    return
                status_label.configure(text=TEXT["token_setup_note"], text_color="#32CD32")
                logger.info("Token status checked")
                logger.info("Token readiness checked")
                refresh_remote_status()

            try:
                remote_window.after(0, finish_setup)
            except Exception:
                return

        threading.Thread(target=run_setup, daemon=True).start()

    def test_secure_storage():
        logger.info("Credential storage provider checked")

        def run_test():
            try:
                result = credential_storage_provider.run_test()
                remote_config = remote_manager.update_credential_diagnostics(result)
                settings.set("remote.credential_storage", "windows_credential_manager")
                settings.set("remote.secure_storage_available", result.get("available", False))
                settings.set("remote.credential_test_passed", result.get("test_passed", False))
                settings.set("remote.credential_last_check", result.get("last_check"))
                settings.set("remote.credential_last_result", result.get("last_result"))
                settings.set("remote.credential_command_status", result.get("command_status", "Unavailable"))
                settings.set("remote.credential_last_operation", result.get("last_operation"))
                settings.set("remote.credential_operation_result", result.get("operation_result"))
                settings.set("remote.credential_duration_ms", result.get("duration_ms", 0))
                settings.set("remote.credential_error_suggestion", result.get("suggestion"))
                settings.set("remote.last_storage_error", result.get("last_error"))
                settings.set("remote.credential_history", remote_config.get("credential_history", []))
                settings.set("remote.credential_steps", result.get("steps", []))
                remote_config = remote_manager.record_diagnostic_history()
                settings.set("remote.network_history", remote_config.get("network_history", []))
                settings.set("remote.security_history", remote_config.get("security_history", []))
                settings.set("remote.authentication_history", remote_config.get("authentication_history", []))
                settings.set("remote.remote_history", remote_config.get("remote_history", []))
                error_message = None
            except Exception as error:
                result = {
                    "available": False,
                    "test_passed": False,
                    "message": str(error),
                    "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                error_message = str(error)

            def finish_test():
                if remote_window is None or not remote_window.winfo_exists():
                    return
                if result.get("test_passed"):
                    status_label.configure(text=TEXT["passed"], text_color="#32CD32")
                    logger.info("Test credential created")
                    logger.info("Test credential removed")
                    logger.info("Credential storage test passed")
                else:
                    status_label.configure(text=result.get("message", TEXT["failed"]), text_color="red")
                    logger.info("Credential storage test failed")
                    if error_message:
                        logger.error(f"Credential storage test failed: {error_message}")
                refresh_remote_status()

            try:
                remote_window.after(0, finish_test)
            except Exception:
                return

        threading.Thread(target=run_test, daemon=True).start()

    def remove_test_credential():
        logger.info("Credential storage provider checked")

        def run_remove():
            try:
                result = credential_storage_provider.delete_test_credential()
                diagnostic_result = {
                    "available": True,
                    "test_passed": False,
                    "last_result": result.get("status"),
                    "last_error": result.get("last_error"),
                    "command_status": "Available",
                    "last_check": result.get("last_check"),
                    "steps": [{
                        "step": "Delete Test Credential",
                        "ok": result.get("removed", False),
                        "result": result.get("status"),
                        "message": result.get("message", "")
                    }]
                }
                remote_config = remote_manager.update_credential_diagnostics(diagnostic_result)
                settings.set("remote.credential_test_passed", False)
                settings.set("remote.credential_last_check", result.get("last_check"))
                settings.set("remote.credential_last_result", result.get("status"))
                settings.set("remote.credential_command_status", "Available")
                settings.set("remote.credential_last_operation", "Delete Test Credential")
                settings.set("remote.credential_operation_result", "Success" if result.get("removed") else "Failed")
                settings.set("remote.credential_duration_ms", result.get("duration_ms", 0))
                settings.set("remote.credential_error_suggestion", result.get("suggestion"))
                settings.set("remote.last_storage_error", result.get("last_error"))
                settings.set("remote.credential_history", remote_config.get("credential_history", []))
                settings.set("remote.credential_steps", diagnostic_result.get("steps", []))
                remote_config = remote_manager.record_diagnostic_history()
                settings.set("remote.network_history", remote_config.get("network_history", []))
                settings.set("remote.security_history", remote_config.get("security_history", []))
                settings.set("remote.authentication_history", remote_config.get("authentication_history", []))
                settings.set("remote.remote_history", remote_config.get("remote_history", []))
                error_message = None
            except Exception as error:
                result = {
                    "removed": False,
                    "message": str(error),
                    "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                error_message = str(error)

            def finish_remove():
                if remote_window is None or not remote_window.winfo_exists():
                    return
                if result.get("removed"):
                    status_label.configure(text=TEXT["remove_test_credential"], text_color="#32CD32")
                    logger.info("Test credential removed")
                else:
                    status_label.configure(text=result.get("message", TEXT["failed"]), text_color="red")
                    if error_message:
                        logger.error(f"Test credential removal failed: {error_message}")
                refresh_remote_status()

            try:
                remote_window.after(0, finish_remove)
            except Exception:
                return

        threading.Thread(target=run_remove, daemon=True).start()

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

    def start_lan_status_page():
        start_check = remote_manager.lan_status_start_check()
        if not start_check.get("user_confirmed"):
            confirmed = messagebox.askyesno(TEXT["lan_status_page"], TEXT["lan_status_warning"])
            if not confirmed:
                status_label.configure(text=TEXT["blocked"], text_color="red")
                logger.info("LAN status page start blocked")
                return
            remote_manager.update(lan_status_user_confirmed=True)
            settings.set("remote.lan_status_user_confirmed", True)
            start_check = remote_manager.lan_status_start_check()

        if not start_check.get("network_available") or not start_check.get("lan_address_available"):
            status_label.configure(text=start_check.get("reason", TEXT["not_ready"]), text_color="red")
            logger.info("LAN status page start blocked")
            return

        status_label.configure(text=TEXT["checking"], text_color="gray")

        def run_start():
            port = settings.get("remote.lan_status_port", DEFAULT_LAN_STATUS_PORT)
            result = lan_status_server.start("0.0.0.0", port, lan_status_snapshot)

            def finish_start():
                if remote_window is None or not remote_window.winfo_exists():
                    return
                if result.get("ok"):
                    if result.get("duplicate"):
                        logger.info("LAN server duplicate start blocked")
                    remote_manager.update(
                        lan_status_page_enabled=True,
                        lan_status_port=result.get("port", port),
                        lan_status_user_confirmed=True
                    )
                    settings.set("remote.lan_status_page_enabled", True)
                    settings.set("remote.lan_status_port", result.get("port", port))
                    settings.set("remote.lan_status_user_confirmed", True)
                    status_label.configure(text=TEXT["running"], text_color="#32CD32")
                    logger.info("LAN status page started")
                else:
                    remote_manager.update(lan_status_page_enabled=False)
                    settings.set("remote.lan_status_page_enabled", False)
                    status_label.configure(text=result.get("message", TEXT["failed"]), text_color="red")
                    logger.info("LAN status page start blocked")
                refresh_remote_status()

            try:
                remote_window.after(0, finish_start)
            except Exception:
                return

        threading.Thread(target=run_start, daemon=True).start()

    def stop_lan_status_page():
        status_label.configure(text=TEXT["checking"], text_color="gray")

        def run_stop():
            result = lan_status_server.stop()

            def finish_stop():
                if remote_window is None or not remote_window.winfo_exists():
                    return
                remote_manager.update(enabled=False, lan_status_page_enabled=False, lan_chat_enabled=False)
                settings.set("remote.enabled", False)
                settings.set("remote.lan_status_page_enabled", False)
                settings.set("remote.lan_chat_enabled", False)
                status_label.configure(
                    text=TEXT["stopped"] if result.get("ok") else result.get("message", TEXT["failed"]),
                    text_color="#32CD32" if result.get("ok") else "red"
                )
                if result.get("released"):
                    logger.info("LAN server port released")
                logger.info("LAN status page stopped")
                refresh_remote_status()

            try:
                remote_window.after(0, finish_stop)
            except Exception:
                return

        threading.Thread(target=run_stop, daemon=True).start()

    def copy_lan_url():
        urls = remote_manager.lan_status_urls()
        lan_url = urls.get("lan_url", TEXT["no_lan_address"])
        app.clipboard_clear()
        app.clipboard_append(lan_url)
        status_label.configure(text=TEXT["lan_url"], text_color="#32CD32")
        logger.info("LAN URL copied")

    def mobile_chat_event(event):
        logger.info(event)

    def start_lan_chat():
        start_check = remote_manager.lan_chat_start_check()
        if not start_check.get("mobile_access_confirmed"):
            confirmed = messagebox.askyesno(TEXT["lan_chat"], TEXT["lan_chat_warning"])
            if not confirmed:
                status_label.configure(text=TEXT["blocked"], text_color="red")
                logger.info("Mobile request blocked")
                return
            remote_manager.update(mobile_access_confirmed=True)
            settings.set("remote.mobile_access_confirmed", True)
            start_check = remote_manager.lan_chat_start_check()

        if not start_check.get("security_confirmed"):
            status_label.configure(text=TEXT["security_confirmation_required"], text_color="red")
            logger.info("Mobile request blocked")
            return
        if not start_check.get("network_available") or not start_check.get("lan_address_available"):
            status_label.configure(text=start_check.get("reason", TEXT["not_ready"]), text_color="red")
            logger.info("Mobile request blocked")
            return

        status_label.configure(text=TEXT["checking"], text_color="gray")

        def run_start():
            port = settings.get("remote.lan_chat_port", settings.get("remote.lan_status_port", DEFAULT_LAN_STATUS_PORT))
            result = lan_status_server.start(
                "0.0.0.0",
                port,
                lan_status_snapshot,
                mobile_chat_service=mobile_chat_service,
                event_callback=mobile_chat_event
            )

            def finish_start():
                if remote_window is None or not remote_window.winfo_exists():
                    return
                if result.get("ok"):
                    remote_manager.update(
                        enabled=True,
                        lan_status_page_enabled=True,
                        lan_status_port=result.get("port", port),
                        lan_chat_enabled=True,
                        lan_chat_port=result.get("port", port),
                        mobile_access_confirmed=True
                    )
                    settings.set("remote.lan_status_page_enabled", True)
                    settings.set("remote.enabled", True)
                    settings.set("remote.lan_status_port", result.get("port", port))
                    settings.set("remote.lan_chat_enabled", True)
                    settings.set("remote.lan_chat_port", result.get("port", port))
                    settings.set("remote.mobile_access_confirmed", True)
                    status_label.configure(text=TEXT["mobile_chat_started"], text_color="#32CD32")
                    logger.info("Mobile chat started")
                else:
                    remote_manager.update(lan_chat_enabled=False)
                    settings.set("remote.lan_chat_enabled", False)
                    message = result.get("message", TEXT["failed"])
                    status_label.configure(text=message, text_color="red")
                    if "Port" in str(message):
                        logger.info("Mobile error handled")
                    logger.info("Mobile request blocked")
                refresh_remote_status()

            try:
                remote_window.after(0, finish_start)
            except Exception:
                return

        threading.Thread(target=run_start, daemon=True).start()

    def stop_lan_chat():
        status_label.configure(text=TEXT["checking"], text_color="gray")

        def run_stop():
            result = lan_status_server.stop()

            def finish_stop():
                if remote_window is None or not remote_window.winfo_exists():
                    return
                remote_manager.update(enabled=False, lan_status_page_enabled=False, lan_chat_enabled=False)
                settings.set("remote.enabled", False)
                settings.set("remote.lan_status_page_enabled", False)
                settings.set("remote.lan_chat_enabled", False)
                status_label.configure(
                    text=TEXT["mobile_chat_stopped"] if result.get("ok") else result.get("message", TEXT["failed"]),
                    text_color="#32CD32" if result.get("ok") else "red"
                )
                if result.get("released"):
                    logger.info("LAN server port released")
                logger.info("Mobile chat stopped")
                refresh_remote_status()

            try:
                remote_window.after(0, finish_stop)
            except Exception:
                return

        threading.Thread(target=run_stop, daemon=True).start()

    def copy_mobile_url():
        urls = remote_manager.lan_chat_urls()
        mobile_url = urls.get("mobile_url", TEXT["no_lan_address"])
        try:
            app.clipboard_clear()
            app.clipboard_append(mobile_url)
            status_label.configure(text=TEXT["mobile_url"], text_color="#32CD32")
            logger.info("LAN URL copied")
        except Exception as error:
            status_label.configure(text=TEXT["copy_failed"], text_color="red")
            logger.error(f"Mobile URL copy failed: {error}")
            logger.info("Mobile error handled")

    remote_button_specs = [
        (TEXT["understand_risk"], confirm_remote_security),
        (TEXT["setup_token"], setup_token_placeholder),
        (TEXT["test_secure_storage"], test_secure_storage),
        (TEXT["remove_test_credential"], remove_test_credential),
        (TEXT["start_lan_status_page"], start_lan_status_page),
        (TEXT["stop_lan_status_page"], stop_lan_status_page),
        (TEXT["copy_lan_url"], copy_lan_url),
        (TEXT["start_lan_chat"], start_lan_chat),
        (TEXT["stop_lan_chat"], stop_lan_chat),
        (TEXT["copy_mobile_url"], copy_mobile_url),
        (TEXT["refresh"], refresh_remote_status),
        (TEXT["close"], close_remote_window),
    ]
    for index, (text, command) in enumerate(remote_button_specs):
        ctk.CTkButton(buttons, text=text, command=command).grid(
            row=index // 3,
            column=index % 3,
            sticky="ew",
            padx=6,
            pady=5
        )
    remote_window.protocol("WM_DELETE_WINDOW", close_remote_window)
    refresh_remote_status()


def show_remote_diagnostics():
    global remote_diagnostics_window
    if remote_diagnostics_window is not None and remote_diagnostics_window.winfo_exists():
        remote_diagnostics_window.focus()
        remote_diagnostics_window.lift()
        return

    logger.info("Remote diagnostics opened")
    remote_diagnostics_window = ctk.CTkToplevel(app)
    remote_diagnostics_window.title(TEXT["remote_diagnostics"])
    remote_diagnostics_window.geometry("760x680")
    remote_diagnostics_window.minsize(620, 520)
    remote_diagnostics_window.transient(app)

    ctk.CTkLabel(
        remote_diagnostics_window,
        text=TEXT["remote_diagnostics"],
        font=("Microsoft YaHei", 22, "bold")
    ).pack(anchor="w", padx=25, pady=(20, 10))

    diagnostic_status = ctk.CTkLabel(
        remote_diagnostics_window,
        text=TEXT["checking"],
        font=("Microsoft YaHei", 12),
        text_color="gray"
    )
    diagnostic_status.pack(anchor="w", padx=25, pady=(0, 10))

    content = ctk.CTkScrollableFrame(remote_diagnostics_window)
    content.pack(fill="both", expand=True, padx=25, pady=(0, 12))
    rows = {}

    def add_title(text):
        ctk.CTkLabel(
            content,
            text=text,
            font=("Microsoft YaHei", 15, "bold"),
            anchor="w"
        ).pack(anchor="w", padx=15, pady=(16, 6))

    def add_row(key, label):
        row = ctk.CTkFrame(content, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=6)
        ctk.CTkLabel(row, text=label, font=("Microsoft YaHei", 13, "bold")).pack(side="left")
        value = ctk.CTkLabel(row, text="--", font=("Microsoft YaHei", 13), anchor="e")
        value.pack(side="right")
        rows[key] = value

    add_title(TEXT["remote_readiness_summary"])
    for key, label in (
        ("summary_network", TEXT["network"]),
        ("summary_lan", TEXT["lan"]),
        ("summary_authentication", TEXT["authentication"]),
        ("summary_credential", TEXT["credential_storage"]),
        ("summary_remote", TEXT["remote_access"]),
    ):
        add_row(key, label)

    add_title(TEXT["remote_diagnostics"])
    for key, label in (
        ("network_status", TEXT["network"]),
        ("lan_readiness", TEXT["lan_readiness"]),
        ("security_gate", TEXT["safety_gate"]),
        ("authentication_status_row", TEXT["authentication"]),
        ("credential_status_row", TEXT["credential_storage"]),
    ):
        add_row(key, label)

    add_title(TEXT["credential_storage_details"])
    for key, label in (
        ("credential_operation", TEXT["last_operation"]),
        ("credential_operation_result", TEXT["operation_result"]),
        ("credential_duration", TEXT["duration"]),
        ("credential_error", TEXT["error_reason"]),
        ("credential_suggestion", TEXT["suggestion"]),
    ):
        add_row(key, label)

    history_box = ctk.CTkTextbox(content, height=170, wrap="word")
    history_box.pack(fill="x", padx=15, pady=(12, 8))
    history_box.configure(state="disabled")

    release_box = ctk.CTkTextbox(content, height=150, wrap="word")
    release_box.pack(fill="x", padx=15, pady=(8, 12))
    release_box.configure(state="disabled")

    def set_box(box, text):
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled")

    def update_diagnostics_view(data):
        summary = data.get("summary", {})
        health = data.get("health", {})
        safety = data.get("safety_gate", {})
        auth = data.get("authentication", {})
        config = data.get("config", {})
        rows["summary_network"].configure(text=TEXT["ready"] if summary.get("network") == "Ready" else TEXT["not_ready"])
        rows["summary_lan"].configure(text=TEXT["ready"] if summary.get("lan") == "Ready" else TEXT["not_ready"])
        rows["summary_authentication"].configure(text=TEXT["ready"] if summary.get("authentication") == "Ready" else TEXT["missing"])
        rows["summary_credential"].configure(text=TEXT["available_status"] if summary.get("credential_storage") == "Available" else TEXT["storage_missing"])
        rows["summary_remote"].configure(text=TEXT["enabled"] if summary.get("remote_access") == "Enabled" else TEXT["disabled"])
        rows["network_status"].configure(text=TEXT["ok"] if health.get("network") == "OK" else TEXT["offline"])
        rows["lan_readiness"].configure(text=TEXT["ready"] if health.get("lan_readiness") == "Ready" else TEXT["not_ready"])
        rows["security_gate"].configure(text=TEXT["ready"] if safety.get("ready") else TEXT["blocked"])
        rows["authentication_status_row"].configure(text=TEXT["ready"] if auth.get("configured") else TEXT["missing"])
        rows["credential_status_row"].configure(text=TEXT["available_status"] if auth.get("secure_storage_available") else TEXT["storage_missing"])
        rows["credential_operation"].configure(text=auth.get("credential_last_operation") or "--")
        rows["credential_operation_result"].configure(text=auth.get("credential_operation_result") or "--")
        rows["credential_duration"].configure(text=f"{auth.get('credential_duration_ms', 0)}ms")
        rows["credential_error"].configure(text=auth.get("last_storage_error") or TEXT["none"])
        rows["credential_suggestion"].configure(text=auth.get("credential_error_suggestion") or TEXT["none"])

        history_lines = []
        for title, key in (
            ("Network History", "network_history"),
            ("Security History", "security_history"),
            ("Authentication History", "authentication_history"),
            ("Credential History", "credential_history"),
            ("Remote History", "remote_history")
        ):
            history_lines.append(title)
            history = config.get(key, [])
            if history:
                for item in reversed(history[-10:]):
                    history_lines.append(f"{item.get('time') or '--'}   {item.get('status') or '--'}   {item.get('result') or '--'}")
            else:
                history_lines.append(TEXT["no_history"])
            history_lines.append("")
        set_box(history_box, "\n".join(history_lines))
        diagnostic_status.configure(text=TEXT["ready"], text_color="#32CD32")

    def refresh_remote_diagnostics():
        diagnostic_status.configure(text=TEXT["checking"], text_color="gray")

        def run_refresh():
            try:
                provider_status = credential_storage_provider.check_available()
                remote_manager.update_credential_diagnostics(provider_status)
                remote_manager.record_diagnostic_history()
                data = remote_manager.diagnostics()
                error_message = None
            except Exception as error:
                data = {}
                error_message = str(error)

            def finish_refresh():
                if remote_diagnostics_window is None or not remote_diagnostics_window.winfo_exists():
                    return
                if error_message:
                    diagnostic_status.configure(text=error_message, text_color="red")
                    return
                update_diagnostics_view(data)

            remote_diagnostics_window.after(0, finish_refresh)

        threading.Thread(target=run_refresh, daemon=True).start()

    def run_release_check():
        logger.info("Release check started")
        set_box(release_box, TEXT["checking"])

        def run_check():
            try:
                result = remote_manager.release_check(Path(__file__).resolve().parent)
                error_message = None
            except Exception as error:
                result = {"checks": [], "passed": False}
                error_message = str(error)

            def finish_check():
                if remote_diagnostics_window is None or not remote_diagnostics_window.winfo_exists():
                    return
                if error_message:
                    set_box(release_box, error_message)
                    return
                lines = [
                    f"{'\u2713' if item.get('ok') else '\u2717'} {item.get('label')}"
                    for item in result.get("checks", [])
                ]
                lines.append("")
                lines.append(f"{TEXT['overall']}: {TEXT['passed'] if result.get('passed') else TEXT['blocked']}")
                set_box(release_box, "\n".join(lines))
                logger.info("Release check completed")
                logger.info("v2.0 release check completed")

            remote_diagnostics_window.after(0, finish_check)

        threading.Thread(target=run_check, daemon=True).start()

    def close_remote_diagnostics():
        global remote_diagnostics_window
        remote_diagnostics_window.destroy()
        remote_diagnostics_window = None

    buttons = ctk.CTkFrame(remote_diagnostics_window, fg_color="transparent")
    buttons.pack(fill="x", padx=25, pady=(0, 20))
    ctk.CTkButton(buttons, text=TEXT["refresh"], command=refresh_remote_diagnostics).pack(side="left", expand=True, fill="x", padx=(0, 6))
    ctk.CTkButton(buttons, text=TEXT["release_check"], command=run_release_check).pack(side="left", expand=True, fill="x", padx=6)
    ctk.CTkButton(buttons, text=TEXT["close"], command=close_remote_diagnostics).pack(side="left", expand=True, fill="x", padx=(6, 0))
    remote_diagnostics_window.protocol("WM_DELETE_WINDOW", close_remote_diagnostics)
    refresh_remote_diagnostics()


actions_frame = ctk.CTkScrollableFrame(app, height=250)
actions_frame.pack(fill="x", padx=20, pady=(0, 8))


action_title = ctk.CTkLabel(
    actions_frame,
    text=TEXT["quick_actions"],
    font=("Microsoft YaHei", 16, "bold")
)
action_title.pack(anchor="w", padx=15, pady=(5, 10))


btn1 = ctk.CTkButton(
    actions_frame,
    text=TEXT["open_webui"],
    command=launch_open_webui
)
btn1.pack(fill="x", padx=40, pady=8)

btn_diagnostic = ctk.CTkButton(
    actions_frame,
    text="Runtime Environment Diagnostics",
    command=run_diagnostic
)
btn_diagnostic.pack(fill="x", padx=40, pady=8)

btn_start_ollama = ctk.CTkButton(
    actions_frame,
    text="鍚姩 Ollama",
    command=start_ollama_manual
)
btn_start_ollama.pack(fill="x", padx=40, pady=8)

btn_restart_webui = ctk.CTkButton(
    actions_frame,
    text="閲嶅惎 Open WebUI",
    command=restart_openwebui_manual
)
btn_restart_webui.pack(fill="x", padx=40, pady=8)

btn_restart_container = ctk.CTkButton(
    actions_frame,
    text="閲嶅惎瀹瑰櫒",
    command=restart_container_manual
)
btn_restart_container.pack(fill="x", padx=40, pady=8)

btn_close_webui = ctk.CTkButton(
    actions_frame,
    text="鍏抽棴 Open WebUI",
    command=close_open_webui
)
btn_close_webui.pack(fill="x", padx=40, pady=8)


btn2 = ctk.CTkButton(
    actions_frame,
    text=TEXT["models"],
    command=show_models
)
btn2.pack(fill="x", padx=40, pady=8)


btn_chat = ctk.CTkButton(
    actions_frame,
    text=TEXT["chat"],
    command=show_chat
)
btn_chat.pack(fill="x", padx=40, pady=8)


btn_memory = ctk.CTkButton(
    actions_frame,
    text=TEXT["memory"],
    command=show_memory
)
btn_memory.pack(fill="x", padx=40, pady=8)


btn_persona = ctk.CTkButton(
    actions_frame,
    text=TEXT["persona"],
    command=show_persona
)
btn_persona.pack(fill="x", padx=40, pady=8)


btn_knowledge = ctk.CTkButton(
    actions_frame,
    text="Knowledge Base",
    command=show_knowledge
)
btn_knowledge.pack(fill="x", padx=40, pady=8)


btn_remote = ctk.CTkButton(
    actions_frame,
    text=TEXT["remote_access"],
    command=show_remote_access
)
btn_remote.pack(fill="x", padx=40, pady=8)


btn_remote_diagnostics = ctk.CTkButton(
    actions_frame,
    text=TEXT["remote_diagnostics"],
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

    settings_window = ctk.CTkToplevel(app)
    settings_window.title(TEXT["settings"])
    settings_window.geometry("560x560")
    settings_window.resizable(False, False)
    settings_window.transient(app)

    settings_title = ctk.CTkLabel(
        settings_window,
        text=TEXT["settings"],
        font=("Microsoft YaHei", 20, "bold")
    )
    settings_title.pack(anchor="w", padx=25, pady=(20, 15))

    content = ctk.CTkScrollableFrame(settings_window)
    content.pack(fill="both", expand=True, padx=25, pady=(0, 12))

    appearance_value = settings.get("appearance", "System")
    if appearance_value not in ["System", "Light", "Dark"]:
        appearance_value = "System"
    appearance_display = {"System": "绯荤粺", "Light": "娴呰壊", "Dark": "娣辫壊"}

    theme_value = settings.get("theme", "blue")
    theme_options = ["blue", "green", "dark-blue"]
    if theme_value not in theme_options:
        theme_value = "blue"

    def add_section_title(text):
        ctk.CTkLabel(
            content,
            text=text,
            font=("Microsoft YaHei", 15, "bold")
        ).pack(anchor="w", padx=10, pady=(12, 6))

    def add_option_row(label_text, values, current_value):
        row = ctk.CTkFrame(content, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=6)

        ctk.CTkLabel(
            row,
            text=label_text,
            anchor="w",
            font=("Microsoft YaHei", 13)
        ).pack(side="left")

        option = ctk.CTkOptionMenu(row, values=values, width=180)
        option.set(current_value)
        option.pack(side="right")
        return option

    def add_entry_row(label_text, current_value):
        row = ctk.CTkFrame(content, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=6)

        ctk.CTkLabel(
            row,
            text=label_text,
            anchor="w",
            font=("Microsoft YaHei", 13)
        ).pack(side="left")

        entry = ctk.CTkEntry(row, width=250)
        entry.insert(0, str(current_value))
        entry.pack(side="right")
        return entry

    def add_status_row(label_text, value_text, color="gray"):
        row = ctk.CTkFrame(content, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(
            row,
            text=label_text,
            anchor="w",
            font=("Microsoft YaHei", 13)
        ).pack(side="left")
        ctk.CTkLabel(
            row,
            text=str(value_text),
            font=("Microsoft YaHei", 12),
            text_color=color
        ).pack(side="right")

    add_section_title("General")
    appearance_option = add_option_row(
        TEXT["appearance"],
        list(appearance_display.values()),
        appearance_display[appearance_value]
    )
    theme_option = add_option_row(TEXT["theme"], theme_options, theme_value)
    language_option = add_option_row(
        "Language",
        ["\u7b80\u4f53\u4e2d\u6587", "English"],
        settings.get("language", "\u7b80\u4f53\u4e2d\u6587")
    )

    add_section_title("AI")
    ollama_host_entry = add_entry_row(
        TEXT["ollama_host"],
        settings.get("ollama.host", "http://127.0.0.1:11434")
    )
    auto_start_ollama_var = ctk.BooleanVar(
        value=bool(settings.get("ollama.auto_start", False))
    )
    ctk.CTkSwitch(
        content,
        text="Ollama Auto Start",
        variable=auto_start_ollama_var
    ).pack(anchor="w", padx=10, pady=6)
    ollama_command_entry = add_entry_row(
        "Ollama Command",
        settings.get("services.ollama.command", "ollama serve")
    )
    chat_model_entry = add_entry_row(
        TEXT["chat_model"],
        settings.get("chat_model", "qwen3:8b")
    )
    embedding_model_entry = add_entry_row(
        TEXT["embedding_model"],
        settings.get("embedding_model", "nomic-embed-text:latest")
    )
    openwebui_url_entry = add_entry_row(
        TEXT["openwebui_url"],
        settings.get("openwebui.host", "http://localhost:8080")
    )
    openwebui_type_option = add_option_row(
        "Open WebUI Type",
        ["docker"],
        settings.get("openwebui.type", "docker")
    )
    openwebui_container_entry = add_entry_row(
        "Container Name",
        settings.get("openwebui.container_name", "open-webui")
    )
    auto_start_openwebui_var = ctk.BooleanVar(
        value=bool(settings.get("openwebui.auto_start", False))
    )
    ctk.CTkSwitch(
        content,
        text="Auto Start Open WebUI",
        variable=auto_start_openwebui_var
    ).pack(anchor="w", padx=10, pady=6)
    docker_auto_start_var = ctk.BooleanVar(
        value=bool(settings.get("services.docker.auto_start", True))
    )
    ctk.CTkSwitch(
        content,
        text="Docker Desktop Auto Start",
        variable=docker_auto_start_var
    ).pack(anchor="w", padx=10, pady=6)
    docker_path_entry = add_entry_row(
        "Docker Desktop Path",
        settings.get("services.docker.path", r"C:\Program Files\Docker\Docker\Docker Desktop.exe")
    )
    docker_timeout_entry = add_entry_row(
        "Docker Startup Timeout",
        settings.get("services.docker.startup_timeout", 60)
    )

    add_section_title("Developer")
    refresh_interval_entry = add_entry_row(
        TEXT["refresh_interval"],
        settings.get("status.refresh_interval", 3)
    )
    add_status_row("Debug Mode", "Enabled" if settings.get("mobile_debug_mode", False) else "Disabled")
    add_status_row("Log Level", settings.get("log.level", "INFO"))

    add_section_title("Remote")
    remote_enabled_var = ctk.BooleanVar(
        value=bool(settings.get("remote.enabled", False))
    )
    ctk.CTkSwitch(
        content,
        text=TEXT["remote_access_enable"],
        variable=remote_enabled_var
    ).pack(anchor="w", padx=10, pady=6)
    remote_mode_option = add_option_row(
        TEXT["remote_mode"],
        ["local"],
        settings.get("remote.mode", "local")
    )
    add_status_row("Public Access", "Not available in this version", "orange")
    preferred_interface_entry = add_entry_row(
        TEXT["preferred_interface"],
        settings.get("network.preferred_interface", "")
    )
    ignore_virtual_adapter_var = ctk.BooleanVar(
        value=bool(settings.get("network.ignore_virtual_adapter", True))
    )
    ctk.CTkSwitch(
        content,
        text=TEXT["ignore_virtual_adapter"],
        variable=ignore_virtual_adapter_var
    ).pack(anchor="w", padx=10, pady=6)
    lan_chat_enabled_var = ctk.BooleanVar(
        value=bool(settings.get("remote.lan_chat_enabled", False))
    )
    ctk.CTkSwitch(
        content,
        text=TEXT["lan_chat_enable"],
        variable=lan_chat_enabled_var
    ).pack(anchor="w", padx=10, pady=6)
    mobile_access_confirmed_var = ctk.BooleanVar(
        value=bool(settings.get("remote.mobile_access_confirmed", False))
    )
    ctk.CTkSwitch(
        content,
        text=TEXT["mobile_access_confirm"],
        variable=mobile_access_confirmed_var
    ).pack(anchor="w", padx=10, pady=6)
    mobile_chat_timeout_entry = add_entry_row(
        TEXT["mobile_chat_timeout"],
        settings.get("mobile_chat_timeout", 60)
    )
    mobile_debug_mode_var = ctk.BooleanVar(
        value=bool(settings.get("mobile_debug_mode", False))
    )
    ctk.CTkSwitch(
        content,
        text=TEXT["mobile_debug_mode"],
        variable=mobile_debug_mode_var
    ).pack(anchor="w", padx=10, pady=6)
    mobile_response_limit_entry = add_entry_row(
        TEXT["mobile_response_limit"],
        settings.get("mobile_response_limit", 12000)
    )
    add_section_title("Persona")
    try:
        current_persona = persona_store.status(settings.get("persona.enabled", True), persona_store.load(update_timestamp=False))
        add_status_row("Current Persona", current_persona.get("name", "Aurora"), "#32CD32")
    except Exception as error:
        add_status_row("Current Persona", error, "red")
    persona_enabled_var = ctk.BooleanVar(
        value=bool(settings.get("persona.enabled", True))
    )
    ctk.CTkSwitch(
        content,
        text=TEXT["persona_enable"],
        variable=persona_enabled_var
    ).pack(anchor="w", padx=10, pady=6)

    add_section_title("Memory")
    add_status_row("Memory Available", "Yes")
    max_injection_entry = add_entry_row(
        "Maximum Memory Injection",
        settings.get("memory.max_injection", 5)
    )
    min_importance_entry = add_entry_row(
        "Minimum Memory Importance",
        settings.get("memory.min_importance", 0)
    )

    add_section_title("Knowledge")
    knowledge_enabled_var = ctk.BooleanVar(
        value=bool(settings.get("knowledge.enabled", True))
    )
    ctk.CTkSwitch(
        content,
        text="Knowledge Enable",
        variable=knowledge_enabled_var
    ).pack(anchor="w", padx=10, pady=6)
    max_knowledge_entry = add_entry_row(
        "Maximum Knowledge Results",
        settings.get("knowledge.max_results", 3)
    )

    add_section_title("Status Overview")
    try:
        health_report = system_self_check(timeout=2)
        health_items = {
            item.get("name"): item
            for item in health_report.get("items", [])
            if isinstance(item, dict)
        }
    except Exception as error:
        health_report = {"status": "Error"}
        health_items = {}
        add_status_row("Health Check", error, "red")

    def status_value(name):
        item = health_items.get(name, {})
        status = item.get("status", "Unknown")
        color = health_status_color(status) if status in {"Healthy", "Warning", "Error"} else "gray"
        return status, color, item.get("details", {})

    for status_name in [
        "Ollama",
        "Chat Model",
        "Embedding Model",
        "Persona",
        "Memory",
        "Knowledge",
        "Vector Index",
        "Conversation Store",
        "Remote"
    ]:
        value, color, _details = status_value(status_name)
        add_status_row("Conversation" if status_name == "Conversation Store" else status_name, value, color)

    _memory_status, _memory_color, memory_details = status_value("Memory")
    _knowledge_status, _knowledge_color, knowledge_details = status_value("Knowledge")
    _conversation_status, _conversation_color, conversation_details = status_value("Conversation Store")
    add_status_row("Memory Count", memory_details.get("records", 0))
    add_status_row("Knowledge Documents", knowledge_details.get("total", 0))
    add_status_row("Conversation Count", conversation_details.get("records", 0))
    add_status_row("Remote Enabled", "Yes" if settings.get("remote.enabled", False) else "No")
    add_status_row("Log Level", settings.get("log.level", "INFO"))

    result_label = ctk.CTkLabel(
        settings_window,
        text="",
        font=("Microsoft YaHei", 12),
        text_color="#32CD32"
    )
    result_label.pack(pady=(0, 8))

    def check_service_connection(service_name, url, callback):
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
                reason = "Timeout"
            except ConnectionRefusedError:
                reason = "Connection refused"
            except urllib.error.URLError as error:
                if isinstance(error.reason, socket.timeout):
                    reason = "Timeout"
                elif isinstance(error.reason, ConnectionRefusedError):
                    reason = "Connection refused"
                else:
                    reason = "Connection error"
            except (OSError, ValueError):
                reason = "Connection error"

            elapsed_ms = int((time.perf_counter() - started_at) * 1000)

            if connected:
                logger.info(
                    f"{service_name} connected ({elapsed_ms}ms)"
                )
            else:
                logger.info(
                    f"{service_name} connection failed: {reason}"
                )

            def update_result():
                try:
                    if settings_window is None or not settings_window.winfo_exists():
                        return
                    callback(connected, elapsed_ms, reason)
                except Exception:
                    return

            try:
                settings_window.after(0, update_result)
            except Exception:
                return

        logger.info(f"Testing {service_name} connection...")
        threading.Thread(target=run_check, daemon=True).start()

    def update_connection_result(label, button, connected, elapsed_ms, reason):
        button.configure(state="normal")

        if connected:
            label.configure(
                text=f"\u2705 Connected ({elapsed_ms}ms)",
                text_color="#32CD32"
            )
        else:
            label.configure(
                text=f"\u274c Cannot connect - {reason}",
                text_color="red"
            )

    ollama_result_label = ctk.CTkLabel(
        content,
        text="",
        font=("Microsoft YaHei", 12),
        text_color="gray"
    )
    ollama_result_label.pack(anchor="e", padx=10, pady=(0, 2))

    openwebui_result_label = ctk.CTkLabel(
        content,
        text="",
        font=("Microsoft YaHei", 12),
        text_color="gray"
    )
    openwebui_result_label.pack(anchor="e", padx=10, pady=(0, 8))

    def test_ollama_url():
        url = ollama_host_entry.get().strip()
        ollama_test_button.configure(state="disabled")
        ollama_result_label.configure(
                text="娴嬭瘯涓?..",
            text_color="gray"
        )
        check_service_connection(
            "Ollama",
            url,
            lambda connected, elapsed_ms, reason: update_connection_result(
                ollama_result_label,
                ollama_test_button,
                connected,
                elapsed_ms,
                reason
            )
        )

    def test_openwebui_url():
        url = openwebui_url_entry.get().strip()
        openwebui_test_button.configure(state="disabled")
        openwebui_result_label.configure(
                text="娴嬭瘯涓?..",
            text_color="gray"
        )
        check_service_connection(
            "Open WebUI",
            url,
            lambda connected, elapsed_ms, reason: update_connection_result(
                openwebui_result_label,
                openwebui_test_button,
                connected,
                elapsed_ms,
                reason
            )
        )

    ollama_test_button = ctk.CTkButton(
        ollama_host_entry.master,
        text=TEXT["test"],
        width=70,
        command=test_ollama_url
    )
    ollama_test_button.pack(side="right", padx=(0, 8))

    openwebui_test_button = ctk.CTkButton(
        openwebui_url_entry.master,
        text=TEXT["test"],
        width=70,
        command=test_openwebui_url
    )
    openwebui_test_button.pack(side="right", padx=(0, 8))

    def save_settings():
        try:
            refresh_interval = float(refresh_interval_entry.get().strip())
            if refresh_interval <= 0:
                raise ValueError
            max_injection = int(max_injection_entry.get().strip())
            min_importance = float(min_importance_entry.get().strip())
            max_knowledge = int(max_knowledge_entry.get().strip())
            docker_timeout = int(docker_timeout_entry.get().strip())
            mobile_chat_timeout = int(mobile_chat_timeout_entry.get().strip())
            mobile_response_limit = int(mobile_response_limit_entry.get().strip())
            chat_model_value = chat_model_entry.get().strip()
            embedding_model_value = embedding_model_entry.get().strip()
            if (
                max_injection < 1
                or min_importance < 0
                or max_knowledge < 0
                or docker_timeout < 1
                or mobile_chat_timeout < 1
                or mobile_response_limit < 1000
                or not chat_model_value
                or not embedding_model_value
            ):
                raise ValueError
        except ValueError:
            result_label.configure(
                text="Invalid refresh interval, injection count, or importance threshold.",
                text_color="red"
            )
            return

        def persist_settings():
            selected_appearance = {
                "绯荤粺": "System",
                "娴呰壊": "Light",
                "娣辫壊": "Dark"
            }.get(appearance_option.get(), "System")
            settings.set("appearance", selected_appearance)
            settings.set("theme", theme_option.get())
            settings.set("ollama.host", ollama_host_entry.get().strip())
            settings.set("ollama.auto_start", auto_start_ollama_var.get())
            settings.set("services.ollama.command", ollama_command_entry.get().strip())
            settings.set("openwebui.host", openwebui_url_entry.get().strip())
            settings.set("openwebui.type", openwebui_type_option.get())
            settings.set("openwebui.container_name", openwebui_container_entry.get().strip())
            settings.set("openwebui.auto_start", auto_start_openwebui_var.get())
            settings.set("services.docker.auto_start", docker_auto_start_var.get())
            settings.set("services.docker.path", docker_path_entry.get().strip())
            settings.set("services.docker.startup_timeout", max(1, int(docker_timeout_entry.get().strip())))
            settings.set("status.refresh_interval", refresh_interval)
            settings.set("network.preferred_interface", preferred_interface_entry.get().strip())
            settings.set("network.ignore_virtual_adapter", ignore_virtual_adapter_var.get())
            settings.set("chat_model", chat_model_value)
            settings.set("embedding_model", embedding_model_value)
            logger.info("Chat model loaded")
            logger.info("Embedding model loaded")
            logger.info("Model capability checked")
            if infer_model_capability(chat_model_value) != "Chat Supported":
                logger.info("Embedding model blocked from chat")
            requested_remote_enabled = bool(remote_enabled_var.get())
            remote_manager.update(
                enabled=False,
                mode=remote_mode_option.get(),
                auth_required=True,
                auth_enabled=settings.get("remote.auth_enabled", False),
                authentication_type=settings.get("remote.authentication_type", "none"),
                token_configured=settings.get("remote.token_configured", False),
                credential_storage=settings.get("remote.credential_storage", "windows_credential_manager"),
                secure_storage_configured=settings.get("remote.secure_storage_configured", False),
                secure_storage_available=settings.get("remote.secure_storage_available", False),
                credential_test_passed=settings.get("remote.credential_test_passed", False),
                credential_last_check=settings.get("remote.credential_last_check", None),
                credential_last_result=settings.get("remote.credential_last_result", None),
                credential_command_status=settings.get("remote.credential_command_status", "Unavailable"),
                last_storage_error=settings.get("remote.last_storage_error", None),
                credential_history=settings.get("remote.credential_history", []),
                credential_steps=settings.get("remote.credential_steps", []),
                authentication_configured=authentication_manager.is_configured(),
                lan_ready=settings.get("remote.lan_ready", False),
                ios_access_ready=settings.get("remote.ios_access_ready", False),
                tailscale_ready=settings.get("remote.tailscale_ready", False),
                user_confirmed=settings.get("remote.user_confirmed", False),
                security_confirmed=settings.get("remote.security_confirmed", False),
                lan_chat_enabled=lan_chat_enabled_var.get(),
                lan_chat_port=settings.get("remote.lan_chat_port", DEFAULT_LAN_STATUS_PORT),
                mobile_access_confirmed=mobile_access_confirmed_var.get(),
                mobile_chat_timeout=mobile_chat_timeout,
                mobile_debug_mode=mobile_debug_mode_var.get(),
                mobile_response_limit=mobile_response_limit
            )
            remote_enable_allowed = False
            if requested_remote_enabled:
                logger.info("Remote safety check started")
                enable_result = remote_manager.request_enable()
                remote_enable_allowed = bool(enable_result.get("allowed"))
                if remote_enable_allowed:
                    logger.info("Remote safety check passed")
                else:
                    logger.info("Remote safety check blocked")
                    if "Authentication is required" in enable_result.get("message", ""):
                        logger.info("Remote enable blocked authentication missing")
                    if "Token authentication" in enable_result.get("message", ""):
                        logger.info("Token configuration missing")
                    if "Secure credential storage" in enable_result.get("message", ""):
                        logger.info("Secure storage missing")
                    remote_enabled_var.set(False)
                    result_label.configure(
                        text=TEXT["remote_blocked_storage_unavailable"] if "Secure credential storage unavailable" in enable_result.get("message", "") else TEXT["secure_credential_storage_required"] if "Secure credential storage" in enable_result.get("message", "") else TEXT["authentication_required_before_remote"],
                        text_color="red"
                    )
            settings.set("remote.enabled", remote_enable_allowed if requested_remote_enabled else False)
            settings.set("remote.mode", remote_mode_option.get())
            settings.set("remote.auth_required", True)
            settings.set("remote.authentication_required", True)
            settings.set("remote.auth_enabled", settings.get("remote.auth_enabled", False))
            settings.set("remote.authentication_type", settings.get("remote.authentication_type", "none"))
            settings.set("remote.token_configured", settings.get("remote.token_configured", False))
            settings.set("remote.last_token_update", settings.get("remote.last_token_update", None))
            settings.set("remote.credential_storage", settings.get("remote.credential_storage", "windows_credential_manager"))
            settings.set("remote.secure_storage_configured", settings.get("remote.secure_storage_configured", False))
            settings.set("remote.secure_storage_available", settings.get("remote.secure_storage_available", False))
            settings.set("remote.credential_test_passed", settings.get("remote.credential_test_passed", False))
            settings.set("remote.credential_last_check", settings.get("remote.credential_last_check", None))
            settings.set("remote.credential_last_result", settings.get("remote.credential_last_result", None))
            settings.set("remote.credential_command_status", settings.get("remote.credential_command_status", "Unavailable"))
            settings.set("remote.credential_last_operation", settings.get("remote.credential_last_operation", None))
            settings.set("remote.credential_operation_result", settings.get("remote.credential_operation_result", None))
            settings.set("remote.credential_duration_ms", settings.get("remote.credential_duration_ms", 0))
            settings.set("remote.credential_error_suggestion", settings.get("remote.credential_error_suggestion", None))
            settings.set("remote.last_storage_error", settings.get("remote.last_storage_error", None))
            settings.set("remote.credential_history", settings.get("remote.credential_history", []))
            settings.set("remote.credential_steps", settings.get("remote.credential_steps", []))
            settings.set("remote.network_history", settings.get("remote.network_history", []))
            settings.set("remote.security_history", settings.get("remote.security_history", []))
            settings.set("remote.authentication_history", settings.get("remote.authentication_history", []))
            settings.set("remote.remote_history", settings.get("remote.remote_history", []))
            settings.set("remote.authentication_configured", authentication_manager.is_configured())
            settings.set("remote.lan_ready", settings.get("remote.lan_ready", False))
            settings.set("remote.ios_access_ready", settings.get("remote.ios_access_ready", False))
            settings.set("remote.tailscale_ready", settings.get("remote.tailscale_ready", False))
            settings.set("remote.user_confirmed", settings.get("remote.user_confirmed", False))
            settings.set("remote.security_confirmed", settings.get("remote.security_confirmed", False))
            settings.set("remote.lan_chat_enabled", lan_chat_enabled_var.get())
            settings.set("remote.lan_chat_port", settings.get("remote.lan_chat_port", DEFAULT_LAN_STATUS_PORT))
            settings.set("remote.mobile_access_confirmed", mobile_access_confirmed_var.get())
            settings.set("remote.mobile_chat_timeout", mobile_chat_timeout)
            settings.set("remote.mobile_debug_mode", mobile_debug_mode_var.get())
            settings.set("remote.mobile_response_limit", mobile_response_limit)
            settings.set("mobile_chat_timeout", mobile_chat_timeout)
            settings.set("mobile_debug_mode", mobile_debug_mode_var.get())
            settings.set("mobile_response_limit", mobile_response_limit)
            logger.info("Remote configuration updated")
            if not remote_enable_allowed:
                logger.info("Remote access disabled")
            settings.set("memory.max_injection", max_injection)
            settings.set("memory.min_importance", min_importance)
            settings.set("persona.enabled", persona_enabled_var.get())
            logger.info("Persona enabled" if persona_enabled_var.get() else "Persona disabled")
            settings.set("knowledge.enabled", knowledge_enabled_var.get())
            settings.set("knowledge.max_results", max_knowledge)
            settings.set("language", language_option.get())
            set_language(language_option.get())

            if selected_appearance.lower() == "system":
                ctk.set_appearance_mode("System")
            elif selected_appearance.lower() == "light":
                ctk.set_appearance_mode("Light")
            else:
                ctk.set_appearance_mode("Dark")

            save_button.configure(state="normal")
            ollama_test_button.configure(state="normal")
            openwebui_test_button.configure(state="normal")
            logger.info("Settings saved")
            logger.info("Language changed")
            result_label.configure(
                text="Settings saved.",
                text_color="#32CD32"
            )

        def finish_save(connected, elapsed_ms, reason):
            if not connected:
                should_save = messagebox.askyesno(
                    "Connection Warning",
                    "\u5f53\u524d\u5730\u5740\u65e0\u6cd5\u8fde\u63a5\uff0c\u662f\u5426\u4ecd\u7136\u4fdd\u5b58\uff1f",
                    parent=settings_window
                )
                if not should_save:
                    save_button.configure(state="normal")
                    ollama_test_button.configure(state="normal")
                    openwebui_test_button.configure(state="normal")
                    result_label.configure(
                        text="Save canceled.",
                        text_color="gray"
                    )
                    return

            persist_settings()

        save_button.configure(state="disabled")
        ollama_test_button.configure(state="disabled")
        openwebui_test_button.configure(state="disabled")
        result_label.configure(
            text="Testing before save...",
            text_color="gray"
        )
        check_service_connection(
            "Open WebUI",
            openwebui_url_entry.get().strip(),
            finish_save
        )

    def close_settings_window():
        global settings_window
        settings_window.destroy()
        settings_window = None

    button_frame = ctk.CTkFrame(settings_window, fg_color="transparent")
    button_frame.pack(fill="x", padx=25, pady=(0, 20))

    save_button = ctk.CTkButton(
        button_frame,
        text=TEXT["save"],
        command=save_settings
    )
    save_button.pack(side="left", expand=True, fill="x", padx=(0, 6))

    ctk.CTkButton(
        button_frame,
        text=TEXT["close"],
        command=close_settings_window
    ).pack(side="left", expand=True, fill="x", padx=(6, 0))

    settings_window.protocol("WM_DELETE_WINDOW", close_settings_window)


settings_button = ctk.CTkButton(
    actions_frame,
    text=TEXT["settings"],
    command=show_settings
)
settings_button.pack(fill="x", padx=40, pady=8)


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

    health_window = ctk.CTkToplevel(app)
    health_window.title(TEXT["health_dashboard"])
    health_window.geometry("520x500")
    health_window.resizable(False, False)
    health_window.transient(app)

    dashboard_title = ctk.CTkLabel(
        health_window,
        text=TEXT["health_dashboard"],
        font=("Microsoft YaHei", 20, "bold")
    )
    dashboard_title.pack(anchor="w", padx=25, pady=(20, 15))

    status_frame = ctk.CTkFrame(health_window)
    status_frame.pack(fill="x", padx=25, pady=(0, 12))

    health_labels = {}

    health_items = [
        ("Ollama", "ollama"),
        ("Open WebUI", "webui"),
        ("API 11434", "api")
    ]

    for name, key in health_items:
        row = ctk.CTkFrame(status_frame, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=7)

        ctk.CTkLabel(
            row,
            text=name,
            anchor="w",
            font=("Microsoft YaHei", 14)
        ).pack(side="left")

        state = ctk.CTkLabel(
            row,
            text=TEXT["checking"],
            font=("Microsoft YaHei", 13),
            text_color="gray"
        )
        state.pack(side="right")
        health_labels[key] = state

    system_frame = ctk.CTkFrame(health_window)
    system_frame.pack(fill="x", padx=25, pady=(0, 12))

    def add_information_row(label_text, initial_text):
        row = ctk.CTkFrame(system_frame, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=7)

        ctk.CTkLabel(
            row,
            text=label_text,
            anchor="w",
            font=("Microsoft YaHei", 14)
        ).pack(side="left")

        value = ctk.CTkLabel(
            row,
            text=initial_text,
            font=("Microsoft YaHei", 13),
            text_color="gray"
        )
        value.pack(side="right")
        return value

    add_information_row("Python Version", sys.version.split()[0])
    add_information_row(
        "CustomTkinter Version",
        getattr(ctk, "__version__", "Unknown")
    )
    last_check_label = add_information_row("Last Check Time", "--")

    check_state = {"running": False}

    def update_status_label(label, online):
        if online:
            label.configure(text=TEXT["online"], text_color="#32CD32")
        else:
            label.configure(text=TEXT["offline"], text_color="red")

    def refresh_dashboard():
        if check_state["running"]:
            return

        check_state["running"] = True
        refresh_button.configure(state="disabled", text=TEXT["checking"])

        for label in health_labels.values():
            label.configure(text=TEXT["checking"], text_color="gray")

        logger.info("Health dashboard check started")

        def run_check():
            try:
                status = check_all()
                error_message = None
            except Exception as error:
                status = {
                    "ollama": False,
                    "webui": False,
                    "api": False
                }
                error_message = str(error)

            checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if error_message:
                logger.error(
                    f"Health dashboard check failed: {error_message}"
                )
            else:
                logger.info("Health dashboard check completed")

            def update_dashboard():
                try:
                    window_is_open = (
                        health_window is not None
                        and health_window == dashboard
                        and health_window.winfo_exists()
                    )
                except Exception:
                    window_is_open = False

                if not window_is_open:
                    return

                for key, label in health_labels.items():
                    update_status_label(label, status.get(key, False))

                last_check_label.configure(
                    text=checked_at,
                    text_color="white"
                )
                check_state["running"] = False
                refresh_button.configure(
                    state="normal",
                    text=TEXT["refresh"]
                )

            try:
                app.after(0, update_dashboard)
            except Exception:
                pass

        dashboard = health_window
        threading.Thread(target=run_check, daemon=True).start()

    def close_health_window():
        global health_window
        health_window.destroy()
        health_window = None

    button_frame = ctk.CTkFrame(health_window, fg_color="transparent")
    button_frame.pack(fill="x", padx=25, pady=(0, 20))

    refresh_button = ctk.CTkButton(
        button_frame,
        text=TEXT["refresh"],
        command=refresh_dashboard
    )
    refresh_button.pack(side="left", expand=True, fill="x", padx=(0, 6))

    close_button = ctk.CTkButton(
        button_frame,
        text=TEXT["close"],
        command=close_health_window
    )
    close_button.pack(side="left", expand=True, fill="x", padx=(6, 0))

    health_window.protocol("WM_DELETE_WINDOW", close_health_window)
    refresh_dashboard()


def show_about():
    messagebox.showinfo(
        TEXT["about_title"],
        f"{APP_NAME}\n\n"
        f"Version: v{VERSION}\n"
        f"Build: {BUILD}\n\n"
        f"{TEXT['a_personal_local_ai_assistant']}\n\n"
        f"{TEXT['core_features']}:\n"
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


btn3 = ctk.CTkButton(
    actions_frame,
    text=TEXT["health"],
    command=health_check
)
btn3.pack(fill="x", padx=40, pady=8)


btn4 = ctk.CTkButton(
    actions_frame,
    text=TEXT["about"],
    command=show_about
)
btn4.pack(fill="x", padx=40, pady=8)


btn5 = ctk.CTkButton(
    actions_frame,
    text=TEXT["exit"],
    command=shutdown_app
)
btn5.pack(fill="x", padx=40, pady=8)


recent_log_title = ctk.CTkLabel(
    app,
    text=TEXT["recent_log"],
    font=("Microsoft YaHei", 16, "bold")
)
recent_log_title.pack(anchor="w", padx=35, pady=(5, 10))

recent_log_box = ctk.CTkTextbox(
    app,
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
        logger.get_recent_logs_text() or TEXT["no_logs"]
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
            label.configure(text=f"馃煝 {name}")
            state.configure(
                text=TEXT["online"],
                text_color="#32CD32"
            )
        else:
            label.configure(text=f"馃敶 {name}")
            state.configure(
                text=TEXT["offline"],
                text_color="red"
            )
        label.configure(text=f"{'馃煝' if online else '馃敶'} {display_name}")

    online_count = sum(mapping.values())
    if online_count == len(mapping):
        status_summary_label.configure(
            text=TEXT["all_ready"],
            text_color="#32CD32"
        )
    else:
        status_summary_label.configure(
            text=f"{online_count} / {len(mapping)} services online",
            text_color="orange"
        )

    dashboard_last_check_label.configure(
        text=(
            f"{TEXT['last_check']}: "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ),
        text_color="gray"
    )

    docker_ready = bool(status.get("docker", False))
    docker_desktop = bool(status.get("docker_desktop", docker_ready))
    if "Docker Desktop" in docker_status_labels:
        docker_status_labels["Docker Desktop"].configure(
            text=TEXT["online"] if docker_desktop else TEXT["offline"],
            text_color="#32CD32" if docker_desktop else "red"
        )
        docker_status_labels["Docker Engine"].configure(
            text=TEXT["ready"] if docker_ready and "ready" in TEXT else ("Ready" if docker_ready else "Not Ready"),
            text_color="#32CD32" if docker_ready else "red"
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


logger.info("Application started")

app.protocol("WM_DELETE_WINDOW", shutdown_app)

if first_run_required:
    app.after(100, show_first_run_wizard)
else:
    startup_check()
    refresh_recent_logs()
    refresh_status()
    refresh_system_health_center()

app.mainloop()

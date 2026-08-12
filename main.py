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
from modules.app_paths import CONFIG_FILE, DEFAULT_SETTINGS_FILE, ensure_user_data_directories


configuration_file = CONFIG_FILE


def ensure_runtime_directories():
    ensure_user_data_directories()


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
        "chat_model",
        "embedding_model",
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
from modules.health import check_all, system_self_check
from modules.models import get_model_records, get_models, infer_model_capability
from modules.chat import (
    ChatError,
    DEFAULT_SYSTEM_CONTEXT,
    assemble_final_prompt,
    build_context_debug_report,
    build_final_prompt_preview,
    summarize_context_sections,
    stream_chat
)
from modules.context_builder import ContextBuilder
from modules.conversation import ConversationManager
from modules.rag_integration import run_rag_pipeline_with_fallback
from modules.memory import MemoryStore
from modules.knowledge import KnowledgeStore
from modules.persona import PersonaStore
from modules.language import TEXT, set_language as set_legacy_language
from modules.i18n import normalize_language, set_language as set_i18n_language, t
from modules.startup_diagnostics import initialization_check
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
from modules.search import search_memories, search_conversations
from modules.memory_retrieval import format_memory_context, retrieve_memories
from modules.retrieval import format_knowledge_context, search_knowledge, retrieval_summary
from modules.service_manager import ServiceManager
from modules.shutdown_manager import ShutdownManager
from modules.experience.audio.device_discovery import resolve_ffmpeg_path, resolve_voice_input_device
from modules.experience.audio.recorder import FFmpegMicrophoneRecorder
from modules.experience.state import CompanionStateStore
from modules.experience.voice.dependency_manager import check_dependencies as check_voice_dependencies
from modules.experience.voice.integration import create_voice_runtime
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
from widgets.pages.learning_center_page import LearningCenterPage
from widgets.pages.library_page import LibraryPage
from widgets.pages.memory_page import MemoryPage
from widgets.pages.persona_page import PersonaPage
from widgets.pages.settings_page import SettingsPage
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
voice_runtime = None
active_chat_page = None
companion_state_store = CompanionStateStore()
models_window = None
health_window = None
settings_window = None
chat_window = None
context_inspector_window = None
memory_window = None
knowledge_window = None
conversation_browser_window = None
persona_window = None
active_conversation_id = None
chat_load_conversation_callback = None
pending_conversation_id = None
memory_store = MemoryStore()
knowledge_store = KnowledgeStore()
persona_store = PersonaStore()
service_manager = ServiceManager()
shutdown_manager = ShutdownManager(logger=logger)
service_lifecycle = {
    "ollama_started_by_app": False
}


def schedule_after(delay_ms, callback, *args):
    if shutdown_manager.shutting_down:
        return None
    return shutdown_manager.register_after(app.after(delay_ms, callback, *args))


def mark_service_started_by_app(service_name):
    if service_name == "ollama":
        service_lifecycle["ollama_started_by_app"] = True
        metadata = service_manager.service_process_metadata("ollama")
        logger.info(
            "Ollama started by Aurora: "
            f"pid={metadata.get('pid')}, executable={metadata.get('executable_path')}"
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
        initialization_check_provider=lambda: initialization_check(settings),
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

for name in ["Ollama", "API 11434"]:

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
    (t("system"), ["Conversation Store", "Persona"])
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
    (t("persona_system"), t("enabled") if settings.get("persona.enabled", True) else t("disabled"))
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
        ollama = service_manager.diagnose_ollama(
            settings.get("ollama.host", "http://127.0.0.1:11434")
        )
        lines = ["AI Environment Diagnostic"]
        lines.append(f"{'OK' if ollama['available'] else 'FAIL'} Ollama API: {ollama['status']} - {ollama['reason']}")
        if not ollama["available"]:
            logger.error("Ollama API unavailable")
        logger.info("Diagnostic completed")

        def finish():
            global diagnostic_running
            diagnostic_running = False
            _show_diagnostic(lines)
        app.after(0, finish)

    threading.Thread(target=worker, daemon=True).start()


def start_ollama_manual():
    logger.info("Starting Ollama")
    def ollama_manual_event(event):
        if isinstance(event, dict):
            if event.get("event") == "ollama_snapshot_before_start":
                logger.info(f"[OLLAMA SNAPSHOT BEFORE START] {event.get('processes')}")
            elif event.get("event") == "ollama_root_started":
                logger.info(
                    f"Ollama root started: pid={event.get('pid')}, "
                    f"executable={event.get('executable')}, args={event.get('args')}"
                )
            elif event.get("event") == "ollama_snapshot_after_start":
                logger.info(f"[OLLAMA SNAPSHOT AFTER START] {event.get('processes')}")
            elif event.get("event") == "ollama_owned_processes":
                logger.info(f"[OLLAMA OWNERSHIP RESULT] {event.get('processes')}")
            return
        if event == "started":
            mark_service_started_by_app("ollama")
            logger.info("Ollama started")

    service_manager.start_ollama(
        settings.get("services.ollama.command", "ollama serve"),
        settings.get("ollama.host", "http://127.0.0.1:11434"),
        callback=ollama_manual_event
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

def build_conversation_context(conversation_messages=None):
    conversation_lines = []
    for message in conversation_messages or []:
        role = message.get("role", "")
        if role == "system":
            continue
        content = str(message.get("content", "")).strip()
        if content:
            conversation_lines.append(f"{role}: {content}")
    return "\n\n".join(conversation_lines)


def context_warning_tokens():
    try:
        return max(1, int(settings.get("context.warning_tokens", 6000)))
    except (TypeError, ValueError):
        return 6000


def build_context_package(
    memories=None,
    knowledge_items=None,
    persona=None,
    conversation_messages=None,
    memory_text=None,
    knowledge_text=None,
):
    builder = ContextBuilder(
        system_context=DEFAULT_SYSTEM_CONTEXT,
        warning_tokens=context_warning_tokens()
    )
    return builder.build_from_formatted_context(
        system_context=DEFAULT_SYSTEM_CONTEXT,
        persona_text=persona_store.build_context(persona) if persona else "",
        memory_text=(format_memory_context(memories) if memory_text is None else memory_text),
        knowledge_text=(format_knowledge_context(knowledge_items) if knowledge_text is None else knowledge_text),
        conversation_text=build_conversation_context(conversation_messages)
    )


def build_context_sections(
    memories=None,
    knowledge_items=None,
    persona=None,
    conversation_messages=None,
    memory_text=None,
    knowledge_text=None,
):
    return build_context_package(
        memories,
        knowledge_items,
        persona,
        conversation_messages,
        memory_text=memory_text,
        knowledge_text=knowledge_text,
    )["sections"]


def build_memory_context(memories=None, knowledge_items=None, persona=None, memory_text=None, knowledge_text=None):
    lines = []
    for section in build_context_package(
        memories,
        knowledge_items,
        persona,
        memory_text=memory_text,
        knowledge_text=knowledge_text,
    )["sections"][:4]:
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

    def context_section_title(name):
        key_map = {
            "System Context": "context_section_system",
            "Persona": "persona",
            "Memory": "memory",
            "Knowledge": "knowledge",
            "Conversation Context": "context_section_conversation",
        }
        return t(key_map.get(str(name or ""), "context_sidebar_title"))

    context_inspector_window = ctk.CTkToplevel(parent_window or app)
    context_inspector_window.title(t("chat_window_context_inspector"))
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
        text=t("context_inspector_final_chat_context"),
        font=("Microsoft YaHei", 22, "bold")
    ).pack(anchor="w")
    ctk.CTkLabel(
        header,
        text=(
            f"{t('context_inspector_generated')}: {payload.get('generated_time', '')} | "
            f"{t('context_inspector_build_time')}: {payload.get('build_duration_ms', 0)}ms | "
            f"{t('total_characters')}: {summary.get('total_characters', 0)} | "
            f"{t('tokens')}: {summary.get('total_tokens', 0)}"
        ),
        font=("Microsoft YaHei", 12),
        text_color="gray"
    ).pack(anchor="w", pady=(4, 0))

    status_frame = ctk.CTkFrame(context_inspector_window)
    status_frame.pack(fill="x", padx=25, pady=(0, 10))
    status_line = "    ".join(
        f"{context_section_title(item.get('name', 'Context'))} {t('enabled') if item.get('enabled') else t('disabled')}"
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
            text=t("context_size_warning") + "\n" + "\n".join(summary.get("warning_reasons", [])),
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
        display_name = context_section_title(name)
        collapsed[name] = False
        outer = ctk.CTkFrame(content_frame)
        outer.pack(fill="x", padx=8, pady=8)

        body = ctk.CTkFrame(outer, fg_color="transparent")

        def toggle():
            collapsed[name] = not collapsed[name]
            marker = "\u25b6" if collapsed[name] else "\u25bc"
            title_button.configure(text=f"{marker} {display_name}")
            if collapsed[name]:
                body.pack_forget()
            else:
                body.pack(fill="x", padx=12, pady=(0, 12))

        title_button = ui_button(
            outer,
            text=f"\u25bc {display_name}",
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


def build_chat_runtime_callbacks():
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
        rag_enabled = bool(settings.get("rag.pipeline_enabled", False))
        matched_memories = retrieve_memories(
            prompt,
            memory_store.list_memories(),
            max_results=max_injection,
            min_importance=min_importance,
            enriched=rag_enabled,
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
                max_results=max_knowledge,
                enriched=rag_enabled,
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

        rag_result = run_rag_pipeline_with_fallback(
            matched_memories,
            matched_knowledge,
            enabled=rag_enabled,
            logger=logger,
        )
        optimized_memory_text = None
        optimized_knowledge_text = None
        if rag_enabled and rag_result["diagnostics"].get("success"):
            for section in rag_result.get("sections", []):
                if not isinstance(section, dict):
                    continue
                if section.get("name") == "Memory":
                    optimized_memory_text = section.get("content", "")
                elif section.get("name") == "Knowledge":
                    optimized_knowledge_text = section.get("content", "")
            logger.info("RAG pipeline completed")
        elif rag_enabled:
            logger.error(rag_result["diagnostics"].get("reason", "RAG pipeline fallback used."))

        if matched_memories:
            logger.info("Memory injected")
        if matched_knowledge:
            logger.info("Knowledge injected")

        debug_text = ""
        if debug_enabled:
            debug_text, warning, _tokens = build_context_debug_report(
                build_context_sections(
                    matched_memories,
                    matched_knowledge,
                    active_persona,
                    conversation_messages,
                    memory_text=optimized_memory_text,
                    knowledge_text=optimized_knowledge_text,
                ),
                warning_tokens=settings.get("context.warning_tokens", 6000)
            )
            if warning:
                logger.info("Context size warning")

        return {
            "system_context": build_memory_context(
                matched_memories,
                matched_knowledge,
                active_persona,
                memory_text=optimized_memory_text,
                knowledge_text=optimized_knowledge_text,
            ),
            "debug_text": debug_text,
            "context_diagnostics": {
                "memory_retrieval": True,
                "memory_matches": len(matched_memories),
                "knowledge_retrieval": bool(settings.get("knowledge.enabled", True)),
                "knowledge_matches": len(matched_knowledge),
                "persona_enabled": bool(settings.get("persona.enabled", True)),
                "conversation_messages": len(conversation_messages or []),
            }
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

    return {
        "initial_context_provider": initial_chat_context,
        "model_records_provider": get_model_records,
        "model_capability_provider": infer_model_capability,
        "prepare_prompt_context_callback": prepare_chat_prompt_context,
        "stream_chat_callback": stream_chat,
        "context_preview_builder": build_chat_context_preview,
        "context_preview_callback": show_context_inspector,
        "get_active_conversation_id": lambda: active_conversation_id,
        "set_active_conversation_id": set_active_conversation,
        "register_load_callback": register_chat_load_callback
    }


def build_voice_text_input_handler():
    """Route recognized voice text through the active ChatPage message path."""

    def handle_voice_text(prompt, *, on_chunk=None, cancel_event=None):
        if active_chat_page is not None:
            return active_chat_page.handle_external_prompt(
                prompt,
                on_chunk=on_chunk,
                cancel_event=cancel_event,
                source="voice",
            )
        raise ChatError("Chat page is not ready for voice input.")

    return handle_voice_text


def create_application_voice_runtime():
    """Create the one application Voice Runtime and share its state store."""

    if not settings.get("voice.enabled", False):
        return None
    device_name = resolve_voice_input_device(settings)
    ffmpeg_path = resolve_ffmpeg_path(settings.get("voice.recorder.ffmpeg_path", "ffmpeg"))
    logger.info(f"Voice input device: {device_name}")
    recorder = FFmpegMicrophoneRecorder(
        device_name=device_name,
        sample_rate=int(settings.get("voice.recorder.sample_rate", 16000)),
        channels=int(settings.get("voice.recorder.channels", 1)),
        ffmpeg_path=ffmpeg_path,
        min_duration_ms=int(settings.get("voice.recorder.min_duration_ms", 750)),
    )
    voice_text_handler = build_voice_text_input_handler()
    return create_voice_runtime(
        settings,
        recorder=recorder,
        text_input_handler=voice_text_handler,
        stream_text_input_handler=voice_text_handler,
        state_store=companion_state_store,
        input_device_name=device_name,
        use_frame_pipeline=str(
            settings.get("voice.recorder.backend", "frame_pipeline")
        ).lower() != "ffmpeg",
    )


def show_chat():
    global pending_conversation_id

    shell = create_app_shell()
    shell.navigate("chat")

    if pending_conversation_id:
        pending_id = pending_conversation_id
        pending_conversation_id = None
        if callable(chat_load_conversation_callback):
            chat_load_conversation_callback(pending_id)

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
    open_learning_center_tab("memory")

def show_knowledge():
    open_learning_center_tab("knowledge")

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
    open_learning_center_tab("persona")

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
    text=t("compatibility_tools"),
    font=FONT_HEADER
)
action_title.pack(anchor="w", padx=15, pady=(5, 10))


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
    action_title.configure(text=t("compatibility_tools"))
    btn_diagnostic.configure(text=t("runtime_environment_diagnostics"))
    btn_start_ollama.configure(text=t("start_ollama"))
    btn2.configure(text=t("models"))
    btn_chat.configure(text=t("chat"))
    btn_conversation_browser.configure(text=t("conversation_browser"))
    btn_memory.configure(text=t("memory"))
    btn_persona.configure(text=t("persona"))
    btn_knowledge.configure(text=t("knowledge_base"))
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
        f"- Context Inspector"
    )


def active_chat_surfaces():
    surfaces = []
    if chat_window is not None:
        try:
            if chat_window.winfo_exists():
                surfaces.append(chat_window)
        except Exception:
            pass
    if app_shell is not None:
        try:
            chat_page = app_shell.page_frames.get("chat")
            if chat_page is not None and chat_page.winfo_exists():
                surfaces.append(chat_page)
        except Exception:
            pass
    return surfaces


def cleanup_chat_surfaces():
    for surface in active_chat_surfaces():
        try:
            if surface.stream_state.get("running"):
                surface.stop_generation()
        except Exception as error:
            logger.error(f"Chat streaming shutdown failed: {error}")
        try:
            if len(surface.session.snapshot()) > 1:
                surface.save_conversation(auto=True)
        except Exception as error:
            logger.error(f"Chat save on shutdown failed: {error}")


def cleanup_callbacks():
    global chat_load_conversation_callback
    chat_load_conversation_callback = None
    if chat_window is not None:
        try:
            chat_window.register_load_callback(None)
        except Exception:
            pass


def cleanup_started_services():
    if service_lifecycle.get("ollama_started_by_app"):
        logger.info("Ollama cleanup callback started")
        logger.info("[OLLAMA SHUTDOWN BEGIN]")
        result = service_manager.stop_ollama_owned_processes(allow_image_fallback=True)
        logger.info(f"[OLLAMA SHUTDOWN BEGIN] {result.get('shutdown_begin')}")
        logger.info(f"Ollama shutdown owned PID list: {result.get('owned')}")
        for item in result.get("terminated", []):
            logger.info(
                f"Terminate Ollama PID: {item.get('pid')}, "
                f"terminated={item.get('terminated')}, killed={item.get('killed')}, taskkill={item.get('taskkill')}"
            )
        for item in result.get("image_fallback", []):
            logger.info(
                f"taskkill result: image={item.get('image')}, returncode={item.get('returncode')}"
            )
        logger.info(f"[OLLAMA TERMINATE RESULT] {result.get('terminated')}")
        logger.info(f"[OLLAMA SNAPSHOT AFTER SHUTDOWN] {result.get('remaining')}")
        logger.info(f"Remaining Ollama processes: {result.get('remaining')}")
        if not result.get("ok"):
            logger.error(f"Ollama shutdown incomplete: {result.get('remaining_owned_candidates')}")
        logger.info("Ollama cleanup callback finished")


def cleanup_settings():
    try:
        settings.save()
        logger.info("Settings saved")
    except Exception as error:
        logger.error(f"Settings save failed: {error}")


shutdown_manager.register_cleanup(cleanup_settings, "settings")
shutdown_manager.register_cleanup(cleanup_started_services, "started_services")
shutdown_manager.register_cleanup(cleanup_callbacks, "callbacks")
shutdown_manager.register_cleanup(cleanup_chat_surfaces, "chat_surfaces")


def shutdown_app(source="unknown"):
    first_shutdown = not shutdown_manager.shutting_down
    logger.info(f"shutdown_app() requested: source={source}, first_shutdown={first_shutdown}")
    shutdown_manager.cancel_after_timers(app)
    if first_shutdown:
        logger.info("Application shutdown started")
        shutdown_manager.shutdown()
        logger.info("Application shutdown finished")
    logger.info("root.destroy() before")
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
    command=lambda: shutdown_app("legacy_dashboard_exit"),
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
    if shutdown_manager.shutting_down:
        return

    recent_log_box.configure(state="normal")
    recent_log_box.delete("1.0", "end")
    recent_log_box.insert(
        "1.0",
        logger.get_recent_logs_text() or t("no_logs")
    )
    recent_log_box.configure(state="disabled")

    schedule_after(1000, refresh_recent_logs)


status_check_running = False


def refresh_status():
    global status_check_running
    if shutdown_manager.shutting_down:
        return
    if status_check_running:
        return
    status_check_running = True

    def run_check():
        try:
            result = check_all()
            ollama_diag = service_manager.diagnose_ollama(
                settings.get("ollama.host", "http://127.0.0.1:11434")
            )
            result["ollama"] = ollama_diag["available"]
        except Exception as error:
            logger.error(f"Status check failed: {error}")
            result = {"ollama": False, "api": False}

        def finish_check():
            global status_check_running
            status_check_running = False
            apply_status(result)

        if not shutdown_manager.shutting_down:
            app.after(0, finish_check)

    threading.Thread(target=run_check, daemon=True).start()


def apply_status(status):

    mapping = {
        "Ollama": status["ollama"],
        "API 11434": status["api"]
    }

    endpoints = {
        "Ollama": ServiceManager.endpoint(settings.get("ollama.host", "http://127.0.0.1:11434")),
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

    try:
        refresh_interval = float(
            settings.get("status.refresh_interval", 3)
        )
        refresh_interval = max(refresh_interval, 0.1)
    except (TypeError, ValueError):
        refresh_interval = 3

    schedule_after(int(refresh_interval * 1000), refresh_status)


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
        DEFAULT_SETTINGS_FILE
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
    voice_dependency_report = check_voice_dependencies(settings)
    if voice_dependency_report["ready"]:
        logger.info("Voice dependencies ready")
    else:
        missing = [item["name"] for item in voice_dependency_report["missing"]]
        logger.warning("Voice dependency missing:")
        for dependency_name in missing:
            logger.warning(f"- {dependency_name}")

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
                    if isinstance(event, dict):
                        if event.get("event") == "ollama_snapshot_before_start":
                            logger.info(f"[OLLAMA SNAPSHOT BEFORE START] {event.get('processes')}")
                        elif event.get("event") == "ollama_root_started":
                            logger.info(
                                f"Ollama root started: pid={event.get('pid')}, "
                                f"executable={event.get('executable')}, args={event.get('args')}"
                            )
                        elif event.get("event") == "ollama_snapshot_after_start":
                            logger.info(f"[OLLAMA SNAPSHOT AFTER START] {event.get('processes')}")
                        elif event.get("event") == "ollama_owned_processes":
                            logger.info(f"[OLLAMA OWNERSHIP RESULT] {event.get('processes')}")
                        return
                    if event == "starting":
                        logger.info("Starting Ollama")
                    elif event == "started":
                        mark_service_started_by_app("ollama")
                        logger.info("Ollama started")
                        if not shutdown_manager.shutting_down:
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

        logger.info("Startup Diagnostic:")
        logger.info(f"Ollama: {'Ready' if ollama_connected else 'Offline'}")
        logger.info("Startup diagnostic completed")
        logger.info(
            f"Service check duration: {int((time.perf_counter() - service_started) * 1000)}ms"
        )
        logger.info(
            f"Startup Check finished: {int((time.perf_counter() - startup_started) * 1000)}ms"
        )

    threading.Thread(target=check_services, daemon=True).start()


def navigate_app_shell(page_name):
    learning_routes = {
        "library": "knowledge",
        "memory": "memory",
        "persona": "persona"
    }
    if page_name in learning_routes:
        open_learning_center_tab(learning_routes[page_name])
        return
    if app_shell is not None:
        app_shell.navigate(page_name)


def open_settings_panel(panel_id):
    shell = create_app_shell()
    shell.navigate("settings")
    settings_page = shell.page_frames.get("settings")
    if settings_page is None:
        return
    if panel_id == "persona":
        settings_page.show_category("ai")
        show_panel = getattr(settings_page, "_show_persona_panel", None)
    elif panel_id == "memory":
        settings_page.show_category("data")
        show_panel = getattr(settings_page, "_show_memory_panel", None)
    elif panel_id == "knowledge":
        settings_page.show_category("data")
        show_panel = getattr(settings_page, "_show_knowledge_panel", None)
    else:
        settings_page.show_category("ai")
        show_panel = None
    if callable(show_panel):
        show_panel()
    logger.info(f"Settings legacy route opened: {panel_id}")


def open_learning_center_tab(panel_id):
    open_settings_panel(panel_id)


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

    chat_model = settings.get("chat_model", "")
    return {
        "overall": "healthy",
        "summary": "",
        "ai_runtime": {
            "status": "healthy" if chat_model else "warning",
            "text": t("available") if chat_model else t("missing"),
            "detail": chat_model or "--"
        },
        "memory": {
            "status": "healthy",
            "text": t("available"),
            "detail": f"{t('memory_count')}: {memory_count}"
        },
        "knowledge": {
            "status": "healthy",
            "text": t("available"),
            "detail": f"{t('knowledge_documents')}: {knowledge_count}"
        },
        "persona": {
            "status": "enabled" if settings.get("persona.enabled", True) else "disabled",
            "text": t("enabled") if settings.get("persona.enabled", True) else t("disabled"),
            "detail": persona_name
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
            "retrieval": t("enabled") if settings.get("knowledge.enabled", True) else t("disabled"),
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
    global app_shell, active_chat_page
    if app_shell is not None:
        return app_shell

    page_builders = {
        "chat": lambda parent: ChatPage(
            parent,
            text=TEXT,
            translate=t,
            logger=logger,
            settings=settings,
            conversation_manager=ConversationManager(),
            voice_runtime=voice_runtime,
            companion_state=companion_state_store,
            **build_chat_runtime_callbacks()
        ),
        "settings": lambda parent: SettingsPage(
            parent,
            translate=t,
            settings=settings,
            text=TEXT,
            persona_store=persona_store,
            memory_store=memory_store,
            search_memories=search_memories,
            knowledge_store=knowledge_store,
            version=VERSION,
            retrieval_summary=retrieval_summary,
            final_prompt_preview_callback=build_persona_final_prompt_preview,
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
        initial_page_id="chat",
        on_page_change=lambda page_name: logger.info(f"AppShell page opened: {page_name}"),
        on_shutdown=shutdown_app
    )
    app_shell.pack(fill="both", expand=True)
    active_chat_page = app_shell.page_frames.get("chat")
    logger.info("AppShell initialized")
    return app_shell


logger.info("Application started")

app.protocol("WM_DELETE_WINDOW", lambda: shutdown_app("wm_delete_window"))

voice_runtime = create_application_voice_runtime()
create_app_shell()

if first_run_required:
    schedule_after(100, show_first_run_wizard)
else:
    startup_check()
    refresh_recent_logs()
    refresh_status()
    refresh_system_health_center()

app.mainloop()

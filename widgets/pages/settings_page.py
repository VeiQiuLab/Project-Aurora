import subprocess
import threading
from pathlib import Path

import customtkinter as ctk

from modules.app_paths import CONVERSATIONS_DIR, KNOWLEDGE_DIR, MEMORY_DIR, PERSONA_DIR
from modules.experience.audio.device_discovery import (
    AudioDeviceDiscoveryError,
    WINDOWS_DEFAULT_INPUT_ID,
    device_choice_map,
    enumerate_dshow_audio_devices,
    friendly_device_name,
    resolve_voice_input_device,
    select_voice_input_device,
)
from modules.runtime_dependencies import RuntimeDependencyManager
from modules.runtime_display import localized_runtime_item, model_mode_text
from modules.ui_theme import (
    COLOR_ERROR,
    COLOR_MUTED,
    COLOR_SUCCESS,
    FONT_HEADER,
    FONT_NORMAL,
    FONT_NORMAL_BOLD,
    FONT_SMALL,
    FONT_TITLE,
    SPACING_LARGE,
    SPACING_MEDIUM,
    SPACING_SMALL
)
from modules.version import BUILD_DATE, VERSION
from widgets.components.knowledge_panel import KnowledgePanel
from widgets.components.memory_panel import MemoryPanel
from widgets.components.persona_panel import PersonaPanel
from widgets.components.dependency_center import DependencyCenter
from widgets.ui_components import PrimaryButton, SecondaryButton, SectionCard
from widgets.voice_setup_wizard import VoiceSetupWizard


class SettingsPage(ctk.CTkFrame):
    """Chat-first Settings hub with grouped product settings."""

    CATEGORIES = ["ai", "runtime", "voice", "appearance", "data", "developer"]
    CATEGORY_KEYS = {
        "ai": "ai",
        "runtime": "runtime_title",
        "voice": "runtime_domain_voice",
        "appearance": "appearance",
        "data": "settings_category_data",
        "developer": "developer",
    }

    def __init__(
        self,
        parent,
        *,
        translate,
        settings,
        text,
        persona_store=None,
        memory_store=None,
        search_memories=None,
        knowledge_store=None,
        version=VERSION,
        retrieval_summary=None,
        final_prompt_preview_callback=None,
        open_settings_callback=None,
        settings_status_provider=None,
        service_manager=None,
        logger=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.t = translate
        self.settings = settings
        self.text = text
        self.persona_store = persona_store
        self.memory_store = memory_store
        self.search_memories = search_memories
        self.knowledge_store = knowledge_store
        self.version = version
        self.retrieval_summary = retrieval_summary
        self.final_prompt_preview_callback = final_prompt_preview_callback
        self.open_settings_callback = open_settings_callback
        self.settings_status_provider = settings_status_provider
        self.service_manager = service_manager
        self.logger = logger
        self.category_buttons = {}
        self.voice_environment_rows = {}
        self.voice_environment_status = None
        self.voice_environment_button = None
        self.voice_device_label = None
        self.voice_device_status = None
        self.voice_setup_button = None
        self.voice_setup_status = None
        self.ai_model_status_label = None
        self.ai_model_current_label = None
        self.ai_embedding_current_label = None
        self.ai_embedding_status_label = None
        self.ai_model_scan_running = False
        self.current_category = "ai"
        self.active_panel = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build()
        self.show_category(self.current_category)

    def _build(self):
        self.sidebar = ctk.CTkFrame(self, width=220)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, SPACING_MEDIUM))
        self.sidebar.grid_propagate(False)

        for category_id in self.CATEGORIES:
            button = SecondaryButton(
                self.sidebar,
                text=self.t(self.CATEGORY_KEYS[category_id]),
                command=lambda value=category_id: self.show_category(value),
                anchor="w"
            )
            button.pack(fill="x", padx=SPACING_SMALL, pady=SPACING_SMALL)
            self.category_buttons[category_id] = button

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)

        self.header = ctk.CTkFrame(self.content, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_MEDIUM))
        self.header.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(self.header, text="", font=FONT_TITLE, anchor="w")
        self.title_label.grid(row=0, column=0, sticky="w")

        self.body = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)

    def use_external_sidebar(self):
        self.sidebar.grid_remove()
        self.content.grid(row=0, column=0, sticky="nsew")
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)

    def show_category(self, category_id):
        self.current_category = category_id
        self._clear_body()
        title = self.t(self.CATEGORY_KEYS.get(category_id, "settings"))
        self.title_label.configure(text=title)
        builders = {
            "ai": self._build_ai,
            "runtime": self._build_runtime,
            "voice": self._build_voice,
            "appearance": self._build_appearance,
            "data": self._build_data,
            "developer": self._build_developer
        }
        builders.get(category_id, self._build_ai)()
        self._refresh_category_buttons()
        if self.logger:
            self.logger.info(f"Settings page category selected: {category_id}")

    def refresh_status(self):
        return None

    def open_settings_editor(self):
        if callable(self.open_settings_callback):
            self.open_settings_callback()
            if self.logger:
                self.logger.info("Settings page opened existing SettingsWindow")

    def _clear_body(self):
        self.active_panel = None
        self.ai_model_status_label = None
        self.ai_model_current_label = None
        self.ai_embedding_current_label = None
        self.ai_embedding_status_label = None
        self.voice_setup_button = None
        self.voice_setup_status = None
        for child in self.body.winfo_children():
            child.destroy()

    def _refresh_category_buttons(self):
        for category_id, button in self.category_buttons.items():
            selected = category_id == self.current_category
            button.configure(font=FONT_HEADER if selected else FONT_NORMAL)

    def _card(self, title, description=None):
        card = SectionCard(self.body, title)
        card.grid(row=len(self.body.winfo_children()), column=0, sticky="ew", pady=(0, SPACING_MEDIUM))
        if description:
            ctk.CTkLabel(
                card.body,
                text=description,
                font=FONT_NORMAL,
                text_color=COLOR_MUTED,
                anchor="w",
                justify="left",
                wraplength=720
            ).pack(fill="x", pady=(0, SPACING_SMALL))
        return card

    def _setting_row(self, parent, label, value):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=SPACING_SMALL)
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(row, text=label, font=FONT_NORMAL, anchor="w").grid(row=0, column=0, sticky="w")
        value_label = ctk.CTkLabel(row, text=str(value), font=FONT_SMALL, text_color=COLOR_MUTED, anchor="e")
        value_label.grid(
            row=0,
            column=1,
            sticky="e"
        )
        return value_label

    def _action_button(self, parent, text, command):
        SecondaryButton(parent, text=text, command=command, anchor="w").pack(fill="x", pady=SPACING_SMALL)

    def _build_ai(self):
        card = self._card(self.t("ai_model_settings"), self.t("ai_model_settings_hint"))
        mode = str(self.settings.get("chat_model_mode", "auto") or "auto").casefold()
        self._setting_row(card.body, self.t("ai_model_mode"), model_mode_text(mode, self.t))
        self.ai_model_current_label = self._setting_row(
            card.body,
            self.t("chat_model"),
            self.settings.get("chat_model", "") or self.t("ai_model_unresolved"),
        )
        self.ai_model_status_label = self._setting_row(
            card.body,
            self.t("status"),
            self.t("ai_model_scanning"),
        )
        embedding_mode = str(self.settings.get("embedding_model_mode", "manual") or "manual").casefold()
        self.ai_embedding_current_label = self._setting_row(
            card.body,
            self.t("runtime_item_embedding"),
            self.settings.get("embedding_model", "") or self.t("ai_model_optional_unset"),
        )
        self.ai_embedding_status_label = self._setting_row(
            card.body,
            self.t("ai_embedding_mode"),
            model_mode_text(embedding_mode, self.t),
        )
        self._setting_row(card.body, "Ollama", self.settings.get("ollama.host", ""))
        model_actions = ctk.CTkFrame(card.body, fg_color="transparent")
        model_actions.pack(fill="x", pady=SPACING_SMALL)
        SecondaryButton(
            model_actions,
            text=self.t("ai_model_rescan"),
            command=self._rescan_ai_models,
        ).pack(side="left", padx=(0, SPACING_SMALL))
        SecondaryButton(
            model_actions,
            text=self.t("ai_model_rerecommend"),
            command=lambda: self._rescan_ai_models(reevaluate=True),
        ).pack(side="left", padx=(0, SPACING_SMALL))
        SecondaryButton(
            model_actions,
            text=self.t("ai_model_choose"),
            command=self.open_settings_editor,
        ).pack(side="left")
        self.after(0, self._rescan_ai_models)

        tools = self._card(self.t("ai_capabilities"))
        self._action_button(tools.body, "Persona", self._show_persona_panel)
        self._action_button(tools.body, "Memory", self._show_memory_panel)
        self._action_button(tools.body, "Knowledge / RAG", self._show_knowledge_panel)

    def _rescan_ai_models(self, reevaluate=False):
        if self.ai_model_scan_running:
            return
        if reevaluate and str(
            self.settings.get("chat_model_mode", "auto") or "auto"
        ).casefold() != "auto":
            if self.ai_model_status_label is not None:
                self.ai_model_status_label.configure(
                    text=self.t("ai_model_manual_rerecommend_hint")
                )
            return
        self.ai_model_scan_running = True

        def worker():
            try:
                report = RuntimeDependencyManager(self.settings).check_models(
                    timeout=1.0,
                    reevaluate_models=bool(reevaluate),
                )
                item = report.get("ollama", {}).get("chat_model", {})
                embedding_item = report.get("ollama", {}).get("embedding_model", {})
                chat_display = localized_runtime_item(item, self.t)
                embedding_display = localized_runtime_item(embedding_item, self.t)
                result = {
                    "model": chat_display["detail"],
                    "detail": chat_display["status"],
                    "embedding": embedding_display["detail"],
                    "embedding_status": embedding_display["status"],
                }
            except Exception as error:
                result = {
                    "model": None,
                    "detail": self.t("ai_model_scan_failed"),
                    "embedding": None,
                    "embedding_status": self.t("ai_model_scan_failed"),
                }
                if self.logger:
                    self.logger.error(
                        f"AI model scan failed: {type(error).__name__}: {error}"
                    )

            def finish():
                self.ai_model_scan_running = False
                if self.ai_model_current_label is None or self.ai_model_status_label is None:
                    return
                try:
                    if result["model"] is not None:
                        self.ai_model_current_label.configure(text=result["model"])
                    self.ai_model_status_label.configure(text=result["detail"])
                    if self.ai_embedding_current_label is not None and result["embedding"] is not None:
                        self.ai_embedding_current_label.configure(text=result["embedding"])
                    if self.ai_embedding_status_label is not None:
                        self.ai_embedding_status_label.configure(text=result["embedding_status"])
                except Exception:
                    return

            try:
                self.after(0, finish)
            except Exception:
                return

        threading.Thread(target=worker, daemon=True).start()

    def _build_runtime(self):
        center = DependencyCenter(
            self.body,
            settings=self.settings,
            service_manager=self.service_manager,
            open_settings_callback=self.open_settings_editor,
            logger=self.logger,
        )
        center.grid(row=0, column=0, sticky="ew")
        self.active_panel = center

    def _build_voice(self):
        card = self._card(self.t("runtime_domain_voice"), self.t("voice_settings_hint"))
        voice_enabled = bool(self.settings.get("voice.enabled", False))
        self._setting_row(card.body, self.t("voice_enabled"), self.t("yes") if voice_enabled else self.t("no"))
        self.voice_device_label = self._setting_row(
            card.body,
            self.t("voice_current_input"),
            self._current_voice_device_text()
        )
        device_actions = ctk.CTkFrame(card.body, fg_color="transparent")
        device_actions.pack(fill="x", pady=(0, SPACING_SMALL))
        choose_button = SecondaryButton(device_actions, text=self.t("voice_choose_device"), command=self._choose_voice_input_device)
        choose_button.pack(
            side="left",
            padx=(0, SPACING_SMALL)
        )
        test_button = SecondaryButton(device_actions, text=self.t("voice_test_device"), command=self._test_voice_input_device)
        test_button.pack(side="left")
        if not voice_enabled:
            device_actions.pack_forget()
        self.voice_device_status = ctk.CTkLabel(
            card.body,
            text="",
            font=FONT_SMALL,
            text_color=COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=720
        )
        self.voice_device_status.pack(fill="x", pady=(0, SPACING_SMALL))
        if voice_enabled:
            self.voice_setup_status = ctk.CTkLabel(
                card.body,
                text=self.t("runtime_status_checking"),
                font=FONT_SMALL,
                text_color=COLOR_MUTED,
                anchor="w",
            )
            self.voice_setup_status.pack(fill="x", pady=(SPACING_SMALL, 0))
            self.voice_setup_button = PrimaryButton(
                card.body,
                text=self.t("voice_setup_one_click"),
                command=self._open_voice_setup,
            )
            self.voice_setup_button.pack(anchor="w", pady=(SPACING_SMALL, SPACING_MEDIUM))
            self.voice_setup_button.configure(state="disabled")
            self._refresh_voice_setup_state()
        self._action_button(card.body, self.t("voice_open_settings"), self.open_settings_editor)

        environment = self._card(self.t("voice_environment"))
        ctk.CTkLabel(
            environment.body,
            text=self.t("voice_environment_hint"),
            font=FONT_SMALL,
            text_color=COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=720,
        ).pack(fill="x", pady=(0, SPACING_SMALL))
        self._action_button(environment.body, self.t("voice_open_runtime"), lambda: self.show_category("runtime"))

    def _build_appearance(self):
        card = self._card(self.t("appearance"), self.t("appearance_settings_hint"))
        self._setting_row(card.body, self.t("theme"), self.settings.get("theme", "blue"))
        self._setting_row(card.body, self.t("appearance"), self.settings.get("appearance", "System"))
        self._setting_row(card.body, self.t("language"), self.settings.get("language", "zh_CN"))
        window_size = f"{self.settings.get('window.width', '')} x {self.settings.get('window.height', '')}"
        self._setting_row(card.body, self.t("window"), window_size)
        self._action_button(card.body, self.t("appearance_open_settings"), self.open_settings_editor)

    def _build_data(self):
        card = self._card(self.t("settings_category_data"), self.t("data_settings_hint"))
        self._setting_row(card.body, self.t("data_conversations"), CONVERSATIONS_DIR)
        self._setting_row(card.body, self.t("data_memory"), MEMORY_DIR)
        self._setting_row(card.body, self.t("data_knowledge"), KNOWLEDGE_DIR)
        self._setting_row(card.body, self.t("data_persona"), PERSONA_DIR)

        actions = self._card(self.t("data_management"))
        self._action_button(actions.body, self.t("data_memory"), self._show_memory_panel)
        self._action_button(actions.body, self.t("data_knowledge"), self._show_knowledge_panel)

    def _build_developer(self):
        card = self._card("")
        logo = ctk.CTkFrame(card.body, width=72, height=72, corner_radius=36, fg_color="#111827")
        logo.pack(anchor="center", pady=(SPACING_SMALL, SPACING_MEDIUM))
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="A", font=(FONT_TITLE[0], 34, "bold"), text_color="white").pack(expand=True)

        ctk.CTkLabel(card.body, text="Project Aurora", font=FONT_TITLE).pack(anchor="center")
        ctk.CTkLabel(card.body, text=self.t("developer_product_tagline"), font=FONT_NORMAL, text_color=COLOR_MUTED).pack(
            anchor="center",
            pady=(0, SPACING_LARGE)
        )
        self._setting_row(card.body, self.t("developer_version"), VERSION)
        self._setting_row(card.body, self.t("developer_build_date"), BUILD_DATE)
        self._setting_row(card.body, "Git", self._git_info())

        changelog = self._recent_changelog()
        if changelog:
            ctk.CTkLabel(card.body, text=self.t("developer_changelog"), font=FONT_NORMAL_BOLD, anchor="w").pack(
                fill="x",
                pady=(SPACING_MEDIUM, SPACING_SMALL)
            )
            ctk.CTkLabel(
                card.body,
                text=changelog,
                font=FONT_SMALL,
                text_color=COLOR_MUTED,
                anchor="w",
                justify="left",
                wraplength=720
            ).pack(fill="x")

        actions = self._card(self.t("developer_entry"))
        self._action_button(actions.body, self.t("developer_open_full_settings"), self.open_settings_editor)

    def _current_voice_device_text(self):
        device_id = str(self.settings.get("voice.recorder.device_id", "") or "").strip()
        display_name = str(self.settings.get("voice.recorder.device_display_name", "") or "").strip()
        configured = str(self.settings.get("voice.recorder.device_name", "") or "").strip()
        keyword = str(self.settings.get("voice.recorder.preferred_device_keyword", "") or "").strip()
        if device_id == WINDOWS_DEFAULT_INPUT_ID or not any((device_id, configured, keyword)):
            return self.t("voice_windows_default_input")
        return display_name or friendly_device_name(configured) or (
            f"{self.t('voice_default_device')} / {keyword}"
            if keyword
            else self.t("voice_saved_device")
        )

    def _open_voice_setup(self):
        VoiceSetupWizard(self, settings=self.settings, logger=self.logger, translate=self.t)

    def _refresh_voice_setup_state(self):
        button = self.voice_setup_button
        status_label = self.voice_setup_status
        if button is None or status_label is None:
            return

        def worker():
            try:
                ready = bool(RuntimeDependencyManager(self.settings).check_voice_requirements()["ready"])
            except Exception:
                ready = False

            def finish():
                try:
                    if not button.winfo_exists() or not status_label.winfo_exists():
                        return
                    status_label.configure(
                        text=self.t("voice_setup_ready" if ready else "voice_setup_incomplete"),
                        text_color=COLOR_SUCCESS if ready else COLOR_MUTED,
                    )
                    if ready:
                        button.pack_forget()
                    else:
                        button.configure(state="normal")
                except Exception:
                    return

            try:
                self.after(0, finish)
            except Exception:
                return

        threading.Thread(target=worker, daemon=True).start()

    def _set_voice_device_status(self, text, status="disabled"):
        if self.voice_device_status is None:
            return
        colors = {
            "healthy": COLOR_SUCCESS,
            "error": COLOR_ERROR,
            "warning": COLOR_ERROR,
            "disabled": COLOR_MUTED,
        }
        self.voice_device_status.configure(text=text, text_color=colors.get(status, COLOR_MUTED))

    def _refresh_voice_device_label(self):
        if self.voice_device_label is not None:
            self.voice_device_label.configure(text=self._current_voice_device_text())

    def _choose_voice_input_device(self):
        ffmpeg_path = str(self.settings.get("voice.recorder.ffmpeg_path", "ffmpeg") or "ffmpeg")
        try:
            devices = enumerate_dshow_audio_devices(ffmpeg_path)
        except AudioDeviceDiscoveryError:
            self._set_voice_device_status(
                self.t("voice_device_not_found"),
                "error",
            )
            return

        window = ctk.CTkToplevel(self)
        window.title(self.t("voice_choose_device"))
        window.geometry("560x180")
        window.transient(self.winfo_toplevel())
        window.grab_set()

        choices = device_choice_map(
            devices,
            default_label=self.t("voice_windows_default_input"),
            fallback_label=self.t("runtime_item_microphone"),
        )
        values = list(choices)
        selected = ctk.StringVar(value=values[0])
        ctk.CTkLabel(window, text=self.t("voice_current_input"), font=FONT_NORMAL).pack(
            anchor="w",
            padx=SPACING_MEDIUM,
            pady=(SPACING_MEDIUM, SPACING_SMALL)
        )
        ctk.CTkOptionMenu(window, values=values, variable=selected, width=500).pack(
            fill="x",
            padx=SPACING_MEDIUM,
            pady=(0, SPACING_MEDIUM)
        )

        def save_selection():
            label = selected.get()
            select_voice_input_device(self.settings, choices[label], display_name="" if choices[label] == WINDOWS_DEFAULT_INPUT_ID else label)
            self._refresh_voice_device_label()
            self._set_voice_device_status(self.t("voice_device_selected").format(device=label), "healthy")
            window.grab_release()
            window.destroy()

        PrimaryButton(window, text=self.t("save"), command=save_selection).pack(anchor="e", padx=SPACING_MEDIUM)

    def _test_voice_input_device(self):
        if not bool(self.settings.get("voice.enabled", False)):
            self._set_voice_device_status(self.t("voice_device_test_disabled"), "disabled")
            return
        self._set_voice_device_status(self.t("voice_device_testing"), "disabled")

        def run_test():
            try:
                resolve_voice_input_device(self.settings)
                result = {"ok": True, "message": self.t("voice_device_available").format(device=self._current_voice_device_text())}
            except Exception:
                result = {
                    "ok": False,
                    "message": self.t("voice_device_unavailable"),
                }

            def finish():
                self._refresh_voice_device_label()
                self._set_voice_device_status(result["message"], "healthy" if result["ok"] else "error")

            self.after(0, finish)

        threading.Thread(target=run_test, daemon=True).start()

    def _show_persona_panel(self):
        if self.persona_store is None:
            return
        self._mount_panel(
            lambda parent: PersonaPanel(
                parent,
                persona_store=self.persona_store,
                settings=self.settings,
                translate=self.t,
                logger=self.logger,
                final_prompt_preview_callback=self.final_prompt_preview_callback,
                show_close_button=False,
                show_header_title=False
            )
        )

    def _show_memory_panel(self):
        if self.memory_store is None or self.search_memories is None:
            return
        self._mount_panel(
            lambda parent: MemoryPanel(
                parent,
                memory_store=self.memory_store,
                search_memories=self.search_memories,
                translate=self.t,
                logger=self.logger,
                show_close_button=False,
                show_header_title=False
            )
        )

    def _show_knowledge_panel(self):
        if self.knowledge_store is None:
            return
        self._mount_panel(
            lambda parent: KnowledgePanel(
                parent,
                knowledge_store=self.knowledge_store,
                settings=self.settings,
                text=self.text,
                translate=self.t,
                logger=self.logger,
                version=self.version,
                retrieval_summary=self.retrieval_summary,
                show_close_button=False,
                show_header_title=False
            )
        )

    def _mount_panel(self, factory):
        self._clear_body()
        holder = ctk.CTkFrame(self.body, fg_color="transparent")
        holder.grid(row=0, column=0, sticky="nsew")
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_rowconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)
        self.active_panel = factory(holder)
        self.active_panel.grid(row=0, column=0, sticky="nsew")

    def _git_info(self):
        root = Path(__file__).resolve().parents[2]
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False
            ).stdout.strip()
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False
            ).stdout.strip()
        except Exception:
            return self.t("developer_unavailable")
        if commit and branch:
            return f"{branch} @ {commit}"
        return commit or branch or self.t("developer_unavailable")

    def _recent_changelog(self):
        path = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ""
        entries = []
        for line in lines:
            text = line.strip()
            if text.startswith("- "):
                entries.append(text)
            if len(entries) >= 4:
                break
        return "\n".join(entries)

import customtkinter as ctk
import threading

from modules.runtime_dependencies import RuntimeDependencyManager
from modules.ui_theme import (
    FORM_CONTROL_WIDTH,
    FORM_LABEL_WRAP,
    FONT_NORMAL,
    FONT_SMALL,
    FONT_TITLE,
    SPACING_SMALL,
    SPACING_MEDIUM,
    SPACING_LARGE,
    status_color
)
from widgets.ui_components import (
    FixedFooter,
    FormRow,
    PrimaryButton,
    SecondaryButton,
    SectionCard,
    StatusLabel
)


class SettingsWindow(ctk.CTkToplevel):
    HEALTH_LABEL_KEYS = {
        "Ollama": "settings_window_ollama",
        "Chat Model": "chat_model",
        "Embedding Model": "embedding_model",
        "Persona": "persona",
        "Memory": "memory",
        "Knowledge": "knowledge",
        "Vector Index": "vector_index",
        "Conversation Store": "conversation"
    }

    def __init__(
        self,
        parent,
        *,
        settings,
        controller,
        text,
        translate,
        language_display,
        language_code,
        apply_language,
        refresh_main_texts,
        logger,
        persona_status_provider=None,
        health_report_provider=None,
        service_test_callback=None,
        model_capability_provider=None,
        on_close=None
    ):
        super().__init__(parent)
        self.settings = settings
        self.controller = controller
        self.text = text
        self.t = translate
        self.language_display = language_display
        self.language_code = language_code
        self.apply_language = apply_language
        self.refresh_main_texts = refresh_main_texts
        self.logger = logger
        self.persona_status_provider = persona_status_provider
        self.health_report_provider = health_report_provider
        self.service_test_callback = service_test_callback
        self.model_capability_provider = model_capability_provider
        self.on_close_callback = on_close
        self.initial_voice_enabled = bool(self.settings.get("voice.enabled", False))
        self.initial_chat_model_mode = str(
            self.settings.get("chat_model_mode", "auto") or "auto"
        ).casefold()
        self.initial_embedding_model_mode = str(
            self.settings.get("embedding_model_mode", "manual") or "manual"
        ).casefold()
        self.section_body = None
        self._disposed = False
        self._model_check_running = False

        self.title(self.t("settings"))
        self.geometry("680x680")
        self.minsize(560, 560)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.build()

    def build(self):
        self.settings_title = ctk.CTkLabel(
            self,
            text=self.t("settings"),
            font=FONT_TITLE
        )
        self.settings_title.pack(
            anchor="w",
            padx=SPACING_LARGE + SPACING_SMALL,
            pady=(SPACING_LARGE, SPACING_MEDIUM + SPACING_SMALL)
        )

        self.footer = FixedFooter(self)
        self.footer.pack(side="bottom", fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_LARGE))

        self.content = ctk.CTkScrollableFrame(self)
        self.content.pack(side="top", fill="both", expand=True, padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_MEDIUM))
        self.section_body = self.content

        self.build_general_section()
        self.build_ai_section()
        self.build_voice_section()
        self.build_developer_section()
        self.build_persona_section()
        self.build_memory_section()
        self.build_knowledge_section()
        self.build_status_section()
        self.build_service_test_controls()
        self.build_footer()

    def add_section_title(self, text):
        section = SectionCard(self.content, text)
        section.pack(fill="x", padx=0, pady=(SPACING_SMALL, SPACING_MEDIUM))
        self.section_body = section.body
        return section

    def add_option_row(self, label_text, values, current_value):
        row = FormRow(self.section_body, label_text)
        row.pack(fill="x", pady=SPACING_SMALL)
        return row.add_option(values, current_value)

    def add_entry_row(self, label_text, current_value):
        row = FormRow(self.section_body, label_text)
        row.pack(fill="x", pady=SPACING_SMALL)
        return row.add_entry(current_value)

    def add_status_row(self, label_text, value_text, status="disabled"):
        row = ctk.CTkFrame(self.section_body, fg_color="transparent")
        row.pack(fill="x", pady=SPACING_SMALL)
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            row,
            text=label_text,
            anchor="w",
            font=FONT_NORMAL,
            wraplength=FORM_LABEL_WRAP,
            justify="left"
        ).grid(row=0, column=0, sticky="w", padx=(0, SPACING_MEDIUM))
        label = StatusLabel(
            row,
            status=status,
            text=str(value_text),
        )
        label.grid(row=0, column=1, sticky="e")
        return label

    def add_switch(self, text, variable):
        ctk.CTkSwitch(
            self.section_body,
            text=text,
            variable=variable
        ).pack(anchor="w", pady=SPACING_SMALL)

    def build_general_section(self):
        self.add_section_title(self.t("general"))
        appearance_value = self.settings.get("appearance", "System")
        if appearance_value not in ["System", "Light", "Dark"]:
            appearance_value = "System"
        self.appearance_display = {
            "System": self.t("appearance_system"),
            "Light": self.t("appearance_light"),
            "Dark": self.t("appearance_dark")
        }

        theme_value = self.settings.get("theme", "blue")
        theme_options = ["blue", "green", "dark-blue"]
        if theme_value not in theme_options:
            theme_value = "blue"

        self.appearance_option = self.add_option_row(
            self.t("appearance"),
            list(self.appearance_display.values()),
            self.appearance_display[appearance_value]
        )
        self.theme_option = self.add_option_row(self.t("theme"), theme_options, theme_value)
        self.language_option = self.add_option_row(
            self.t("language"),
            [self.language_display("zh_CN"), self.language_display("en_US")],
            self.language_display(self.settings.get("language", "zh_CN"))
        )

    def build_ai_section(self):
        self.add_section_title(self.t("ai"))
        self.ollama_host_entry = self.add_entry_row(
            self.t("ollama_host"),
            self.settings.get("ollama.host", "http://127.0.0.1:11434")
        )
        self.auto_start_ollama_var = ctk.BooleanVar(
            value=bool(self.settings.get("ollama.auto_start", False))
        )
        self.add_switch(self.t("ollama_auto_start"), self.auto_start_ollama_var)
        self.ollama_command_entry = self.add_entry_row(
            self.t("ollama_command"),
            self.settings.get("services.ollama.command", "ollama serve")
        )
        chat_mode = str(self.settings.get("chat_model_mode", "auto") or "auto").casefold()
        embedding_mode = str(
            self.settings.get("embedding_model_mode", "manual") or "manual"
        ).casefold()
        self.chat_model_mode_option = self.add_option_row(
            "Chat Model Mode",
            ["Auto", "Manual"],
            "Manual" if chat_mode == "manual" else "Auto",
        )
        self.chat_model_entry = self.add_option_row(
            self.t("chat_model"),
            [self.settings.get("chat_model", "") or "No installed Chat models"],
            self.settings.get("chat_model", "") or "No installed Chat models",
        )
        self.chat_model_status = self.add_status_row(
            "Chat Model Status",
            "Checking installed models...",
        )
        self.embedding_model_mode_option = self.add_option_row(
            "Embedding Mode",
            ["Auto", "Manual"],
            "Manual" if embedding_mode == "manual" else "Auto",
        )
        self.embedding_model_entry = self.add_option_row(
            self.t("embedding_model"),
            [self.settings.get("embedding_model", "") or "No installed Embedding models"],
            self.settings.get("embedding_model", "") or "No installed Embedding models",
        )
        self.embedding_model_status = self.add_status_row(
            "Embedding Status",
            "Optional",
        )
        model_actions = ctk.CTkFrame(self.section_body, fg_color="transparent")
        model_actions.pack(fill="x", pady=SPACING_SMALL)
        self.reload_models_button = SecondaryButton(
            model_actions,
            text="Reload Models",
            command=self.reload_models,
        )
        self.reload_models_button.pack(side="left", padx=(0, SPACING_SMALL))
        self.reevaluate_models_button = SecondaryButton(
            model_actions,
            text="Re-run Recommendation",
            command=lambda: self.reload_models(reevaluate=True),
        )
        self.reevaluate_models_button.pack(side="left")
        self.chat_model_mode_option.configure(command=self._model_mode_changed)
        self.embedding_model_mode_option.configure(command=self._model_mode_changed)
        self._model_mode_changed()
        self.after(0, self.reload_models)

    def _model_mode_changed(self, _value=None):
        chat_auto = self.chat_model_mode_option.get().casefold() == "auto"
        embedding_auto = self.embedding_model_mode_option.get().casefold() == "auto"
        self.chat_model_entry.configure(state="disabled" if chat_auto else "normal")
        self.embedding_model_entry.configure(
            state="disabled" if embedding_auto else "normal"
        )

    @staticmethod
    def _selected_model(option, placeholder):
        value = str(option.get() or "").strip()
        return "" if value == placeholder else value

    @staticmethod
    def _model_picker_values(installed, current, placeholder):
        values = [str(value or "").strip() for value in installed if str(value or "").strip()]
        selected = str(current or "").strip()
        if selected and selected not in values:
            values.insert(0, selected)
        return (values or [placeholder], selected or (values[0] if values else placeholder))

    def reload_models(self, reevaluate=False):
        if self._model_check_running or self._disposed:
            return
        if reevaluate and self.chat_model_mode_option.get().casefold() != "auto":
            self.result_label.configure(
                text="Switch Chat Model Mode to Auto and save before re-running the recommendation.",
                text_color=status_color("warning"),
            )
            return
        self._model_check_running = True
        self.reload_models_button.configure(state="disabled", text="Scanning...")
        self.reevaluate_models_button.configure(state="disabled")

        def worker():
            try:
                report = RuntimeDependencyManager(self.settings).check_models(
                    timeout=1.0,
                    reevaluate_models=bool(reevaluate),
                )
            except Exception as error:
                report = None
                if self.logger:
                    self.logger.error(
                        f"Model refresh failed: {type(error).__name__}: {error}"
                    )

            def finish():
                self._model_check_running = False
                self.reload_models_button.configure(state="normal", text="Reload Models")
                self.reevaluate_models_button.configure(state="normal")
                if report is None:
                    self.chat_model_status.set_status(
                        "warning", "Models could not be checked. Try again."
                    )
                    return
                ollama = report.get("ollama", {})
                chat_names = [
                    item.get("name", "")
                    for item in ollama.get("models", {}).get("chat", [])
                    if item.get("name")
                ]
                embedding_names = [
                    item.get("name", "")
                    for item in ollama.get("models", {}).get("embedding", [])
                    if item.get("name")
                ]
                chat_item = ollama.get("chat_model", {})
                embedding_item = ollama.get("embedding_model", {})
                chat_value = str(chat_item.get("data", {}).get("configured") or "")
                embedding_value = str(
                    embedding_item.get("data", {}).get("configured") or ""
                )
                chat_values, chat_selected = self._model_picker_values(
                    chat_names,
                    chat_value,
                    "No installed Chat models",
                )
                embedding_values, embedding_selected = self._model_picker_values(
                    embedding_names,
                    embedding_value,
                    "No installed Embedding models",
                )
                self.chat_model_entry.configure(values=chat_values)
                self.chat_model_entry.set(chat_selected)
                self.embedding_model_entry.configure(values=embedding_values)
                self.embedding_model_entry.set(embedding_selected)
                self.chat_model_status.set_status(
                    self._runtime_status_style(chat_item.get("status")),
                    chat_item.get("detail") or "Not checked",
                )
                self.embedding_model_status.set_status(
                    self._runtime_status_style(embedding_item.get("status")),
                    embedding_item.get("detail") or "Optional",
                )
                self.initial_chat_model_mode = str(
                    self.settings.get("chat_model_mode", "auto") or "auto"
                ).casefold()
                self.initial_embedding_model_mode = str(
                    self.settings.get("embedding_model_mode", "manual") or "manual"
                ).casefold()
                self._model_mode_changed()

            self._after(finish)

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _runtime_status_style(status):
        return {
            "Ready": "healthy",
            "Missing": "warning",
            "Offline": "error",
            "Optional": "disabled",
            "Degraded": "warning",
        }.get(str(status or ""), "disabled")

    def build_voice_section(self):
        self.add_section_title("Voice")
        self.voice_enabled_var = ctk.BooleanVar(
            value=bool(self.settings.get("voice.enabled", False))
        )
        self.add_switch("Voice Enabled", self.voice_enabled_var)
        self.voice_stt_option = self.add_option_row(
            "STT Provider",
            ["Faster Whisper"],
            "Faster Whisper"
        )
        self.voice_tts_option = self.add_option_row(
            "TTS Provider",
            ["Edge TTS"],
            "Edge TTS"
        )
        self.voice_entry = self.add_entry_row(
            "Voice",
            self.settings.get("voice.tts.voice", "zh-CN-XiaoxiaoNeural")
        )
        self.voice_playback_var = ctk.BooleanVar(
            value=bool(self.settings.get("voice.playback.enabled", True))
        )
        self.add_switch("Playback Enabled", self.voice_playback_var)

    def build_developer_section(self):
        self.add_section_title(self.t("developer"))
        self.refresh_interval_entry = self.add_entry_row(
            self.t("refresh_interval"),
            self.settings.get("status.refresh_interval", 3)
        )
        self.add_status_row(self.t("debug_mode"), self.t("disabled"), "disabled")
        self.add_status_row(self.t("log_level"), self.settings.get("log.level", "INFO"))

    def build_persona_section(self):
        self.add_section_title(self.t("persona"))
        try:
            current_persona = self.persona_status_provider() if self.persona_status_provider else {}
            self.add_status_row(
                self.t("settings_window_current_persona"),
                current_persona.get("name", "Aurora"),
                "healthy"
            )
        except Exception as error:
            self.add_status_row(self.t("settings_window_current_persona"), error, "error")
        self.persona_enabled_var = ctk.BooleanVar(
            value=bool(self.settings.get("persona.enabled", True))
        )
        self.add_switch(self.t("persona_enable"), self.persona_enabled_var)

    def build_memory_section(self):
        self.add_section_title(self.t("memory"))
        self.add_status_row(self.t("memory_available"), self.t("yes"), "healthy")
        self.max_injection_entry = self.add_entry_row(
            self.t("maximum_memory_injection"),
            self.settings.get("memory.max_injection", 5)
        )
        self.min_importance_entry = self.add_entry_row(
            self.t("minimum_memory_importance"),
            self.settings.get("memory.min_importance", 0)
        )
        self.retrieval_threshold_entry = self.add_entry_row(
            self.t("memory_retrieval_threshold"),
            self.settings.get("memory.retrieval_threshold", 0.35)
        )
        self.rag_pipeline_enabled_var = ctk.BooleanVar(
            value=bool(self.settings.get("rag.pipeline_enabled", True))
        )
        self.add_switch(self.t("rag_pipeline_enable"), self.rag_pipeline_enabled_var)
        self.rag_context_budget_entry = self.add_entry_row(
            self.t("rag_context_budget"),
            self.settings.get("rag.context_budget", 4000)
        )
        self.adaptive_context_enabled_var = ctk.BooleanVar(
            value=bool(self.settings.get("context.adaptive_enabled", False))
        )
        self.add_switch(self.t("adaptive_context_enable"), self.adaptive_context_enabled_var)

    def build_knowledge_section(self):
        self.add_section_title(self.t("knowledge"))
        self.knowledge_enabled_var = ctk.BooleanVar(
            value=bool(self.settings.get("knowledge.enabled", True))
        )
        self.add_switch(self.t("knowledge_enable"), self.knowledge_enabled_var)
        self.max_knowledge_entry = self.add_entry_row(
            self.t("maximum_knowledge_results"),
            self.settings.get("knowledge.max_results", 3)
        )

    def build_status_section(self):
        self.add_section_title(self.t("status_overview"))
        try:
            health_report = self.health_report_provider() if self.health_report_provider else {"items": []}
            health_items = {
                item.get("name"): item
                for item in health_report.get("items", [])
                if isinstance(item, dict)
            }
        except Exception as error:
            health_items = {}
            self.add_status_row(self.t("health_check"), error, "error")

        for status_name in [
            "Ollama",
            "Chat Model",
            "Embedding Model",
            "Persona",
            "Memory",
            "Knowledge",
            "Vector Index",
            "Conversation Store"
        ]:
            item = health_items.get(status_name, {})
            value = item.get("status", self.t("settings_window_unknown_status"))
            self.add_status_row(self.t(self.HEALTH_LABEL_KEYS.get(status_name, status_name)), value, value)

        memory_details = health_items.get("Memory", {}).get("details", {})
        knowledge_details = health_items.get("Knowledge", {}).get("details", {})
        conversation_details = health_items.get("Conversation Store", {}).get("details", {})
        self.add_status_row(self.t("memory_count"), memory_details.get("records", 0))
        self.add_status_row(self.t("knowledge_documents"), knowledge_details.get("total", 0))
        self.add_status_row(self.t("conversation_count"), conversation_details.get("records", 0))
        self.add_status_row(self.t("log_level"), self.settings.get("log.level", "INFO"))

    def build_service_test_controls(self):
        self.ollama_result_label = ctk.CTkLabel(
            self.content,
            text="",
            font=FONT_SMALL,
            text_color=status_color("disabled")
        )
        self.ollama_result_label.pack(anchor="e", padx=10, pady=(0, 2))

        self.ollama_test_button = PrimaryButton(
            self.ollama_host_entry.master,
            text=self.t("test"),
            width=FORM_CONTROL_WIDTH // 3,
            command=lambda: self.test_service(
                "Ollama",
                self.ollama_host_entry.get().strip(),
                self.ollama_result_label,
                self.ollama_test_button
            )
        )
        self.ollama_test_button.pack(side="right", padx=(0, 8))

    def build_footer(self):
        self.result_label = self.footer.message
        self.save_button = PrimaryButton(
            self.footer.buttons,
            text=self.t("save"),
            command=self.save
        )
        self.save_button.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.close_button = SecondaryButton(
            self.footer.buttons,
            text=self.t("close"),
            command=self.close
        )
        self.close_button.pack(side="left", expand=True, fill="x", padx=(6, 0))

    def test_service(self, service_name, url, label, button):
        if not self.service_test_callback:
            return
        button.configure(state="disabled")
        label.configure(
            text=self.t("testing"),
            text_color=status_color("disabled")
        )
        self.service_test_callback(
            service_name,
            url,
            lambda connected, elapsed_ms, reason: self.update_connection_result(
                label,
                button,
                connected,
                elapsed_ms,
                reason
            )
        )

    def update_connection_result(self, label, button, connected, elapsed_ms, reason):
        button.configure(state="normal")
        if connected:
            label.configure(
                text=self.t("settings_window_connection_ok").format(elapsed_ms=elapsed_ms),
                text_color=status_color("healthy")
            )
        else:
            label.configure(
                text=self.t("settings_window_connection_failed").format(reason=reason),
                text_color=status_color("error")
            )

    def collect_settings(self):
        selected_appearance = {
            self.t("appearance_system"): "System",
            self.t("appearance_light"): "Light",
            self.t("appearance_dark"): "Dark"
        }.get(self.appearance_option.get(), "System")
        selected_language = self.language_code(self.language_option.get())
        chat_mode = self.chat_model_mode_option.get().casefold()
        embedding_mode = self.embedding_model_mode_option.get().casefold()
        chat_model = self._selected_model(
            self.chat_model_entry, "No installed Chat models"
        )
        embedding_model = self._selected_model(
            self.embedding_model_entry, "No installed Embedding models"
        )
        if chat_mode == "auto":
            chat_model = (
                self.settings.get("chat_model", "")
                if self.initial_chat_model_mode == "auto"
                else ""
            )
        if embedding_mode == "auto":
            embedding_model = (
                self.settings.get("embedding_model", "")
                if self.initial_embedding_model_mode == "auto"
                else ""
            )
        values = {
            "appearance": selected_appearance,
            "theme": self.theme_option.get(),
            "ollama.host": self.ollama_host_entry.get().strip(),
            "ollama.auto_start": bool(self.auto_start_ollama_var.get()),
            "services.ollama.command": self.ollama_command_entry.get().strip(),
            "status.refresh_interval": self.refresh_interval_entry.get().strip(),
            "chat_model_mode": chat_mode,
            "chat_model": chat_model,
            "resolved_chat_model": (
                self.settings.get("resolved_chat_model", "")
                if chat_mode == "auto" and self.initial_chat_model_mode == "auto"
                else ""
            ),
            "chat_model_resolution_reason": (
                self.settings.get("chat_model_resolution_reason", "")
                if chat_mode == "auto" and self.initial_chat_model_mode == "auto"
                else "manual_selection"
            ),
            "embedding_model_mode": embedding_mode,
            "embedding_model": embedding_model,
            "resolved_embedding_model": (
                self.settings.get("resolved_embedding_model", "")
                if embedding_mode == "auto"
                and self.initial_embedding_model_mode == "auto"
                else ""
            ),
            "embedding_model_resolution_reason": (
                self.settings.get("embedding_model_resolution_reason", "")
                if embedding_mode == "auto"
                and self.initial_embedding_model_mode == "auto"
                else "manual_selection"
            ),
            "voice.enabled": bool(self.voice_enabled_var.get()),
            "voice.stt.provider": "faster_whisper",
            "voice.tts.provider": "edge_tts",
            "voice.tts.voice": self.voice_entry.get().strip(),
            "voice.playback.enabled": bool(self.voice_playback_var.get()),
            "memory.max_injection": self.max_injection_entry.get().strip(),
            "memory.min_importance": self.min_importance_entry.get().strip(),
            "memory.retrieval_threshold": self.retrieval_threshold_entry.get().strip(),
            "rag.pipeline_enabled": bool(self.rag_pipeline_enabled_var.get()),
            "rag.context_budget": self.rag_context_budget_entry.get().strip(),
            "context.adaptive_enabled": bool(self.adaptive_context_enabled_var.get()),
            "persona.enabled": bool(self.persona_enabled_var.get()),
            "knowledge.enabled": bool(self.knowledge_enabled_var.get()),
            "knowledge.max_results": self.max_knowledge_entry.get().strip(),
            "language": selected_language
        }
        if chat_mode == "manual" and chat_model:
            values["last_successful_chat_model"] = chat_model
        return values

    def refresh_after_settings_change(self, saved_values):
        selected_appearance = saved_values.get("appearance", "System")
        selected_language = saved_values.get("language", "zh_CN")
        self.apply_language(selected_language)

        if str(selected_appearance).lower() == "system":
            ctk.set_appearance_mode("System")
        elif str(selected_appearance).lower() == "light":
            ctk.set_appearance_mode("Light")
        else:
            ctk.set_appearance_mode("Dark")

        self.title(self.t("settings"))
        self.settings_title.configure(text=self.t("settings"))
        self.save_button.configure(text=self.t("save"))
        self.close_button.configure(text=self.t("close"))
        self.refresh_main_texts()
        self.logger.info("Settings UI refreshed")

    def save(self):
        self.save_button.configure(state="disabled")
        self.ollama_test_button.configure(state="disabled")
        self.result_label.configure(
            text=self.t("saving"),
            text_color=status_color("disabled")
        )

        result = self.controller.save(self.collect_settings())
        self.save_button.configure(state="normal")
        self.ollama_test_button.configure(state="normal")

        if not result.get("ok"):
            self.result_label.configure(
                text=self.t("invalid_settings"),
                text_color=status_color("error")
            )
            self.logger.info(f"Settings save failed: {result.get('errors', [])}")
            return

        saved_values = result.get("values", {})
        self.refresh_after_settings_change(saved_values)
        self.initial_chat_model_mode = str(
            saved_values.get("chat_model_mode", "auto") or "auto"
        ).casefold()
        self.initial_embedding_model_mode = str(
            saved_values.get("embedding_model_mode", "manual") or "manual"
        ).casefold()
        self.reload_models()
        self.logger.info("Settings saved")
        self.logger.info("Language changed")
        if (
            self.model_capability_provider
            and self.model_capability_provider(saved_values.get("chat_model", "")) != "Chat Supported"
        ):
            self.logger.info("Embedding model blocked from chat")
        self.logger.info("Persona enabled" if saved_values.get("persona.enabled") else "Persona disabled")
        self.result_label.configure(
            text=f"{self.t('settings_saved')} {self.t('restart_required_for_full_language_refresh')}",
            text_color=status_color("healthy")
        )
        if saved_values.get("voice.enabled") and not self.initial_voice_enabled:
            self.initial_voice_enabled = True
            self._check_first_voice_enablement()

    def _check_first_voice_enablement(self):
        """Explain optional Voice gaps after its first enable without blocking save."""

        self.result_label.configure(
            text="Settings saved. Checking optional Voice dependencies...",
            text_color=status_color("disabled"),
        )

        def worker():
            try:
                report = RuntimeDependencyManager(
                    self.settings
                ).check_voice_requirements()
            except Exception as error:
                if self.logger:
                    self.logger.error(f"Voice dependency check failed: {error}")
                report = {"ready": False, "items": [{"name": "Voice environment", "status": "Degraded"}]}
            missing = [
                item.get("name", item.get("key", "component"))
                for item in report.get("missing", [])
            ]

            def finish():
                if report.get("ready"):
                    message = "Settings saved. Voice dependencies are ready; restart Aurora to enable Voice."
                    state = "healthy"
                else:
                    message = (
                        "Settings saved. Voice remains unavailable until these optional components are ready: "
                        + ", ".join(missing)
                        + ". Open Runtime / Dependencies."
                    )
                    state = "warning"
                self.result_label.configure(text=message, text_color=status_color(state))

            self._after(finish)

        threading.Thread(target=worker, daemon=True).start()

    def _after(self, callback):
        """Schedule a UI update only while this Settings window still exists."""

        if self._disposed:
            return

        def guarded_callback():
            if self._disposed:
                return
            try:
                if self.winfo_exists():
                    callback()
            except Exception as error:
                if not self._disposed and self.logger:
                    self.logger.error(f"Settings UI update failed: {error}")

        try:
            self.after(0, guarded_callback)
        except Exception:
            return

    def close(self):
        self.destroy()
        if self.on_close_callback:
            self.on_close_callback()

    def destroy(self):
        if self._disposed:
            return
        self._disposed = True
        super().destroy()

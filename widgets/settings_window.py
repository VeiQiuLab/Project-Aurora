import customtkinter as ctk

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
        self.section_body = None

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
        StatusLabel(
            row,
            status=status,
            text=str(value_text),
        ).grid(row=0, column=1, sticky="e")

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
        self.chat_model_entry = self.add_entry_row(
            self.t("chat_model"),
            self.settings.get("chat_model", "qwen3:8b")
        )
        self.embedding_model_entry = self.add_entry_row(
            self.t("embedding_model"),
            self.settings.get("embedding_model", "nomic-embed-text:latest")
        )
        self.openwebui_url_entry = self.add_entry_row(
            self.t("openwebui_url"),
            self.settings.get("openwebui.host", "http://localhost:8080")
        )
        self.openwebui_type_option = self.add_option_row(
            self.t("openwebui_type"),
            ["docker"],
            self.settings.get("openwebui.type", "docker")
        )
        self.openwebui_container_entry = self.add_entry_row(
            self.t("container_name"),
            self.settings.get("openwebui.container_name", "open-webui")
        )
        self.auto_start_openwebui_var = ctk.BooleanVar(
            value=bool(self.settings.get("openwebui.auto_start", False))
        )
        self.add_switch(self.t("auto_start_openwebui"), self.auto_start_openwebui_var)
        self.docker_auto_start_var = ctk.BooleanVar(
            value=bool(self.settings.get("services.docker.auto_start", True))
        )
        self.add_switch(self.t("docker_desktop_auto_start"), self.docker_auto_start_var)
        self.docker_path_entry = self.add_entry_row(
            self.t("docker_desktop_path"),
            self.settings.get("services.docker.path", r"C:\Program Files\Docker\Docker\Docker Desktop.exe")
        )
        self.docker_timeout_entry = self.add_entry_row(
            self.t("docker_startup_timeout"),
            self.settings.get("services.docker.startup_timeout", 60)
        )

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

        self.openwebui_result_label = ctk.CTkLabel(
            self.content,
            text="",
            font=FONT_SMALL,
            text_color=status_color("disabled")
        )
        self.openwebui_result_label.pack(anchor="e", padx=10, pady=(0, 8))

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

        self.openwebui_test_button = PrimaryButton(
            self.openwebui_url_entry.master,
            text=self.t("test"),
            width=FORM_CONTROL_WIDTH // 3,
            command=lambda: self.test_service(
                "Open WebUI",
                self.openwebui_url_entry.get().strip(),
                self.openwebui_result_label,
                self.openwebui_test_button
            )
        )
        self.openwebui_test_button.pack(side="right", padx=(0, 8))

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
        return {
            "appearance": selected_appearance,
            "theme": self.theme_option.get(),
            "ollama.host": self.ollama_host_entry.get().strip(),
            "ollama.auto_start": bool(self.auto_start_ollama_var.get()),
            "services.ollama.command": self.ollama_command_entry.get().strip(),
            "openwebui.host": self.openwebui_url_entry.get().strip(),
            "openwebui.type": self.openwebui_type_option.get(),
            "openwebui.container_name": self.openwebui_container_entry.get().strip(),
            "openwebui.auto_start": bool(self.auto_start_openwebui_var.get()),
            "services.docker.auto_start": bool(self.docker_auto_start_var.get()),
            "services.docker.path": self.docker_path_entry.get().strip(),
            "services.docker.startup_timeout": self.docker_timeout_entry.get().strip(),
            "status.refresh_interval": self.refresh_interval_entry.get().strip(),
            "chat_model": self.chat_model_entry.get().strip(),
            "embedding_model": self.embedding_model_entry.get().strip(),
            "voice.enabled": bool(self.voice_enabled_var.get()),
            "voice.stt.provider": "faster_whisper",
            "voice.tts.provider": "edge_tts",
            "voice.tts.voice": self.voice_entry.get().strip(),
            "voice.playback.enabled": bool(self.voice_playback_var.get()),
            "memory.max_injection": self.max_injection_entry.get().strip(),
            "memory.min_importance": self.min_importance_entry.get().strip(),
            "persona.enabled": bool(self.persona_enabled_var.get()),
            "knowledge.enabled": bool(self.knowledge_enabled_var.get()),
            "knowledge.max_results": self.max_knowledge_entry.get().strip(),
            "language": selected_language
        }

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
        self.openwebui_test_button.configure(state="disabled")
        self.result_label.configure(
            text=self.t("saving"),
            text_color=status_color("disabled")
        )

        result = self.controller.save(self.collect_settings())
        self.save_button.configure(state="normal")
        self.ollama_test_button.configure(state="normal")
        self.openwebui_test_button.configure(state="normal")

        if not result.get("ok"):
            self.result_label.configure(
                text=self.t("invalid_settings"),
                text_color=status_color("error")
            )
            self.logger.info(f"Settings save failed: {result.get('errors', [])}")
            return

        saved_values = result.get("values", {})
        self.refresh_after_settings_change(saved_values)
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

    def close(self):
        self.destroy()
        if self.on_close_callback:
            self.on_close_callback()

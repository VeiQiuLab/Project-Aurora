import customtkinter as ctk

from modules.ui_theme import FONT_NORMAL, FONT_SMALL, FONT_TITLE, status_color
from widgets.ui_components import (
    FixedFooter,
    FormRow,
    PrimaryButton,
    SecondaryButton,
    SectionCard,
    StatusLabel
)


class SettingsWindow(ctk.CTkToplevel):
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

        self.title(self.text["settings"])
        self.geometry("680x680")
        self.minsize(560, 560)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.build()

    def build(self):
        self.settings_title = ctk.CTkLabel(
            self,
            text=self.text["settings"],
            font=FONT_TITLE
        )
        self.settings_title.pack(anchor="w", padx=25, pady=(20, 15))

        self.footer = FixedFooter(self)
        self.footer.pack(side="bottom", fill="x", padx=25, pady=(0, 20))

        self.content = ctk.CTkScrollableFrame(self)
        self.content.pack(side="top", fill="both", expand=True, padx=25, pady=(0, 12))
        self.section_body = self.content

        self.build_general_section()
        self.build_ai_section()
        self.build_developer_section()
        self.build_remote_section()
        self.build_persona_section()
        self.build_memory_section()
        self.build_knowledge_section()
        self.build_status_section()
        self.build_service_test_controls()
        self.build_footer()

    def add_section_title(self, text):
        section = SectionCard(self.content, text)
        section.pack(fill="x", padx=0, pady=(8, 10))
        self.section_body = section.body
        return section

    def add_option_row(self, label_text, values, current_value):
        row = FormRow(self.section_body, label_text)
        row.pack(fill="x", pady=6)
        return row.add_option(values, current_value)

    def add_entry_row(self, label_text, current_value):
        row = FormRow(self.section_body, label_text)
        row.pack(fill="x", pady=6)
        return row.add_entry(current_value)

    def add_status_row(self, label_text, value_text, status="disabled"):
        row = ctk.CTkFrame(self.section_body, fg_color="transparent")
        row.pack(fill="x", pady=4)
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            row,
            text=label_text,
            anchor="w",
            font=FONT_NORMAL,
            wraplength=300,
            justify="left"
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
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
        ).pack(anchor="w", pady=6)

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
            self.text["appearance"],
            list(self.appearance_display.values()),
            self.appearance_display[appearance_value]
        )
        self.theme_option = self.add_option_row(self.text["theme"], theme_options, theme_value)
        self.language_option = self.add_option_row(
            self.t("language"),
            [self.language_display("zh_CN"), self.language_display("en_US")],
            self.language_display(self.settings.get("language", "zh_CN"))
        )

    def build_ai_section(self):
        self.add_section_title(self.t("ai"))
        self.ollama_host_entry = self.add_entry_row(
            self.text["ollama_host"],
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
            self.text["chat_model"],
            self.settings.get("chat_model", "qwen3:8b")
        )
        self.embedding_model_entry = self.add_entry_row(
            self.text["embedding_model"],
            self.settings.get("embedding_model", "nomic-embed-text:latest")
        )
        self.openwebui_url_entry = self.add_entry_row(
            self.text["openwebui_url"],
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

    def build_developer_section(self):
        self.add_section_title(self.t("developer"))
        self.refresh_interval_entry = self.add_entry_row(
            self.text["refresh_interval"],
            self.settings.get("status.refresh_interval", 3)
        )
        self.add_status_row(
            self.t("debug_mode"),
            self.t("enabled") if self.settings.get("mobile_debug_mode", False) else self.text["disabled"],
            "enabled" if self.settings.get("mobile_debug_mode", False) else "disabled"
        )
        self.add_status_row(self.t("log_level"), self.settings.get("log.level", "INFO"))

    def build_remote_section(self):
        self.add_section_title(self.t("remote"))
        self.remote_enabled_var = ctk.BooleanVar(
            value=bool(self.settings.get("remote.enabled", False))
        )
        self.add_switch(self.text["remote_access_enable"], self.remote_enabled_var)
        self.remote_mode_option = self.add_option_row(
            self.text["remote_mode"],
            ["local"],
            self.settings.get("remote.mode", "local")
        )
        self.add_status_row(self.t("public_access"), self.t("not_available_this_version"), "warning")
        self.preferred_interface_entry = self.add_entry_row(
            self.text["preferred_interface"],
            self.settings.get("network.preferred_interface", "")
        )
        self.ignore_virtual_adapter_var = ctk.BooleanVar(
            value=bool(self.settings.get("network.ignore_virtual_adapter", True))
        )
        self.add_switch(self.text["ignore_virtual_adapter"], self.ignore_virtual_adapter_var)
        self.lan_chat_enabled_var = ctk.BooleanVar(
            value=bool(self.settings.get("remote.lan_chat_enabled", False))
        )
        self.add_switch(self.text["lan_chat_enable"], self.lan_chat_enabled_var)
        self.mobile_access_confirmed_var = ctk.BooleanVar(
            value=bool(self.settings.get("remote.mobile_access_confirmed", False))
        )
        self.add_switch(self.text["mobile_access_confirm"], self.mobile_access_confirmed_var)
        self.mobile_chat_timeout_entry = self.add_entry_row(
            self.text["mobile_chat_timeout"],
            self.settings.get("mobile_chat_timeout", 60)
        )
        self.mobile_debug_mode_var = ctk.BooleanVar(
            value=bool(self.settings.get("mobile_debug_mode", False))
        )
        self.add_switch(self.text["mobile_debug_mode"], self.mobile_debug_mode_var)
        self.mobile_response_limit_entry = self.add_entry_row(
            self.text["mobile_response_limit"],
            self.settings.get("mobile_response_limit", 12000)
        )

    def build_persona_section(self):
        self.add_section_title(self.t("persona"))
        try:
            current_persona = self.persona_status_provider() if self.persona_status_provider else {}
            self.add_status_row("Current Persona", current_persona.get("name", "Aurora"), "healthy")
        except Exception as error:
            self.add_status_row("Current Persona", error, "error")
        self.persona_enabled_var = ctk.BooleanVar(
            value=bool(self.settings.get("persona.enabled", True))
        )
        self.add_switch(self.text["persona_enable"], self.persona_enabled_var)

    def build_memory_section(self):
        self.add_section_title(self.t("memory"))
        self.add_status_row(self.t("memory_available"), self.text["yes"], "healthy")
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
            "Conversation Store",
            "Remote"
        ]:
            item = health_items.get(status_name, {})
            value = item.get("status", "Unknown")
            self.add_status_row("Conversation" if status_name == "Conversation Store" else status_name, value, value)

        memory_details = health_items.get("Memory", {}).get("details", {})
        knowledge_details = health_items.get("Knowledge", {}).get("details", {})
        conversation_details = health_items.get("Conversation Store", {}).get("details", {})
        self.add_status_row(self.t("memory_count"), memory_details.get("records", 0))
        self.add_status_row(self.t("knowledge_documents"), knowledge_details.get("total", 0))
        self.add_status_row(self.t("conversation_count"), conversation_details.get("records", 0))
        self.add_status_row(
            self.t("remote_enabled"),
            self.text["yes"] if self.settings.get("remote.enabled", False) else self.text["no"],
            "enabled" if self.settings.get("remote.enabled", False) else "disabled"
        )
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
            text=self.text["test"],
            width=70,
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
            text=self.text["test"],
            width=70,
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
            text=self.text["save"],
            command=self.save
        )
        self.save_button.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.close_button = SecondaryButton(
            self.footer.buttons,
            text=self.text["close"],
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
                text=f"\u2705 Connected ({elapsed_ms}ms)",
                text_color=status_color("healthy")
            )
        else:
            label.configure(
                text=f"\u274c Cannot connect - {reason}",
                text_color=status_color("error")
            )

    def collect_settings(self):
        selected_appearance = {
            self.t("appearance_system"): "System",
            self.t("appearance_light"): "Light",
            self.t("appearance_dark"): "Dark"
        }.get(self.appearance_option.get(), "System")
        selected_language = self.language_code(self.language_option.get())
        mobile_chat_timeout = self.mobile_chat_timeout_entry.get().strip()
        mobile_response_limit = self.mobile_response_limit_entry.get().strip()

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
            "network.preferred_interface": self.preferred_interface_entry.get().strip(),
            "network.ignore_virtual_adapter": bool(self.ignore_virtual_adapter_var.get()),
            "chat_model": self.chat_model_entry.get().strip(),
            "embedding_model": self.embedding_model_entry.get().strip(),
            "remote.enabled": bool(self.settings.get("remote.enabled", False)) and bool(self.remote_enabled_var.get()),
            "remote.mode": self.remote_mode_option.get(),
            "remote.auth_required": True,
            "remote.authentication_required": True,
            "remote.lan_chat_enabled": bool(self.lan_chat_enabled_var.get()),
            "remote.mobile_access_confirmed": bool(self.mobile_access_confirmed_var.get()),
            "remote.mobile_chat_timeout": mobile_chat_timeout,
            "remote.mobile_debug_mode": bool(self.mobile_debug_mode_var.get()),
            "remote.mobile_response_limit": mobile_response_limit,
            "mobile_chat_timeout": mobile_chat_timeout,
            "mobile_debug_mode": bool(self.mobile_debug_mode_var.get()),
            "mobile_response_limit": mobile_response_limit,
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

        self.title(self.text["settings"])
        self.settings_title.configure(text=self.text["settings"])
        self.save_button.configure(text=self.text["save"])
        self.close_button.configure(text=self.text["close"])
        self.remote_enabled_var.set(bool(saved_values.get("remote.enabled", False)))
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
        self.logger.info("Remote configuration saved without starting remote services")
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

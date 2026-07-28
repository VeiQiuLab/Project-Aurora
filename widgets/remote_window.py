import threading
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from modules.i18n import t as translate_text
from modules.ui_theme import (
    FONT_BODY,
    FONT_SMALL,
    FONT_TITLE,
    SPACING_LARGE,
    SPACING_MEDIUM,
    SPACING_SMALL,
    WINDOW_DEFAULT_WIDTH,
    status_color
)
from widgets.ui_components import (
    DangerButton,
    FixedFooter,
    FormRow,
    PrimaryButton,
    SecondaryButton,
    SectionCard,
    StatusLabel
)


REMOTE_TEXT_DEFAULT_KEYS = {
    "authentication_history": "remote_window_authentication_history",
    "authentication_not_configured_hint": "remote_window_authentication_not_configured_hint",
    "lan_only_description": "remote_window_lan_only_description",
    "lan_url": "remote_window_lan_url",
    "local_only_description": "remote_window_local_only_description",
    "local_url": "remote_window_local_url",
    "no_history": "remote_window_no_history",
    "no_lan_address": "remote_window_no_lan_address",
    "not_ready": "remote_window_not_ready",
    "release_check": "remote_page_release_check",
    "secure_remote_description": "remote_window_secure_remote_description",
    "security": "remote_page_security",
    "understand_risk": "remote_window_understand_risk",
    "remote_history": "remote_window_remote_history"
}


def remote_text_defaults():
    return {key: translate_text(locale_key) for key, locale_key in REMOTE_TEXT_DEFAULT_KEYS.items()}


def localized_text(text):
    values = {}
    for key, value in text.items():
        translated = translate_text(key)
        values[key] = translated if translated != key else value
    return values


class RemoteWindow(ctk.CTkToplevel):
    """Remote Access status and control window.

    This window delegates all Remote state changes to the existing Remote,
    Authentication, Credential Storage, and LAN server services.
    """

    def __init__(
        self,
        parent,
        remote_manager,
        authentication_manager,
        credential_storage_provider,
        settings,
        lan_status_server,
        lan_status_snapshot,
        mobile_chat_service,
        text,
        logger,
        default_lan_status_port,
        on_close=None
    ):
        super().__init__(parent)
        self.parent = parent
        self.remote_manager = remote_manager
        self.authentication_manager = authentication_manager
        self.credential_storage_provider = credential_storage_provider
        self.settings = settings
        self.lan_status_server = lan_status_server
        self.lan_status_snapshot = lan_status_snapshot
        self.mobile_chat_service = mobile_chat_service
        self.TEXT = {**remote_text_defaults(), **localized_text(text)}
        self.logger = logger
        self.default_lan_status_port = default_lan_status_port
        self.on_close = on_close
        self.rows = {}
        self.text_boxes = {}

        self.title(self.ui_text("remote_access"))
        self.geometry("780x700")
        self.minsize(640, 540)
        self.transient(parent)

        self._initialize_remote_state()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh_remote_status()

    def ui_text(self, key):
        locale_key = REMOTE_TEXT_DEFAULT_KEYS.get(key, key)
        value = translate_text(locale_key)
        if value != locale_key:
            return value
        return dict.get(self.TEXT, key, key)

    def _initialize_remote_state(self):
        self.logger.info("Remote configuration loaded")
        self.authentication_manager.load()
        self.logger.info("Authentication configuration loaded")
        self.logger.info("Authentication framework initialized")
        self.logger.info("Credential diagnostics opened")
        self.remote_manager.update(
            enabled=self.settings.get("remote.enabled", False),
            mode=self.settings.get("remote.mode", "local"),
            auth_required=self.settings.get("remote.auth_required", True),
            auth_enabled=self.settings.get("remote.auth_enabled", False),
            authentication_type=self.settings.get("remote.authentication_type", "none"),
            token_configured=self.settings.get("remote.token_configured", False),
            credential_storage=self.settings.get("remote.credential_storage", "windows_credential_manager"),
            secure_storage_configured=self.settings.get("remote.secure_storage_configured", False),
            secure_storage_available=self.settings.get("remote.secure_storage_available", False),
            credential_test_passed=self.settings.get("remote.credential_test_passed", False),
            credential_last_check=self.settings.get("remote.credential_last_check", None),
            credential_last_result=self.settings.get("remote.credential_last_result", None),
            credential_command_status=self.settings.get("remote.credential_command_status", "Unavailable"),
            credential_last_operation=self.settings.get("remote.credential_last_operation", None),
            credential_operation_result=self.settings.get("remote.credential_operation_result", None),
            credential_duration_ms=self.settings.get("remote.credential_duration_ms", 0),
            credential_error_suggestion=self.settings.get("remote.credential_error_suggestion", None),
            last_storage_error=self.settings.get("remote.last_storage_error", None),
            credential_history=self.settings.get("remote.credential_history", []),
            credential_steps=self.settings.get("remote.credential_steps", []),
            network_history=self.settings.get("remote.network_history", []),
            security_history=self.settings.get("remote.security_history", []),
            authentication_history=self.settings.get("remote.authentication_history", []),
            remote_history=self.settings.get("remote.remote_history", []),
            lan_status_page_enabled=self.settings.get("remote.lan_status_page_enabled", False),
            lan_status_port=self.settings.get("remote.lan_status_port", self.default_lan_status_port),
            lan_status_user_confirmed=self.settings.get("remote.lan_status_user_confirmed", False),
            lan_chat_enabled=self.settings.get("remote.lan_chat_enabled", False),
            lan_chat_port=self.settings.get("remote.lan_chat_port", self.default_lan_status_port),
            mobile_access_confirmed=self.settings.get("remote.mobile_access_confirmed", False),
            mobile_chat_timeout=self.settings.get("mobile_chat_timeout", 60),
            mobile_debug_mode=self.settings.get("mobile_debug_mode", False),
            mobile_response_limit=self.settings.get("mobile_response_limit", 12000),
            selected_lan_ip=self.settings.get("remote.selected_lan_ip", ""),
            selected_adapter=self.settings.get("remote.selected_adapter", ""),
            last_mobile_error=self.settings.get("remote.last_mobile_error", ""),
            last_mobile_stage=self.settings.get("remote.last_mobile_stage", ""),
            last_mobile_status=self.settings.get("remote.last_mobile_status", ""),
            last_mobile_duration_ms=self.settings.get("remote.last_mobile_duration_ms", 0),
            last_mobile_model=self.settings.get("remote.last_mobile_model", ""),
            last_mobile_capability=self.settings.get("remote.last_mobile_capability", ""),
            last_mobile_ollama_url=self.settings.get("remote.last_mobile_ollama_url", ""),
            last_mobile_client=self.settings.get("remote.last_mobile_client", ""),
            last_mobile_time=self.settings.get("remote.last_mobile_time", ""),
            authentication_configured=self.settings.get("remote.authentication_configured", False),
            lan_ready=self.settings.get("remote.lan_ready", False),
            ios_access_ready=self.settings.get("remote.ios_access_ready", False),
            tailscale_ready=self.settings.get("remote.tailscale_ready", False),
            user_confirmed=self.settings.get("remote.user_confirmed", False),
            security_confirmed=self.settings.get("remote.security_confirmed", False)
        )

    def _build(self):
        ctk.CTkLabel(self, text=self.ui_text("remote_access"), font=FONT_TITLE).pack(
            anchor="w", padx=SPACING_LARGE, pady=(SPACING_LARGE, SPACING_MEDIUM)
        )
        self.status_label = StatusLabel(self, status="disabled", text=self.ui_text("checking"), anchor="w", justify="left")
        self.status_label.pack(anchor="w", padx=SPACING_LARGE, pady=(0, SPACING_MEDIUM))

        self.content = ctk.CTkScrollableFrame(self)
        self.content.pack(fill="both", expand=True, padx=SPACING_LARGE, pady=(0, SPACING_MEDIUM))

        self._add_status_card(self.ui_text("remote_access"), [
            ("remote_status", self.ui_text("remote_status")),
            ("mode", self.ui_text("remote_mode")),
            ("local_address", self.ui_text("local_address")),
            ("lan_address", self.ui_text("lan_address")),
            ("selected_adapter", self.ui_text("selected_network_adapter")),
            ("selected_lan_ip", self.ui_text("selected_lan_ip")),
            ("network_available", self.ui_text("network_available")),
            ("listening_ports", self.ui_text("listening_ports")),
        ])
        self._add_status_card(self.ui_text("safety_gate"), [
            ("gate_network", self.ui_text("network")),
            ("gate_lan", self.ui_text("lan")),
            ("gate_auth_required", self.ui_text("required")),
            ("gate_auth_configured", self.ui_text("configured")),
            ("gate_security_confirmed", self.ui_text("security_confirmation")),
            ("gate_overall", self.ui_text("overall")),
            ("remote_safety_status", self.ui_text("remote_safety_status")),
        ])
        self._add_status_card(self.ui_text("lan_chat"), [
            ("lan_status_state", self.ui_text("lan_status_page")),
            ("lan_status_local_url", self.ui_text("local_url")),
            ("lan_status_lan_url", self.ui_text("lan_url")),
            ("lan_chat_state", self.ui_text("status")),
            ("lan_chat_url", self.ui_text("mobile_url")),
            ("lan_chat_confirmation", self.ui_text("mobile_access_confirmation")),
        ])
        self._add_status_card(self.ui_text("authentication"), [
            ("auth_required_detail", self.ui_text("authentication_required")),
            ("auth_status_detail", self.ui_text("authentication_status")),
            ("auth_type_detail", self.ui_text("authentication_type")),
            ("token_status_detail", self.ui_text("token_status")),
            ("credential_storage_status", self.ui_text("credential_storage")),
            ("credential_provider_status", self.ui_text("provider")),
            ("credential_test_status", self.ui_text("test_status")),
            ("credential_last_check", self.ui_text("last_check_time")),
        ])
        self._add_status_card(self.ui_text("remote_health"), [
            ("health_network", self.ui_text("network")),
            ("health_local_access", self.ui_text("local_access")),
            ("health_lan_access", self.ui_text("lan_access")),
            ("health_lan_readiness", self.ui_text("lan_readiness")),
            ("health_ios_access", self.ui_text("ios_access")),
            ("health_cellular_access", self.ui_text("cellular_access")),
            ("health_security", self.ui_text("security")),
        ])
        self._add_status_card(self.ui_text("mobile_debug_panel"), [
            ("mobile_debug_client", self.ui_text("client")),
            ("mobile_debug_stage", self.ui_text("stage")),
            ("mobile_debug_status", self.ui_text("status")),
            ("mobile_debug_duration", self.ui_text("duration")),
            ("mobile_debug_model", self.ui_text("model_name")),
            ("mobile_debug_capability", self.ui_text("model_capability")),
            ("mobile_debug_ollama_url", self.ui_text("ollama_url")),
            ("mobile_debug_error", self.ui_text("error")),
        ])
        self._add_text_card(self.ui_text("lan_access_preparation"), "checklist", 120)
        self._add_text_card(self.ui_text("credential_storage_diagnostics"), "credential_steps", 120)
        self._add_text_card(self.ui_text("credential_history"), "credential_history", 140)
        self._add_hint()
        self._add_footer()

    def _add_status_card(self, title, specs):
        card = SectionCard(self.content, title)
        card.pack(fill="x", pady=(0, SPACING_MEDIUM))
        for key, label in specs:
            row = FormRow(card.body, label)
            row.pack(fill="x", pady=SPACING_SMALL)
            value = StatusLabel(row.control_frame, status="disabled", text="--")
            value.pack(side="left")
            self.rows[key] = value

    def _add_text_card(self, title, key, height):
        card = SectionCard(self.content, title)
        card.pack(fill="x", pady=(0, SPACING_MEDIUM))
        box = ctk.CTkTextbox(card.body, height=height, wrap="word", font=FONT_BODY)
        box.pack(fill="x")
        box.configure(state="disabled")
        self.text_boxes[key] = box

    def _add_hint(self):
        card = SectionCard(self.content, self.ui_text("security_status"))
        card.pack(fill="x", pady=(0, SPACING_MEDIUM))
        box = ctk.CTkTextbox(card.body, height=150, wrap="word", font=FONT_BODY)
        box.pack(fill="x")
        box.insert(
            "1.0",
            (
                f"{self.ui_text('do_not_expose_warning')}\n\n"
                f"{self.ui_text('auth_required_hint')}\n\n"
                f"{self.ui_text('local_only_description')}\n"
                f"{self.ui_text('lan_only_description')}\n"
                f"{self.ui_text('secure_remote_description')}\n\n"
                f"{self.ui_text('authentication_not_configured_hint')}"
            )
        )
        box.configure(state="disabled")

    def _add_footer(self):
        footer = FixedFooter(self)
        footer.pack(fill="x", padx=SPACING_LARGE, pady=(0, SPACING_LARGE))
        buttons = [
            (SecondaryButton, self.ui_text("understand_risk"), self.confirm_remote_security),
            (SecondaryButton, self.ui_text("setup_token"), self.setup_token_placeholder),
            (SecondaryButton, self.ui_text("test_secure_storage"), self.test_secure_storage),
            (DangerButton, self.ui_text("remove_test_credential"), self.remove_test_credential),
            (PrimaryButton, self.ui_text("start_lan_status_page"), self.start_lan_status_page),
            (SecondaryButton, self.ui_text("stop_lan_status_page"), self.stop_lan_status_page),
            (SecondaryButton, self.ui_text("copy_lan_url"), self.copy_lan_url),
            (PrimaryButton, self.ui_text("start_lan_chat"), self.start_lan_chat),
            (SecondaryButton, self.ui_text("stop_lan_chat"), self.stop_lan_chat),
            (SecondaryButton, self.ui_text("copy_mobile_url"), self.copy_mobile_url),
            (SecondaryButton, self.ui_text("refresh"), self.refresh_remote_status),
            (SecondaryButton, self.ui_text("close"), self.close),
        ]
        for index, (button_class, text, command) in enumerate(buttons):
            button = button_class(footer.buttons, text=text, command=command)
            button.grid(row=index // 3, column=index % 3, sticky="ew", padx=SPACING_SMALL, pady=SPACING_SMALL)
        for column in range(3):
            footer.buttons.grid_columnconfigure(column, weight=1)

    def _set_row(self, key, text, status=None):
        if key in self.rows:
            self.rows[key].set_status(status or text, text=text)

    def _set_box(self, key, text):
        box = self.text_boxes.get(key)
        if not box:
            return
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text or "--")
        box.configure(state="disabled")

    def update_remote_rows(self, status):
        config = status.get("config", {})
        network = status.get("network", {})
        security = status.get("security", {})
        health = status.get("health", {})
        safety_gate = status.get("safety_gate", {})
        readiness = safety_gate.get("readiness", {})
        auth = status.get("authentication", {})
        lan_status = status.get("lan_status", {})
        lan_chat = status.get("lan_chat", {})
        mobile_debug = status.get("mobile_debug", {})
        checklist = status.get("lan_checklist", [])

        self._set_row("remote_status", self.ui_text("enabled") if config.get("enabled") else self.ui_text("disabled"))
        self._set_row("mode", config.get("mode", "local"))
        self._set_row("local_address", network.get("local_address", "127.0.0.1"))
        self._set_row("lan_address", network.get("lan_address", self.ui_text("unavailable")))
        self._set_row("selected_adapter", network.get("selected_adapter", self.ui_text("unavailable")))
        self._set_row("selected_lan_ip", network.get("selected_lan_ip") or self.ui_text("unavailable"))
        self._set_row("network_available", self.ui_text("yes") if network.get("network_available") else self.ui_text("no"))
        ports = security.get("listening_ports", [])
        self._set_row("listening_ports", ", ".join(str(port.get("port")) for port in ports) if ports else self.ui_text("none"))

        checks = safety_gate.get("checks", {})
        self._set_row("gate_network", self.ui_text("ready") if checks.get("network") else self.ui_text("missing"))
        self._set_row("gate_lan", self.ui_text("ready") if checks.get("lan") else self.ui_text("missing"))
        self._set_row("gate_auth_required", self.ui_text("ready") if checks.get("authentication_required") else self.ui_text("missing"))
        self._set_row("gate_auth_configured", self.ui_text("ready") if checks.get("authentication_configured") else self.ui_text("missing"))
        self._set_row("gate_security_confirmed", self.ui_text("yes") if checks.get("security_confirmed") else self.ui_text("no"))
        self._set_row("gate_overall", readiness.get("overall", "Blocked"))
        self._set_row("remote_safety_status", safety_gate.get("blocked_reason") or self.ui_text("ready"))

        lan_urls = lan_status.get("urls", self.remote_manager.lan_status_urls())
        chat_urls = lan_chat.get("urls", self.remote_manager.lan_chat_urls())
        self._set_row("lan_status_state", self.ui_text("running") if lan_status.get("enabled") else self.ui_text("stopped"))
        self._set_row("lan_status_local_url", lan_urls.get("local_url", "--"))
        self._set_row("lan_status_lan_url", lan_urls.get("lan_url", "--"))
        self._set_row("lan_chat_state", self.ui_text("running") if lan_chat.get("enabled") else self.ui_text("stopped"))
        self._set_row("lan_chat_url", chat_urls.get("mobile_url", "--"))
        self._set_row("lan_chat_confirmation", self.ui_text("yes") if lan_chat.get("mobile_access_confirmed") else self.ui_text("no"))

        self._set_row("auth_required_detail", self.ui_text("yes") if config.get("auth_required", True) else self.ui_text("no"))
        self._set_row("auth_status_detail", self.ui_text("ready") if auth.get("configured") else self.ui_text("missing"))
        self._set_row("auth_type_detail", self.ui_text("token_authentication") if auth.get("authentication_type") == "token" else self.ui_text("none"))
        self._set_row("token_status_detail", self.ui_text("configured") if auth.get("token_configured") else self.ui_text("not_configured"))
        self._set_row("credential_storage_status", self.ui_text("available_status") if auth.get("secure_storage_available") else self.ui_text("unavailable_status"))
        self._set_row("credential_provider_status", self.ui_text("windows_credential_manager"))
        self._set_row("credential_test_status", self.ui_text("passed") if auth.get("credential_test_passed") else self.ui_text("failed"))
        self._set_row("credential_last_check", auth.get("credential_last_check") or "--")

        for key in ("network", "local_access", "lan_access", "lan_readiness", "ios_access", "cellular_access", "security"):
            self._set_row(f"health_{key}", health.get(key, "--"))

        self._set_row("mobile_debug_client", mobile_debug.get("client") or "--")
        self._set_row("mobile_debug_stage", mobile_debug.get("stage") or "--")
        self._set_row("mobile_debug_status", mobile_debug.get("status") or "--")
        self._set_row("mobile_debug_duration", f"{mobile_debug.get('duration_ms', 0)}ms")
        self._set_row("mobile_debug_model", mobile_debug.get("model") or "--")
        self._set_row("mobile_debug_capability", mobile_debug.get("capability") or "--")
        self._set_row("mobile_debug_ollama_url", mobile_debug.get("ollama_url") or "--")
        self._set_row("mobile_debug_error", mobile_debug.get("error") or self.ui_text("none"))

        checklist_lines = [
            f"{item.get('label', '--')}: {self.ui_text('status_ok_short') if item.get('ok') else self.ui_text('missing')}"
            for item in checklist
        ]
        self._set_box("checklist", "\n".join(checklist_lines))
        credential_steps = auth.get("credential_steps", [])
        self._set_box("credential_steps", "\n".join(
            f"{item.get('step', '--')}: {item.get('result', '--')} {item.get('message', '')}".strip()
            for item in credential_steps
        ))
        history = auth.get("credential_history", [])
        self._set_box("credential_history", "\n".join(
            f"{item.get('time', '--')} | {item.get('status', '--')} | {item.get('result', '--')}"
            for item in history
        ) or self.ui_text("no_history"))

        self.logger.info("Remote status checked")
        self.logger.info("Remote security checked")
        self.logger.info("Remote health checked")
        self.logger.info("Remote mode displayed")
        self.logger.info("Remote authentication status checked")

    def refresh_remote_status(self):
        self.status_label.set_status("disabled", self.ui_text("checking"))

        def run_check():
            try:
                provider_status = self.credential_storage_provider.check_available()
                remote_config = self.remote_manager.update_credential_diagnostics(provider_status)
                self.settings.set("remote.credential_storage", "windows_credential_manager")
                self.settings.set("remote.secure_storage_available", provider_status.get("available", False))
                self.settings.set("remote.credential_last_check", provider_status.get("last_check"))
                self.settings.set("remote.credential_last_result", provider_status.get("last_result"))
                self.settings.set("remote.credential_command_status", provider_status.get("command_status", "Unavailable"))
                self.settings.set("remote.credential_last_operation", provider_status.get("last_operation"))
                self.settings.set("remote.credential_operation_result", provider_status.get("operation_result"))
                self.settings.set("remote.credential_duration_ms", provider_status.get("duration_ms", 0))
                self.settings.set("remote.credential_error_suggestion", provider_status.get("suggestion"))
                self.settings.set("remote.last_storage_error", provider_status.get("last_error"))
                self.settings.set("remote.credential_history", remote_config.get("credential_history", []))
                self.settings.set("remote.credential_steps", provider_status.get("steps", []))
                remote_config = self.remote_manager.record_diagnostic_history()
                self.settings.set("remote.network_history", remote_config.get("network_history", []))
                self.settings.set("remote.security_history", remote_config.get("security_history", []))
                self.settings.set("remote.authentication_history", remote_config.get("authentication_history", []))
                self.settings.set("remote.remote_history", remote_config.get("remote_history", []))
                status = self.remote_manager.assessment()
                status["config"] = self.remote_manager.load()
                status["authentication"] = self.remote_manager.authentication_status()
                error_message = None
            except Exception as error:
                status = None
                error_message = str(error)

            def finish_check():
                if not self.winfo_exists():
                    return
                if error_message:
                    self.status_label.set_status("error", error_message)
                    self.logger.error(f"Remote status check failed: {error_message}")
                    return
                self.update_remote_rows(status)
                self.status_label.set_status("healthy", self.ui_text("ready"))

            try:
                self.after(0, finish_check)
            except Exception:
                return

        threading.Thread(target=run_check, daemon=True).start()

    def confirm_remote_security(self):
        self.logger.info("Remote safety check started")

        def run_confirm():
            try:
                self.remote_manager.confirm_security()
                self.settings.set("remote.security_confirmed", True)
                self.settings.set("remote.user_confirmed", True)
                error_message = None
            except Exception as error:
                error_message = str(error)

            def finish_confirm():
                if not self.winfo_exists():
                    return
                if error_message:
                    self.status_label.set_status("error", error_message)
                    self.logger.error(f"Remote security confirmation failed: {error_message}")
                    return
                self.status_label.set_status("healthy", self.ui_text("remote_safety_check"))
                self.logger.info("Remote security confirmation updated")
                self.refresh_remote_status()

            try:
                self.after(0, finish_confirm)
            except Exception:
                return

        threading.Thread(target=run_confirm, daemon=True).start()

    def setup_token_placeholder(self):
        def run_setup():
            try:
                self.authentication_manager.setup_token_placeholder(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                error_message = None
            except Exception as error:
                error_message = str(error)

            def finish_setup():
                if not self.winfo_exists():
                    return
                if error_message:
                    self.status_label.set_status("error", error_message)
                    self.logger.error(f"Token setup failed: {error_message}")
                    return
                self.status_label.set_status("healthy", self.ui_text("token_setup_note"))
                self.logger.info("Token status checked")
                self.logger.info("Token readiness checked")
                self.refresh_remote_status()

            try:
                self.after(0, finish_setup)
            except Exception:
                return

        threading.Thread(target=run_setup, daemon=True).start()

    def test_secure_storage(self):
        self.logger.info("Credential storage provider checked")

        def run_test():
            try:
                result = self.credential_storage_provider.run_test()
                remote_config = self.remote_manager.update_credential_diagnostics(result)
                self.settings.set("remote.credential_storage", "windows_credential_manager")
                self.settings.set("remote.secure_storage_available", result.get("available", False))
                self.settings.set("remote.credential_test_passed", result.get("test_passed", False))
                self.settings.set("remote.credential_last_check", result.get("last_check"))
                self.settings.set("remote.credential_last_result", result.get("last_result"))
                self.settings.set("remote.credential_command_status", result.get("command_status", "Unavailable"))
                self.settings.set("remote.credential_last_operation", result.get("last_operation"))
                self.settings.set("remote.credential_operation_result", result.get("operation_result"))
                self.settings.set("remote.credential_duration_ms", result.get("duration_ms", 0))
                self.settings.set("remote.credential_error_suggestion", result.get("suggestion"))
                self.settings.set("remote.last_storage_error", result.get("last_error"))
                self.settings.set("remote.credential_history", remote_config.get("credential_history", []))
                self.settings.set("remote.credential_steps", result.get("steps", []))
                remote_config = self.remote_manager.record_diagnostic_history()
                self.settings.set("remote.network_history", remote_config.get("network_history", []))
                self.settings.set("remote.security_history", remote_config.get("security_history", []))
                self.settings.set("remote.authentication_history", remote_config.get("authentication_history", []))
                self.settings.set("remote.remote_history", remote_config.get("remote_history", []))
                error_message = None
            except Exception as error:
                result = {"test_passed": False, "message": str(error)}
                error_message = str(error)

            def finish_test():
                if not self.winfo_exists():
                    return
                if result.get("test_passed"):
                    self.status_label.set_status("healthy", self.ui_text("passed"))
                    self.logger.info("Test credential created")
                    self.logger.info("Test credential removed")
                    self.logger.info("Credential storage test passed")
                else:
                    self.status_label.set_status("error", result.get("message", self.ui_text("failed")))
                    self.logger.info("Credential storage test failed")
                    if error_message:
                        self.logger.error(f"Credential storage test failed: {error_message}")
                self.refresh_remote_status()

            try:
                self.after(0, finish_test)
            except Exception:
                return

        threading.Thread(target=run_test, daemon=True).start()

    def remove_test_credential(self):
        self.logger.info("Credential storage provider checked")

        def run_remove():
            try:
                result = self.credential_storage_provider.delete_test_credential()
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
                remote_config = self.remote_manager.update_credential_diagnostics(diagnostic_result)
                self.settings.set("remote.credential_test_passed", False)
                self.settings.set("remote.credential_last_check", result.get("last_check"))
                self.settings.set("remote.credential_last_result", result.get("status"))
                self.settings.set("remote.credential_command_status", "Available")
                self.settings.set("remote.credential_last_operation", "Delete Test Credential")
                self.settings.set("remote.credential_operation_result", "Success" if result.get("removed") else "Failed")
                self.settings.set("remote.credential_duration_ms", result.get("duration_ms", 0))
                self.settings.set("remote.credential_error_suggestion", result.get("suggestion"))
                self.settings.set("remote.last_storage_error", result.get("last_error"))
                self.settings.set("remote.credential_history", remote_config.get("credential_history", []))
                self.settings.set("remote.credential_steps", diagnostic_result.get("steps", []))
                error_message = None
            except Exception as error:
                result = {"removed": False, "message": str(error)}
                error_message = str(error)

            def finish_remove():
                if not self.winfo_exists():
                    return
                if result.get("removed"):
                    self.status_label.set_status("healthy", self.ui_text("remove_test_credential"))
                    self.logger.info("Test credential removed")
                else:
                    self.status_label.set_status("error", result.get("message", self.ui_text("failed")))
                    if error_message:
                        self.logger.error(f"Test credential removal failed: {error_message}")
                self.refresh_remote_status()

            try:
                self.after(0, finish_remove)
            except Exception:
                return

        threading.Thread(target=run_remove, daemon=True).start()

    def start_lan_status_page(self):
        start_check = self.remote_manager.lan_status_start_check()
        if not start_check.get("user_confirmed"):
            if not messagebox.askyesno(self.ui_text("lan_status_page"), self.ui_text("lan_status_warning")):
                self.status_label.set_status("error", self.ui_text("blocked"))
                self.logger.info("LAN status page start blocked")
                return
            self.remote_manager.update(lan_status_user_confirmed=True)
            self.settings.set("remote.lan_status_user_confirmed", True)
            start_check = self.remote_manager.lan_status_start_check()
        if not start_check.get("network_available") or not start_check.get("lan_address_available"):
            self.status_label.set_status("error", start_check.get("reason", self.ui_text("not_ready")))
            self.logger.info("LAN status page start blocked")
            return
        self.status_label.set_status("disabled", self.ui_text("checking"))

        def run_start():
            port = self.settings.get("remote.lan_status_port", self.default_lan_status_port)
            result = self.lan_status_server.start("0.0.0.0", port, self.lan_status_snapshot)

            def finish_start():
                if not self.winfo_exists():
                    return
                if result.get("ok"):
                    self.remote_manager.update(
                        lan_status_page_enabled=True,
                        lan_status_port=result.get("port", port),
                        lan_status_user_confirmed=True
                    )
                    self.settings.set("remote.lan_status_page_enabled", True)
                    self.settings.set("remote.lan_status_port", result.get("port", port))
                    self.settings.set("remote.lan_status_user_confirmed", True)
                    self.status_label.set_status("healthy", self.ui_text("running"))
                    self.logger.info("LAN status page started")
                else:
                    self.remote_manager.update(lan_status_page_enabled=False)
                    self.settings.set("remote.lan_status_page_enabled", False)
                    self.status_label.set_status("error", result.get("message", self.ui_text("failed")))
                    self.logger.info("LAN status page start blocked")
                self.refresh_remote_status()

            self.after(0, finish_start)

        threading.Thread(target=run_start, daemon=True).start()

    def stop_lan_status_page(self):
        self.status_label.set_status("disabled", self.ui_text("checking"))

        def run_stop():
            result = self.lan_status_server.stop()

            def finish_stop():
                if not self.winfo_exists():
                    return
                self.remote_manager.update(enabled=False, lan_status_page_enabled=False, lan_chat_enabled=False)
                self.settings.set("remote.enabled", False)
                self.settings.set("remote.lan_status_page_enabled", False)
                self.settings.set("remote.lan_chat_enabled", False)
                self.status_label.set_status("healthy" if result.get("ok") else "error", self.ui_text("stopped") if result.get("ok") else result.get("message", self.ui_text("failed")))
                self.logger.info("LAN status page stopped")
                self.refresh_remote_status()

            self.after(0, finish_stop)

        threading.Thread(target=run_stop, daemon=True).start()

    def copy_lan_url(self):
        lan_url = self.remote_manager.lan_status_urls().get("lan_url", self.ui_text("no_lan_address"))
        self.parent.clipboard_clear()
        self.parent.clipboard_append(lan_url)
        self.status_label.set_status("healthy", self.ui_text("lan_url"))
        self.logger.info("LAN URL copied")

    def start_lan_chat(self):
        start_check = self.remote_manager.lan_chat_start_check()
        if not start_check.get("mobile_access_confirmed"):
            if not messagebox.askyesno(self.ui_text("lan_chat"), self.ui_text("lan_chat_warning")):
                self.status_label.set_status("error", self.ui_text("blocked"))
                self.logger.info("Mobile request blocked")
                return
            self.remote_manager.update(mobile_access_confirmed=True)
            self.settings.set("remote.mobile_access_confirmed", True)
            start_check = self.remote_manager.lan_chat_start_check()
        if not start_check.get("security_confirmed"):
            self.status_label.set_status("error", self.ui_text("security_confirmation_required"))
            self.logger.info("Mobile request blocked")
            return
        if not start_check.get("network_available") or not start_check.get("lan_address_available"):
            self.status_label.set_status("error", start_check.get("reason", self.ui_text("not_ready")))
            self.logger.info("Mobile request blocked")
            return
        self.status_label.set_status("disabled", self.ui_text("checking"))

        def mobile_chat_event(event):
            self.logger.info(event)

        def run_start():
            port = self.settings.get("remote.lan_chat_port", self.settings.get("remote.lan_status_port", self.default_lan_status_port))
            result = self.lan_status_server.start(
                "0.0.0.0",
                port,
                self.lan_status_snapshot,
                mobile_chat_service=self.mobile_chat_service,
                event_callback=mobile_chat_event
            )

            def finish_start():
                if not self.winfo_exists():
                    return
                if result.get("ok"):
                    self.remote_manager.update(
                        enabled=True,
                        lan_status_page_enabled=True,
                        lan_status_port=result.get("port", port),
                        lan_chat_enabled=True,
                        lan_chat_port=result.get("port", port),
                        mobile_access_confirmed=True
                    )
                    self.settings.set("remote.lan_status_page_enabled", True)
                    self.settings.set("remote.enabled", True)
                    self.settings.set("remote.lan_status_port", result.get("port", port))
                    self.settings.set("remote.lan_chat_enabled", True)
                    self.settings.set("remote.lan_chat_port", result.get("port", port))
                    self.settings.set("remote.mobile_access_confirmed", True)
                    self.status_label.set_status("healthy", self.ui_text("mobile_chat_started"))
                    self.logger.info("Mobile chat started")
                else:
                    self.remote_manager.update(lan_chat_enabled=False)
                    self.settings.set("remote.lan_chat_enabled", False)
                    self.status_label.set_status("error", result.get("message", self.ui_text("failed")))
                    self.logger.info("Mobile request blocked")
                self.refresh_remote_status()

            self.after(0, finish_start)

        threading.Thread(target=run_start, daemon=True).start()

    def stop_lan_chat(self):
        self.status_label.set_status("disabled", self.ui_text("checking"))

        def run_stop():
            result = self.lan_status_server.stop()

            def finish_stop():
                if not self.winfo_exists():
                    return
                self.remote_manager.update(enabled=False, lan_status_page_enabled=False, lan_chat_enabled=False)
                self.settings.set("remote.enabled", False)
                self.settings.set("remote.lan_status_page_enabled", False)
                self.settings.set("remote.lan_chat_enabled", False)
                self.status_label.set_status("healthy" if result.get("ok") else "error", self.ui_text("mobile_chat_stopped") if result.get("ok") else result.get("message", self.ui_text("failed")))
                self.logger.info("Mobile chat stopped")
                self.refresh_remote_status()

            self.after(0, finish_stop)

        threading.Thread(target=run_stop, daemon=True).start()

    def copy_mobile_url(self):
        try:
            mobile_url = self.remote_manager.lan_chat_urls().get("mobile_url", self.ui_text("no_lan_address"))
            self.parent.clipboard_clear()
            self.parent.clipboard_append(mobile_url)
            self.status_label.set_status("healthy", self.ui_text("mobile_url"))
            self.logger.info("LAN URL copied")
        except Exception as error:
            self.status_label.set_status("error", self.ui_text("copy_failed"))
            self.logger.error(f"Mobile URL copy failed: {error}")
            self.logger.info("Mobile error handled")

    def close(self):
        if self.on_close:
            self.on_close()
        self.destroy()


class RemoteDiagnosticsWindow(ctk.CTkToplevel):
    """Remote diagnostic information window."""

    def __init__(self, parent, remote_manager, credential_storage_provider, text, logger, project_root, on_close=None):
        super().__init__(parent)
        self.remote_manager = remote_manager
        self.credential_storage_provider = credential_storage_provider
        self.TEXT = {**remote_text_defaults(), **localized_text(text)}
        self.logger = logger
        self.project_root = Path(project_root)
        self.on_close = on_close
        self.rows = {}
        self.text_boxes = {}

        self.title(self.ui_text("remote_diagnostics"))
        self.geometry("760x680")
        self.minsize(620, 520)
        self.transient(parent)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh_remote_diagnostics()

    def _build(self):
        ctk.CTkLabel(self, text=self.ui_text("remote_diagnostics"), font=FONT_TITLE).pack(
            anchor="w", padx=SPACING_LARGE, pady=(SPACING_LARGE, SPACING_MEDIUM)
        )
        self.status_label = StatusLabel(self, status="disabled", text=self.ui_text("checking"), anchor="w", justify="left")
        self.status_label.pack(anchor="w", padx=SPACING_LARGE, pady=(0, SPACING_MEDIUM))
        content = ctk.CTkScrollableFrame(self)
        content.pack(fill="both", expand=True, padx=SPACING_LARGE, pady=(0, SPACING_MEDIUM))

        self._add_status_card(content, self.ui_text("remote_readiness_summary"), [
            ("summary_network", self.ui_text("network")),
            ("summary_security", self.ui_text("security")),
            ("summary_authentication", self.ui_text("authentication")),
            ("summary_credential", self.ui_text("credential_storage")),
        ])
        self._add_status_card(content, self.ui_text("credential_storage_details"), [
            ("authentication_status_row", self.ui_text("authentication")),
            ("credential_status_row", self.ui_text("credential_storage")),
            ("credential_operation", self.ui_text("last_operation")),
            ("credential_operation_result", self.ui_text("operation_result")),
            ("credential_duration", self.ui_text("duration")),
            ("credential_error", self.ui_text("error_reason")),
            ("credential_suggestion", self.ui_text("suggestion")),
        ])
        self._add_text_card(content, "authentication_history", self.ui_text("authentication_history"), 120)
        self._add_text_card(content, "credential_history", self.ui_text("credential_history"), 120)
        self._add_text_card(content, "remote_history", self.ui_text("remote_history"), 120)
        self._add_text_card(content, "release_check", self.ui_text("release_check"), 130)

        footer = FixedFooter(self)
        footer.pack(fill="x", padx=SPACING_LARGE, pady=(0, SPACING_LARGE))
        SecondaryButton(footer.buttons, text=self.ui_text("refresh"), command=self.refresh_remote_diagnostics).pack(side="left", expand=True, fill="x", padx=(0, SPACING_SMALL))
        PrimaryButton(footer.buttons, text=self.ui_text("release_check"), command=self.run_release_check).pack(side="left", expand=True, fill="x", padx=SPACING_SMALL)
        SecondaryButton(footer.buttons, text=self.ui_text("close"), command=self.close).pack(side="left", expand=True, fill="x", padx=(SPACING_SMALL, 0))

    def _add_status_card(self, parent, title, specs):
        card = SectionCard(parent, title)
        card.pack(fill="x", pady=(0, SPACING_MEDIUM))
        for key, label in specs:
            row = FormRow(card.body, label)
            row.pack(fill="x", pady=SPACING_SMALL)
            value = StatusLabel(row.control_frame, status="disabled", text="--")
            value.pack(side="left")
            self.rows[key] = value

    def _add_text_card(self, parent, key, title, height):
        card = SectionCard(parent, title)
        card.pack(fill="x", pady=(0, SPACING_MEDIUM))
        box = ctk.CTkTextbox(card.body, height=height, wrap="word", font=FONT_SMALL)
        box.pack(fill="x")
        box.configure(state="disabled")
        self.text_boxes[key] = box

    def ui_text(self, key):
        locale_key = REMOTE_TEXT_DEFAULT_KEYS.get(key, key)
        value = translate_text(locale_key)
        if value != locale_key:
            return value
        return dict.get(self.TEXT, key, key)

    def _set_row(self, key, text, status=None):
        if key in self.rows:
            self.rows[key].set_status(status or text, text=text)

    def _set_box(self, key, text):
        box = self.text_boxes.get(key)
        if not box:
            return
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text or "--")
        box.configure(state="disabled")

    def _history_text(self, values):
        if not values:
            return self.ui_text("no_history")
        return "\n".join(
            f"{item.get('time', '--')} | {item.get('status', '--')} | {item.get('result', '--')}"
            for item in values
        )

    def update_rows(self, data):
        summary = data.get("summary", {})
        auth = data.get("authentication", {})
        config = data.get("config", {})
        self._set_row("summary_network", self.ui_text("ready") if summary.get("network") == "Ready" else self.ui_text("missing"))
        self._set_row("summary_security", self.ui_text("ready") if summary.get("security") == "Ready" else self.ui_text("missing"))
        self._set_row("summary_authentication", self.ui_text("ready") if summary.get("authentication") == "Ready" else self.ui_text("missing"))
        self._set_row("summary_credential", self.ui_text("available_status") if summary.get("credential_storage") == "Available" else self.ui_text("storage_missing"))
        self._set_row("authentication_status_row", self.ui_text("ready") if auth.get("configured") else self.ui_text("missing"))
        self._set_row("credential_status_row", self.ui_text("available_status") if auth.get("secure_storage_available") else self.ui_text("storage_missing"))
        self._set_row("credential_operation", auth.get("credential_last_operation") or "--")
        self._set_row("credential_operation_result", auth.get("credential_operation_result") or "--")
        self._set_row("credential_duration", f"{auth.get('credential_duration_ms', 0)}ms")
        self._set_row("credential_error", auth.get("last_storage_error") or self.ui_text("none"))
        self._set_row("credential_suggestion", auth.get("credential_error_suggestion") or self.ui_text("none"))
        self._set_box("authentication_history", self._history_text(config.get("authentication_history", [])))
        self._set_box("credential_history", self._history_text(config.get("credential_history", [])))
        self._set_box("remote_history", self._history_text(config.get("remote_history", [])))

    def refresh_remote_diagnostics(self):
        self.status_label.set_status("disabled", self.ui_text("checking"))

        def run_refresh():
            try:
                provider_status = self.credential_storage_provider.check_available()
                self.remote_manager.update_credential_diagnostics(provider_status)
                self.remote_manager.record_diagnostic_history()
                data = self.remote_manager.diagnostics()
                error_message = None
            except Exception as error:
                data = None
                error_message = str(error)

            def finish_refresh():
                if not self.winfo_exists():
                    return
                if error_message:
                    self.status_label.set_status("error", error_message)
                    self.logger.error(f"Remote diagnostics refresh failed: {error_message}")
                    return
                self.update_rows(data)
                self.status_label.set_status("healthy", self.ui_text("ready"))

            self.after(0, finish_refresh)

        threading.Thread(target=run_refresh, daemon=True).start()

    def run_release_check(self):
        self.status_label.set_status("disabled", self.ui_text("checking"))

        def run_check():
            try:
                result = self.remote_manager.release_check(self.project_root)
                lines = [
                    f"{item.get('label', '--')}: {self.ui_text('passed') if item.get('ok') else self.ui_text('failed')}"
                    for item in result.get("checks", [])
                ]
                lines.append("")
                lines.append(f"{self.ui_text('passed')}: {result.get('passed')}")
                error_message = None
            except Exception as error:
                lines = []
                error_message = str(error)

            def finish_check():
                if not self.winfo_exists():
                    return
                if error_message:
                    self.status_label.set_status("error", error_message)
                    self.logger.error(f"Remote release check failed: {error_message}")
                    return
                self._set_box("release_check", "\n".join(lines))
                self.status_label.set_status("healthy", self.ui_text("ready"))

            self.after(0, finish_check)

        threading.Thread(target=run_check, daemon=True).start()

    def close(self):
        if self.on_close:
            self.on_close()
        self.destroy()

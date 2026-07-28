import customtkinter as ctk

from modules.ui_theme import (
    FORM_LABEL_WRAP,
    FONT_HEADER,
    FONT_NORMAL,
    FONT_SMALL,
    SPACING_MEDIUM,
    SPACING_SMALL,
    status_color
)
from widgets.ui_components import PrimaryButton, SectionCard, SecondaryButton, StatusLabel


class RemotePage(ctk.CTkFrame):
    """AppShell remote page wrapper that reuses the existing RemoteWindow."""

    ADVANCED_ITEMS = [
        ("remote_page_pairing", "remote"),
        ("remote_page_diagnostics", "diagnostics"),
        ("remote_page_credential_test", "remote"),
        ("remote_page_release_check", "diagnostics")
    ]

    def __init__(
        self,
        parent,
        *,
        translate,
        open_remote_callback=None,
        open_diagnostics_callback=None,
        remote_status_provider=None,
        logger=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.t = translate
        self.open_remote_callback = open_remote_callback
        self.open_diagnostics_callback = open_diagnostics_callback
        self.remote_status_provider = remote_status_provider
        self.logger = logger
        self.advanced_visible = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build()
        self.refresh()

    def _build(self):
        self._build_header()
        self._build_summary_grid()
        self._build_action_area()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_MEDIUM))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=self.t("remote_page_title"),
            font=FONT_HEADER,
            anchor="w"
        ).grid(row=0, column=0, sticky="w")

        self.remote_status = StatusLabel(
            header,
            status="disabled",
            text=self.t("remote_page_status_unknown"),
            anchor="e"
        )
        self.remote_status.grid(row=0, column=1, sticky="e")

    def _build_summary_grid(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure((0, 1), weight=1)

        self.status_card = SectionCard(body, self.t("remote_page_status"))
        self.status_card.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING_MEDIUM), pady=(0, SPACING_MEDIUM))

        ctk.CTkLabel(
            self.status_card.body,
            text=self.t("remote_page_status_detail"),
            font=FONT_NORMAL,
            text_color=status_color("disabled"),
            wraplength=FORM_LABEL_WRAP,
            justify="left",
            anchor="w"
        ).pack(fill="x", pady=(0, SPACING_SMALL))

        self.remote_state_label = self._detail_label(self.status_card.body, "remote_page_remote_state")
        self.authentication_label = self._detail_label(self.status_card.body, "remote_page_authentication_state")
        self.safety_label = self._detail_label(self.status_card.body, "remote_page_safety_state")

        self.devices_card = SectionCard(body, self.t("remote_page_devices"))
        self.devices_card.grid(row=0, column=1, sticky="nsew", padx=(SPACING_MEDIUM, 0), pady=(0, SPACING_MEDIUM))

        ctk.CTkLabel(
            self.devices_card.body,
            text=self.t("remote_page_devices_detail"),
            font=FONT_NORMAL,
            text_color=status_color("disabled"),
            wraplength=FORM_LABEL_WRAP,
            justify="left",
            anchor="w"
        ).pack(fill="x", pady=(0, SPACING_SMALL))

        self.devices_label = self._detail_label(self.devices_card.body, "remote_page_connected_devices")
        SecondaryButton(
            self.devices_card.body,
            text=self.t("remote_page_manage_devices"),
            command=self.open_remote_window
        ).pack(fill="x", pady=SPACING_SMALL)

        self.security_card = SectionCard(body, self.t("remote_page_security"))
        self.security_card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, SPACING_MEDIUM))
        self.security_card.body.grid_columnconfigure((0, 1), weight=1)

        self.security_policy_label = self._grid_detail_label(
            self.security_card.body,
            0,
            0,
            "remote_page_security_policy_state"
        )
        self.access_control_label = self._grid_detail_label(
            self.security_card.body,
            0,
            1,
            "remote_page_access_control_state"
        )

        self.advanced_card = SectionCard(body, self.t("remote_page_advanced"))
        self.advanced_card.body.grid_columnconfigure((0, 1), weight=1)
        for index, (item_key, target) in enumerate(self.ADVANCED_ITEMS):
            SecondaryButton(
                self.advanced_card.body,
                text=self.t(item_key),
                command=lambda value=target: self.open_remote_tool(value)
            ).grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=SPACING_SMALL,
                pady=SPACING_SMALL
            )

    def _build_action_area(self):
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", pady=(SPACING_MEDIUM, 0))
        footer.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            footer,
            text=self.t("remote_page_existing_window_note"),
            font=FONT_SMALL,
            text_color=status_color("disabled"),
            wraplength=FORM_LABEL_WRAP * 2,
            justify="left",
            anchor="w"
        ).grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, SPACING_SMALL))

        PrimaryButton(
            footer,
            text=self.t("remote_page_open_remote_window"),
            command=self.open_remote_window
        ).grid(row=1, column=0, sticky="ew", padx=(0, SPACING_SMALL))

        SecondaryButton(
            footer,
            text=self.t("remote_page_open_diagnostics"),
            command=self.open_diagnostics
        ).grid(row=1, column=1, sticky="ew", padx=SPACING_SMALL)

        SecondaryButton(
            footer,
            text=self.t("remote_page_toggle_advanced"),
            command=self.toggle_advanced
        ).grid(row=1, column=2, sticky="ew", padx=(SPACING_SMALL, 0))

    def _detail_label(self, parent, label_key):
        label = ctk.CTkLabel(
            parent,
            text="",
            font=FONT_NORMAL,
            text_color=status_color("disabled"),
            wraplength=FORM_LABEL_WRAP,
            justify="left",
            anchor="w"
        )
        label.pack(fill="x", pady=SPACING_SMALL)
        label.label_key = label_key
        return label

    def _grid_detail_label(self, parent, row, column, label_key):
        label = ctk.CTkLabel(
            parent,
            text="",
            font=FONT_NORMAL,
            text_color=status_color("disabled"),
            wraplength=FORM_LABEL_WRAP,
            justify="left",
            anchor="w"
        )
        label.grid(row=row, column=column, sticky="ew", padx=SPACING_SMALL, pady=SPACING_SMALL)
        label.label_key = label_key
        return label

    def refresh(self):
        status = {}
        if callable(self.remote_status_provider):
            try:
                status = self.remote_status_provider() or {}
            except Exception as error:
                status = {"status": "error", "text": str(error)}
                if self.logger:
                    self.logger.error(f"Remote page status failed: {error}")

        state = status.get("status", "disabled")
        status_text = status.get("text", self.t("remote_page_status_unknown"))
        self.remote_status.set_status(state, status_text)

        self._set_detail(self.remote_state_label, status.get("remote", status_text))
        self._set_detail(self.authentication_label, status.get("authentication", self.t("remote_page_status_unknown")))
        self._set_detail(self.safety_label, status.get("safety", self.t("remote_page_status_unknown")))
        self._set_detail(self.devices_label, status.get("devices", self.t("remote_page_status_unknown")))
        self._set_detail(self.security_policy_label, status.get("security_policy", self.t("remote_page_status_unknown")))
        self._set_detail(self.access_control_label, status.get("access_control", self.t("remote_page_status_unknown")))

    def open_remote_window(self):
        if callable(self.open_remote_callback):
            self.open_remote_callback()
            if self.logger:
                self.logger.info("Remote page opened existing RemoteWindow")

    def open_diagnostics(self):
        if callable(self.open_diagnostics_callback):
            self.open_diagnostics_callback()
            if self.logger:
                self.logger.info("Remote page opened existing diagnostics window")

    def open_remote_tool(self, target):
        if target == "diagnostics":
            self.open_diagnostics()
            return
        self.open_remote_window()

    def toggle_advanced(self):
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_card.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(SPACING_SMALL, 0))
        else:
            self.advanced_card.grid_forget()

    def _set_detail(self, label, value):
        label.configure(text=f"{self.t(label.label_key)}: {value}")

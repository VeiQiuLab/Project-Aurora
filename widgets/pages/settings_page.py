import customtkinter as ctk

from modules.ui_theme import (
    FORM_CONTROL_WIDTH,
    FORM_LABEL_WRAP,
    FONT_HEADER,
    FONT_NORMAL,
    FONT_SMALL,
    SPACING_LARGE,
    SPACING_MEDIUM,
    SPACING_SMALL,
    status_color
)
from widgets.ui_components import PrimaryButton, SectionCard, SecondaryButton, StatusLabel


class SettingsPage(ctk.CTkFrame):
    """AppShell settings page wrapper that reuses the existing SettingsWindow."""

    CATEGORIES = [
        ("general", "general"),
        ("ai", "ai"),
        ("persona", "persona"),
        ("memory", "memory"),
        ("library", "nav_library"),
        ("remote", "remote"),
        ("developer", "developer")
    ]

    def __init__(
        self,
        parent,
        *,
        translate,
        open_settings_callback=None,
        settings_status_provider=None,
        logger=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.t = translate
        self.open_settings_callback = open_settings_callback
        self.settings_status_provider = settings_status_provider
        self.logger = logger
        self.category_buttons = {}
        self.current_category = "general"

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build()
        self.show_category(self.current_category)

    def _build(self):
        self.sidebar = ctk.CTkFrame(self, width=FORM_CONTROL_WIDTH)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, SPACING_MEDIUM))
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(
            self.sidebar,
            text=self.t("settings"),
            font=FONT_HEADER,
            anchor="w"
        ).pack(fill="x", padx=SPACING_MEDIUM, pady=(SPACING_LARGE, SPACING_MEDIUM))

        for category_id, label_key in self.CATEGORIES:
            button = SecondaryButton(
                self.sidebar,
                text=self.t(label_key),
                command=lambda value=category_id: self.show_category(value),
                anchor="w"
            )
            button.pack(fill="x", padx=SPACING_SMALL, pady=SPACING_SMALL)
            self.category_buttons[category_id] = button

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)

        self.summary_card = SectionCard(self.content, self.t("settings"))
        self.summary_card.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_MEDIUM))

        self.category_title = ctk.CTkLabel(
            self.summary_card.body,
            text="",
            font=FONT_HEADER,
            anchor="w"
        )
        self.category_title.pack(fill="x", pady=(0, SPACING_SMALL))

        self.category_description = ctk.CTkLabel(
            self.summary_card.body,
            text="",
            font=FONT_NORMAL,
            text_color=status_color("disabled"),
            wraplength=FORM_LABEL_WRAP * 2,
            justify="left",
            anchor="w"
        )
        self.category_description.pack(fill="x")

        self.status_card = SectionCard(self.content, self.t("settings_page_existing_editor"))
        self.status_card.grid(row=1, column=0, sticky="ew", pady=(0, SPACING_MEDIUM))

        self.status_label = StatusLabel(
            self.status_card.body,
            status="disabled",
            text=self.t("settings_page_reuse_note"),
            anchor="w",
            justify="left",
            wraplength=FORM_LABEL_WRAP * 2
        )
        self.status_label.pack(fill="x", pady=(0, SPACING_MEDIUM))

        PrimaryButton(
            self.status_card.body,
            text=self.t("settings_page_open_editor"),
            command=self.open_settings_editor
        ).pack(fill="x", pady=SPACING_SMALL)

        self.footer_note = ctk.CTkLabel(
            self.status_card.body,
            text=self.t("settings_page_footer_note"),
            font=FONT_SMALL,
            text_color=status_color("disabled"),
            wraplength=FORM_LABEL_WRAP * 2,
            justify="left",
            anchor="w"
        )
        self.footer_note.pack(fill="x", pady=(SPACING_MEDIUM, 0))

    def show_category(self, category_id):
        self.current_category = category_id
        title_key = dict(self.CATEGORIES).get(category_id, "settings")
        self.category_title.configure(text=self.t(title_key))
        self.category_description.configure(text=self.t(f"settings_page_{category_id}_summary"))
        self._refresh_category_buttons()
        self.refresh_status()

        if self.logger:
            self.logger.info(f"Settings page category selected: {category_id}")

    def refresh_status(self):
        if callable(self.settings_status_provider):
            try:
                status = self.settings_status_provider()
            except Exception as error:
                self.status_label.set_status("error", str(error))
                return
            if isinstance(status, dict):
                self.status_label.set_status(
                    status.get("status", "disabled"),
                    status.get("text", self.t("settings_page_reuse_note"))
                )
                return
        self.status_label.set_status("disabled", self.t("settings_page_reuse_note"))

    def open_settings_editor(self):
        if callable(self.open_settings_callback):
            self.open_settings_callback()
            if self.logger:
                self.logger.info("Settings page opened existing SettingsWindow")

    def _refresh_category_buttons(self):
        for category_id, button in self.category_buttons.items():
            button.configure(font=FONT_HEADER if category_id == self.current_category else FONT_NORMAL)

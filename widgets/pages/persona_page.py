import customtkinter as ctk

from modules.ui_theme import (
    FONT_HEADER,
    FONT_NORMAL,
    FONT_SMALL,
    SPACING_MEDIUM,
    SPACING_SMALL,
    status_color
)
from widgets.ui_components import DangerButton, PrimaryButton, SectionCard, SecondaryButton, StatusLabel


class PersonaPage(ctk.CTkFrame):
    """AppShell persona page wrapper that reuses the existing PersonaWindow."""

    ADVANCED_ITEMS = [
        ("persona_page_prompt_preview", SecondaryButton),
        ("persona_page_reset_persona", DangerButton),
        ("persona_page_export_persona", SecondaryButton)
    ]

    def __init__(
        self,
        parent,
        *,
        translate,
        open_persona_callback=None,
        persona_status_provider=None,
        logger=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.t = translate
        self.open_persona_callback = open_persona_callback
        self.persona_status_provider = persona_status_provider
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
            text=self.t("persona_page_title"),
            font=FONT_HEADER,
            anchor="w"
        ).grid(row=0, column=0, sticky="w")

        self.persona_status = StatusLabel(
            header,
            status="disabled",
            text=self.t("persona_page_status_unknown"),
            anchor="e"
        )
        self.persona_status.grid(row=0, column=1, sticky="e")

    def _build_summary_grid(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure((0, 1), weight=1)

        self.current_card = SectionCard(body, self.t("persona_page_current_persona"))
        self.current_card.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING_MEDIUM), pady=(0, SPACING_MEDIUM))

        self.name_label = self._detail_label(self.current_card.body, "persona_page_name")
        self.description_label = self._detail_label(self.current_card.body, "persona_page_description")
        self.style_label = self._detail_label(self.current_card.body, "persona_page_style")
        self.current_status_label = StatusLabel(
            self.current_card.body,
            status="disabled",
            text=self.t("persona_page_status_unknown"),
            anchor="w",
            justify="left"
        )
        self.current_status_label.pack(fill="x", pady=(SPACING_SMALL, 0))

        self.rules_card = SectionCard(body, self.t("persona_page_rules"))
        self.rules_card.grid(row=0, column=1, sticky="nsew", padx=(SPACING_MEDIUM, 0), pady=(0, SPACING_MEDIUM))

        ctk.CTkLabel(
            self.rules_card.body,
            text=self.t("persona_page_rules_detail"),
            font=FONT_NORMAL,
            text_color=status_color("disabled"),
            wraplength=360,
            justify="left",
            anchor="w"
        ).pack(fill="x", pady=(0, SPACING_SMALL))

        self.behavior_rules_label = self._detail_label(self.rules_card.body, "persona_page_behavior_rules")
        self.personality_rules_label = self._detail_label(self.rules_card.body, "persona_page_personality_rules")
        self.rules_count_label = StatusLabel(
            self.rules_card.body,
            status="disabled",
            text=self.t("persona_page_status_unknown"),
            anchor="w",
            justify="left"
        )
        self.rules_count_label.pack(fill="x", pady=(SPACING_SMALL, 0))

        self.advanced_card = SectionCard(body, self.t("persona_page_advanced"))
        self.advanced_card.body.grid_columnconfigure((0, 1), weight=1)
        for index, (item_key, button_factory) in enumerate(self.ADVANCED_ITEMS):
            button_factory(
                self.advanced_card.body,
                text=self.t(item_key),
                command=self.open_persona_window
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
            text=self.t("persona_page_existing_window_note"),
            font=FONT_SMALL,
            text_color=status_color("disabled"),
            wraplength=720,
            justify="left",
            anchor="w"
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, SPACING_SMALL))

        PrimaryButton(
            footer,
            text=self.t("persona_page_open_persona_window"),
            command=self.open_persona_window
        ).grid(row=1, column=0, sticky="ew", padx=(0, SPACING_SMALL))

        SecondaryButton(
            footer,
            text=self.t("persona_page_toggle_advanced"),
            command=self.toggle_advanced
        ).grid(row=1, column=1, sticky="ew", padx=(SPACING_SMALL, 0))

    def _detail_label(self, parent, label_key):
        label = ctk.CTkLabel(
            parent,
            text="",
            font=FONT_NORMAL,
            text_color=status_color("disabled"),
            wraplength=360,
            justify="left",
            anchor="w"
        )
        label.pack(fill="x", pady=SPACING_SMALL)
        label.label_key = label_key
        return label

    def refresh(self):
        status = {}
        if callable(self.persona_status_provider):
            try:
                status = self.persona_status_provider() or {}
            except Exception as error:
                status = {"status": "error", "text": str(error)}
                if self.logger:
                    self.logger.error(f"Persona page status failed: {error}")

        enabled = status.get("enabled", None)
        state = status.get("status", None)
        if state is None:
            state = "enabled" if enabled is True else "disabled" if enabled is False else "disabled"

        status_text = status.get("text")
        if not status_text:
            if enabled is True:
                status_text = self.t("enabled")
            elif enabled is False:
                status_text = self.t("disabled")
            else:
                status_text = self.t("persona_page_status_unknown")

        self.persona_status.set_status(state, status_text)
        self.current_status_label.set_status(state, f"{self.t('status')}: {status_text}")

        self._set_detail(self.name_label, status.get("name", self.t("persona_page_status_unknown")))
        self._set_detail(self.description_label, status.get("description", self.t("persona_page_summary_unavailable")))
        self._set_detail(self.style_label, status.get("style", self.t("persona_page_summary_unavailable")))

        rules_count = status.get("rules_count", None)
        rules_text = self.t("persona_page_status_unknown")
        if rules_count is not None:
            rules_text = f"{self.t('persona_page_rules_count')}: {rules_count}"
        self.rules_count_label.set_status(state, rules_text)

        self._set_detail(self.behavior_rules_label, status.get("behavior_rules", self.t("persona_page_managed_in_editor")))
        self._set_detail(self.personality_rules_label, status.get("personality_rules", self.t("persona_page_managed_in_editor")))

    def open_persona_window(self):
        if callable(self.open_persona_callback):
            self.open_persona_callback()
            if self.logger:
                self.logger.info("Persona page opened existing PersonaWindow")

    def toggle_advanced(self):
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(SPACING_SMALL, 0))
        else:
            self.advanced_card.grid_forget()

    def _set_detail(self, label, value):
        label.configure(text=f"{self.t(label.label_key)}: {value}")

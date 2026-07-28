import customtkinter as ctk

from modules.ui_theme import (
    FORM_CONTROL_WIDTH,
    FONT_HEADER,
    FONT_NORMAL,
    FONT_NORMAL_BOLD,
    FONT_SMALL,
    SPACING_MEDIUM,
    SPACING_SMALL,
    status_color
)
from widgets.ui_components import PrimaryButton, SecondaryButton, SectionCard, StatusLabel


class HomePage(ctk.CTkFrame):
    """Dashboard summary page for the v2.6 AppShell."""

    STATUS_ITEMS = [
        ("ai_runtime", "home_ai_runtime"),
        ("memory", "home_memory"),
        ("knowledge", "home_knowledge"),
        ("persona", "home_persona"),
        ("remote", "home_remote")
    ]

    def __init__(
        self,
        parent,
        *,
        translate,
        status_provider=None,
        quick_actions=None,
        logger=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.t = translate
        self.status_provider = status_provider
        self.quick_actions = quick_actions or {}
        self.logger = logger
        self.status_labels = {}
        self.detail_labels = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build()
        self.refresh()

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_MEDIUM))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=self.t("home_title"),
            font=FONT_HEADER,
            anchor="w"
        ).grid(row=0, column=0, sticky="w")

        self.summary_label = StatusLabel(
            header,
            status="disabled",
            text=self.t("app_shell_ready"),
            anchor="e"
        )
        self.summary_label.grid(row=0, column=1, sticky="e")

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=0)
        content.grid_rowconfigure(0, weight=1)

        status_card = SectionCard(content, self.t("home_status_summary"))
        status_card.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING_MEDIUM))
        status_card.body.grid_columnconfigure(0, weight=1)

        for index, (status_id, label_key) in enumerate(self.STATUS_ITEMS):
            row = ctk.CTkFrame(status_card.body, fg_color="transparent")
            row.grid(row=index, column=0, sticky="ew", pady=SPACING_SMALL)
            row.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(
                row,
                text=self.t(label_key),
                font=FONT_NORMAL_BOLD,
                anchor="w"
            ).grid(row=0, column=0, sticky="w", padx=(0, SPACING_MEDIUM))

            detail = ctk.CTkLabel(
                row,
                text="--",
                font=FONT_NORMAL,
                anchor="w"
            )
            detail.grid(row=0, column=1, sticky="ew")
            self.detail_labels[status_id] = detail

            status = StatusLabel(row, status="disabled", text="--")
            status.grid(row=0, column=2, sticky="e")
            self.status_labels[status_id] = status

        action_card = SectionCard(content, self.t("quick_actions"))
        action_card.grid(row=0, column=1, sticky="nsew", padx=(SPACING_MEDIUM, 0))

        PrimaryButton(
            action_card.body,
            text=self.t("home_new_chat"),
            command=self.quick_actions.get("new_chat")
        ).pack(fill="x", pady=SPACING_SMALL)

        SecondaryButton(
            action_card.body,
            text=self.t("home_open_library"),
            command=self.quick_actions.get("open_library")
        ).pack(fill="x", pady=SPACING_SMALL)

        SecondaryButton(
            action_card.body,
            text=self.t("settings"),
            command=self.quick_actions.get("settings")
        ).pack(fill="x", pady=SPACING_SMALL)

        self.note_label = ctk.CTkLabel(
            action_card.body,
            text=self.t("home_advanced_hidden_note"),
            font=FONT_SMALL,
            text_color=status_color("disabled"),
            wraplength=FORM_CONTROL_WIDTH,
            justify="left"
        )
        self.note_label.pack(fill="x", pady=(SPACING_MEDIUM, 0))

    def refresh(self):
        status = self._load_status()
        overall = status.get("overall", "disabled")
        self.summary_label.set_status(overall, status.get("summary", self.t("app_shell_ready")))

        for status_id, _label_key in self.STATUS_ITEMS:
            record = status.get(status_id, {})
            if not isinstance(record, dict):
                record = {}
            label_status = record.get("status", "disabled")
            detail = record.get("detail", "--")
            text = record.get("text", label_status)
            self.detail_labels[status_id].configure(text=str(detail))
            self.status_labels[status_id].set_status(label_status, str(text))

        if self.logger:
            self.logger.info("Home page refreshed")

    def _load_status(self):
        if callable(self.status_provider):
            try:
                data = self.status_provider()
                if isinstance(data, dict):
                    return data
            except Exception as error:
                if self.logger:
                    self.logger.error(f"Home page status failed: {error}")
        return {
            "overall": "disabled",
            "summary": self.t("app_shell_ready"),
            "ai_runtime": {"status": "disabled", "text": "--", "detail": "--"},
            "memory": {"status": "disabled", "text": "--", "detail": "--"},
            "knowledge": {"status": "disabled", "text": "--", "detail": "--"},
            "persona": {"status": "disabled", "text": "--", "detail": "--"},
            "remote": {"status": "disabled", "text": "--", "detail": "--"}
        }

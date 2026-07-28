import customtkinter as ctk

from modules.ui_theme import (
    FONT_HEADER,
    FONT_NORMAL,
    FONT_SMALL,
    SPACING_MEDIUM,
    SPACING_SMALL,
    status_color
)
from widgets.ui_components import PrimaryButton, SectionCard, SecondaryButton, StatusLabel


class MemoryPage(ctk.CTkFrame):
    """AppShell memory page wrapper that reuses the existing MemoryWindow."""

    ADVANCED_ITEMS = [
        "memory_page_candidate_memories",
        "memory_page_quality_control",
        "import_memory",
        "export_memory"
    ]

    def __init__(
        self,
        parent,
        *,
        translate,
        open_memory_callback=None,
        memory_status_provider=None,
        logger=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.t = translate
        self.open_memory_callback = open_memory_callback
        self.memory_status_provider = memory_status_provider
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
            text=self.t("memory_page_title"),
            font=FONT_HEADER,
            anchor="w"
        ).grid(row=0, column=0, sticky="w")

        self.memory_status = StatusLabel(
            header,
            status="disabled",
            text=self.t("memory_page_status_unknown"),
            anchor="e"
        )
        self.memory_status.grid(row=0, column=1, sticky="e")

    def _build_summary_grid(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure((0, 1), weight=1)

        self.summary_card = SectionCard(body, self.t("memory_page_summary"))
        self.summary_card.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING_MEDIUM), pady=(0, SPACING_MEDIUM))

        ctk.CTkLabel(
            self.summary_card.body,
            text=self.t("memory_page_summary_detail"),
            font=FONT_NORMAL,
            text_color=status_color("disabled"),
            wraplength=360,
            justify="left",
            anchor="w"
        ).pack(fill="x", pady=(0, SPACING_SMALL))

        self.total_label = self._detail_label(self.summary_card.body, "memory_page_total_memories")
        self.recent_label = self._detail_label(self.summary_card.body, "memory_page_recent_memories")
        self.summary_status_label = StatusLabel(
            self.summary_card.body,
            status="disabled",
            text=self.t("memory_page_status_unknown"),
            anchor="w",
            justify="left"
        )
        self.summary_status_label.pack(fill="x", pady=(SPACING_SMALL, 0))

        self.list_card = SectionCard(body, self.t("memory_page_memory_list"))
        self.list_card.grid(row=0, column=1, sticky="nsew", padx=(SPACING_MEDIUM, 0), pady=(0, SPACING_MEDIUM))

        ctk.CTkLabel(
            self.list_card.body,
            text=self.t("memory_page_list_detail"),
            font=FONT_NORMAL,
            text_color=status_color("disabled"),
            wraplength=360,
            justify="left",
            anchor="w"
        ).pack(fill="x", pady=(0, SPACING_SMALL))

        self.search_entry = ctk.CTkEntry(
            self.list_card.body,
            placeholder_text=self.t("memory_page_search_placeholder")
        )
        self.search_entry.pack(fill="x", pady=(0, SPACING_SMALL))

        SecondaryButton(
            self.list_card.body,
            text=self.t("memory_page_open_list"),
            command=self.open_memory_window
        ).pack(fill="x", pady=SPACING_SMALL)

        SecondaryButton(
            self.list_card.body,
            text=self.t("memory_page_view_detail"),
            command=self.open_memory_window
        ).pack(fill="x", pady=SPACING_SMALL)

        self.advanced_card = SectionCard(body, self.t("memory_page_advanced"))
        self.advanced_card.body.grid_columnconfigure((0, 1), weight=1)
        for index, item_key in enumerate(self.ADVANCED_ITEMS):
            SecondaryButton(
                self.advanced_card.body,
                text=self.t(item_key),
                command=self.open_memory_window
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
            text=self.t("memory_page_existing_window_note"),
            font=FONT_SMALL,
            text_color=status_color("disabled"),
            wraplength=720,
            justify="left",
            anchor="w"
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, SPACING_SMALL))

        PrimaryButton(
            footer,
            text=self.t("memory_page_open_memory_window"),
            command=self.open_memory_window
        ).grid(row=1, column=0, sticky="ew", padx=(0, SPACING_SMALL))

        SecondaryButton(
            footer,
            text=self.t("memory_page_toggle_advanced"),
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
        if callable(self.memory_status_provider):
            try:
                status = self.memory_status_provider() or {}
            except Exception as error:
                status = {"status": "error", "text": str(error)}
                if self.logger:
                    self.logger.error(f"Memory page status failed: {error}")

        state = status.get("status", "disabled")
        status_text = status.get("text", self.t("memory_page_status_unknown"))
        self.memory_status.set_status(state, status_text)
        self.summary_status_label.set_status(state, f"{self.t('status')}: {status_text}")

        total = status.get("total", status.get("count", status.get("memory_count", None)))
        recent = status.get("recent", status.get("recent_count", None))
        self._set_detail(self.total_label, total if total is not None else self.t("memory_page_status_unknown"))
        self._set_detail(self.recent_label, recent if recent is not None else self.t("memory_page_status_unknown"))

    def open_memory_window(self):
        if callable(self.open_memory_callback):
            self.open_memory_callback()
            if self.logger:
                self.logger.info("Memory page opened existing MemoryWindow")

    def toggle_advanced(self):
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(SPACING_SMALL, 0))
        else:
            self.advanced_card.grid_forget()

    def _set_detail(self, label, value):
        label.configure(text=f"{self.t(label.label_key)}: {value}")

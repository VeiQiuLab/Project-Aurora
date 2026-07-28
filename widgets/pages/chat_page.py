import customtkinter as ctk

from modules.ui_theme import (
    FONT_HEADER,
    FONT_NORMAL,
    FONT_SMALL,
    SPACING_LARGE,
    SPACING_MEDIUM,
    SPACING_SMALL,
    status_color
)
from widgets.ui_components import PrimaryButton, SectionCard, SecondaryButton, StatusLabel


class ChatPage(ctk.CTkFrame):
    """AppShell chat page wrapper that reuses the existing ChatWindow."""

    ADVANCED_ITEMS = [
        "chat_page_context_inspector",
        "chat_page_debug_info",
        "chat_page_raw_prompt"
    ]

    def __init__(
        self,
        parent,
        *,
        translate,
        open_chat_callback=None,
        new_chat_callback=None,
        conversation_provider=None,
        model_provider=None,
        logger=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.t = translate
        self.open_chat_callback = open_chat_callback
        self.new_chat_callback = new_chat_callback
        self.conversation_provider = conversation_provider
        self.model_provider = model_provider
        self.logger = logger
        self.advanced_visible = False

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build()
        self.refresh()

    def _build(self):
        self.sidebar = ctk.CTkFrame(self, width=260)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, SPACING_MEDIUM))
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self._build_conversation_sidebar()

        self.chat_area = ctk.CTkFrame(self, fg_color="transparent")
        self.chat_area.grid(row=0, column=1, sticky="nsew")
        self.chat_area.grid_columnconfigure(0, weight=1)
        self.chat_area.grid_rowconfigure(1, weight=1)

        self._build_chat_header()
        self._build_chat_body()
        self._build_chat_footer()

    def _build_conversation_sidebar(self):
        ctk.CTkLabel(
            self.sidebar,
            text=self.t("chat_page_conversations"),
            font=FONT_HEADER,
            anchor="w"
        ).grid(row=0, column=0, sticky="ew", padx=SPACING_MEDIUM, pady=(SPACING_LARGE, SPACING_SMALL))

        self.search_entry = ctk.CTkEntry(
            self.sidebar,
            placeholder_text=self.t("chat_page_search_placeholder")
        )
        self.search_entry.grid(row=1, column=0, sticky="ew", padx=SPACING_MEDIUM, pady=SPACING_SMALL)

        PrimaryButton(
            self.sidebar,
            text=self.t("home_new_chat"),
            command=self.open_new_chat
        ).grid(row=2, column=0, sticky="ew", padx=SPACING_MEDIUM, pady=SPACING_SMALL)

        self.conversation_card = SectionCard(self.sidebar, self.t("conversation"))
        self.conversation_card.grid(row=3, column=0, sticky="nsew", padx=SPACING_MEDIUM, pady=SPACING_MEDIUM)
        self.sidebar.grid_rowconfigure(3, weight=1)

        self.conversation_list = ctk.CTkOptionMenu(
            self.conversation_card.body,
            values=[self.t("chat_page_no_conversations")]
        )
        self.conversation_list.pack(fill="x", pady=SPACING_SMALL)

        SecondaryButton(
            self.conversation_card.body,
            text=self.t("chat_page_open_existing_chat"),
            command=self.open_chat
        ).pack(fill="x", pady=SPACING_SMALL)

    def _build_chat_header(self):
        header = ctk.CTkFrame(self.chat_area, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_MEDIUM))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=self.t("chat"),
            font=FONT_HEADER,
            anchor="w"
        ).grid(row=0, column=0, sticky="w")

        self.model_status = StatusLabel(
            header,
            status="disabled",
            text=self.t("chat_page_model_unknown"),
            anchor="e"
        )
        self.model_status.grid(row=0, column=1, sticky="e")

    def _build_chat_body(self):
        self.message_card = SectionCard(self.chat_area, self.t("chat_page_message_area"))
        self.message_card.grid(row=1, column=0, sticky="nsew", pady=(0, SPACING_MEDIUM))

        self.placeholder = ctk.CTkLabel(
            self.message_card.body,
            text=self.t("chat_page_existing_window_note"),
            font=FONT_NORMAL,
            text_color=status_color("disabled"),
            wraplength=680,
            justify="center"
        )
        self.placeholder.pack(fill="both", expand=True, padx=SPACING_LARGE, pady=SPACING_LARGE)

        self.advanced_card = SectionCard(self.chat_area, self.t("chat_page_advanced"))
        for item_key in self.ADVANCED_ITEMS:
            ctk.CTkLabel(
                self.advanced_card.body,
                text=self.t(item_key),
                font=FONT_SMALL,
                text_color=status_color("disabled"),
                anchor="w"
            ).pack(fill="x", pady=SPACING_SMALL)

    def _build_chat_footer(self):
        footer = ctk.CTkFrame(self.chat_area, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)

        PrimaryButton(
            footer,
            text=self.t("chat_page_open_chat_window"),
            command=self.open_chat
        ).grid(row=0, column=0, sticky="ew", padx=(0, SPACING_SMALL))

        SecondaryButton(
            footer,
            text=self.t("chat_page_toggle_advanced"),
            command=self.toggle_advanced
        ).grid(row=0, column=1, sticky="ew", padx=(SPACING_SMALL, 0))

    def refresh(self):
        self.refresh_model()
        self.refresh_conversations()

    def refresh_model(self):
        model = ""
        if callable(self.model_provider):
            try:
                model = str(self.model_provider() or "")
            except Exception as error:
                if self.logger:
                    self.logger.error(f"Chat page model status failed: {error}")
        self.model_status.set_status("disabled", model or self.t("chat_page_model_unknown"))

    def refresh_conversations(self):
        values = [self.t("chat_page_no_conversations")]
        if callable(self.conversation_provider):
            try:
                records = self.conversation_provider()
            except Exception as error:
                records = []
                if self.logger:
                    self.logger.error(f"Chat page conversation list failed: {error}")
            values = self._conversation_labels(records) or values
        self.conversation_list.configure(values=values)
        self.conversation_list.set(values[0])

    def open_chat(self):
        if callable(self.open_chat_callback):
            self.open_chat_callback()
            if self.logger:
                self.logger.info("Chat page opened existing ChatWindow")

    def open_new_chat(self):
        if callable(self.new_chat_callback):
            self.new_chat_callback()
        else:
            self.open_chat()

    def toggle_advanced(self):
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_card.grid(row=3, column=0, sticky="ew", pady=(0, SPACING_MEDIUM))
        else:
            self.advanced_card.grid_forget()

    def _conversation_labels(self, records):
        labels = []
        for record in records or []:
            if not isinstance(record, dict):
                continue
            title = str(record.get("title") or self.t("conversation"))
            updated = str(record.get("updated_at") or "")
            labels.append(f"{title}  {updated}".strip())
        return labels

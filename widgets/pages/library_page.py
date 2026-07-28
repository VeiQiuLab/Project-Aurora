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


class LibraryPage(ctk.CTkFrame):
    """AppShell library page wrapper that reuses the existing KnowledgeWindow."""

    ADVANCED_ITEMS = [
        "library_page_rebuild_index",
        "library_page_metadata_repair",
        "library_page_backup",
        "library_page_restore"
    ]

    def __init__(
        self,
        parent,
        *,
        translate,
        open_knowledge_callback=None,
        knowledge_status_provider=None,
        logger=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.t = translate
        self.open_knowledge_callback = open_knowledge_callback
        self.knowledge_status_provider = knowledge_status_provider
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
            text=self.t("library_page_title"),
            font=FONT_HEADER,
            anchor="w"
        ).grid(row=0, column=0, sticky="w")

        self.library_status = StatusLabel(
            header,
            status="disabled",
            text=self.t("library_page_status_unknown"),
            anchor="e"
        )
        self.library_status.grid(row=0, column=1, sticky="e")

    def _build_summary_grid(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure((0, 1), weight=1)

        self.documents_card = self._summary_card(
            body,
            0,
            0,
            "library_page_documents",
            "library_page_documents_detail"
        )
        self.search_card = self._summary_card(
            body,
            0,
            1,
            "library_page_search",
            "library_page_search_detail"
        )
        self.retrieval_card = self._summary_card(
            body,
            1,
            0,
            "library_page_retrieval",
            "library_page_retrieval_detail"
        )
        self.index_card = self._summary_card(
            body,
            1,
            1,
            "library_page_index",
            "library_page_index_detail"
        )

        self.document_count_label = StatusLabel(
            self.documents_card.body,
            status="disabled",
            text=self.t("library_page_status_unknown"),
            anchor="w",
            justify="left"
        )
        self.document_count_label.pack(fill="x", pady=(SPACING_SMALL, 0))

        self.search_entry = ctk.CTkEntry(
            self.search_card.body,
            placeholder_text=self.t("search_knowledge")
        )
        self.search_entry.pack(fill="x", pady=(SPACING_SMALL, 0))

        self.retrieval_status = StatusLabel(
            self.retrieval_card.body,
            status="disabled",
            text=self.t("library_page_status_unknown"),
            anchor="w",
            justify="left"
        )
        self.retrieval_status.pack(fill="x", pady=(SPACING_SMALL, 0))

        self.index_status = StatusLabel(
            self.index_card.body,
            status="disabled",
            text=self.t("library_page_status_unknown"),
            anchor="w",
            justify="left"
        )
        self.index_status.pack(fill="x", pady=(SPACING_SMALL, 0))

        self.advanced_card = SectionCard(body, self.t("library_page_advanced"))
        self.advanced_card.body.grid_columnconfigure((0, 1), weight=1)
        for index, item_key in enumerate(self.ADVANCED_ITEMS):
            SecondaryButton(
                self.advanced_card.body,
                text=self.t(item_key),
                command=self.open_knowledge_window
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

        note = ctk.CTkLabel(
            footer,
            text=self.t("library_page_existing_window_note"),
            font=FONT_SMALL,
            text_color=status_color("disabled"),
            wraplength=720,
            justify="left",
            anchor="w"
        )
        note.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, SPACING_SMALL))

        PrimaryButton(
            footer,
            text=self.t("library_page_open_knowledge_window"),
            command=self.open_knowledge_window
        ).grid(row=1, column=0, sticky="ew", padx=(0, SPACING_SMALL))

        SecondaryButton(
            footer,
            text=self.t("library_page_toggle_advanced"),
            command=self.toggle_advanced
        ).grid(row=1, column=1, sticky="ew", padx=(SPACING_SMALL, 0))

    def _summary_card(self, parent, row, column, title_key, detail_key):
        card = SectionCard(parent, self.t(title_key))
        card.grid(
            row=row,
            column=column,
            sticky="nsew",
            padx=(0, SPACING_MEDIUM) if column == 0 else (SPACING_MEDIUM, 0),
            pady=(0, SPACING_MEDIUM)
        )
        ctk.CTkLabel(
            card.body,
            text=self.t(detail_key),
            font=FONT_NORMAL,
            text_color=status_color("disabled"),
            wraplength=360,
            justify="left",
            anchor="w"
        ).pack(fill="x")
        return card

    def refresh(self):
        status = {}
        if callable(self.knowledge_status_provider):
            try:
                status = self.knowledge_status_provider() or {}
            except Exception as error:
                status = {"status": "error", "text": str(error)}
                if self.logger:
                    self.logger.error(f"Library page status failed: {error}")

        overall_status = status.get("status", "disabled")
        overall_text = status.get("text", self.t("library_page_status_unknown"))
        self.library_status.set_status(overall_status, overall_text)

        document_count = status.get("documents", status.get("document_count", None))
        document_text = self.t("library_page_status_unknown")
        if document_count is not None:
            document_text = f"{self.t('knowledge_documents')}: {document_count}"
        self.document_count_label.set_status(overall_status, document_text)

        retrieval_text = status.get("retrieval", status.get("retrieval_status", self.t("library_page_status_unknown")))
        self.retrieval_status.set_status(status.get("retrieval_state", overall_status), retrieval_text)

        index_text = status.get("index", status.get("index_status", self.t("library_page_status_unknown")))
        self.index_status.set_status(status.get("index_state", overall_status), index_text)

    def open_knowledge_window(self):
        if callable(self.open_knowledge_callback):
            self.open_knowledge_callback()
            if self.logger:
                self.logger.info("Library page opened existing KnowledgeWindow")

    def toggle_advanced(self):
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_card.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(SPACING_SMALL, 0))
        else:
            self.advanced_card.grid_forget()

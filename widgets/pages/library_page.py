import customtkinter as ctk

from widgets.components.knowledge_panel import KnowledgePanel


class LibraryPage(ctk.CTkFrame):
    """AppShell workspace page that hosts the shared KnowledgePanel."""

    def __init__(
        self,
        parent,
        *,
        knowledge_store,
        settings,
        text,
        translate,
        logger,
        version,
        retrieval_summary,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.t = translate
        self.logger = logger

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.panel = KnowledgePanel(
            self,
            knowledge_store=knowledge_store,
            settings=settings,
            text=text,
            translate=translate,
            logger=logger,
            version=version,
            retrieval_summary=retrieval_summary,
            show_close_button=False
        )
        self.panel.grid(row=0, column=0, sticky="nsew")

    def refresh(self):
        self.panel.refresh_backup_history()
        self.panel.refresh_knowledge_list()

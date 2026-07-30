import customtkinter as ctk

from widgets.components.knowledge_panel import KnowledgePanel


class KnowledgeWindow(ctk.CTkToplevel):
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
        on_close=None
    ):
        super().__init__(parent)
        self.t = translate
        self.on_close_callback = on_close

        self.title(self.t("knowledge_base"))
        self.geometry("900x760")
        self.minsize(760, 640)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.panel = KnowledgePanel(
            self,
            knowledge_store=knowledge_store,
            settings=settings,
            text=text,
            translate=translate,
            logger=logger,
            version=version,
            retrieval_summary=retrieval_summary,
            close_callback=self.close,
            show_close_button=True
        )
        self.panel.grid(row=0, column=0, sticky="nsew")

    def close(self):
        self.destroy()
        if self.on_close_callback:
            self.on_close_callback()

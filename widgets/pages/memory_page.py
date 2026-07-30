import customtkinter as ctk

from widgets.components.memory_panel import MemoryPanel


class MemoryPage(ctk.CTkFrame):
    """AppShell workspace page that hosts the shared MemoryPanel."""

    def __init__(
        self,
        parent,
        *,
        memory_store,
        search_memories,
        translate,
        logger=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.t = translate
        self.logger = logger

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.panel = MemoryPanel(
            self,
            memory_store=memory_store,
            search_memories=search_memories,
            translate=translate,
            logger=logger,
            show_close_button=False
        )
        self.panel.grid(row=0, column=0, sticky="nsew")

    def refresh(self):
        self.panel.refresh_memory_list()

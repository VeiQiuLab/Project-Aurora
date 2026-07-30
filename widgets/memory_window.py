import customtkinter as ctk

from widgets.components.memory_panel import MemoryPanel


class MemoryWindow(ctk.CTkToplevel):
    def __init__(self, parent, *, memory_store, search_memories, text, translate, logger, on_close=None):
        super().__init__(parent)
        self.t = translate
        self.on_close_callback = on_close

        self.title(self.t("memory"))
        self.geometry("1100x820")
        self.minsize(980, 720)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.panel = MemoryPanel(
            self,
            memory_store=memory_store,
            search_memories=search_memories,
            translate=translate,
            logger=logger,
            close_callback=self.close
        )
        self.panel.grid(row=0, column=0, sticky="nsew")

    def close(self):
        self.destroy()
        if self.on_close_callback:
            self.on_close_callback()

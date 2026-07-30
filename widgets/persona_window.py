import customtkinter as ctk

from widgets.components.persona_panel import PersonaPanel


class PersonaWindow(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        *,
        persona_store,
        settings,
        text,
        translate,
        logger,
        final_prompt_preview_callback=None,
        on_close=None
    ):
        super().__init__(parent)
        self.t = translate
        self.on_close_callback = on_close

        self.title(self.t("persona_page_title"))
        self.geometry("860x720")
        self.minsize(720, 560)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.panel = PersonaPanel(
            self,
            persona_store=persona_store,
            settings=settings,
            translate=translate,
            logger=logger,
            final_prompt_preview_callback=final_prompt_preview_callback,
            close_callback=self.close
        )
        self.panel.grid(row=0, column=0, sticky="nsew")

    def close(self):
        self.destroy()
        if self.on_close_callback:
            self.on_close_callback()

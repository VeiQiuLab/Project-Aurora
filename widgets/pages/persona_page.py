import customtkinter as ctk

from widgets.components.persona_panel import PersonaPanel


class PersonaPage(ctk.CTkFrame):
    """AppShell workspace page that hosts the shared PersonaPanel."""

    def __init__(
        self,
        parent,
        *,
        persona_store,
        settings,
        translate,
        logger=None,
        final_prompt_preview_callback=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.t = translate
        self.logger = logger

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.panel = PersonaPanel(
            self,
            persona_store=persona_store,
            settings=settings,
            translate=translate,
            logger=logger,
            final_prompt_preview_callback=final_prompt_preview_callback,
            show_close_button=False
        )
        self.panel.grid(row=0, column=0, sticky="nsew")

    def refresh(self):
        self.panel.refresh_persona()

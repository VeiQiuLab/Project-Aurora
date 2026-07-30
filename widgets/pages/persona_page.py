import traceback
import customtkinter as ctk

from widgets.components.workspace_empty_state import WorkspaceEmptyState
from widgets.components.workspace_header import WorkspaceHeader
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

        if self.logger:
            self.logger.info("PersonaPage creating PersonaPanel")
        try:
            self.panel = PersonaPanel(
                self,
                persona_store=persona_store,
                settings=settings,
                translate=translate,
                logger=logger,
                final_prompt_preview_callback=final_prompt_preview_callback,
                show_close_button=False,
                show_header_title=False
            )
            self.panel.grid(row=0, column=0, sticky="nsew")
            if self.logger:
                self.logger.info("PersonaPage created successfully")
        except Exception as error:
            self.panel = None
            error_traceback = traceback.format_exc()
            if self.logger:
                self.logger.error(f"PersonaPage creation failed: {error}")
                self.logger.error(error_traceback)
            traceback.print_exc()
            self.show_creation_error(str(error))

    def refresh(self):
        if self.panel:
            self.panel.refresh_persona()

    def show_creation_error(self, message):
        header = WorkspaceHeader(
            self,
            title=self.t("persona_page_title"),
            description=self.t("workspace_persona_description"),
            status="error",
            status_text=message,
            show_title=False
        )
        header.grid_with_workspace_padding()
        empty_state = WorkspaceEmptyState(
            self,
            title=self.t("workspace_persona_empty_title"),
            description=message
        )
        empty_state.grid(row=1, column=0, sticky="new", padx=32, pady=(0, 16))

import customtkinter as ctk

from modules.ui_theme import (
    COLOR_MUTED,
    FONT_NORMAL,
    FONT_TITLE,
    SPACING_LARGE,
    SPACING_MEDIUM,
    SPACING_SMALL
)
from widgets.components.workspace_status import WorkspaceStatus


class WorkspaceHeader(ctk.CTkFrame):
    """Consistent title, description, and status header for workspace panels."""

    def __init__(self, parent, *, title, description="", status="disabled", status_text="", **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(self, text=title, font=FONT_TITLE, anchor="w")
        self.title_label.grid(row=0, column=0, sticky="w")

        self.status_label = WorkspaceStatus(
            self,
            state=status,
            text=status_text,
        )
        self.status_label.grid(row=0, column=1, sticky="e", padx=(SPACING_MEDIUM, 0))

        self.description_label = ctk.CTkLabel(
            self,
            text=description,
            font=FONT_NORMAL,
            text_color=COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=760
        )
        self.description_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(SPACING_SMALL, 0))

    def grid_with_workspace_padding(self, row=0, column=0, columnspan=1):
        self.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            sticky="ew",
            padx=SPACING_LARGE + SPACING_SMALL,
            pady=(SPACING_LARGE, SPACING_MEDIUM)
        )

    def pack_with_workspace_padding(self):
        self.pack(
            fill="x",
            padx=SPACING_LARGE + SPACING_SMALL,
            pady=(SPACING_LARGE, SPACING_MEDIUM)
        )

    def set_status(self, status, text=None):
        self.status_label.set_status(status, text=text)

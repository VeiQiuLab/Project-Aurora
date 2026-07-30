import customtkinter as ctk

from modules.ui_theme import (
    COLOR_MUTED,
    FONT_HEADER,
    FONT_NORMAL,
    FONT_TITLE,
    SPACING_MEDIUM,
    SPACING_SMALL
)
from widgets.ui_components import PrimaryButton


class WorkspaceEmptyState(ctk.CTkFrame):
    """Consistent empty-state block for workspace panels."""

    def __init__(
        self,
        parent,
        *,
        title,
        description,
        action_text=None,
        action_callback=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="○", font=FONT_TITLE, text_color=COLOR_MUTED).grid(
            row=0,
            column=0,
            pady=(0, SPACING_SMALL)
        )
        ctk.CTkLabel(self, text=title, font=FONT_HEADER, anchor="center").grid(
            row=1,
            column=0,
            sticky="ew"
        )
        ctk.CTkLabel(
            self,
            text=description,
            font=FONT_NORMAL,
            text_color=COLOR_MUTED,
            wraplength=420,
            justify="center"
        ).grid(row=2, column=0, sticky="ew", pady=(SPACING_SMALL, SPACING_MEDIUM))

        if action_text and action_callback:
            PrimaryButton(self, text=action_text, command=action_callback).grid(row=3, column=0)

import customtkinter as ctk

from widgets.ui_components import StatusLabel


class WorkspaceStatus(ctk.CTkFrame):
    """Compact workspace-level status display."""

    STATE_TO_STATUS = {
        "ready": "healthy",
        "loading": "disabled",
        "processing": "warning",
        "warning": "warning",
        "error": "error"
    }

    def __init__(self, parent, *, state="ready", text="", **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.label = StatusLabel(self, status="disabled", text="", anchor="e", justify="right")
        self.label.pack(fill="x")
        self.set_status(state, text)

    def set_status(self, state, text=None):
        mapped_state = self.STATE_TO_STATUS.get(str(state or "").strip().casefold(), state)
        self.label.set_status(mapped_state, text=text if text is not None else state)



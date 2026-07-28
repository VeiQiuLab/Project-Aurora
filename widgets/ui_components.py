import customtkinter as ctk

from modules.ui_theme import (
    button_style,
    COLOR_MUTED,
    FONT_HEADER,
    FONT_NORMAL,
    FONT_SMALL,
    BUTTON_HEIGHT,
    CONTROL_CORNER_RADIUS,
    FORM_CONTROL_WIDTH,
    FORM_LABEL_WRAP,
    SPACING_SMALL,
    SPACING_MEDIUM,
    SPACING_LARGE,
    status_color
)


def _button(parent, text, command=None, kind="secondary", **kwargs):
    options = button_style(kind)
    options.setdefault("height", BUTTON_HEIGHT)
    options.setdefault("corner_radius", CONTROL_CORNER_RADIUS)
    options.setdefault("font", FONT_NORMAL)
    options.update(kwargs)
    return ctk.CTkButton(parent, text=text, command=command, **options)


def PrimaryButton(parent, text, command=None, **kwargs):
    return _button(parent, text, command=command, kind="primary", **kwargs)


def SecondaryButton(parent, text, command=None, **kwargs):
    return _button(parent, text, command=command, kind="secondary", **kwargs)


def DangerButton(parent, text, command=None, **kwargs):
    return _button(parent, text, command=command, kind="danger", **kwargs)


class StatusLabel(ctk.CTkLabel):
    def __init__(self, parent, status="disabled", text=None, **kwargs):
        kwargs.setdefault("font", FONT_SMALL)
        kwargs.setdefault("anchor", "e")
        kwargs.setdefault("wraplength", 240)
        kwargs.setdefault("justify", "right")
        super().__init__(parent, **kwargs)
        self.set_status(status, text=text)

    def set_status(self, status, text=None):
        self.configure(
            text=str(text if text is not None else status),
            text_color=status_color(status)
        )


class SectionCard(ctk.CTkFrame):
    def __init__(self, parent, title, **kwargs):
        kwargs.setdefault("corner_radius", CONTROL_CORNER_RADIUS)
        super().__init__(parent, **kwargs)
        self.title = ctk.CTkLabel(
            self,
            text=title,
            font=FONT_HEADER,
            anchor="w"
        )
        self.title.pack(fill="x", padx=SPACING_LARGE, pady=(SPACING_MEDIUM, SPACING_SMALL))

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=SPACING_LARGE, pady=(0, SPACING_MEDIUM))


class FormRow(ctk.CTkFrame):
    def __init__(self, parent, label_text, **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        self.label = ctk.CTkLabel(
            self,
            text=label_text,
            anchor="w",
            font=FONT_NORMAL,
            wraplength=FORM_LABEL_WRAP,
            justify="left"
        )
        self.label.grid(row=0, column=0, sticky="w", padx=(0, SPACING_MEDIUM))

        self.control_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.control_frame.grid(row=0, column=1, sticky="e")

    def add_entry(self, current_value, width=FORM_CONTROL_WIDTH):
        entry = ctk.CTkEntry(self.control_frame, width=width)
        entry.insert(0, str(current_value))
        entry.pack(side="left")
        return entry

    def add_option(self, values, current_value, width=180):
        option = ctk.CTkOptionMenu(self.control_frame, values=values, width=width)
        option.set(current_value)
        option.pack(side="left")
        return option


class FixedFooter(ctk.CTkFrame):
    def __init__(self, parent, **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.message = ctk.CTkLabel(
            self,
            text="",
            font=FONT_SMALL,
            text_color=COLOR_MUTED
        )
        self.message.pack(pady=(0, SPACING_SMALL))

        self.buttons = ctk.CTkFrame(self, fg_color="transparent")
        self.buttons.pack(fill="x")

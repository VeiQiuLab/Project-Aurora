import customtkinter as ctk

from modules.ui_theme import (
    COLOR_MUTED,
    FONT_APP_TITLE,
    FONT_HEADER,
    FONT_NORMAL,
    FONT_SMALL,
    SPACING_LARGE,
    SPACING_MEDIUM,
    SPACING_SMALL
)
from widgets.ui_components import PrimaryButton, SecondaryButton, StatusLabel


class AppShell(ctk.CTkFrame):
    """Navigation shell for the future v2.6 page-based UI."""

    DEFAULT_NAV_ITEMS = [
        ("home", "nav_home"),
        ("chat", "nav_chat"),
        ("library", "nav_library"),
        ("memory", "nav_memory"),
        ("persona", "nav_persona"),
        ("remote", "nav_remote"),
        ("settings", "nav_settings")
    ]

    def __init__(
        self,
        parent,
        *,
        app_name="Aurora",
        translate=None,
        nav_items=None,
        page_builders=None,
        on_page_change=None,
        on_shutdown=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.app_name = app_name
        self.t = translate or (lambda key, default=None: default if default is not None else key)
        self.nav_items = list(nav_items or self.DEFAULT_NAV_ITEMS)
        self.on_page_change = on_page_change
        self.current_page = None
        self.page_builders = dict(page_builders or {})
        self.on_shutdown = on_shutdown
        self.page_frames = {}
        self.nav_buttons = {}

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=220)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, SPACING_MEDIUM), pady=0)
        self.sidebar.grid_propagate(False)

        self.content_area = ctk.CTkFrame(self)
        self.content_area.grid(row=0, column=1, sticky="nsew")
        self.content_area.grid_columnconfigure(0, weight=1)
        self.content_area.grid_rowconfigure(1, weight=1)

        self._build_sidebar()
        self._build_content_header()

        if self.nav_items:
            self.show_page(self.nav_items[0][0])

    def _build_sidebar(self):
        title = ctk.CTkLabel(
            self.sidebar,
            text=self.app_name,
            font=FONT_APP_TITLE,
            anchor="w"
        )
        title.pack(fill="x", padx=SPACING_LARGE, pady=(SPACING_LARGE, SPACING_SMALL))

        self.shell_status = StatusLabel(
            self.sidebar,
            status="disabled",
            text="",
            anchor="w",
            justify="left"
        )

        for page_id, label_key in self.nav_items:
            button = SecondaryButton(
                self.sidebar,
                text=self.t(label_key),
                command=lambda value=page_id: self.show_page(value),
                anchor="w"
            )
            button.pack(fill="x", padx=SPACING_MEDIUM, pady=SPACING_SMALL)
            self.nav_buttons[page_id] = button

        self.exit_button = SecondaryButton(
            self.sidebar,
            text=self.t("exit_aurora"),
            command=self._request_shutdown,
            anchor="w"
        )
        self.exit_button.pack(side="bottom", fill="x", padx=SPACING_MEDIUM, pady=(SPACING_SMALL, SPACING_LARGE))

    def _request_shutdown(self):
        if callable(self.on_shutdown):
            try:
                self.on_shutdown("app_shell_exit")
            except TypeError:
                self.on_shutdown()

    def _build_content_header(self):
        self.page_header = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.page_header.grid(row=0, column=0, sticky="ew", padx=SPACING_LARGE, pady=(SPACING_LARGE, SPACING_MEDIUM))
        self.page_title = ctk.CTkLabel(
            self.page_header,
            text="",
            font=FONT_HEADER,
            anchor="w"
        )
        self.page_title.pack(side="left", fill="x", expand=True)

        self.page_status = StatusLabel(
            self.page_header,
            status="disabled",
            text="",
            anchor="e"
        )

        self.page_container = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.page_container.grid(row=1, column=0, sticky="nsew", padx=SPACING_LARGE, pady=(0, SPACING_LARGE))
        self.page_container.grid_columnconfigure(0, weight=1)
        self.page_container.grid_rowconfigure(0, weight=1)

    def register_page(self, page_id, builder):
        self.page_builders[page_id] = builder

    def register_pages(self, page_builders):
        self.page_builders.update(page_builders or {})

    def navigate(self, page_id):
        self.show_page(page_id)

    def show_page(self, page_id):
        if page_id not in {item[0] for item in self.nav_items}:
            return

        if self.current_page in self.page_frames:
            self.page_frames[self.current_page].grid_forget()

        if page_id not in self.page_frames:
            self.page_frames[page_id] = self._create_page(page_id)

        frame = self.page_frames[page_id]
        frame.grid(row=0, column=0, sticky="nsew")
        self.current_page = page_id
        self._refresh_nav_state()
        self._refresh_header(page_id)

        if callable(self.on_page_change):
            self.on_page_change(page_id)

    def set_shell_status(self, status, text=None):
        if text:
            if not self.shell_status.winfo_ismapped():
                self.shell_status.pack(fill="x", padx=SPACING_LARGE, pady=(0, SPACING_LARGE))
        else:
            self.shell_status.pack_forget()
        self.shell_status.set_status(status, text=text)

    def _create_page(self, page_id):
        builder = self.page_builders.get(page_id)
        if callable(builder):
            try:
                return builder(self.page_container)
            except Exception:
                import traceback
                traceback.print_exc()
                raise
        return self._placeholder_page(page_id)

    def _placeholder_page(self, page_id):
        frame = ctk.CTkFrame(self.page_container)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        label = ctk.CTkLabel(
            frame,
            text=self.t("app_shell_page_placeholder", default=page_id),
            font=FONT_NORMAL,
            text_color=COLOR_MUTED,
            wraplength=520,
            justify="center"
        )
        label.grid(row=0, column=0, padx=SPACING_LARGE, pady=SPACING_LARGE)
        return frame

    def _refresh_header(self, page_id):
        label_key = dict(self.nav_items).get(page_id, page_id)
        self.page_title.configure(text=self.t(label_key))
        self.page_status.pack_forget()

    def _refresh_nav_state(self):
        for page_id, button in self.nav_buttons.items():
            selected = page_id == self.current_page
            button.configure(font=FONT_HEADER if selected else FONT_NORMAL)

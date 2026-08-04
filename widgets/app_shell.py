import customtkinter as ctk
from tkinter import Menu

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
from widgets.ui_components import PrimaryButton, SecondaryButton, StatusLabel, bind_text_edit_shortcuts


class ConversationList(ctk.CTkScrollableFrame):
    """List-style adapter for ChatPage's existing conversation selector API."""

    MAX_TITLE_LENGTH = 20

    def __init__(self, parent, *, command=None, empty_text="", **kwargs):
        kwargs.setdefault("height", 260)
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.command = command
        self.empty_text = empty_text
        self.values = []
        self.selected = ""
        self.buttons = []
        self.button_titles = {}
        self._context_callback = None

    def configure(self, **kwargs):
        values = kwargs.pop("values", None)
        if values is not None:
            self.values = list(values or [])
            if self.selected not in self.values:
                self.selected = self.values[0] if self.values else ""
            self._render()
        if kwargs:
            super().configure(**kwargs)

    def set(self, value):
        self.selected = value
        if value and value not in self.values:
            self.values = [value]
        self._render()

    def get(self):
        return self.selected

    def cget(self, key):
        if key == "values":
            return list(self.values)
        return super().cget(key)

    def bind(self, sequence=None, func=None, add=None):
        if sequence == "<Button-3>":
            self._context_callback = func
            for button in self.buttons:
                button.bind(sequence, func, add=add)
            return None
        return super().bind(sequence, func, add=add)

    def _render(self):
        for button in self.buttons:
            button.destroy()
        self.buttons = []
        self.button_titles = {}

        display_values = self.values or [self.empty_text]
        for value in display_values:
            selected = value == self.selected
            display_text = self._display_title(value)
            button = ctk.CTkButton(
                self,
                text=display_text,
                anchor="w",
                height=28,
                corner_radius=4,
                fg_color="#E5E7EB" if selected else "transparent",
                hover_color="#E5E7EB",
                text_color="#111827",
                command=lambda item=value: self._select(item)
            )
            button.pack(fill="x", padx=0, pady=(0, SPACING_SMALL))
            button.bind("<Enter>", lambda _event, item=value, widget=button: widget.configure(text=item))
            button.bind(
                "<Leave>",
                lambda _event, item=value, widget=button: widget.configure(text=self._display_title(item))
            )
            if self._context_callback is not None:
                button.bind("<Button-3>", self._context_callback)
            self.buttons.append(button)
            self.button_titles[button] = value

    def _select(self, value):
        if not self.values:
            return
        self.selected = value
        self._render()
        if callable(self.command):
            self.command(value)

    def _display_title(self, value):
        text = str(value or "")
        if len(text) <= self.MAX_TITLE_LENGTH:
            return text
        return text[:self.MAX_TITLE_LENGTH] + "..."


class AppShell(ctk.CTkFrame):
    """Navigation shell for the future v2.6 page-based UI."""

    DEFAULT_SETTINGS_CATEGORIES = [
        ("ai", "AI"),
        ("voice", "Voice"),
        ("appearance", "Appearance"),
        ("data", "Data"),
        ("developer", "Developer")
    ]

    DEFAULT_NAV_ITEMS = [
        ("chat", "nav_chat"),
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
        initial_page_id="chat",
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
        self.initial_page_id = initial_page_id
        self.on_shutdown = on_shutdown
        self.page_frames = {}
        self.nav_buttons = {}
        self.settings_category_buttons = {}
        self.chat_sidebar_page = None
        self.settings_sidebar_page = None

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
            self.show_page(self._initial_page_id())

    def _initial_page_id(self):
        page_ids = {item[0] for item in self.nav_items}
        if self.initial_page_id in page_ids:
            return self.initial_page_id
        return self.nav_items[0][0]

    def _build_sidebar(self):
        self.chat_sidebar = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.settings_sidebar = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self._build_chat_sidebar()
        self._build_settings_sidebar()
        self._show_chat_sidebar()

    def _build_chat_sidebar(self):
        title = ctk.CTkLabel(
            self.chat_sidebar,
            text="Aurora",
            font=FONT_APP_TITLE,
            anchor="w"
        )
        title.pack(fill="x", padx=SPACING_LARGE, pady=(SPACING_LARGE, SPACING_SMALL))

        self.shell_status = StatusLabel(
            self.chat_sidebar,
            status="disabled",
            text="",
            anchor="w",
            justify="left"
        )

        self.new_chat_button = PrimaryButton(
            self.chat_sidebar,
            text=self.t("new_chat"),
            command=self._new_chat_from_sidebar,
            anchor="w",
            fg_color="transparent",
            hover_color="#E5E7EB",
            text_color="#111827"
        )
        self.new_chat_button.pack(fill="x", padx=SPACING_MEDIUM, pady=(SPACING_MEDIUM, SPACING_SMALL))
        self.nav_buttons["chat"] = self.new_chat_button

        self.search_row = ctk.CTkFrame(self.chat_sidebar, fg_color="transparent")
        self.search_row.pack(fill="x", padx=SPACING_MEDIUM, pady=(SPACING_SMALL, SPACING_SMALL))
        self.search_row.grid_columnconfigure(0, weight=1)
        self.search_button = SecondaryButton(
            self.search_row,
            text="🔍",
            command=self._show_conversation_search,
            width=40
        )
        self.search_button.grid(row=0, column=0, sticky="w")
        self.conversation_search_entry = ctk.CTkEntry(
            self.search_row,
            height=28,
            placeholder_text=self.t("chat_window_search_conversations")
        )
        bind_text_edit_shortcuts(self.conversation_search_entry)
        self.conversation_search_entry.bind("<Return>", lambda _event=None: self._search_chat_from_sidebar())

        self.conversation_selector = ConversationList(
            self.chat_sidebar,
            empty_text=self.t("no_conversations"),
            command=lambda _value: self._load_chat_from_sidebar()
        )
        self.conversation_selector.pack(fill="both", expand=True, padx=SPACING_MEDIUM, pady=(0, SPACING_SMALL))
        self.conversation_selector.bind("<Button-3>", self._show_conversation_actions_menu)

        self.conversation_actions_menu = Menu(self, tearoff=0)
        self.conversation_actions_menu.add_command(
            label=self.t("rename_chat"),
            command=self._rename_chat_from_sidebar
        )
        self.conversation_actions_menu.add_command(
            label=self.t("delete_chat"),
            command=self._delete_chat_from_sidebar
        )

        self.settings_button = SecondaryButton(
            self.chat_sidebar,
            text=self.t("nav_settings"),
            command=lambda: self.show_page("settings"),
            anchor="w"
        )
        self.settings_button.pack(side="bottom", fill="x", padx=SPACING_MEDIUM, pady=(SPACING_SMALL, SPACING_SMALL))
        self.nav_buttons["settings"] = self.settings_button

    def _build_settings_sidebar(self):
        self.return_button = SecondaryButton(
            self.settings_sidebar,
            text="← 返回",
            command=lambda: self.show_page("chat"),
            anchor="w"
        )
        self.return_button.pack(fill="x", padx=SPACING_MEDIUM, pady=(SPACING_LARGE, SPACING_MEDIUM))

        ctk.CTkLabel(
            self.settings_sidebar,
            text=self.t("settings"),
            font=FONT_HEADER,
            anchor="w"
        ).pack(fill="x", padx=SPACING_LARGE, pady=(0, SPACING_MEDIUM))

    def _show_chat_sidebar(self):
        self.settings_sidebar.pack_forget()
        self.chat_sidebar.pack(fill="both", expand=True)

    def _show_settings_sidebar(self):
        self.chat_sidebar.pack_forget()
        self.settings_sidebar.pack(fill="both", expand=True)

    def _chat_page(self):
        page = self.page_frames.get("chat")
        if page is None:
            self.show_page("chat")
            page = self.page_frames.get("chat")
        return page

    def _bind_chat_sidebar(self, page):
        if page is self.chat_sidebar_page:
            return
        binder = getattr(page, "attach_sidebar_conversation_controls", None)
        if callable(binder):
            binder(self.conversation_search_entry, self.conversation_selector)
            self.chat_sidebar_page = page

    def _bind_settings_sidebar(self, page):
        if page is self.settings_sidebar_page:
            return
        for button in self.settings_category_buttons.values():
            button.destroy()
        self.settings_category_buttons = {}

        categories = getattr(page, "CATEGORIES", self.DEFAULT_SETTINGS_CATEGORIES)
        for category_id, label_key in categories:
            button = SecondaryButton(
                self.settings_sidebar,
                text=self.t(label_key),
                command=lambda value=category_id: self._show_settings_category(value),
                anchor="w"
            )
            button.pack(fill="x", padx=SPACING_MEDIUM, pady=SPACING_SMALL)
            self.settings_category_buttons[category_id] = button

        use_external_sidebar = getattr(page, "use_external_sidebar", None)
        if callable(use_external_sidebar):
            use_external_sidebar()
        self.settings_sidebar_page = page
        self._refresh_settings_nav_state()

    def _show_settings_category(self, category_id):
        page = self._settings_page()
        if page is not None:
            page.show_category(category_id)
            self._refresh_settings_nav_state()

    def _settings_page(self):
        page = self.page_frames.get("settings")
        if page is None:
            self.show_page("settings")
            page = self.page_frames.get("settings")
        return page

    def _new_chat_from_sidebar(self):
        page = self._chat_page()
        if page is not None:
            page.new_conversation()

    def _search_chat_from_sidebar(self):
        page = self._chat_page()
        if page is not None:
            page.search_conversation_list()
        self._hide_conversation_search()
        return "break"

    def _show_conversation_search(self):
        self.search_button.grid_remove()
        self.conversation_search_entry.grid(row=0, column=0, sticky="ew")
        self.conversation_search_entry.focus_set()

    def _hide_conversation_search(self):
        try:
            self.conversation_search_entry.delete(0, "end")
        except Exception:
            pass
        self.conversation_search_entry.grid_remove()
        self.search_button.grid(row=0, column=0, sticky="w")

    def _load_chat_from_sidebar(self):
        page = self._chat_page()
        if page is not None:
            page.load_conversation()

    def _rename_chat_from_sidebar(self):
        page = self._chat_page()
        if page is not None:
            page.rename_conversation()

    def _delete_chat_from_sidebar(self):
        page = self._chat_page()
        if page is not None:
            page.delete_conversation()

    def _show_conversation_actions_menu(self, event):
        try:
            self.conversation_actions_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.conversation_actions_menu.grab_release()
        return "break"

    def _refresh_settings_nav_state(self):
        page = self.page_frames.get("settings")
        current_category = getattr(page, "current_category", None)
        for category_id, button in self.settings_category_buttons.items():
            selected = category_id == current_category
            button.configure(font=FONT_HEADER if selected else FONT_NORMAL)

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
            if page_id == "chat":
                self._bind_chat_sidebar(self.page_frames[page_id])
            elif page_id == "settings":
                self._bind_settings_sidebar(self.page_frames[page_id])

        frame = self.page_frames[page_id]
        frame.grid(row=0, column=0, sticky="nsew")
        self.current_page = page_id
        if page_id == "settings":
            self._show_settings_sidebar()
            self._refresh_settings_nav_state()
        else:
            self._show_chat_sidebar()
        self._refresh_nav_state()
        self._refresh_header(page_id)

        on_show = getattr(frame, "on_show", None)
        if callable(on_show):
            on_show()

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
        if page_id == "chat":
            self.page_header.grid_remove()
        else:
            self.page_header.grid()
            self.page_title.configure(text=self.t(label_key))
        self.page_status.pack_forget()

    def _refresh_nav_state(self):
        for page_id, button in self.nav_buttons.items():
            selected = page_id == self.current_page
            button.configure(font=FONT_HEADER if selected else FONT_NORMAL)

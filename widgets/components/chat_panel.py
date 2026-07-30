import re
from tkinter import Menu

import customtkinter as ctk

from modules.ui_theme import (
    COLOR_MUTED,
    FONT_BODY,
    FONT_HEADER,
    FONT_NORMAL_BOLD,
    FONT_SMALL,
    FONT_TITLE,
    SPACING_SMALL,
    SPACING_MEDIUM,
    SPACING_LARGE
)
from modules.version import RELEASE
from widgets.ui_components import (
    PrimaryButton,
    SecondaryButton,
    SectionCard,
    StatusLabel
)
from widgets.components.workspace_header import WorkspaceHeader
from widgets.components.workspace_empty_state import WorkspaceEmptyState


class ChatPanel(ctk.CTkFrame):
    """Reusable chat UI panel shared by the chat window and future chat page."""

    def __init__(
        self,
        parent,
        *,
        translate,
        settings,
        debug_context_var,
        new_conversation_callback,
        search_conversation_callback,
        load_conversation_callback,
        model_selected_callback,
        save_conversation_callback,
        rename_conversation_callback,
        delete_conversation_callback,
        close_callback,
        send_prompt_callback,
        stop_generation_callback,
        preview_context_callback,
        clear_chat_callback,
        show_header_title=True,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.t = translate
        self.settings = settings
        self.debug_context_var = debug_context_var
        self.new_conversation_callback = new_conversation_callback
        self.search_conversation_callback = search_conversation_callback
        self.load_conversation_callback = load_conversation_callback
        self.model_selected_callback = model_selected_callback
        self.save_conversation_callback = save_conversation_callback
        self.rename_conversation_callback = rename_conversation_callback
        self.delete_conversation_callback = delete_conversation_callback
        self.close_callback = close_callback
        self.send_prompt_callback = send_prompt_callback
        self.stop_generation_callback = stop_generation_callback
        self.preview_context_callback = preview_context_callback
        self.clear_chat_callback = clear_chat_callback
        self.show_header_title = show_header_title
        self.buttons = {}
        self.input_default_height = 72
        self.input_line_height = 24

        self.build()

    def build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.workspace_header = WorkspaceHeader(
            self,
            title="Aurora Chat",
            description=self.t("workspace_chat_description"),
            status="disabled",
            status_text=self.t("chat_window_loading_models"),
            show_status=False,
            show_title=self.show_header_title
        )
        self.workspace_header.grid_with_workspace_padding()
        self.header_model_label = self.workspace_header.status_label

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=SPACING_LARGE + SPACING_SMALL,
            pady=(0, SPACING_LARGE)
        )
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=0, minsize=280)
        body.grid_columnconfigure(1, weight=1)

        left_panel = ctk.CTkFrame(body, width=280)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING_MEDIUM))
        left_panel.grid_propagate(False)
        left_panel.grid_columnconfigure(0, weight=1)
        left_panel.grid_rowconfigure(5, weight=1)
        ctk.CTkLabel(left_panel, text=self.t("conversation_list"), font=FONT_HEADER).grid(
            row=0,
            column=0,
            sticky="w",
            padx=SPACING_MEDIUM,
            pady=(SPACING_MEDIUM, SPACING_SMALL)
        )
        new_chat_button = PrimaryButton(left_panel, text=self.t("new_chat"), command=self.new_conversation_callback)
        new_chat_button.grid(row=1, column=0, sticky="ew", padx=SPACING_MEDIUM, pady=(0, SPACING_MEDIUM))
        ctk.CTkLabel(left_panel, text=self.t("chat_window_search_conversations"), font=FONT_SMALL).grid(
            row=2,
            column=0,
            sticky="w",
            padx=SPACING_MEDIUM,
            pady=(0, SPACING_SMALL)
        )
        self.conversation_search_entry = ctk.CTkEntry(left_panel)
        self.conversation_search_entry.grid(row=3, column=0, sticky="ew", padx=SPACING_MEDIUM, pady=(0, SPACING_SMALL))
        search_button = SecondaryButton(
            left_panel,
            text=self.t("chat_window_search"),
            command=self.search_conversation_callback
        )
        search_button.grid(row=4, column=0, sticky="ew", padx=SPACING_MEDIUM, pady=(0, SPACING_MEDIUM))
        self.conversation_selector = ctk.CTkOptionMenu(
            left_panel,
            values=[self.t("no_conversations")],
            command=lambda _value: self.load_conversation_callback()
        )
        self.conversation_selector.grid(row=5, column=0, sticky="new", padx=SPACING_MEDIUM, pady=(0, SPACING_MEDIUM))

        sidebar_status = ctk.CTkFrame(left_panel, height=176)
        sidebar_status.grid(row=6, column=0, sticky="ew", padx=SPACING_MEDIUM, pady=(SPACING_SMALL, SPACING_MEDIUM))
        sidebar_status.grid_propagate(False)
        sidebar_status.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(sidebar_status, text=self.t("aurora_status"), font=FONT_SMALL).grid(
            row=0,
            column=0,
            sticky="w",
            padx=SPACING_SMALL,
            pady=(SPACING_SMALL, 0)
        )
        self.chat_status = StatusLabel(
            sidebar_status,
            status="disabled",
            text=self.t("loading_ollama_models"),
            anchor="w",
            justify="left"
        )
        self.chat_status.grid(row=1, column=0, sticky="ew", padx=SPACING_SMALL, pady=(SPACING_SMALL, 0))
        self.sidebar_model_status = self.add_sidebar_status(
            sidebar_status,
            2,
            f"{self.t('model')}: {self.t('chat_window_loading_models')}"
        )
        self.sidebar_persona_status = self.add_sidebar_status(
            sidebar_status,
            3,
            self.compact_status_text(self.t("persona"), True)
        )
        self.sidebar_memory_status = self.add_sidebar_status(
            sidebar_status,
            4,
            self.compact_status_text(self.t("memory"), True)
        )
        self.sidebar_knowledge_status = self.add_sidebar_status(
            sidebar_status,
            5,
            self.compact_status_text(self.t("knowledge"), True)
        )
        ctk.CTkLabel(sidebar_status, text=f"Aurora {RELEASE}", font=FONT_SMALL, text_color=COLOR_MUTED).grid(
            row=6,
            column=0,
            sticky="w",
            padx=SPACING_SMALL,
            pady=(SPACING_SMALL, 0)
        )

        more_button = SecondaryButton(
            left_panel,
            text=self.t("more_actions"),
            command=lambda: self.show_conversation_actions_menu(more_button)
        )
        more_button.grid(row=7, column=0, sticky="ew", padx=SPACING_MEDIUM, pady=(0, SPACING_MEDIUM))
        self.conversation_actions_menu = Menu(self, tearoff=0)
        self.conversation_actions_menu.add_command(label=self.t("save_chat"), command=self.save_conversation_callback)
        self.conversation_actions_menu.add_command(label=self.t("rename_chat"), command=self.rename_conversation_callback)
        self.conversation_actions_menu.add_separator()
        self.conversation_actions_menu.add_command(label=self.t("delete_chat"), command=self.delete_conversation_callback)
        self.conversation_actions_menu.add_separator()
        self.conversation_actions_menu.add_command(
            label=self.t("chat_window_context_button"),
            command=self.preview_context_callback
        )
        self.conversation_actions_menu.add_checkbutton(
            label=self.t("show_chat_context_debug_info"),
            variable=self.debug_context_var
        )
        self.conversation_actions_menu.add_separator()
        self.conversation_actions_menu.add_command(label=self.t("close"), command=self.close_callback)

        center_panel = ctk.CTkFrame(body, fg_color="transparent")
        center_panel.grid(row=0, column=1, sticky="nsew")
        center_panel.grid_rowconfigure(1, weight=1)
        center_panel.grid_columnconfigure(0, weight=1)

        chat_header = ctk.CTkFrame(center_panel, fg_color="transparent")
        chat_header.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_SMALL))
        chat_header.grid_columnconfigure(0, weight=1)
        self.current_title_label = ctk.CTkLabel(chat_header, text=self.t("chat"), font=FONT_HEADER)
        self.current_title_label.grid(row=0, column=0, sticky="w")
        self.model_inline_label = ctk.CTkLabel(chat_header, text=self.t("chat_window_loading_models"), font=FONT_SMALL)
        self.model_selector = ctk.CTkOptionMenu(
            chat_header,
            values=[self.t("chat_window_loading_models")],
            command=self.model_selected_callback
        )
        self.context_model_status = self.sidebar_model_status
        self.context_persona_status = self.sidebar_persona_status
        self.context_memory_status = self.sidebar_memory_status
        self.context_knowledge_status = self.sidebar_knowledge_status
        self.debug_switch = None

        chat_card = SectionCard(center_panel, self.t("chat_messages"))
        chat_card.grid(row=1, column=0, sticky="nsew", pady=(0, SPACING_MEDIUM))
        chat_card.body.grid_rowconfigure(0, weight=1)
        chat_card.body.grid_columnconfigure(0, weight=1)
        self.chat_display = ctk.CTkTextbox(chat_card.body, wrap="word", font=FONT_BODY, border_spacing=14)
        self.chat_display.grid(row=0, column=0, sticky="nsew")
        self.configure_chat_tags()
        self.chat_display.configure(state="disabled")
        self.empty_state = WorkspaceEmptyState(
            chat_card.body,
            title=self.t("workspace_empty_chat_title"),
            description=self.t("workspace_empty_chat_description"),
            action_text=self.t("new_chat"),
            action_callback=self.new_conversation_callback
        )
        self.empty_state.grid(row=0, column=0, sticky="nsew")

        input_card = SectionCard(center_panel, self.t("input_box"))
        input_card.grid(row=2, column=0, sticky="ew")
        input_card.body.grid_columnconfigure(0, weight=1)
        self.input_box = ctk.CTkTextbox(
            input_card.body,
            height=self.input_default_height,
            wrap="word",
            font=FONT_BODY,
            border_spacing=12
        )
        self.input_box.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_SMALL))
        self.input_box.bind("<Return>", self.handle_input_return)
        self.input_box.bind("<Shift-Return>", self.handle_input_shift_return)
        self.input_box.bind("<KeyRelease>", self.resize_input_box)
        self.attach_text_menu(self.input_box)

        input_actions = ctk.CTkFrame(input_card.body, fg_color="transparent")
        input_actions.grid(row=1, column=0, sticky="ew")
        input_actions.grid_columnconfigure(0, weight=1)

        input_hint = ctk.CTkLabel(input_actions, text="", font=FONT_SMALL)
        input_hint.grid(row=0, column=0, sticky="ew", padx=(0, SPACING_MEDIUM))

        button_specs = [
            (input_actions, 0, 1, PrimaryButton, self.t("send"), self.send_prompt_callback),
            (input_actions, 0, 2, SecondaryButton, self.t("stop_generate"), self.stop_generation_callback),
            (input_actions, 0, 3, SecondaryButton, self.t("clear"), self.clear_chat_callback),
            (chat_header, 0, 1, SecondaryButton, self.t("chat_window_context_button"), self.preview_context_callback),
        ]
        for parent, row, column, button_class, label, command in button_specs:
            button = button_class(parent, text=label, command=command)
            button.grid(row=row, column=column, sticky="ew", padx=SPACING_SMALL, pady=SPACING_SMALL)
            self.buttons[label] = button
        self.buttons[self.t("new_chat")] = new_chat_button
        self.buttons[self.t("chat_window_search")] = search_button
        self.buttons[self.t("more_actions")] = more_button
        self.buttons[self.t("stop_generate")].configure(state="disabled")
        self.refresh_context_statuses()

    def show_conversation_actions_menu(self, button):
        try:
            x = button.winfo_rootx()
            y = button.winfo_rooty() + button.winfo_height()
            self.conversation_actions_menu.tk_popup(x, y)
        finally:
            self.conversation_actions_menu.grab_release()

    def add_sidebar_status(self, parent, row, text):
        status = StatusLabel(parent, status="healthy", text=text, anchor="w", justify="left")
        status.grid(row=row, column=0, sticky="ew", padx=SPACING_SMALL, pady=(SPACING_SMALL, 0))
        return status

    def configure_chat_tags(self):
        try:
            self.chat_display.tag_config("role_user", foreground="#2563EB", font=FONT_NORMAL_BOLD)
            self.chat_display.tag_config("role_assistant", foreground="#2E7D32", font=FONT_NORMAL_BOLD)
            self.chat_display.tag_config("role_notice", foreground=COLOR_MUTED, font=FONT_BODY)
            self.chat_display.tag_config("message_body", lmargin1=8, lmargin2=8, spacing1=4, spacing3=12)
        except Exception:
            return

    def set_status(self, text, status="disabled"):
        self.chat_status.set_status(status, text=text)

    def enabled_state_text(self, enabled):
        return self.t("enabled") if enabled else self.t("disabled")

    @staticmethod
    def compact_status_text(label, enabled):
        marker = "\u2713" if enabled else "-"
        return f"{label} {marker}"

    def refresh_context_statuses(self):
        persona_enabled = bool(self.settings.get("persona.enabled", True))
        knowledge_enabled = bool(self.settings.get("knowledge.enabled", True))
        self.context_persona_status.set_status(
            "healthy" if persona_enabled else "disabled",
            text=self.compact_status_text(self.t("persona"), persona_enabled)
        )
        self.sidebar_persona_status.set_status(
            "healthy" if persona_enabled else "disabled",
            text=self.compact_status_text(self.t("persona"), persona_enabled)
        )
        self.context_memory_status.set_status("healthy", text=self.compact_status_text(self.t("memory"), True))
        self.sidebar_memory_status.set_status("healthy", text=self.compact_status_text(self.t("memory"), True))
        self.context_knowledge_status.set_status(
            "healthy" if knowledge_enabled else "disabled",
            text=self.compact_status_text(self.t("knowledge"), knowledge_enabled)
        )
        self.sidebar_knowledge_status.set_status(
            "healthy" if knowledge_enabled else "disabled",
            text=self.compact_status_text(self.t("knowledge"), knowledge_enabled)
        )

    def set_model_display(self, model_name, status="healthy"):
        text = model_name or self.t("chat_page_model_unknown")
        header_text = f"{text} \u25cf {self.t('local_model_status')}" if model_name else text
        self.model_inline_label.configure(text=text)
        self.context_model_status.set_status(status, text=text)
        self.sidebar_model_status.set_status(status, text=f"{self.t('model')}: {text}")

    def update_model_selector(self, values, selected):
        self.model_selector.configure(values=values)
        self.model_selector.set(selected)

    def render_messages(self, messages):
        self.chat_display.configure(state="normal")
        self.chat_display.delete("1.0", "end")
        visible_count = 0
        for message in messages or []:
            if not isinstance(message, dict) or message.get("role") == "system":
                continue
            role = "user" if message.get("role") == "user" else "assistant"
            self.insert_message(role, message.get("content", ""))
            visible_count += 1
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")
        if visible_count:
            self.hide_empty_state()
        else:
            self.show_empty_state()

    def show_empty_state(self):
        self.empty_state.grid()
        self.empty_state.lift()

    def hide_empty_state(self):
        self.empty_state.grid_remove()

    def focus_input(self):
        try:
            self.input_box.focus_set()
        except Exception:
            return

    def resize_input_box(self, _event=None):
        try:
            content = self.input_box.get("1.0", "end-1c")
            line_count = max(3, min(6, content.count("\n") + 1))
            self.input_box.configure(height=max(self.input_default_height, line_count * self.input_line_height + 24))
        except Exception:
            return

    def reset_input_box_height(self):
        try:
            self.input_box.configure(height=self.input_default_height)
        except Exception:
            return

    @staticmethod
    def text_at_bottom(textbox):
        try:
            _first, last = textbox.yview()
            return last >= 0.98
        except Exception:
            return True

    def insert_message(self, role, content=""):
        role_label = self.t("chat_window_user_label") if role == "user" else "Aurora"
        role_tag = "role_user" if role == "user" else "role_assistant"
        self.chat_display.insert("end", f"{role_label}:\n", role_tag)
        if content:
            self.chat_display.insert("end", f"{self.display_text(content)}\n\n", "message_body")

    def append_message(self, role, content):
        self.hide_empty_state()
        self.chat_display.configure(state="normal")
        self.insert_message(role, content)
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def append_assistant_header(self):
        self.hide_empty_state()
        self.chat_display.configure(state="normal")
        self.insert_message("assistant")
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def finish_stream_message(self):
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", "\n\n", "message_body")
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def append_text(self, text):
        self.hide_empty_state()
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", self.display_text(text) + "\n\n", "role_notice")
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def append_stream_chunk(self, chunk):
        self.hide_empty_state()
        auto_scroll = self.text_at_bottom(self.chat_display)
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", self.display_text(chunk), "message_body")
        if auto_scroll:
            self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def clear_display(self):
        self.chat_display.configure(state="normal")
        self.chat_display.delete("1.0", "end")
        self.chat_display.configure(state="disabled")
        self.show_empty_state()

    def handle_input_return(self, _event=None):
        self.send_prompt_callback()
        return "break"

    def handle_input_shift_return(self, _event=None):
        self.input_box.insert("insert", "\n")
        self.after(0, self.resize_input_box)
        return "break"

    def attach_text_menu(self, widget):
        menu = Menu(widget, tearoff=0)
        menu.add_command(label=self.t("edit_cut"), command=lambda: self.run_text_menu_action(widget, "<<Cut>>"))
        menu.add_command(label=self.t("edit_copy"), command=lambda: self.run_text_menu_action(widget, "<<Copy>>"))
        menu.add_command(label=self.t("edit_paste"), command=lambda: self.run_text_menu_action(widget, "<<Paste>>"))
        menu.add_command(label=self.t("edit_delete"), command=lambda: self.delete_selection(widget))
        menu.add_separator()
        menu.add_command(label=self.t("edit_select_all"), command=lambda: self.select_all_text(widget))

        def show_menu(event):
            try:
                self.focus_text_widget(widget, event)
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
            return "break"

        widget.bind("<Button-3>", show_menu)

    @staticmethod
    def text_widget(widget):
        return getattr(widget, "_textbox", widget)

    def focus_text_widget(self, widget, event=None):
        target = self.text_widget(widget)
        try:
            widget.focus_set()
            target.focus_set()
            if event is not None:
                target.mark_set("insert", f"@{event.x},{event.y}")
        except Exception:
            return target
        return target

    def run_text_menu_action(self, widget, action):
        target = self.focus_text_widget(widget)
        target.event_generate(action)
        if widget is self.input_box:
            self.after(0, self.resize_input_box)

    def delete_selection(self, widget):
        target = self.focus_text_widget(widget)
        try:
            target.delete("sel.first", "sel.last")
        except Exception:
            return
        if widget is self.input_box:
            self.after(0, self.resize_input_box)

    def select_all_text(self, widget):
        target = self.focus_text_widget(widget)
        try:
            target.tag_add("sel", "1.0", "end")
            target.mark_set("insert", "end")
        except Exception:
            return
        return "break"

    @staticmethod
    def display_text(value):
        return re.sub(
            r"\[(?:fact|preference|habit|instruction|project|temporary)\]\s*",
            "",
            str(value or "")
        )

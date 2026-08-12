import re
from tkinter import Menu

import customtkinter as ctk

from modules.logger import logger
from modules.ui_theme import (
    COLOR_MUTED,
    COLOR_TEXT_ON_LIGHT,
    COLOR_TEXT_PRIMARY,
    FONT_BODY,
    FONT_HEADER,
    FONT_NORMAL_BOLD,
    FONT_SMALL,
    FONT_TITLE,
    SPACING_SMALL,
    SPACING_MEDIUM,
    SPACING_LARGE
)
from widgets.ui_components import (
    PrimaryButton,
    SecondaryButton,
    StatusLabel,
    bind_text_edit_shortcuts
)


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
        voice_start_callback=None,
        voice_cancel_callback=None,
        voice_available=False,
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
        self.voice_start_callback = voice_start_callback
        self.voice_cancel_callback = voice_cancel_callback
        self.voice_available = bool(voice_available)
        self.show_header_title = show_header_title
        self.buttons = {}
        self.input_mode = "idle"
        self.voice_active = False
        self.input_default_height = 72
        self.input_line_height = 24
        self._input_has_focus = False
        self._input_placeholder_visible = False
        self.message_rows = []
        self._streaming_assistant_label = None
        self._streaming_assistant_text = ""

        self.build()

    def build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.header_model_label = StatusLabel(self, status="disabled", text="")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=SPACING_LARGE + SPACING_SMALL,
            pady=(SPACING_LARGE, SPACING_LARGE)
        )
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        center_panel = ctk.CTkFrame(body, fg_color="transparent")
        center_panel.grid(row=0, column=0, sticky="nsew")
        center_panel.grid_rowconfigure(0, weight=0)
        center_panel.grid_rowconfigure(1, weight=1)
        center_panel.grid_rowconfigure(2, weight=0)
        center_panel.grid_columnconfigure(0, weight=1)

        chat_header = ctk.CTkFrame(center_panel, fg_color="transparent")
        chat_header.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_SMALL))
        chat_header.grid_columnconfigure(0, weight=1)
        self.current_title_label = ctk.CTkLabel(chat_header, text="", font=FONT_HEADER)
        self.current_title_label.grid(row=0, column=0, sticky="w")
        self.model_inline_label = ctk.CTkLabel(chat_header, text=self.t("chat_window_loading_models"), font=FONT_SMALL)
        self.model_selector = ctk.CTkOptionMenu(
            chat_header,
            values=[self.t("chat_window_loading_models")],
            command=self.model_selected_callback
        )
        self.chat_status = StatusLabel(chat_header, status="disabled", text=self.t("loading_ollama_models"))
        self.context_model_status = StatusLabel(chat_header, status="disabled", text="")
        self.context_persona_status = StatusLabel(chat_header, status="disabled", text="")
        self.context_memory_status = StatusLabel(chat_header, status="disabled", text="")
        self.context_knowledge_status = StatusLabel(chat_header, status="disabled", text="")
        self.debug_switch = None
        more_button = SecondaryButton(
            chat_header,
            text=self.t("more_actions"),
            command=self._show_input_more_menu
        )
        more_button.grid(row=0, column=1, sticky="e", padx=(SPACING_SMALL, 0))
        self.buttons[self.t("more_actions")] = more_button

        message_area = ctk.CTkFrame(center_panel, fg_color="transparent")
        message_area.grid(row=1, column=0, sticky="nsew", pady=(0, SPACING_MEDIUM))
        message_area.grid_rowconfigure(0, weight=1)
        message_area.grid_columnconfigure(0, weight=1)
        self.chat_display = ctk.CTkScrollableFrame(
            message_area,
            fg_color="transparent",
        )
        self.chat_display.grid(row=0, column=0, sticky="nsew")
        self.chat_display.grid_columnconfigure(0, weight=1)
        self.chat_display.bind("<Configure>", self._resize_message_bubbles, add="+")
        self.empty_state = ctk.CTkFrame(message_area, fg_color="transparent")
        self.empty_state.grid_columnconfigure(0, weight=1)
        self.empty_state.grid_rowconfigure(0, weight=1)
        self.empty_state.grid_rowconfigure(3, weight=1)
        ctk.CTkLabel(
            self.empty_state,
            text="你好，我是 Aurora",
            font=FONT_TITLE,
            anchor="center"
        ).grid(row=1, column=0, sticky="ew", pady=(0, SPACING_SMALL))
        ctk.CTkLabel(
            self.empty_state,
            text="今天想聊些什么？",
            font=FONT_BODY,
            text_color=COLOR_MUTED,
            anchor="center"
        ).grid(row=2, column=0, sticky="ew")
        self.empty_state.grid(row=0, column=0, sticky="nsew")

        input_card = ctk.CTkFrame(
            center_panel,
            corner_radius=22,
            fg_color="#F9FAFB",
            border_width=1,
            border_color="#E5E7EB"
        )
        input_card.grid(row=2, column=0, sticky="ew")
        input_card.grid_rowconfigure(0, weight=0)
        input_card.grid_columnconfigure(0, weight=1)
        input_card.grid_columnconfigure(1, weight=0)
        self.input_box = ctk.CTkTextbox(
            input_card,
            height=self.input_default_height,
            wrap="word",
            font=FONT_BODY,
            border_spacing=12,
            fg_color="transparent",
            border_width=0,
            text_color="#111827"
        )
        self.input_box.grid(row=0, column=0, sticky="ew", padx=(SPACING_MEDIUM, SPACING_SMALL), pady=SPACING_SMALL)
        self.input_placeholder_label = ctk.CTkLabel(
            input_card,
            text="输入消息...",
            font=FONT_BODY,
            text_color=COLOR_MUTED,
            anchor="w"
        )
        self.input_placeholder_label.grid(row=0, column=0, sticky="w", padx=(SPACING_LARGE, SPACING_SMALL))
        self._input_placeholder_visible = True
        self.input_placeholder_label.bind("<Button-1>", lambda _event=None: self.focus_input())
        bind_text_edit_shortcuts(self.input_box)
        self.input_box.bind("<Return>", self.handle_input_return)
        self.input_box.bind("<Shift-Return>", self.handle_input_shift_return)
        self.input_box.bind("<KeyRelease>", self.resize_input_box)
        self.input_box.bind("<FocusIn>", self._handle_input_focus_in, add="+")
        self.input_box.bind("<FocusOut>", self._handle_input_focus_out, add="+")
        self.attach_text_menu(self.input_box)

        input_actions = ctk.CTkFrame(input_card, fg_color="transparent")
        input_actions.grid(row=0, column=1, sticky="se", padx=(0, SPACING_MEDIUM), pady=SPACING_SMALL)
        input_actions.grid_columnconfigure(0, weight=0)
        input_actions.grid_columnconfigure(1, weight=0)

        self.voice_state_label = ctk.CTkLabel(
            input_actions,
            text="IDLE  Aurora Ready",
            font=FONT_SMALL,
            text_color=COLOR_MUTED,
            anchor="e"
        )

        button_specs = [
            (input_actions, 0, 0, SecondaryButton, "Voice", "🎤", self._toggle_voice),
            (input_actions, 0, 1, PrimaryButton, self.t("send"), "↑", self._send_prompt),
            (input_actions, 0, 0, SecondaryButton, self.t("stop_generate"), "■", self._stop_generation),
        ]
        for parent, row, column, button_class, label, text, command in button_specs:
            button = button_class(parent, text=text, command=command, width=40, height=36)
            if label == self.t("send"):
                button.configure(fg_color="#111827", hover_color="#374151", text_color="white", corner_radius=18)
            else:
                button.configure(fg_color="transparent", hover_color="#E5E7EB", text_color="#111827", corner_radius=18)
            button.grid(row=row, column=column, sticky="ew", padx=SPACING_SMALL, pady=SPACING_SMALL)
            self.buttons[label] = button
        self.input_more_menu = Menu(self, tearoff=0)
        self.input_more_menu.add_command(label=self.t("clear"), command=self.clear_chat_callback)
        self.input_more_menu.add_separator()
        self.input_more_menu.add_command(
            label=self.t("chat_window_context_button"),
            command=self.preview_context_callback
        )
        self.input_more_menu.add_checkbutton(
            label=self.t("show_chat_context_debug_info"),
            variable=self.debug_context_var
        )
        self.buttons[self.t("stop_generate")].configure(state="disabled")
        if not self.voice_available:
            self.buttons["Voice"].configure(state="disabled")
        self.refresh_context_statuses()
        self._show_idle_actions()

    def _send_prompt(self):
        self._show_generating_actions()
        self.send_prompt_callback()

    def _stop_generation(self):
        self.stop_generation_callback()

    def _show_input_more_menu(self):
        button = self.buttons[self.t("more_actions")]
        try:
            x = button.winfo_rootx()
            y = button.winfo_rooty() + button.winfo_height()
            self.input_more_menu.tk_popup(x, y)
        finally:
            self.input_more_menu.grab_release()

    def _grid_action(self, label, row=0, column=0):
        button = self.buttons[label]
        button.grid(row=row, column=column, sticky="ew", padx=SPACING_SMALL, pady=SPACING_SMALL)

    def _hide_input_actions(self):
        for label in ["Voice", self.t("send"), self.t("stop_generate")]:
            button = self.buttons.get(label)
            if button is not None:
                button.grid_remove()
        self.voice_state_label.grid_remove()

    def _show_idle_actions(self):
        self.input_mode = "idle"
        self._hide_input_actions()
        self._grid_action("Voice", 0, 0)
        self._grid_action(self.t("send"), 0, 1)

    def _show_voice_actions(self):
        self.input_mode = "voice"
        self._hide_input_actions()
        self.voice_state_label.grid(row=0, column=0, sticky="e", padx=SPACING_SMALL, pady=SPACING_SMALL)
        self._grid_action("Voice", 0, 1)

    def _show_generating_actions(self):
        self.input_mode = "generating"
        self._hide_input_actions()
        self._grid_action(self.t("stop_generate"), 0, 0)

    def _toggle_voice(self):
        logger.info(
            f"ChatPanel._toggle_voice clicked voice_available={self.voice_available} "
            f"voice_runtime_callback={callable(self.voice_start_callback)}"
        )
        if not self.voice_available:
            logger.info("ChatPanel._toggle_voice ignored: Voice unavailable")
            return
        if callable(self.voice_cancel_callback) and self.voice_active:
            logger.info("ChatPanel._toggle_voice calling voice_cancel_callback")
            self.voice_cancel_callback()
            return
        if callable(self.voice_start_callback):
            logger.info("ChatPanel._toggle_voice calling voice_start_callback")
            self.voice_start_callback()
        else:
            logger.warning("ChatPanel._toggle_voice ignored: voice_start_callback missing")

    def set_voice_state(self, state, text):
        self.voice_state_label.configure(text=f"{state}  {text}")
        if "Voice" not in self.buttons:
            return
        active = state in {"VOICE_READY", "LISTENING", "TRANSCRIBING", "THINKING", "SPEAKING"}
        self.voice_active = active
        self.buttons["Voice"].configure(
            text="■" if active else "🎤",
            state="normal" if self.voice_available else "disabled"
        )
        if active:
            self._show_voice_actions()
        elif self.input_mode == "voice":
            self._show_idle_actions()

    def add_sidebar_status(self, parent, row, text):
        status = StatusLabel(parent, status="healthy", text=text, anchor="w", justify="left")
        status.grid(row=row, column=0, sticky="ew", padx=SPACING_SMALL, pady=(SPACING_SMALL, 0))
        return status

    def configure_chat_tags(self):
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
        self.context_memory_status.set_status("healthy", text=self.compact_status_text(self.t("memory"), True))
        self.context_knowledge_status.set_status(
            "healthy" if knowledge_enabled else "disabled",
            text=self.compact_status_text(self.t("knowledge"), knowledge_enabled)
        )

    def set_model_display(self, model_name, status="healthy"):
        text = model_name or self.t("chat_page_model_unknown")
        header_text = f"{text} \u25cf {self.t('local_model_status')}" if model_name else text
        self.model_inline_label.configure(text=text)
        self.context_model_status.set_status(status, text=text)

    def update_model_selector(self, values, selected):
        self.model_selector.configure(values=values)
        self.model_selector.set(selected)

    def render_messages(self, messages):
        for row in self.message_rows:
            row.destroy()
        self.message_rows = []
        self._streaming_assistant_label = None
        self._streaming_assistant_text = ""
        visible_count = 0
        for message in messages or []:
            if not isinstance(message, dict) or message.get("role") == "system":
                continue
            role = "user" if message.get("role") == "user" else "assistant"
            self.insert_message(role, message.get("content", ""))
            visible_count += 1
        self._scroll_messages()
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
            self._sync_input_action_mode()
            self.input_box.focus_set()
            self._handle_input_focus_in()
        except Exception:
            return

    def _sync_input_action_mode(self):
        if self.voice_active:
            self._show_voice_actions()
            return
        stop_button = self.buttons.get(self.t("stop_generate"))
        try:
            stop_enabled = stop_button is not None and stop_button.cget("state") != "disabled"
        except Exception:
            stop_enabled = False
        if stop_enabled:
            self._show_generating_actions()
        else:
            self._show_idle_actions()

    def resize_input_box(self, _event=None):
        try:
            content = self.input_box.get("1.0", "end-1c")
            line_count = max(3, min(6, content.count("\n") + 1))
            self.input_box.configure(height=max(self.input_default_height, line_count * self.input_line_height + 24))
            self._refresh_input_placeholder()
        except Exception:
            return

    def _refresh_input_placeholder(self, _event=None):
        try:
            content = self.input_box.get("1.0", "end-1c").strip()
            self._set_input_placeholder_visible(not self._input_has_focus and not content)
        except Exception:
            return

    def _handle_input_focus_in(self, _event=None):
        self._input_has_focus = True
        self._set_input_placeholder_visible(False)

    def _handle_input_focus_out(self, _event=None):
        self._input_has_focus = False
        self._refresh_input_placeholder()

    def _set_input_placeholder_visible(self, visible):
        visible = bool(visible)
        if visible == self._input_placeholder_visible:
            return
        if visible:
            self.input_placeholder_label.grid()
            self.input_placeholder_label.lift()
        else:
            self.input_placeholder_label.grid_remove()
        self._input_placeholder_visible = visible

    def reset_input_box_height(self):
        try:
            self.input_box.configure(height=self.input_default_height)
        except Exception:
            return

    @staticmethod
    def _message_role_color(role):
        return "#E5E7EB" if role == "user" else "transparent"

    def insert_message(self, role, content=""):
        row = ctk.CTkFrame(self.chat_display, fg_color="transparent")
        row.grid(row=len(self.message_rows), column=0, sticky="ew", padx=SPACING_MEDIUM, pady=(0, SPACING_MEDIUM))
        row.grid_columnconfigure(0, weight=1)
        bubble = ctk.CTkLabel(
            row,
            text=self.display_text(content),
            font=FONT_BODY,
            anchor="w",
            justify="left",
            wraplength=520,
            fg_color=self._message_role_color(role),
            text_color=COLOR_TEXT_ON_LIGHT if role == "user" else COLOR_TEXT_PRIMARY,
            corner_radius=14 if role == "user" else 0,
        )
        if role == "user":
            bubble.grid(row=0, column=0, sticky="e", padx=(0, SPACING_LARGE), ipadx=10, ipady=8)
        else:
            bubble.grid(row=0, column=0, sticky="w", padx=(SPACING_SMALL, 0), ipadx=2, ipady=2)
        self.message_rows.append(row)
        if role == "assistant" and content == "":
            self._streaming_assistant_label = bubble
            self._streaming_assistant_text = ""
        self._resize_message_bubbles()
        return bubble

    def append_message(self, role, content):
        self.hide_empty_state()
        self.insert_message(role, content)
        self._scroll_messages()

    def append_assistant_header(self):
        self.hide_empty_state()
        self.insert_message("assistant")
        self._scroll_messages()

    def finish_stream_message(self):
        self._streaming_assistant_label = None
        self._streaming_assistant_text = ""
        self._scroll_messages()

    def append_text(self, text):
        self.hide_empty_state()
        row = ctk.CTkFrame(self.chat_display, fg_color="transparent")
        row.grid(row=len(self.message_rows), column=0, sticky="ew", padx=SPACING_MEDIUM, pady=(0, SPACING_MEDIUM))
        label = ctk.CTkLabel(row, text=self.display_text(text), font=FONT_BODY, text_color=COLOR_MUTED, anchor="w", justify="left", wraplength=520)
        label.pack(anchor="w", padx=SPACING_SMALL)
        self.message_rows.append(row)
        self._resize_message_bubbles()
        self._scroll_messages()

    def append_stream_chunk(self, chunk):
        self.hide_empty_state()
        if self._streaming_assistant_label is None:
            self.insert_message("assistant")
        self._streaming_assistant_text += self.display_text(chunk)
        self._streaming_assistant_label.configure(text=self._streaming_assistant_text)
        self._resize_message_bubbles()
        self._scroll_messages()

    def clear_display(self):
        for row in self.message_rows:
            row.destroy()
        self.message_rows = []
        self._streaming_assistant_label = None
        self._streaming_assistant_text = ""
        self.show_empty_state()

    def _resize_message_bubbles(self, _event=None):
        try:
            width = max(320, self.chat_display.winfo_width())
            wraplength = max(220, int(width * 0.72))
            for row in self.message_rows:
                for child in row.winfo_children():
                    if isinstance(child, ctk.CTkLabel):
                        child.configure(wraplength=wraplength)
        except Exception:
            return

    def _scroll_messages(self):
        try:
            self.chat_display.after_idle(lambda: self.chat_display._parent_canvas.yview_moveto(1.0))
        except Exception:
            return

    def handle_input_return(self, _event=None):
        self._send_prompt()
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

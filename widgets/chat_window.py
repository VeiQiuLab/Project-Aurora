import re
import threading
from tkinter import Menu, messagebox

import customtkinter as ctk

from modules.chat import ChatError, ChatSession
from modules.conversation import ConversationManager
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
from modules.search import search_conversations
from widgets.ui_components import (
    DangerButton,
    PrimaryButton,
    SecondaryButton,
    SectionCard,
    StatusLabel
)


class ChatWindow(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        *,
        text,
        translate,
        logger,
        settings,
        conversation_manager=None,
        initial_context_provider=None,
        model_records_provider=None,
        model_capability_provider=None,
        prepare_prompt_context_callback=None,
        stream_chat_callback=None,
        context_preview_builder=None,
        context_preview_callback=None,
        get_active_conversation_id=None,
        set_active_conversation_id=None,
        register_load_callback=None,
        on_close=None
    ):
        super().__init__(parent)
        self.parent = parent
        self.text = text
        self.t = translate
        self.logger = logger
        self.settings = settings
        self.conversation_manager = conversation_manager or ConversationManager()
        self.initial_context_provider = initial_context_provider
        self.model_records_provider = model_records_provider
        self.model_capability_provider = model_capability_provider
        self.prepare_prompt_context_callback = prepare_prompt_context_callback
        self.stream_chat_callback = stream_chat_callback
        self.context_preview_builder = context_preview_builder
        self.context_preview_callback = context_preview_callback
        self.get_active_conversation_id = get_active_conversation_id or (lambda: None)
        self.set_active_conversation_id = set_active_conversation_id or (lambda _value: None)
        self.register_load_callback = register_load_callback
        self.on_close_callback = on_close

        self.selected_model = {"name": ""}
        self.session = ChatSession(self._initial_context())
        self.conversation_state = {
            "id": None,
            "created_at": None,
            "title": "New Conversation"
        }
        self.stream_state = {
            "running": False,
            "stop_event": None
        }
        self.conversation_records = []
        self.debug_context_var = ctk.BooleanVar(value=False)

        self.title(self.t("chat"))
        self.geometry("1440x920")
        self.minsize(1180, 760)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.build()
        if callable(self.register_load_callback):
            self.register_load_callback(self.load_conversation_by_id)
        self.refresh_conversations()
        threading.Thread(target=self.load_models, daemon=True).start()
        self.after(100, self.focus_input)

    def _initial_context(self):
        if callable(self.initial_context_provider):
            return self.initial_context_provider()
        return ""

    def build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=SPACING_LARGE + SPACING_SMALL,
            pady=(SPACING_LARGE, SPACING_MEDIUM)
        )
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Aurora Chat", font=FONT_TITLE).grid(row=0, column=0, sticky="w")
        self.header_model_label = StatusLabel(
            header,
            status="disabled",
            text=self.t("chat_window_loading_models"),
            anchor="e",
            justify="right"
        )
        self.header_model_label.grid(row=0, column=1, sticky="e")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=SPACING_LARGE + SPACING_SMALL,
            pady=(0, SPACING_LARGE)
        )
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=0, minsize=260)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(2, weight=0, minsize=280)

        left_panel = ctk.CTkFrame(body, width=260)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, SPACING_MEDIUM))
        left_panel.grid_propagate(False)
        left_panel.grid_columnconfigure(0, weight=1)
        left_panel.grid_rowconfigure(5, weight=1)
        ctk.CTkLabel(left_panel, text=self.t("conversation"), font=FONT_HEADER).grid(
            row=0,
            column=0,
            sticky="w",
            padx=SPACING_MEDIUM,
            pady=(SPACING_MEDIUM, SPACING_SMALL)
        )
        new_chat_button = PrimaryButton(left_panel, text=self.t("new_chat"), command=self.new_conversation)
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
            command=self.search_conversation_list
        )
        search_button.grid(row=4, column=0, sticky="ew", padx=SPACING_MEDIUM, pady=(0, SPACING_MEDIUM))
        self.conversation_selector = ctk.CTkOptionMenu(
            left_panel,
            values=[self.t("no_conversations")],
            command=lambda _value: self.load_conversation()
        )
        self.conversation_selector.grid(row=5, column=0, sticky="new", padx=SPACING_MEDIUM, pady=(0, SPACING_MEDIUM))
        conversation_actions = ctk.CTkFrame(left_panel, fg_color="transparent")
        conversation_actions.grid(row=6, column=0, sticky="ew", padx=SPACING_MEDIUM, pady=(0, SPACING_MEDIUM))
        conversation_actions.grid_columnconfigure(0, weight=1)
        conversation_actions.grid_columnconfigure(1, weight=1)

        center_panel = ctk.CTkFrame(body, fg_color="transparent")
        center_panel.grid(row=0, column=1, sticky="nsew")
        center_panel.grid_rowconfigure(1, weight=1)
        center_panel.grid_columnconfigure(0, weight=1)

        chat_header = ctk.CTkFrame(center_panel, fg_color="transparent")
        chat_header.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_SMALL))
        chat_header.grid_columnconfigure(0, weight=1)
        self.current_title_label = ctk.CTkLabel(chat_header, text=self.t("new_chat"), font=FONT_HEADER)
        self.current_title_label.grid(row=0, column=0, sticky="w")
        self.model_inline_label = ctk.CTkLabel(chat_header, text=self.t("chat_window_loading_models"), font=FONT_SMALL)
        self.model_inline_label.grid(row=0, column=1, sticky="e")

        chat_card = SectionCard(center_panel, self.t("chat"))
        chat_card.grid(row=1, column=0, sticky="nsew", pady=(0, SPACING_MEDIUM))
        chat_card.body.grid_rowconfigure(0, weight=1)
        chat_card.body.grid_columnconfigure(0, weight=1)
        self.chat_display = ctk.CTkTextbox(chat_card.body, wrap="word", font=FONT_BODY, border_spacing=14)
        self.chat_display.grid(row=0, column=0, sticky="nsew")
        self.configure_chat_tags()
        self.chat_display.configure(state="disabled")

        input_card = SectionCard(center_panel, self.t("input_box"))
        input_card.grid(row=2, column=0, sticky="ew")
        input_card.body.grid_columnconfigure(0, weight=1)
        self.input_default_height = 112
        self.input_line_height = 24
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

        self.chat_status = StatusLabel(
            input_actions,
            status="disabled",
            text=self.t("loading_ollama_models"),
            anchor="w",
            justify="left"
        )
        self.chat_status.grid(row=0, column=0, sticky="ew", padx=(0, SPACING_MEDIUM))

        right_panel = ctk.CTkFrame(body, width=280)
        right_panel.grid(row=0, column=2, sticky="nsew", padx=(SPACING_MEDIUM, 0))
        right_panel.grid_propagate(False)
        right_panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(right_panel, text=self.t("context_sidebar_title"), font=FONT_HEADER).grid(
            row=0,
            column=0,
            sticky="w",
            padx=SPACING_MEDIUM,
            pady=(SPACING_MEDIUM, SPACING_SMALL)
        )
        self.context_persona_status = self.add_context_status(right_panel, 1, self.t("persona"), self.t("available"))
        self.context_memory_status = self.add_context_status(right_panel, 2, self.t("memory"), self.t("enabled"))
        self.context_knowledge_status = self.add_context_status(right_panel, 3, self.t("knowledge"), self.t("enabled"))
        self.context_model_status = self.add_context_status(right_panel, 4, self.t("model"), self.t("chat_window_loading_models"))

        self.debug_switch = ctk.CTkSwitch(
            right_panel,
            text=self.t("show_chat_context_debug_info"),
            variable=self.debug_context_var,
            font=FONT_SMALL
        )
        self.debug_switch.grid(row=5, column=0, sticky="w", padx=SPACING_MEDIUM, pady=(SPACING_MEDIUM, SPACING_SMALL))

        self.buttons = {}
        button_specs = [
            (conversation_actions, 0, 0, SecondaryButton, self.t("save_chat"), self.save_conversation),
            (conversation_actions, 0, 1, SecondaryButton, self.t("rename_chat"), self.rename_conversation),
            (conversation_actions, 1, 0, DangerButton, self.t("delete_chat"), self.delete_conversation),
            (conversation_actions, 1, 1, SecondaryButton, self.t("close"), self.close),
            (input_actions, 0, 1, PrimaryButton, self.t("send"), self.send_prompt),
            (input_actions, 0, 2, SecondaryButton, self.t("stop_generate"), self.stop_generation),
            (right_panel, 6, 0, SecondaryButton, self.t("chat_window_context_inspector"), self.preview_chat_context),
            (right_panel, 7, 0, SecondaryButton, self.t("clear"), self.clear_chat),
        ]
        for parent, row, column, button_class, label, command in button_specs:
            button = button_class(parent, text=label, command=command)
            padx = SPACING_SMALL if parent is input_actions else SPACING_SMALL
            button.grid(row=row, column=column, sticky="ew", padx=padx, pady=SPACING_SMALL)
            self.buttons[label] = button
        self.buttons[self.t("new_chat")] = new_chat_button
        self.buttons[self.t("chat_window_search")] = search_button
        self.buttons[self.t("stop_generate")].configure(state="disabled")
        self.refresh_context_statuses()

    def add_context_status(self, parent, row, label, value):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=SPACING_MEDIUM, pady=(SPACING_SMALL, SPACING_SMALL))
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text=label, font=FONT_SMALL).grid(row=0, column=0, sticky="w")
        status = StatusLabel(frame, status="healthy", text=f"● {value}", anchor="w", justify="left")
        status.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        return status

    def configure_chat_tags(self):
        try:
            self.chat_display.tag_config("role_user", foreground="#2563EB", font=FONT_NORMAL_BOLD)
            self.chat_display.tag_config("role_assistant", foreground="#2E7D32", font=FONT_NORMAL_BOLD)
            self.chat_display.tag_config("role_notice", foreground=COLOR_MUTED, font=FONT_BODY)
            self.chat_display.tag_config("message_body", lmargin1=8, lmargin2=8, spacing1=4, spacing3=12)
        except Exception:
            return

    def is_open(self):
        try:
            return self.winfo_exists()
        except Exception:
            return False

    def set_status(self, text, status="disabled"):
        self.chat_status.set_status(status, text=text)

    def enabled_state_text(self, enabled):
        return self.t("enabled") if enabled else self.t("disabled")

    def refresh_context_statuses(self):
        persona_enabled = bool(self.settings.get("persona.enabled", True))
        knowledge_enabled = bool(self.settings.get("knowledge.enabled", True))
        self.context_persona_status.set_status(
            "healthy" if persona_enabled else "disabled",
            text=f"● {self.enabled_state_text(persona_enabled)}"
        )
        self.context_memory_status.set_status("healthy", text=f"● {self.t('available')}")
        self.context_knowledge_status.set_status(
            "healthy" if knowledge_enabled else "disabled",
            text=f"● {self.enabled_state_text(knowledge_enabled)}"
        )

    def set_model_display(self, model_name, status="healthy"):
        text = model_name or self.t("chat_page_model_unknown")
        header_text = f"{text} ● {self.t('local_model_status')}" if model_name else text
        self.header_model_label.set_status(status, text=header_text)
        self.model_inline_label.configure(text=text)
        self.context_model_status.set_status(status, text=f"● {text}")

    def update_current_title(self):
        title = self.short_conversation_title({
            "id": self.conversation_state.get("id"),
            "title": self.conversation_state.get("title")
        })
        self.current_title_label.configure(text=title or self.t("new_chat"))

    def focus_input(self):
        try:
            self.input_box.focus_set()
        except Exception:
            return

    def resize_input_box(self, _event=None):
        try:
            content = self.input_box.get("1.0", "end-1c")
            line_count = max(4, min(8, content.count("\n") + 1))
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
        self.chat_display.configure(state="normal")
        self.insert_message(role, content)
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def append_assistant_header(self):
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
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", self.display_text(text) + "\n\n", "role_notice")
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def append_stream_chunk(self, chunk):
        if not self.is_open():
            return
        auto_scroll = self.text_at_bottom(self.chat_display)
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", self.display_text(chunk), "message_body")
        if auto_scroll:
            self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def handle_input_return(self, _event=None):
        self.send_prompt()
        return "break"

    def handle_input_shift_return(self, _event=None):
        self.input_box.insert("insert", "\n")
        self.after(0, self.resize_input_box)
        return "break"

    def attach_text_menu(self, widget):
        menu = Menu(widget, tearoff=0)
        menu.add_command(label=self.t("edit_cut"), command=lambda: self.run_text_menu_action(widget, "<<Cut>>"))
        menu.add_command(label=self.t("edit_copy"), command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label=self.t("edit_paste"), command=lambda: self.run_text_menu_action(widget, "<<Paste>>"))
        menu.add_command(label=self.t("edit_delete"), command=lambda: self.delete_selection(widget))
        menu.add_separator()
        menu.add_command(label=self.t("edit_select_all"), command=lambda: self.select_all_text(widget))

        def show_menu(event):
            try:
                widget.focus_set()
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
            return "break"

        widget.bind("<Button-3>", show_menu)

    def run_text_menu_action(self, widget, action):
        widget.event_generate(action)
        if widget is self.input_box:
            self.after(0, self.resize_input_box)

    def delete_selection(self, widget):
        try:
            widget.delete("sel.first", "sel.last")
        except Exception:
            return
        if widget is self.input_box:
            self.after(0, self.resize_input_box)

    @staticmethod
    def select_all_text(widget):
        try:
            widget.tag_add("sel", "1.0", "end")
            widget.mark_set("insert", "end")
        except Exception:
            return
        return "break"

    def conversation_label(self, record):
        return self.short_conversation_title(record)

    @staticmethod
    def compact_text(value):
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def short_conversation_title(self, record):
        title = self.compact_text(record.get("title", ""))
        if not title or title == "New Conversation":
            title = self.first_user_message_title(record.get("id", ""))
        if not title:
            title = self.t("conversation")
        title = re.sub(r"[?？!！。,.，:：;；]+$", "", title)
        if len(title) > 24:
            title = title[:24].rstrip() + "..."
        return title

    def first_user_message_title(self, conversation_id):
        if not conversation_id:
            return ""
        try:
            data = self.conversation_manager.load(conversation_id)
        except (OSError, ValueError):
            return ""
        for message in data.get("messages", []):
            if isinstance(message, dict) and message.get("role") == "user":
                return self.compact_text(message.get("content", ""))
        return ""

    @staticmethod
    def display_text(value):
        return re.sub(
            r"\[(?:fact|preference|habit|instruction|project|temporary)\]\s*",
            "",
            str(value or "")
        )

    def refresh_conversations(self, keyword=""):
        if keyword.strip():
            self.conversation_records = search_conversations(self.conversation_manager.directory, keyword)
        else:
            self.conversation_records = self.conversation_manager.list_conversations()
        labels = []
        seen = {}
        for item in self.conversation_records:
            base_label = self.conversation_label(item)
            count = seen.get(base_label, 0) + 1
            seen[base_label] = count
            labels.append(base_label if count == 1 else f"{base_label} · {count}")
        self.conversation_selector.configure(values=labels or [self.t("no_conversations")])
        self.conversation_selector.set(labels[0] if labels else self.t("no_conversations"))
        self.update_current_title()

    def search_conversation_list(self):
        self.refresh_conversations(self.conversation_search_entry.get())
        self.logger.info("Conversation searched")

    def select_model(self, model):
        unavailable_labels = {
            self.t("chat_window_loading_models"),
            self.t("chat_window_no_models_available")
        }
        if model and model not in unavailable_labels:
            if callable(self.model_capability_provider) and self.model_capability_provider(model) != "Chat Supported":
                self.set_status(self.t("model_cannot_chat"), "error")
                self.logger.info("Embedding model blocked from chat")
                return
            self.selected_model["name"] = model
            self.settings.set("chat_model", model)
            self.set_model_display(model, "healthy")
            self.logger.info(f"Chat model selected: {model}")

    def update_models(self, records):
        if not self.is_open():
            return
        names = [
            record.get("name", "")
            for record in records
            if callable(self.model_capability_provider) and self.model_capability_provider(record.get("name", "")) == "Chat Supported"
        ]
        names = [name for name in names if name]
        if not names:
            self.model_selector.configure(values=[self.t("chat_window_no_models_available")])
            self.model_selector.set(self.t("chat_window_no_models_available"))
            self.set_model_display("", "warning")
            self.set_status(self.t("chat_window_no_models_found"), "warning")
            return
        configured_chat_model = str(self.settings.get("chat_model", "qwen3:8b") or "").strip()
        selected_name = configured_chat_model if configured_chat_model in names else names[0]
        self.selected_model["name"] = selected_name
        self.model_selector.configure(values=names)
        self.model_selector.set(selected_name)
        self.set_model_display(selected_name, "healthy")
        self.set_status(self.t("chat_window_models_available").format(count=len(names)), "healthy")
        self.logger.info(f"Chat models loaded: {len(names)}")
        self.logger.info("Model capability checked")

    def load_models(self):
        try:
            records = self.model_records_provider() if callable(self.model_records_provider) else []
        except Exception as error:
            self.logger.error(f"Chat model loading failed: {error}")
            records = []
        try:
            self.after(0, lambda: self.update_models(records))
        except Exception:
            return

    def render_messages(self, messages):
        self.chat_display.configure(state="normal")
        self.chat_display.delete("1.0", "end")
        for message in messages:
            if message.get("role") == "system":
                continue
            role = "user" if message.get("role") == "user" else "assistant"
            self.insert_message(role, message.get("content", ""))
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def load_conversation_by_id(self, conversation_id):
        if self.stream_state["running"]:
            self.set_status(self.t("chat_window_stop_before_loading_conversation"), "warning")
            return
        if not conversation_id:
            return
        try:
            if self.conversation_state["id"] and len(self.session.snapshot()) > 1:
                self.save_conversation(auto=True)
            data = self.conversation_manager.load(conversation_id)
            self.session.replace(data.get("messages", []))
            self.conversation_state["id"] = data.get("id")
            self.conversation_state["created_at"] = data.get("created_at")
            self.conversation_state["title"] = data.get("title", "New Conversation")
            self.set_active_conversation_id(self.conversation_state["id"])
            if data.get("model"):
                self.selected_model["name"] = data["model"]
                self.model_selector.set(data["model"])
                self.set_model_display(data["model"], "healthy")
            self.render_messages(self.session.snapshot())
            self.update_current_title()
            self.set_status(self.t("chat_window_conversation_loaded"), "healthy")
            self.logger.info("Conversation loaded")
            self.logger.info("Conversation switched")
        except (OSError, ValueError) as error:
            self.logger.error(f"Conversation load failed: {error}")
            self.set_status(self.t("chat_window_load_conversation_failed"), "error")

    def load_conversation(self):
        if self.stream_state["running"]:
            self.set_status(self.t("chat_window_stop_before_loading"), "warning")
            return
        selected = self.conversation_selector.get()
        values = self.conversation_selector.cget("values")
        index = values.index(selected) if selected in values else -1
        record = self.conversation_records[index] if 0 <= index < len(self.conversation_records) else None
        if record is not None:
            self.load_conversation_by_id(record["id"])

    def new_conversation(self):
        if self.stream_state["running"]:
            self.set_status(self.t("chat_window_stop_generation_first"), "warning")
            return
        if len(self.session.snapshot()) > 1:
            self.save_conversation(auto=True)
        self.session.clear()
        self.conversation_state["id"] = None
        self.conversation_state["created_at"] = None
        self.conversation_state["title"] = "New Conversation"
        self.set_active_conversation_id(None)
        self.render_messages(self.session.snapshot())
        self.update_current_title()
        self.set_status(self.t("chat_window_new_conversation"), "disabled")
        self.logger.info("Conversation created")

    def save_conversation(self, auto=False):
        if self.stream_state["running"]:
            self.set_status(self.t("chat_window_stop_before_saving"), "warning")
            return
        messages = self.session.snapshot()
        if len(messages) <= 1:
            self.set_status(self.t("chat_window_no_content_to_save"), "warning")
            return
        title = self.conversation_state["title"]
        if title == "New Conversation":
            title = next((m.get("content", "") for m in messages if m.get("role") == "user"), title)
        data = self.conversation_manager.save(
            self.conversation_state["id"],
            self.selected_model["name"],
            messages,
            title=title[:40],
            created_at=self.conversation_state["created_at"]
        )
        self.conversation_state["id"] = data["id"]
        self.conversation_state["created_at"] = data["created_at"]
        self.conversation_state["title"] = data["title"]
        self.set_active_conversation_id(data["id"])
        self.refresh_conversations()
        self.update_current_title()
        self.set_status(
            self.t("chat_window_conversation_auto_saved") if auto else self.t("chat_window_conversation_saved"),
            "healthy"
        )
        self.logger.info("Conversation auto saved" if auto else "Conversation saved")

    def delete_conversation(self):
        selected = self.conversation_selector.get()
        values = self.conversation_selector.cget("values")
        index = values.index(selected) if selected in values else -1
        record = self.conversation_records[index] if 0 <= index < len(self.conversation_records) else None
        if record is None or not messagebox.askyesno(
            self.t("chat_window_delete_chat_title"),
            self.t("chat_window_delete_chat_message"),
            parent=self
        ):
            return
        try:
            self.conversation_manager.delete(record["id"])
            if self.conversation_state["id"] == record["id"]:
                self.new_conversation()
            if self.get_active_conversation_id() == record["id"]:
                self.set_active_conversation_id(None)
            self.refresh_conversations()
            self.set_status(self.t("chat_window_conversation_deleted"), "disabled")
            self.logger.info("Conversation deleted")
        except OSError as error:
            self.logger.error(f"Conversation delete failed: {error}")

    def rename_conversation(self):
        if not self.conversation_state["id"]:
            self.set_status(self.t("chat_window_load_conversation_first"), "warning")
            return
        dialog = ctk.CTkInputDialog(text=self.t("chat_window_rename_prompt"), title=self.t("rename_chat"))
        title = dialog.get_input()
        if not title or not title.strip():
            return
        try:
            data = self.conversation_manager.rename(self.conversation_state["id"], title)
            self.conversation_state["title"] = data["title"]
            self.refresh_conversations()
            self.update_current_title()
            self.set_status(self.t("chat_window_conversation_renamed"), "healthy")
            self.logger.info("Conversation renamed")
        except (OSError, ValueError) as error:
            self.logger.error(f"Conversation rename failed: {error}")

    def send_prompt(self):
        if self.stream_state["running"]:
            self.set_status(self.t("chat_window_stop_generation_first"), "warning")
            self.focus_input()
            return
        model = self.selected_model["name"].strip()
        prompt = self.input_box.get("1.0", "end").strip()
        unavailable_labels = {
            self.t("chat_window_loading_models"),
            self.t("chat_window_no_models_available")
        }
        if not model or model in unavailable_labels:
            self.append_text(f"{self.t('error')}: {self.t('chat_window_no_model_available')}")
            return
        if not prompt:
            self.append_text(self.t("chat_window_enter_prompt_first"))
            return
        if not callable(self.prepare_prompt_context_callback) or not callable(self.stream_chat_callback):
            self.append_text(f"{self.t('error')}: {self.t('chat_window_service_unavailable')}")
            return

        context = self.prepare_prompt_context_callback(prompt, self.session.snapshot(), self.debug_context_var.get())
        self.session.set_system_context(context.get("system_context", ""))
        if context.get("debug_text"):
            self.append_text(context["debug_text"])

        self.append_message("user", prompt)
        self.append_assistant_header()
        self.input_box.delete("1.0", "end")
        self.reset_input_box_height()
        self.focus_input()
        self.buttons[self.t("send")].configure(state="disabled")
        self.buttons[self.t("stop_generate")].configure(state="normal")
        self.set_status(self.t("waiting_ollama_response"), "disabled")
        self.logger.info(f"Streaming started: {model}")
        self.stream_state["running"] = True
        self.stream_state["stop_event"] = threading.Event()

        def run_request():
            try:
                def append_chunk(chunk):
                    try:
                        self.after(0, lambda: self.append_stream_chunk(chunk))
                    except Exception:
                        return

                result = self.stream_chat_callback(
                    model,
                    prompt,
                    self.session,
                    append_chunk,
                    self.stream_state["stop_event"]
                )
                error_message = None
                self.logger.info(f"Chat request succeeded: {model}")
            except ChatError as error:
                result = "failed"
                error_message = str(error)
                self.logger.error(f"Chat request failed: {error_message}")
            except Exception as error:
                result = "failed"
                error_message = self.t("chat_window_unexpected_chat_error")
                self.logger.error(f"Chat request failed: {error}")

            def update_chat():
                if not self.is_open():
                    return
                if error_message:
                    self.append_text(f"{self.t('error')}: {error_message}")
                    self.set_status(error_message, "error")
                elif result == "stopped":
                    self.append_text(self.t("chat_window_generation_stopped_marker"))
                    self.set_status(self.t("chat_window_generation_stopped"), "warning")
                else:
                    self.finish_stream_message()
                    self.set_status(self.t("chat_window_response_received"), "healthy")
                self.stream_state["running"] = False
                self.stream_state["stop_event"] = None
                self.buttons[self.t("send")].configure(state="normal")
                self.buttons[self.t("stop_generate")].configure(state="disabled")
                self.focus_input()
                if not error_message:
                    self.save_conversation(auto=True)

            try:
                self.after(0, update_chat)
            except Exception:
                return

        threading.Thread(target=run_request, daemon=True).start()

    def clear_chat(self):
        if self.stream_state["running"]:
            self.set_status(self.t("chat_window_stop_before_clearing"), "warning")
            return
        if not messagebox.askyesno(
            self.t("chat_window_clear_chat_title"),
            self.t("chat_window_clear_chat_message"),
            parent=self
        ):
            return
        self.chat_display.configure(state="normal")
        self.chat_display.delete("1.0", "end")
        self.chat_display.configure(state="disabled")
        self.input_box.delete("1.0", "end")
        self.reset_input_box_height()
        self.session.clear()
        self.set_status(self.t("chat_window_conversation_cleared"), "disabled")
        self.logger.info("Conversation cleared")

    def stop_generation(self):
        if self.stream_state["running"] and self.stream_state["stop_event"] is not None:
            self.stream_state["stop_event"].set()
            self.logger.info("Generation stopped")
            self.set_status(self.t("stopping_generation"), "warning")
            self.buttons[self.t("stop_generate")].configure(state="disabled")

    def preview_chat_context(self):
        prompt = self.input_box.get("1.0", "end").strip()
        self.set_status(self.t("chat_window_building_context_inspector"), "disabled")
        self.logger.info("Context preview opened")
        self.logger.info("Context inspector opened")

        def run_preview():
            try:
                payload = self.context_preview_builder(prompt, self.session.snapshot())
                error_message = None
            except Exception as error:
                payload = None
                error_message = str(error)

            def finish_preview():
                if not self.is_open():
                    return
                if error_message:
                    self.set_status(error_message, "error")
                    return
                if callable(self.context_preview_callback):
                    self.context_preview_callback(payload, self)
                self.set_status(self.t("chat_window_context_inspector_ready"), "healthy")
                self.logger.info("Context generated")
                self.logger.info("Context build duration recorded")
                self.logger.info("Final prompt preview generated")
                if payload.get("summary", {}).get("warning"):
                    self.logger.info("Context size warning")

            try:
                self.after(0, finish_preview)
            except Exception:
                return

        threading.Thread(target=run_preview, daemon=True).start()

    def close(self):
        if callable(self.register_load_callback):
            self.register_load_callback(None)
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()

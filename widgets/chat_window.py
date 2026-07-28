import threading
from tkinter import messagebox

import customtkinter as ctk

from modules.chat import ChatError, ChatSession
from modules.conversation import ConversationManager
from modules.ui_theme import FONT_HEADER, FONT_SMALL, FONT_TITLE, status_color
from modules.search import search_conversations
from widgets.ui_components import (
    DangerButton,
    FixedFooter,
    FormRow,
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

        self.title(self.text["chat"])
        self.geometry("900x680")
        self.minsize(720, 560)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.build()
        if callable(self.register_load_callback):
            self.register_load_callback(self.load_conversation_by_id)
        self.refresh_conversations()
        threading.Thread(target=self.load_models, daemon=True).start()

    def _initial_context(self):
        if callable(self.initial_context_provider):
            return self.initial_context_provider()
        return ""

    def build(self):
        ctk.CTkLabel(self, text=self.text["chat"], font=FONT_TITLE).pack(anchor="w", padx=25, pady=(20, 12))

        model_card = SectionCard(self, self.text["model_selector"])
        model_card.pack(fill="x", padx=25, pady=(0, 10))
        model_row = FormRow(model_card.body, self.text["model_selector"])
        model_row.pack(fill="x", pady=6)
        self.model_selector = ctk.CTkOptionMenu(
            model_row.control_frame,
            values=["Loading..."],
            width=280,
            command=self.select_model
        )
        self.model_selector.set("Loading...")
        self.model_selector.pack(side="left")

        conversation_card = SectionCard(self, self.text["conversation_list"])
        conversation_card.pack(fill="x", padx=25, pady=(0, 10))
        conversation_row = FormRow(conversation_card.body, self.text["conversation_list"])
        conversation_row.pack(fill="x", pady=6)
        self.conversation_selector = ctk.CTkOptionMenu(
            conversation_row.control_frame,
            values=[self.text["no_conversations"]],
            width=320,
            command=lambda _value: self.load_conversation()
        )
        self.conversation_selector.pack(side="left")
        search_row = FormRow(conversation_card.body, "Search conversations")
        search_row.pack(fill="x", pady=6)
        self.conversation_search_entry = search_row.add_entry("")
        PrimaryButton(search_row.control_frame, text="Search", width=80, command=self.search_conversation_list).pack(side="left", padx=(6, 0))

        chat_card = SectionCard(self, self.text["chat"])
        chat_card.pack(fill="both", expand=True, padx=25, pady=(0, 10))
        self.chat_display = ctk.CTkTextbox(chat_card.body, wrap="word")
        self.chat_display.pack(fill="both", expand=True)
        self.chat_display.configure(state="disabled")

        input_card = SectionCard(self, self.text["input_box"])
        input_card.pack(fill="x", padx=25, pady=(0, 10))
        self.input_box = ctk.CTkTextbox(input_card.body, height=90, wrap="word")
        self.input_box.pack(fill="x", pady=(0, 8))
        self.debug_switch = ctk.CTkSwitch(
            input_card.body,
            text=self.t("show_chat_context_debug_info"),
            variable=self.debug_context_var,
            font=FONT_SMALL
        )
        self.debug_switch.pack(anchor="w")

        self.chat_status = StatusLabel(self, status="disabled", text=self.t("loading_ollama_models"), anchor="w", justify="left")
        self.chat_status.pack(anchor="w", padx=25, pady=(0, 8))

        footer = FixedFooter(self)
        footer.pack(fill="x", padx=25, pady=(0, 20))
        specs = [
            (PrimaryButton, self.text["send"], self.send_prompt),
            (SecondaryButton, self.text["new_chat"], self.new_conversation),
            (SecondaryButton, self.text["save_chat"], self.save_conversation),
            (SecondaryButton, self.text["rename_chat"], self.rename_conversation),
            (SecondaryButton, self.text["stop_generate"], self.stop_generation),
            (SecondaryButton, self.text["clear"], self.clear_chat),
            (DangerButton, self.text["delete_chat"], self.delete_conversation),
            (SecondaryButton, "Context Inspector", self.preview_chat_context),
            (SecondaryButton, self.text["close"], self.close),
        ]
        self.buttons = {}
        for index, (button_class, label, command) in enumerate(specs):
            button = button_class(footer.buttons, text=label, command=command)
            button.grid(row=index // 5, column=index % 5, sticky="ew", padx=4, pady=4)
            self.buttons[label] = button
        for column in range(5):
            footer.buttons.grid_columnconfigure(column, weight=1)
        self.buttons[self.text["stop_generate"]].configure(state="disabled")

    def is_open(self):
        try:
            return self.winfo_exists()
        except Exception:
            return False

    def set_status(self, text, status="disabled"):
        self.chat_status.set_status(status, text=text)

    def append_text(self, text):
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", text + "\n\n")
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def append_stream_chunk(self, chunk):
        if not self.is_open():
            return
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", chunk)
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def conversation_label(self, record):
        updated = record.get("updated_at", "").replace("T", " ").replace("+00:00", " UTC")
        return f"{record.get('title', 'New Conversation')}\n{record.get('model', 'Unknown model')}\n{updated}"

    def refresh_conversations(self, keyword=""):
        if keyword.strip():
            self.conversation_records = search_conversations(self.conversation_manager.directory, keyword)
        else:
            self.conversation_records = self.conversation_manager.list_conversations()
        labels = [self.conversation_label(item) for item in self.conversation_records]
        self.conversation_selector.configure(values=labels or [self.text["no_conversations"]])
        self.conversation_selector.set(labels[0] if labels else self.text["no_conversations"])

    def search_conversation_list(self):
        self.refresh_conversations(self.conversation_search_entry.get())
        self.logger.info("Conversation searched")

    def select_model(self, model):
        if model and model not in {"Loading...", "No models available"}:
            if callable(self.model_capability_provider) and self.model_capability_provider(model) != "Chat Supported":
                self.set_status(self.text["model_cannot_chat"], "error")
                self.logger.info("Embedding model blocked from chat")
                return
            self.selected_model["name"] = model
            self.settings.set("chat_model", model)
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
            self.model_selector.configure(values=["No models available"])
            self.model_selector.set("No models available")
            self.set_status("No Ollama models found. Start Ollama and retry.", "warning")
            return
        configured_chat_model = str(self.settings.get("chat_model", "qwen3:8b") or "").strip()
        selected_name = configured_chat_model if configured_chat_model in names else names[0]
        self.selected_model["name"] = selected_name
        self.model_selector.configure(values=names)
        self.model_selector.set(selected_name)
        self.set_status(f"{len(names)} model(s) available", "healthy")
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
            label = "You" if message.get("role") == "user" else "Aurora"
            self.chat_display.insert("end", f"{label}:\n{message.get('content', '')}\n\n")
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def load_conversation_by_id(self, conversation_id):
        if self.stream_state["running"]:
            self.set_status("Please stop generation before loading a conversation.", "warning")
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
            self.render_messages(self.session.snapshot())
            self.set_status("Conversation loaded.", "healthy")
            self.logger.info("Conversation loaded")
            self.logger.info("Conversation switched")
        except (OSError, ValueError) as error:
            self.logger.error(f"Conversation load failed: {error}")
            self.set_status("Unable to load conversation.", "error")

    def load_conversation(self):
        if self.stream_state["running"]:
            self.set_status("Please stop generation before loading.", "warning")
            return
        selected = self.conversation_selector.get()
        record = next((item for item in self.conversation_records if self.conversation_label(item) == selected), None)
        if record is not None:
            self.load_conversation_by_id(record["id"])

    def new_conversation(self):
        if self.stream_state["running"]:
            self.set_status("Please stop generation first.", "warning")
            return
        if len(self.session.snapshot()) > 1:
            self.save_conversation(auto=True)
        self.session.clear()
        self.conversation_state["id"] = None
        self.conversation_state["created_at"] = None
        self.conversation_state["title"] = "New Conversation"
        self.set_active_conversation_id(None)
        self.render_messages(self.session.snapshot())
        self.set_status("New conversation.", "disabled")
        self.logger.info("Conversation created")

    def save_conversation(self, auto=False):
        if self.stream_state["running"]:
            self.set_status("Please stop generation before saving.", "warning")
            return
        messages = self.session.snapshot()
        if len(messages) <= 1:
            self.set_status("No conversation content to save.", "warning")
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
        self.set_status("Conversation auto saved." if auto else "Conversation saved.", "healthy")
        self.logger.info("Conversation auto saved" if auto else "Conversation saved")

    def delete_conversation(self):
        selected = self.conversation_selector.get()
        record = next((item for item in self.conversation_records if self.conversation_label(item) == selected), None)
        if record is None or not messagebox.askyesno("Delete Chat", "Delete selected conversation?", parent=self):
            return
        try:
            self.conversation_manager.delete(record["id"])
            if self.conversation_state["id"] == record["id"]:
                self.new_conversation()
            if self.get_active_conversation_id() == record["id"]:
                self.set_active_conversation_id(None)
            self.refresh_conversations()
            self.set_status("Conversation deleted.", "disabled")
            self.logger.info("Conversation deleted")
        except OSError as error:
            self.logger.error(f"Conversation delete failed: {error}")

    def rename_conversation(self):
        if not self.conversation_state["id"]:
            self.set_status("Please load a conversation first.", "warning")
            return
        dialog = ctk.CTkInputDialog(text="Enter conversation title:", title=self.text["rename_chat"])
        title = dialog.get_input()
        if not title or not title.strip():
            return
        try:
            data = self.conversation_manager.rename(self.conversation_state["id"], title)
            self.conversation_state["title"] = data["title"]
            self.refresh_conversations()
            self.set_status("Conversation renamed.", "healthy")
            self.logger.info("Conversation renamed")
        except (OSError, ValueError) as error:
            self.logger.error(f"Conversation rename failed: {error}")

    def send_prompt(self):
        model = self.selected_model["name"].strip()
        prompt = self.input_box.get("1.0", "end").strip()
        if not model or model in {"Loading...", "No models available"}:
            self.append_text("Error: No Ollama model is available.")
            return
        if not prompt:
            self.append_text("Please enter a prompt first.")
            return
        if not callable(self.prepare_prompt_context_callback) or not callable(self.stream_chat_callback):
            self.append_text("Error: Chat service is unavailable.")
            return

        context = self.prepare_prompt_context_callback(prompt, self.session.snapshot(), self.debug_context_var.get())
        self.session.set_system_context(context.get("system_context", ""))
        if context.get("debug_text"):
            self.append_text(context["debug_text"])

        self.append_text(f"You ({model}):\n{prompt}")
        self.append_text("Aurora:")
        self.input_box.delete("1.0", "end")
        self.buttons[self.text["send"]].configure(state="disabled")
        self.buttons[self.text["stop_generate"]].configure(state="normal")
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
                error_message = "Unexpected chat error."
                self.logger.error(f"Chat request failed: {error}")

            def update_chat():
                if not self.is_open():
                    return
                if error_message:
                    self.append_text(f"Error: {error_message}")
                    self.set_status(error_message, "error")
                elif result == "stopped":
                    self.append_text("[Generation stopped]")
                    self.set_status("Generation stopped.", "warning")
                else:
                    self.set_status("Response received.", "healthy")
                self.stream_state["running"] = False
                self.stream_state["stop_event"] = None
                self.buttons[self.text["send"]].configure(state="normal")
                self.buttons[self.text["stop_generate"]].configure(state="disabled")
                if not error_message:
                    self.save_conversation(auto=True)

            try:
                self.after(0, update_chat)
            except Exception:
                return

        threading.Thread(target=run_request, daemon=True).start()

    def clear_chat(self):
        if self.stream_state["running"]:
            self.set_status("Please stop generation before clearing.", "warning")
            return
        if not messagebox.askyesno("Clear Chat", "Clear current conversation?", parent=self):
            return
        self.chat_display.configure(state="normal")
        self.chat_display.delete("1.0", "end")
        self.chat_display.configure(state="disabled")
        self.input_box.delete("1.0", "end")
        self.session.clear()
        self.set_status("Conversation cleared.", "disabled")
        self.logger.info("Conversation cleared")

    def stop_generation(self):
        if self.stream_state["running"] and self.stream_state["stop_event"] is not None:
            self.stream_state["stop_event"].set()
            self.logger.info("Generation stopped")
            self.set_status(self.t("stopping_generation"), "warning")
            self.buttons[self.text["stop_generate"]].configure(state="disabled")

    def preview_chat_context(self):
        prompt = self.input_box.get("1.0", "end").strip()
        self.set_status("Building Context Inspector...", "disabled")
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
                self.set_status("Context Inspector ready", "healthy")
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

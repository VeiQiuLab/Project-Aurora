import re
import threading
from tkinter import messagebox

import customtkinter as ctk

from modules.chat import ChatError, ChatSession
from modules.conversation import ConversationManager, schedule_conversation_intelligence
from modules.experience.state import CompanionState, CompanionStateStore
from modules.search import search_conversations
from widgets.components.chat_panel import ChatPanel


class ChatPage(ctk.CTkFrame):
    """AppShell chat page that mounts ChatPanel directly."""

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
        voice_runtime=None,
        companion_state=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
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
        self.voice_runtime = voice_runtime
        if not isinstance(companion_state, CompanionStateStore):
            raise TypeError("companion_state must be the application CompanionStateStore")
        self.companion_state = companion_state

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
        self.conversation_labels = []
        self.conversation_search_entry = None
        self.conversation_selector = None
        self.debug_context_var = ctk.BooleanVar(value=False)

        self.build()
        if self.voice_runtime is not None:
            self.voice_runtime.subscribe_state(self._on_voice_state)
        self._on_voice_state_value(CompanionState.IDLE)
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
        self.grid_rowconfigure(0, weight=1)
        self.panel = ChatPanel(
            self,
            translate=self.t,
            settings=self.settings,
            debug_context_var=self.debug_context_var,
            new_conversation_callback=self.new_conversation,
            search_conversation_callback=self.search_conversation_list,
            load_conversation_callback=self.load_conversation,
            model_selected_callback=self.select_model,
            save_conversation_callback=self.save_conversation,
            rename_conversation_callback=self.rename_conversation,
            delete_conversation_callback=self.delete_conversation,
            close_callback=self.close,
            send_prompt_callback=self.send_prompt,
            stop_generation_callback=self.stop_generation,
            preview_context_callback=self.preview_chat_context,
            clear_chat_callback=self.clear_chat,
            voice_start_callback=self.start_voice_session,
            voice_cancel_callback=self.cancel_voice_session,
            voice_available=self.voice_runtime is not None and bool(self.settings.get("voice.enabled", False)),
            show_header_title=False
        )
        self.panel.grid(row=0, column=0, sticky="nsew")
        self._bind_panel_widgets()

    def _bind_panel_widgets(self):
        widget_names = [
            "buttons",
            "chat_display",
            "chat_status",
            "context_knowledge_status",
            "context_memory_status",
            "context_model_status",
            "context_persona_status",
            "current_title_label",
            "header_model_label",
            "input_box",
            "input_default_height",
            "input_line_height",
            "model_selector",
            "model_inline_label",
            "voice_state_label"
        ]
        for name in widget_names:
            setattr(self, name, getattr(self.panel, name))

    def attach_sidebar_conversation_controls(self, search_entry, conversation_selector):
        self.conversation_search_entry = search_entry
        self.conversation_selector = conversation_selector
        self.refresh_conversations()

    def _on_voice_state(self, event):
        try:
            self.after(0, lambda: self._on_voice_state_value(event.current_state))
        except Exception:
            return

    def _on_voice_state_value(self, state):
        labels = {
            CompanionState.IDLE: "Aurora Ready",
            CompanionState.VOICE_READY: "正在聆听...",
            CompanionState.LISTENING: "正在聆听...",
            CompanionState.TRANSCRIBING: "正在理解...",
            CompanionState.THINKING: "正在思考...",
            CompanionState.SPEAKING: "正在回应...",
            CompanionState.ERROR: "出现错误",
        }
        current = state if isinstance(state, CompanionState) else CompanionState.IDLE
        self.panel.set_voice_state(current.value, labels.get(current, current.value))

    def start_voice_session(self):
        self.logger.info(
            f"ChatPage.start_voice_session called voice_runtime_exists={self.voice_runtime is not None} "
            f"voice_enabled={bool(self.settings.get('voice.enabled', False))}"
        )
        if self.voice_runtime is None or not bool(self.settings.get("voice.enabled", False)):
            self.logger.info("ChatPage.start_voice_session blocked: Voice Runtime unavailable or disabled")
            return False
        if self.companion_state.current_state in {
            CompanionState.VOICE_READY,
            CompanionState.LISTENING,
            CompanionState.TRANSCRIBING,
            CompanionState.THINKING,
            CompanionState.SPEAKING,
        }:
            self.logger.info(
                f"ChatPage.start_voice_session blocked: active state="
                f"{self.companion_state.current_state.value}"
            )
            return False
        try:
            self.logger.info("ChatPage.start_voice_session calling voice_runtime.start_voice_session()")
            return self.voice_runtime.start_voice_session()
        except Exception as error:
            self.logger.error(f"Voice session start failed: {error}")
            self._on_voice_state_value(CompanionState.ERROR)
            return False

    def cancel_voice_session(self):
        if self.voice_runtime is None:
            return False
        try:
            return self.voice_runtime.cancel_voice_session()
        except Exception as error:
            self.logger.error(f"Voice session cancel failed: {error}")
            return False

    def is_open(self):
        try:
            return self.winfo_exists()
        except Exception:
            return False

    def set_status(self, text, status="disabled"):
        self.panel.set_status(text, status)

    def enabled_state_text(self, enabled):
        return self.t("enabled") if enabled else self.t("disabled")

    def refresh_context_statuses(self):
        self.panel.refresh_context_statuses()

    def set_model_display(self, model_name, status="healthy"):
        self.panel.set_model_display(model_name, status)

    def update_current_title(self):
        title = self.short_conversation_title({
            "id": self.conversation_state.get("id"),
            "title": self.conversation_state.get("title")
        })
        self.current_title_label.configure(text=title or self.t("new_chat"))

    def focus_input(self):
        self.panel.focus_input()

    def reset_input_box_height(self):
        self.panel.reset_input_box_height()

    def append_message(self, role, content):
        self.panel.append_message(role, content)

    def append_assistant_header(self):
        self.panel.append_assistant_header()

    def finish_stream_message(self):
        self.panel.finish_stream_message()

    def append_text(self, text):
        self.panel.append_text(text)

    def append_stream_chunk(self, chunk):
        if self.is_open():
            self.panel.append_stream_chunk(chunk)

    @staticmethod
    def compact_text(value):
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def conversation_label(self, record):
        return self.short_conversation_title(record)

    def short_conversation_title(self, record):
        title = self.compact_text(record.get("title", ""))
        if not title or title == "New Conversation":
            title = self.first_user_message_title(record.get("id", ""))
        if not title:
            title = self.t("conversation")
        title = re.sub(r"[?!?.。，！？]+$", "", title)
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
            labels.append(base_label if count == 1 else f"{base_label} {count}")
        self.conversation_labels = labels
        if self.conversation_selector is None:
            self.update_current_title()
            return
        self.conversation_selector.configure(values=labels or [self.t("no_conversations")])
        self.conversation_selector.set(labels[0] if labels else self.t("no_conversations"))
        self.update_current_title()

    def search_conversation_list(self):
        if self.conversation_search_entry is None:
            self.refresh_conversations()
            return
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
            unavailable = self.t("chat_window_no_models_available")
            self.panel.update_model_selector([unavailable], unavailable)
            self.set_model_display("", "warning")
            self.set_status(self.t("chat_window_no_models_found"), "warning")
            return
        configured_chat_model = str(self.settings.get("chat_model", "qwen3:8b") or "").strip()
        selected_name = configured_chat_model if configured_chat_model in names else names[0]
        self.selected_model["name"] = selected_name
        self.panel.update_model_selector(names, selected_name)
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
        self.panel.render_messages(messages)

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
                self.panel.update_model_selector(self.model_selector.cget("values"), data["model"])
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
        if self.conversation_selector is None:
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
        schedule_conversation_intelligence(
            self.conversation_manager,
            data["id"],
            messages,
            expected_updated_time=data.get("updated_time"),
            logger=self.logger
        )

    def delete_conversation(self):
        if self.conversation_selector is None:
            return
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

        self.companion_state.transition(
            CompanionState.THINKING,
            reason="chat_request_started",
            source="chat_page",
        )
        try:
            context = self.prepare_prompt_context_callback(
                prompt,
                self.session.snapshot(),
                self.debug_context_var.get(),
            )
        except Exception:
            self.companion_state.transition(
                CompanionState.ERROR,
                reason="chat_context_failed",
                source="chat_page",
            )
            self.companion_state.force_idle(
                reason="chat_context_failed",
                source="chat_page",
            )
            raise
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
                if result == "stopped":
                    self.companion_state.force_idle(
                        reason="chat_request_stopped",
                        source="chat_page",
                    )
                else:
                    self.companion_state.transition(
                        CompanionState.SPEAKING,
                        reason="chat_response_ready",
                        source="chat_page",
                    )
            except ChatError as error:
                result = "failed"
                error_message = str(error)
                self.logger.error(f"Chat request failed: {error_message}")
                self.companion_state.transition(
                    CompanionState.ERROR,
                    reason="chat_request_failed",
                    source="chat_page",
                )
            except Exception as error:
                result = "failed"
                error_message = self.t("chat_window_unexpected_chat_error")
                self.logger.error(f"Chat request failed: {error}")
                self.companion_state.transition(
                    CompanionState.ERROR,
                    reason="chat_request_failed",
                    source="chat_page",
                )

            def update_chat():
                try:
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
                finally:
                    self.companion_state.force_idle(
                        reason="chat_request_finished",
                        source="chat_page",
                    )

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
        self.panel.clear_display()
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
                    self.context_preview_callback(payload, self.winfo_toplevel())
                self.set_status(self.t("chat_window_context_inspector_generated"), "healthy")
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
        self.set_status("", "disabled")
        self.focus_input()

import threading
from tkinter import StringVar

import customtkinter as ctk

from modules.ui_theme import FONT_APP_TITLE, FONT_BODY, FONT_HEADER, FONT_TITLE
from widgets.ui_components import (
    FixedFooter,
    FormRow,
    PrimaryButton,
    SecondaryButton,
    SectionCard,
    StatusLabel
)


class FirstRunWizard(ctk.CTkToplevel):
    """First launch setup wizard UI.

    The wizard delegates model fetching, persona status, and final persistence
    to callbacks supplied by the application.
    """

    def __init__(
        self,
        parent,
        *,
        release,
        build,
        text,
        translate,
        settings_get,
        model_fetcher,
        persona_status_provider,
        on_complete,
        logger
    ):
        super().__init__(parent)
        self.release = release
        self.build = build
        self.text = text
        self.t = translate
        self.settings_get = settings_get
        self.model_fetcher = model_fetcher
        self.persona_status_provider = persona_status_provider
        self.on_complete = on_complete
        self.logger = logger
        self.state = {
            "step": 0,
            "models": [],
            "ollama_ok": False,
            "chat_model": str(self.settings_get("chat_model", "qwen3:8b") or "qwen3:8b"),
            "embedding_model": str(self.settings_get("embedding_model", "nomic-embed-text:latest") or "nomic-embed-text:latest")
        }

        self.title("Project Aurora First Run")
        self.geometry("620x520")
        self.minsize(560, 480)
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self.grab_set()
        self.build_ui()
        self.logger.info("First Run Wizard opened")
        self.render()

    def build_ui(self):
        self.container = ctk.CTkFrame(self)
        self.container.pack(fill="both", expand=True, padx=24, pady=24)

        self.title_label = ctk.CTkLabel(self.container, text="", font=FONT_TITLE)
        self.title_label.pack(anchor="w", pady=(4, 10))

        self.content_card = SectionCard(self.container, "Project Aurora")
        self.content_card.pack(fill="both", expand=True)

        self.footer = FixedFooter(self.container)
        self.footer.pack(fill="x", pady=(16, 0))
        self.back_button = SecondaryButton(self.footer.buttons, text="Back", width=100, command=self.prev_step)
        self.back_button.pack(side="left")
        self.next_button = PrimaryButton(self.footer.buttons, text="Next", width=120, command=self.next_step)
        self.next_button.pack(side="right")

    def clear_content(self):
        for child in self.content_card.body.winfo_children():
            child.destroy()

    def text_row(self, text, status="disabled", size=None):
        label = StatusLabel(
            self.content_card.body,
            status=status,
            text=text,
            anchor="w",
            justify="left",
            wraplength=500
        )
        if size:
            label.configure(font=FONT_TITLE if size >= 18 else FONT_HEADER)
        label.pack(fill="x", pady=6)
        return label

    def refresh_nav(self):
        self.back_button.configure(state="normal" if self.state["step"] > 0 else "disabled")
        self.next_button.configure(text="Finish" if self.state["step"] == 5 else "Next")

    def load_models_async(self, status_label=None):
        def run():
            result = self.model_fetcher()

            def finish():
                self.state["ollama_ok"] = bool(result.get("ok"))
                self.state["models"] = result.get("models", [])
                if status_label is not None:
                    if result.get("ok"):
                        status_label.set_status("healthy", text=f"OK | Models: {len(self.state['models'])}")
                    else:
                        status_label.set_status("error", text=f"Not detected | {result.get('reason', '')}")

            try:
                self.after(0, finish)
            except Exception:
                return

        threading.Thread(target=run, daemon=True).start()

    def choose_model_step(self, kind):
        self.clear_content()
        is_chat = kind == "chat"
        self.title_label.configure(text="Step 3 - Chat Model" if is_chat else "Step 4 - Embedding Model")
        self.text_row("Read Ollama /api/tags and select the model used for chat or embeddings.")
        candidates = [
            item["name"]
            for item in self.state["models"]
            if (item.get("capability") == "Chat Supported") == is_chat
        ]
        if not candidates:
            candidates = [item["name"] for item in self.state["models"]]
        current = self.state["chat_model"] if is_chat else self.state["embedding_model"]
        if current and current not in candidates:
            candidates.insert(0, current)
        values = candidates or [current or "No models available"]
        selected = StringVar(value=current if current in values else values[0])
        row = FormRow(self.content_card.body, self.text["chat_model"] if is_chat else self.text["embedding_model"])
        row.pack(fill="x", pady=12)
        menu = ctk.CTkOptionMenu(row.control_frame, values=values, variable=selected, width=360)
        menu.pack(side="left")

        def remember_choice(*_args):
            if is_chat:
                self.state["chat_model"] = selected.get()
            else:
                self.state["embedding_model"] = selected.get()

        selected.trace_add("write", remember_choice)
        remember_choice()

    def render(self):
        self.clear_content()
        step = self.state["step"]
        if step == 0:
            self.title_label.configure(text="Welcome to Project Aurora")
            ctk.CTkLabel(self.content_card.body, text="Aurora", font=FONT_APP_TITLE).pack(anchor="w", pady=(12, 6))
            self.text_row(f"Version: {self.release} | Build: {self.build}", status="healthy")
            self.text_row("Welcome to Project Aurora. This wizard completes the basic local AI setup for first launch.", size=15)
        elif step == 1:
            self.title_label.configure(text="Step 2 - Detect Ollama")
            self.text_row("Detect the local Ollama service status.")
            status_label = self.text_row("Checking Ollama...", "disabled", 16)
            self.load_models_async(status_label)
        elif step == 2:
            self.choose_model_step("chat")
        elif step == 3:
            self.choose_model_step("embedding")
        elif step == 4:
            self.title_label.configure(text="Step 5 - Persona")
            persona_status = self.persona_status_provider()
            self.text_row(f"Current Persona: {persona_status.get('name', 'Aurora')}", "healthy", 16)
            self.text_row(f"Rules: {persona_status.get('rules_count', 0)}")
            self.text_row(f"Enabled: {'Yes' if persona_status.get('enabled') else 'No'}")
        else:
            self.title_label.configure(text="Step 6 - Complete")
            self.text_row("Aurora is ready.", "healthy", 18)
            self.text_row(f"Chat Model: {self.state['chat_model']}")
            self.text_row(f"Embedding Model: {self.state['embedding_model']}")
            self.text_row("Click Finish to enter the main dashboard.")
        self.refresh_nav()

    def next_step(self):
        if self.state["step"] >= 5:
            if callable(self.on_complete):
                self.on_complete(dict(self.state), self)
            return
        self.state["step"] += 1
        self.render()

    def prev_step(self):
        if self.state["step"] > 0:
            self.state["step"] -= 1
            self.render()

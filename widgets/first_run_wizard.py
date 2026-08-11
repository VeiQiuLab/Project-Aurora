import threading
from tkinter import StringVar

import customtkinter as ctk

from modules.ui_theme import (
    FONT_APP_TITLE,
    FONT_HEADER,
    FONT_TITLE,
    FORM_CONTROL_WIDTH,
    FORM_LABEL_WRAP,
    SPACING_SMALL,
    SPACING_MEDIUM,
    SPACING_LARGE
)
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
        logger,
        initialization_check_provider=None
    ):
        super().__init__(parent)
        self.release = release
        self.build = build
        self.text = text
        self.t = translate
        self.settings_get = settings_get
        self.model_fetcher = model_fetcher
        self.persona_status_provider = persona_status_provider
        self.initialization_check_provider = initialization_check_provider
        self.on_complete = on_complete
        self.logger = logger
        self.state = {
            "step": 0,
            "models": [],
            "ollama_ok": False,
            "chat_model": str(self.settings_get("chat_model", "") or ""),
            "embedding_model": str(self.settings_get("embedding_model", "") or "")
        }

        self.title(self.t("first_run_window_title"))
        self.geometry("620x520")
        self.minsize(560, 480)
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self.grab_set()
        self.build_ui()
        self.logger.info("First Run Wizard opened")
        self.render()

    def build_ui(self):
        self.container = ctk.CTkFrame(self)
        self.container.pack(fill="both", expand=True, padx=SPACING_LARGE + SPACING_SMALL, pady=SPACING_LARGE + SPACING_SMALL)

        self.title_label = ctk.CTkLabel(self.container, text="", font=FONT_TITLE)
        self.title_label.pack(anchor="w", pady=(SPACING_SMALL, SPACING_MEDIUM))

        self.content_card = SectionCard(self.container, self.t("project_aurora"))
        self.content_card.pack(fill="both", expand=True)

        self.footer = FixedFooter(self.container)
        self.footer.pack(fill="x", pady=(SPACING_LARGE - SPACING_SMALL, 0))
        self.back_button = SecondaryButton(self.footer.buttons, text=self.t("back"), width=FORM_CONTROL_WIDTH - 150, command=self.prev_step)
        self.back_button.pack(side="left")
        self.next_button = PrimaryButton(self.footer.buttons, text=self.t("next"), width=FORM_CONTROL_WIDTH - 130, command=self.next_step)
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
            wraplength=FORM_LABEL_WRAP + 180
        )
        if size:
            label.configure(font=FONT_TITLE if size >= 18 else FONT_HEADER)
        label.pack(fill="x", pady=SPACING_SMALL)
        return label

    def refresh_nav(self):
        self.back_button.configure(state="normal" if self.state["step"] > 0 else "disabled")
        self.next_button.configure(text=self.t("finish") if self.state["step"] == 5 else self.t("next"))

    def load_models_async(self, status_label=None):
        def run():
            result = self.model_fetcher()

            def finish():
                self.state["ollama_ok"] = bool(result.get("ok"))
                self.state["models"] = result.get("models", [])
                if status_label is not None:
                    if result.get("ok"):
                        status_label.set_status("healthy", text=self.t("first_run_ollama_detected").format(count=len(self.state["models"])))
                    else:
                        status_label.set_status("error", text=self.t("first_run_ollama_not_detected").format(reason=result.get("reason", "")))

            try:
                self.after(0, finish)
            except Exception:
                return

        threading.Thread(target=run, daemon=True).start()

    def choose_model_step(self, kind):
        self.clear_content()
        is_chat = kind == "chat"
        self.title_label.configure(text=self.t("first_run_step_chat_model") if is_chat else self.t("first_run_step_embedding_model"))
        self.text_row(self.t("first_run_model_selection_hint"))
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
        values = candidates or [current or self.t("models_window_no_models")]
        selected = StringVar(value=current if current in values else values[0])
        row = FormRow(self.content_card.body, self.t("chat_model") if is_chat else self.t("embedding_model"))
        row.pack(fill="x", pady=SPACING_MEDIUM)
        menu = ctk.CTkOptionMenu(row.control_frame, values=values, variable=selected, width=FORM_CONTROL_WIDTH + 110)
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
            self.title_label.configure(text=self.t("first_run_welcome_title"))
            ctk.CTkLabel(self.content_card.body, text="Aurora", font=FONT_APP_TITLE).pack(anchor="w", pady=(12, 6))
            self.text_row(self.t("first_run_version_build").format(release=self.release, build=self.build), status="healthy")
            self.text_row(self.t("first_run_welcome_message"), size=15)
            if callable(self.initialization_check_provider):
                for item in self.initialization_check_provider():
                    status = item.get("status", "disabled")
                    marker = "✓" if status == "healthy" else "!"
                    self.text_row(
                        f"{marker} {item.get('name', '')}: {item.get('detail', '')}",
                        status=status
                    )
        elif step == 1:
            self.title_label.configure(text=self.t("first_run_step_detect_ollama"))
            self.text_row(self.t("first_run_detect_ollama_hint"))
            status_label = self.text_row(self.t("first_run_checking_ollama"), "disabled", 16)
            self.load_models_async(status_label)
        elif step == 2:
            self.choose_model_step("chat")
        elif step == 3:
            self.choose_model_step("embedding")
        elif step == 4:
            self.title_label.configure(text=self.t("first_run_step_persona"))
            persona_status = self.persona_status_provider()
            self.text_row(self.t("first_run_current_persona").format(name=persona_status.get("name", "Aurora")), "healthy", 16)
            self.text_row(self.t("first_run_rules_count").format(count=persona_status.get("rules_count", 0)))
            self.text_row(self.t("first_run_enabled_state").format(value=self.t("yes") if persona_status.get("enabled") else self.t("no")))
        else:
            self.title_label.configure(text=self.t("first_run_step_complete"))
            self.text_row(self.t("first_run_ready"), "healthy", 18)
            self.text_row(self.t("first_run_chat_model_summary").format(model=self.state["chat_model"]))
            self.text_row(self.t("first_run_embedding_model_summary").format(model=self.state["embedding_model"]))
            self.text_row(self.t("first_run_finish_hint"))
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

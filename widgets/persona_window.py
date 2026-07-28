import threading
import customtkinter as ctk
from tkinter import messagebox

from modules.ui_theme import FONT_NORMAL_BOLD, FONT_TITLE, status_color
from widgets.ui_components import (
    DangerButton,
    FixedFooter,
    FormRow,
    PrimaryButton,
    SecondaryButton,
    SectionCard,
    StatusLabel
)


class PersonaWindow(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        *,
        persona_store,
        settings,
        text,
        translate,
        logger,
        final_prompt_preview_callback=None,
        on_close=None
    ):
        super().__init__(parent)
        self.persona_store = persona_store
        self.settings = settings
        self.text = text
        self.t = translate
        self.logger = logger
        self.final_prompt_preview_callback = final_prompt_preview_callback
        self.on_close_callback = on_close
        self.persona = self.persona_store.load()
        self.persona_state = {
            "last_loaded_time": self.persona.get("last_loaded_time", "Never loaded."),
            "last_updated_time": self.persona.get("last_updated_time", "Never loaded.")
        }

        self.title(self.text["persona"])
        self.geometry("860x720")
        self.minsize(720, 560)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.build()
        self.update_persona_status()

    def build(self):
        ctk.CTkLabel(self, text=self.text["persona"], font=FONT_TITLE).pack(anchor="w", padx=25, pady=(20, 12))
        self.persona_status_label = StatusLabel(self, status="disabled", text="", anchor="w", justify="left")
        self.persona_status_label.pack(anchor="w", padx=25, pady=(0, 8))

        self.content = ctk.CTkScrollableFrame(self)
        self.content.pack(fill="both", expand=True, padx=25, pady=(0, 12))

        details = SectionCard(self.content, self.text["persona"])
        details.pack(fill="x", padx=0, pady=(0, 10))
        name_row = FormRow(details.body, self.text["persona_name"])
        name_row.pack(fill="x", pady=6)
        self.name_entry = name_row.add_entry(self.persona.get("name", "Aurora"))

        ctk.CTkLabel(details.body, text=self.text["persona_description"], font=FONT_NORMAL_BOLD).pack(anchor="w", pady=(10, 4))
        self.description_box = ctk.CTkTextbox(details.body, height=80, wrap="word")
        self.description_box.pack(fill="x", pady=(0, 6))
        self.description_box.insert("1.0", self.persona.get("description", ""))

        ctk.CTkLabel(details.body, text=self.text["persona_style"], font=FONT_NORMAL_BOLD).pack(anchor="w", pady=(10, 4))
        self.style_box = ctk.CTkTextbox(details.body, height=80, wrap="word")
        self.style_box.pack(fill="x", pady=(0, 6))
        self.style_box.insert("1.0", self.persona.get("style", ""))

        ctk.CTkLabel(details.body, text=self.text["persona_rules"], font=FONT_NORMAL_BOLD).pack(anchor="w", pady=(10, 4))
        self.rules_box = ctk.CTkTextbox(details.body, height=160, wrap="word")
        self.rules_box.pack(fill="both", expand=True, pady=(0, 6))
        self.rules_box.insert("1.0", "\n".join(self.persona.get("rules", [])))
        self.character_label = StatusLabel(details.body, status="disabled", text="", anchor="w", justify="left")
        self.character_label.pack(anchor="w", pady=(0, 6))

        preview = SectionCard(self.content, self.t("test_persona"))
        preview.pack(fill="both", expand=True, padx=0, pady=(0, 10))
        test_row = FormRow(preview.body, self.t("test_persona"))
        test_row.pack(fill="x", pady=6)
        self.test_prompt_entry = test_row.add_entry("")
        self.preview_box = ctk.CTkTextbox(preview.body, height=180, wrap="word")
        self.preview_box.pack(fill="both", expand=True, pady=(0, 6))
        self.preview_box.configure(state="disabled")

        self.status_label = StatusLabel(self, status="disabled", text="", anchor="w", justify="left")
        self.status_label.pack(anchor="w", padx=25, pady=(0, 8))

        self.footer = FixedFooter(self)
        self.footer.pack(fill="x", padx=25, pady=(0, 20))
        self.build_buttons()

    def build_buttons(self):
        actions = [
            (self.text["edit_persona"], self.edit_persona, SecondaryButton),
            (self.text["save_persona"], self.save_persona, PrimaryButton),
            (self.text["reset_persona"], self.reset_persona, DangerButton),
            ("Add Rule", self.add_rule, SecondaryButton),
            ("Delete Rule", self.delete_rule, DangerButton),
            ("Preview Persona Prompt", self.preview_persona_prompt, SecondaryButton),
            ("Test Persona", self.test_persona_prompt, PrimaryButton),
            ("Preview Final Prompt", self.preview_final_prompt, SecondaryButton),
            (self.text["close"], self.close, SecondaryButton)
        ]
        for index, (label, command, button_factory) in enumerate(actions):
            button_factory(self.footer.buttons, text=label, command=command).grid(
                row=index // 3,
                column=index % 3,
                sticky="ew",
                padx=4,
                pady=4
            )
        for column in range(3):
            self.footer.buttons.grid_columnconfigure(column, weight=1)

    def load_persona_into_fields(self, data):
        self.persona_state["last_loaded_time"] = data.get("last_loaded_time", self.persona_state["last_loaded_time"])
        self.persona_state["last_updated_time"] = data.get("last_updated_time", self.persona_state["last_updated_time"])
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, data.get("name", "Aurora"))
        self.description_box.delete("1.0", "end")
        self.description_box.insert("1.0", data.get("description", ""))
        self.style_box.delete("1.0", "end")
        self.style_box.insert("1.0", data.get("style", ""))
        self.rules_box.delete("1.0", "end")
        self.rules_box.insert("1.0", "\n".join(data.get("rules", [])))
        self.update_persona_status()

    def current_persona_from_fields(self):
        return {
            "name": self.name_entry.get().strip(),
            "description": self.description_box.get("1.0", "end").strip(),
            "style": self.style_box.get("1.0", "end").strip(),
            "rules": [line.strip() for line in self.rules_box.get("1.0", "end").splitlines() if line.strip()],
            "last_loaded_time": self.persona_state.get("last_loaded_time", "Never loaded."),
            "last_updated_time": self.persona_state.get("last_updated_time", "Never loaded.")
        }

    def set_preview(self, text):
        self.preview_box.configure(state="normal")
        self.preview_box.delete("1.0", "end")
        self.preview_box.insert("1.0", text)
        self.preview_box.configure(state="disabled")

    def update_persona_status(self):
        data = self.current_persona_from_fields()
        status = self.persona_store.status(self.settings.get("persona.enabled", True), data)
        self.persona_status_label.configure(
            text=(
                f"Current Status: Persona: {'Enabled' if status['enabled'] else 'Disabled'} | "
                f"Name: {status['name']} | Rules Count: {status['rules_count']} | "
                f"Last Loaded: {status['last_loaded_time']} | Last Updated: {status['last_updated_time']}"
            ),
            text_color=status_color("enabled" if status["enabled"] else "disabled")
        )
        self.character_label.configure(
            text=(
                f"Characters: name {len(data.get('name', ''))}, "
                f"description {len(data.get('description', ''))}, "
                f"style {len(data.get('style', ''))}, "
                f"rules {sum(len(rule) for rule in data.get('rules', []))}"
            ),
            text_color=status_color("disabled")
        )

    def validate_current_persona(self):
        data = self.current_persona_from_fields()
        self.persona_store.validate(data)
        return data

    def save_persona(self):
        try:
            data = self.validate_current_persona()
            data = self.persona_store.save(data)
            self.persona_state["last_loaded_time"] = data.get("last_loaded_time", self.persona_state["last_loaded_time"])
            self.persona_state["last_updated_time"] = data.get("last_updated_time", self.persona_state["last_updated_time"])
            self.update_persona_status()
            self.status_label.set_status("healthy", "Persona saved.")
            self.logger.info("Persona updated")
        except ValueError as error:
            self.status_label.set_status("error", str(error))
            self.logger.info("Persona validation failed")
        except Exception as error:
            self.status_label.set_status("error", "Invalid Persona format.")
            self.logger.error(f"Persona update failed: {error}")

    def reset_persona(self):
        if not messagebox.askyesno(self.text["persona"], "Restore default Persona?", parent=self):
            return
        data = self.persona_store.reset()
        self.persona_state["last_loaded_time"] = data.get("last_loaded_time", self.persona_state["last_loaded_time"])
        self.persona_state["last_updated_time"] = data.get("last_updated_time", self.persona_state["last_updated_time"])
        self.load_persona_into_fields(data)
        self.status_label.set_status("healthy", "Default Persona restored.")
        self.logger.info("Persona reset")

    def edit_persona(self):
        self.status_label.set_status("disabled", "Persona editable.")
        self.update_persona_status()

    def add_rule(self):
        self.rules_box.insert("end", "\n")
        self.update_persona_status()
        self.logger.info("Persona rules updated")

    def delete_rule(self):
        lines = [line for line in self.rules_box.get("1.0", "end").splitlines() if line.strip()]
        if lines:
            lines.pop()
        self.rules_box.delete("1.0", "end")
        self.rules_box.insert("1.0", "\n".join(lines))
        self.update_persona_status()
        self.logger.info("Persona rules updated")

    def preview_persona_prompt(self):
        self.set_preview("Loading Persona preview...")
        self.run_persona_action(
            lambda: self.persona_store.preview_prompt(self.validate_current_persona()),
            lambda text: (self.set_preview(text), self.logger.info("Persona preview opened"))
        )

    def test_persona_prompt(self):
        self.set_preview("Testing Persona...")
        self.run_persona_action(
            lambda: self.persona_store.test_prompt(self.test_prompt_entry.get().strip(), self.validate_current_persona()),
            lambda text: (self.set_preview(text), self.logger.info("Persona tested"))
        )

    def preview_final_prompt(self):
        self.set_preview("Building Final Chat Context Preview...")
        self.logger.info("Context preview opened")
        if not self.final_prompt_preview_callback:
            self.set_preview("Final prompt preview unavailable.")
            return
        self.run_persona_action(
            lambda: self.final_prompt_preview_callback(
                self.test_prompt_entry.get().strip(),
                self.validate_current_persona()
            ),
            self.finish_final_prompt
        )

    def finish_final_prompt(self, result):
        text, warning = result
        self.set_preview(text)
        self.logger.info("Final prompt preview generated")
        self.logger.info("Knowledge retrieval explained")
        if warning:
            self.logger.info("Context size warning")

    def run_persona_action(self, action, on_success):
        def worker():
            try:
                result = action()
                error_message = None
            except Exception as error:
                result = None
                error_message = str(error)

            def finish():
                if not self.winfo_exists():
                    return
                if error_message:
                    self.set_preview(error_message)
                    self.logger.info("Persona validation failed")
                    return
                on_success(result)

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def close(self):
        self.destroy()
        if self.on_close_callback:
            self.on_close_callback()

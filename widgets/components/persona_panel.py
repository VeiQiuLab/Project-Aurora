import threading
import traceback
import customtkinter as ctk
from tkinter import Menu, messagebox

from modules.ui_theme import (
    FONT_NORMAL_BOLD,
    FONT_TITLE,
    SPACING_SMALL,
    SPACING_MEDIUM,
    SPACING_LARGE,
    status_color
)
from widgets.ui_components import (
    DangerButton,
    FixedFooter,
    FormRow,
    PrimaryButton,
    SecondaryButton,
    SectionCard,
    StatusLabel
)
from widgets.components.workspace_header import WorkspaceHeader
from widgets.components.workspace_empty_state import WorkspaceEmptyState


class PersonaPanel(ctk.CTkFrame):
    """Reusable Persona editor panel for window and future page workspaces."""

    def __init__(
        self,
        parent,
        *,
        persona_store,
        settings,
        translate,
        logger,
        final_prompt_preview_callback=None,
        close_callback=None,
        show_close_button=True,
        show_header_title=True
    ):
        super().__init__(parent, fg_color="transparent")
        self.persona_store = persona_store
        self.settings = settings
        self.t = translate
        self.logger = logger
        self.final_prompt_preview_callback = final_prompt_preview_callback
        self.close_callback = close_callback
        self.show_close_button = show_close_button
        self.show_header_title = show_header_title
        self.test_section_expanded = False
        self.persona_load_error = None
        if self.logger:
            self.logger.info("PersonaPanel initialization started")
        try:
            self.persona = self.persona_store.load()
            if self.logger:
                self.logger.info(
                    f"PersonaStore.load returned: {self.persona_debug_summary(self.persona)}"
                )
        except Exception as error:
            self.persona_load_error = str(error)
            if self.logger:
                self.logger.error(f"PersonaStore.load failed: {error}")
                self.logger.error(traceback.format_exc())
            traceback.print_exc()
            self.persona = {}
        self.persona_missing = not isinstance(self.persona, dict) or not self.persona
        self.persona_state = {
            "last_loaded_time": self.persona.get("last_loaded_time", "Never loaded."),
            "last_updated_time": self.persona.get("last_updated_time", "Never loaded.")
        }

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.build()
        self.update_persona_status()
        if self.logger:
            self.logger.info("PersonaPanel initialization finished")

    def build(self):
        self.workspace_header = WorkspaceHeader(
            self,
            title=self.t("persona_page_title"),
            description=self.t("workspace_persona_description"),
            status="disabled",
            status_text=self.t("persona_page_status_unknown"),
            show_title=self.show_header_title
        )
        self.workspace_header.grid_with_workspace_padding()
        self.persona_status_label = self.workspace_header.status_label

        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=SPACING_LARGE + SPACING_SMALL,
            pady=(0, SPACING_SMALL)
        )
        self.basic_tab = self.tabs.add(self.t("persona_tab_basic"))
        self.rules_tab = self.tabs.add(self.t("persona_tab_rules"))
        self.test_tab = self.tabs.add(self.t("persona_tab_test"))
        for tab in (self.basic_tab, self.rules_tab, self.test_tab):
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)
        self.empty_state = WorkspaceEmptyState(
            self.basic_tab,
            title=self.t("workspace_persona_empty_title"),
            description=self.t("workspace_persona_empty_description")
        )

        self.details_card = SectionCard(self.basic_tab, self.t("persona_current_configuration"))
        self.details_card.pack(fill="x", padx=0, pady=(0, SPACING_MEDIUM))
        name_row = FormRow(self.details_card.body, self.t("persona_page_name"))
        name_row.pack(fill="x", pady=SPACING_SMALL)
        self.name_entry = name_row.add_entry(self.persona.get("name", "Aurora"))

        ctk.CTkLabel(self.details_card.body, text=self.t("persona_page_description"), font=FONT_NORMAL_BOLD).pack(anchor="w", pady=(SPACING_MEDIUM, SPACING_SMALL))
        self.description_box = ctk.CTkTextbox(self.details_card.body, height=80, wrap="word")
        self.description_box.pack(fill="x", pady=(0, SPACING_SMALL))
        self.description_box.insert("1.0", self.persona.get("description", ""))

        ctk.CTkLabel(self.details_card.body, text=self.t("persona_page_style"), font=FONT_NORMAL_BOLD).pack(anchor="w", pady=(SPACING_MEDIUM, SPACING_SMALL))
        self.style_box = ctk.CTkTextbox(self.details_card.body, height=80, wrap="word")
        self.style_box.pack(fill="x", pady=(0, SPACING_SMALL))
        self.style_box.insert("1.0", self.persona.get("style", ""))

        self.rules_card = SectionCard(self.rules_tab, self.t("persona_page_rules"))
        self.rules_card.grid(row=0, column=0, sticky="nsew")
        self.rules_card.body.grid_columnconfigure(0, weight=1)
        self.rules_card.body.grid_rowconfigure(0, weight=1)
        self.rules_box = ctk.CTkTextbox(self.rules_card.body, height=220, wrap="word")
        self.rules_box.grid(row=0, column=0, sticky="nsew", pady=(0, SPACING_SMALL))
        self.rules_box.insert("1.0", "\n".join(self.persona.get("rules", [])))
        self.character_label = StatusLabel(self.rules_card.body, status="disabled", text="", anchor="w", justify="left")
        self.character_label.grid(row=1, column=0, sticky="w", pady=(0, SPACING_SMALL))

        self.test_card = SectionCard(self.test_tab, self.t("test_persona"))
        self.test_card.grid(row=0, column=0, sticky="nsew")
        self.test_card.body.grid_columnconfigure(0, weight=1)
        self.test_card.body.grid_rowconfigure(1, weight=1)
        test_header = ctk.CTkFrame(self.test_card.body, fg_color="transparent")
        test_header.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_SMALL))
        test_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            test_header,
            text=self.t("persona_test_collapsed_hint"),
            anchor="w",
            justify="left"
        ).grid(row=0, column=0, sticky="ew", padx=(0, SPACING_SMALL))
        self.test_toggle_button = SecondaryButton(
            test_header,
            text=self.t("expand"),
            command=self.toggle_test_section
        )
        self.test_toggle_button.grid(row=0, column=1, sticky="e")

        self.test_body = ctk.CTkFrame(self.test_card.body, fg_color="transparent")
        self.test_body.grid_columnconfigure(0, weight=1)
        self.test_body.grid_rowconfigure(1, weight=1)
        test_row = FormRow(self.test_body, self.t("test_persona"))
        test_row.grid(row=0, column=0, sticky="ew", pady=SPACING_SMALL)
        self.test_prompt_entry = test_row.add_entry("")
        self.preview_box = ctk.CTkTextbox(self.test_body, height=180, wrap="word")
        self.preview_box.grid(row=1, column=0, sticky="nsew", pady=(0, SPACING_SMALL))
        self.preview_box.configure(state="disabled")

        self.status_label = StatusLabel(self, status="disabled", text="", anchor="w", justify="left")
        self.status_label.grid(
            row=2,
            column=0,
            sticky="w",
            padx=SPACING_LARGE + SPACING_SMALL,
            pady=(0, 0)
        )

        self.footer = FixedFooter(self)
        self.footer.grid(
            row=3,
            column=0,
            sticky="ew",
            padx=SPACING_LARGE + SPACING_SMALL,
            pady=(SPACING_SMALL, SPACING_MEDIUM)
        )
        self.build_buttons()
        if self.persona_load_error:
            self.show_empty_state(self.persona_load_error)
        elif self.persona_missing:
            self.show_empty_state()

    def build_buttons(self):
        actions = [
            (self.t("save"), self.save_persona, PrimaryButton),
            (self.t("test_persona"), self.test_persona_prompt, PrimaryButton),
            (self.t("more_actions"), self.show_more_actions_menu, SecondaryButton)
        ]
        if self.show_close_button:
            actions.append((self.t("close"), self.close, SecondaryButton))
        for index, (label, command, button_factory) in enumerate(actions):
            button_factory(self.footer.buttons, text=label, command=command).grid(
                row=0,
                column=index,
                sticky="ew",
                padx=SPACING_SMALL,
                pady=SPACING_SMALL
            )
        for column in range(len(actions)):
            self.footer.buttons.grid_columnconfigure(column, weight=1)
        self.more_actions_menu = Menu(self, tearoff=0)
        self.more_actions_menu.add_command(label=self.t("edit"), command=self.edit_persona)
        self.more_actions_menu.add_separator()
        self.more_actions_menu.add_command(label=self.t("persona_window_add_rule"), command=self.add_rule)
        self.more_actions_menu.add_command(label=self.t("persona_window_delete_rule"), command=self.delete_rule)
        self.more_actions_menu.add_separator()
        self.more_actions_menu.add_command(label=self.t("reset"), command=self.reset_persona)
        self.more_actions_menu.add_separator()
        self.more_actions_menu.add_command(
            label=self.t("persona_window_preview_persona_prompt"),
            command=self.preview_persona_prompt
        )
        self.more_actions_menu.add_command(
            label=self.t("persona_window_preview_final_prompt"),
            command=self.preview_final_prompt
        )

    def show_more_actions_menu(self):
        try:
            button = next(
                widget for widget in self.footer.buttons.winfo_children()
                if getattr(widget, "cget", lambda _key: None)("text") == self.t("more_actions")
            )
            x = button.winfo_rootx()
            y = button.winfo_rooty() + button.winfo_height()
            self.more_actions_menu.tk_popup(x, y)
        finally:
            self.more_actions_menu.grab_release()

    def toggle_test_section(self):
        self.test_section_expanded = not self.test_section_expanded
        if self.test_section_expanded:
            self.test_body.grid(row=1, column=0, sticky="nsew")
            self.test_toggle_button.configure(text=self.t("collapse"))
        else:
            self.test_body.grid_remove()
            self.test_toggle_button.configure(text=self.t("expand"))

    def load_persona_into_fields(self, data):
        self.persona_missing = not isinstance(data, dict) or not data
        if self.persona_missing:
            self.show_empty_state()
            return
        self.empty_state.pack_forget()
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

    def refresh_persona(self):
        if self.logger:
            self.logger.info("PersonaPanel refresh_persona started")
        try:
            data = self.persona_store.load(update_timestamp=False)
            if self.logger:
                self.logger.info(
                    f"PersonaStore.load returned during refresh: {self.persona_debug_summary(data)}"
                )
        except Exception as error:
            if self.logger:
                self.logger.error(f"PersonaPanel refresh_persona failed: {error}")
                self.logger.error(traceback.format_exc())
            traceback.print_exc()
            self.show_empty_state(str(error))
            return
        self.load_persona_into_fields(data)
        if self.logger:
            self.logger.info("PersonaPanel refresh_persona finished")

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
        if not self.test_section_expanded:
            self.toggle_test_section()
        self.preview_box.configure(state="normal")
        self.preview_box.delete("1.0", "end")
        self.preview_box.insert("1.0", text)
        self.preview_box.configure(state="disabled")

    def display_time(self, value):
        if not value or value == "Never loaded.":
            return self.t("persona_window_never_loaded")
        return value

    def update_persona_status(self):
        data = self.current_persona_from_fields()
        status = self.persona_store.status(self.settings.get("persona.enabled", True), data)
        self.workspace_header.set_status(
            "ready" if status["enabled"] else "warning",
            self.t("enabled") if status["enabled"] else self.t("disabled")
        )
        self.character_label.configure(
            text=(
                f"{self.t('characters')}: {self.t('persona_page_name')} {len(data.get('name', ''))}, "
                f"{self.t('persona_page_description')} {len(data.get('description', ''))}, "
                f"{self.t('persona_page_style')} {len(data.get('style', ''))}, "
                f"{self.t('persona_page_rules')} {sum(len(rule) for rule in data.get('rules', []))}"
            ),
            text_color=status_color("disabled")
        )

    def validate_current_persona(self):
        data = self.current_persona_from_fields()
        self.persona_store.validate(data)
        return data

    def show_empty_state(self, message=None):
        if message:
            self.workspace_header.set_status("error", message)
            self.status_label.set_status("error", message)
        else:
            self.workspace_header.set_status("warning", self.t("workspace_persona_empty_title"))
        pack_options = {"fill": "x", "pady": SPACING_MEDIUM}
        if hasattr(self, "details_card"):
            pack_options["before"] = self.details_card
        self.empty_state.pack(**pack_options)

    def persona_debug_summary(self, data):
        if not isinstance(data, dict):
            return f"type={type(data).__name__}"
        rules = data.get("rules", [])
        return (
            f"type=dict, keys={sorted(data.keys())}, "
            f"name={data.get('name', '')!r}, "
            f"rules_count={len(rules) if isinstance(rules, list) else 'invalid'}, "
            f"has_description={bool(data.get('description'))}, "
            f"has_style={bool(data.get('style'))}"
        )

    def save_persona(self):
        try:
            data = self.validate_current_persona()
            data = self.persona_store.save(data)
            self.persona_state["last_loaded_time"] = data.get("last_loaded_time", self.persona_state["last_loaded_time"])
            self.persona_state["last_updated_time"] = data.get("last_updated_time", self.persona_state["last_updated_time"])
            self.update_persona_status()
            self.empty_state.pack_forget()
            self.status_label.set_status("healthy", self.t("persona_window_saved"))
            self.logger.info("Persona updated")
        except ValueError as error:
            self.status_label.set_status("error", str(error))
            self.logger.info("Persona validation failed")
        except Exception as error:
            self.status_label.set_status("error", self.t("persona_window_invalid_format"))
            self.logger.error(f"Persona update failed: {error}")

    def reset_persona(self):
        if not messagebox.askyesno(
            self.t("persona_page_title"),
            self.t("persona_window_restore_default_confirm"),
            parent=self.winfo_toplevel()
        ):
            return
        data = self.persona_store.reset()
        self.persona_state["last_loaded_time"] = data.get("last_loaded_time", self.persona_state["last_loaded_time"])
        self.persona_state["last_updated_time"] = data.get("last_updated_time", self.persona_state["last_updated_time"])
        self.load_persona_into_fields(data)
        self.status_label.set_status("healthy", self.t("persona_window_default_restored"))
        self.logger.info("Persona reset")

    def edit_persona(self):
        self.status_label.set_status("disabled", self.t("persona_window_editable"))
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
        self.set_preview(self.t("persona_window_loading_preview"))
        self.workspace_header.set_status("loading", self.t("persona_window_loading_preview"))
        self.run_persona_action(
            lambda: self.persona_store.preview_prompt(self.validate_current_persona()),
            lambda text: (self.set_preview(text), self.logger.info("Persona preview opened"))
        )

    def test_persona_prompt(self):
        self.set_preview(self.t("persona_window_testing"))
        self.workspace_header.set_status("processing", self.t("persona_window_testing"))
        self.run_persona_action(
            lambda: self.persona_store.test_prompt(self.test_prompt_entry.get().strip(), self.validate_current_persona()),
            lambda text: (self.set_preview(text), self.logger.info("Persona tested"))
        )

    def preview_final_prompt(self):
        self.set_preview(self.t("persona_window_building_final_prompt"))
        self.workspace_header.set_status("processing", self.t("persona_window_building_final_prompt"))
        self.logger.info("Context preview opened")
        if not self.final_prompt_preview_callback:
            self.set_preview(self.t("persona_window_final_prompt_unavailable"))
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
                    self.workspace_header.set_status("error", error_message)
                    self.set_preview(error_message)
                    self.logger.info("Persona validation failed")
                    return
                on_success(result)
                self.update_persona_status()

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def close(self):
        if self.close_callback:
            self.close_callback()

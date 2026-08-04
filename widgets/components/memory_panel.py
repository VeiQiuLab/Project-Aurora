import customtkinter as ctk
from tkinter import Menu, messagebox

from modules.ui_theme import (
    FORM_CONTROL_WIDTH,
    FONT_TITLE,
    SPACING_SMALL,
    SPACING_MEDIUM,
    SPACING_LARGE
)
from widgets.ui_components import (
    DangerButton,
    FixedFooter,
    FormRow,
    PrimaryButton,
    SecondaryButton,
    SectionCard,
    StatusLabel,
    bind_text_edit_shortcuts
)
from widgets.components.workspace_header import WorkspaceHeader
from widgets.components.workspace_empty_state import WorkspaceEmptyState


class MemoryPanel(ctk.CTkFrame):
    """Reusable Memory workspace panel for listing and editing memories."""

    def __init__(
        self,
        parent,
        *,
        memory_store,
        search_memories,
        translate,
        logger,
        close_callback=None,
        show_close_button=True,
        show_header_title=True
    ):
        super().__init__(parent, fg_color="transparent")
        self.memory_store = memory_store
        self.search_memories = search_memories
        self.t = translate
        self.logger = logger
        self.close_callback = close_callback
        self.show_close_button = show_close_button
        self.show_header_title = show_header_title
        self.records = []
        self.selected_id = {"value": None}
        self.is_creating_memory = False

        self.grid_columnconfigure(0, weight=0, minsize=330)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.build()
        self.refresh_memory_list()

    def build(self):
        self.workspace_header = WorkspaceHeader(
            self,
            title=self.t("memory"),
            description=self.t("workspace_memory_description"),
            status="healthy",
            status_text="",
            show_status=False,
            show_title=self.show_header_title
        )
        self.workspace_header.grid_with_workspace_padding(columnspan=2)

        left_panel = ctk.CTkFrame(self, fg_color="transparent")
        left_panel.grid(row=1, column=0, sticky="nsew", padx=(SPACING_LARGE + SPACING_SMALL, SPACING_MEDIUM), pady=(0, SPACING_MEDIUM))
        left_panel.grid_columnconfigure(0, weight=1)
        left_panel.grid_rowconfigure(2, weight=1)

        search_card = SectionCard(left_panel, self.t("memory_window_search_memories"))
        search_card.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_MEDIUM))
        search_row = FormRow(search_card.body, self.t("memory_window_search_memories"))
        search_row.pack(fill="x", pady=SPACING_SMALL)
        self.memory_search_entry = search_row.add_entry("")
        PrimaryButton(
            search_row.control_frame,
            text=self.t("memory_window_search"),
            width=FORM_CONTROL_WIDTH // 3,
            command=self.search_memory_list
        ).pack(side="left", padx=(SPACING_SMALL, 0))

        filter_card = SectionCard(left_panel, self.t("memory_window_filters"))
        filter_card.grid(row=1, column=0, sticky="ew", pady=(0, SPACING_MEDIUM))
        type_filter_row = FormRow(filter_card.body, self.t("type"))
        type_filter_row.pack(fill="x", pady=SPACING_SMALL)
        self.type_filter = type_filter_row.add_option(self.type_filter_options(), self.t("memory_window_all_types"), width=FORM_CONTROL_WIDTH)
        importance_filter_row = FormRow(filter_card.body, self.t("memory_window_importance"))
        importance_filter_row.pack(fill="x", pady=SPACING_SMALL)
        self.importance_filter = importance_filter_row.add_option(self.importance_filter_options(), self.t("memory_window_all_importance"), width=FORM_CONTROL_WIDTH)
        enabled_filter_row = FormRow(filter_card.body, self.t("status"))
        enabled_filter_row.pack(fill="x", pady=SPACING_SMALL)
        self.enabled_filter = enabled_filter_row.add_option(self.enabled_filter_options(), self.t("memory_window_all_status"), width=FORM_CONTROL_WIDTH)
        self.type_filter.configure(command=self.apply_memory_filters)
        self.importance_filter.configure(command=self.apply_memory_filters)
        self.enabled_filter.configure(command=self.apply_memory_filters)

        list_card = SectionCard(left_panel, self.t("memory_list"))
        list_card.grid(row=2, column=0, sticky="nsew")
        list_card.body.grid_columnconfigure(0, weight=1)
        list_card.body.grid_rowconfigure(0, weight=1)
        self.list_box = ctk.CTkOptionMenu(list_card.body, values=[self.t("memory_window_no_memories")])
        self.list_box.grid(row=0, column=0, sticky="ew", pady=SPACING_SMALL)
        self.list_box.configure(command=self.select_memory)
        right_panel = ctk.CTkFrame(self, fg_color="transparent")
        right_panel.grid(row=1, column=1, sticky="nsew", padx=(0, SPACING_LARGE + SPACING_SMALL), pady=(0, SPACING_MEDIUM))
        right_panel.grid_columnconfigure(0, weight=1)
        right_panel.grid_rowconfigure(0, weight=1)

        form_card = SectionCard(right_panel, self.t("detail"))
        form_card.grid(row=0, column=0, sticky="nsew")
        form_card.body.grid_columnconfigure(0, weight=1)
        form_card.body.grid_rowconfigure(1, weight=1)
        self.type_row = FormRow(form_card.body, self.t("type"))
        self.type_row.grid(row=0, column=0, sticky="ew", pady=SPACING_SMALL)
        self.type_box = self.type_row.add_option(self.memory_type_options(), self.memory_type_label("fact"))
        self.content_box = ctk.CTkTextbox(form_card.body, height=120, wrap="word")
        self.content_box.grid(row=1, column=0, sticky="nsew", pady=(SPACING_SMALL, SPACING_MEDIUM))
        bind_text_edit_shortcuts(self.content_box)
        self.attach_text_menu(self.content_box)
        self.importance_row = FormRow(form_card.body, self.t("memory_window_importance"))
        self.importance_row.grid(row=2, column=0, sticky="ew", pady=SPACING_SMALL)
        self.importance_box = self.importance_row.add_option(self.importance_options(), self.importance_label("normal"))
        self.enabled_var = ctk.BooleanVar(value=True)
        self.enabled_switch = ctk.CTkSwitch(
            form_card.body,
            text=self.t("memory_window_enable_memory"),
            variable=self.enabled_var,
            command=self.toggle_memory
        )
        self.enabled_switch.grid(row=3, column=0, sticky="w", pady=(0, SPACING_MEDIUM))
        self.status = StatusLabel(form_card.body, status="disabled", text="")
        self.status.grid(row=4, column=0, sticky="w", pady=(0, SPACING_SMALL))
        self.detail_empty_state = WorkspaceEmptyState(
            form_card.body,
            title=self.t("workspace_memory_no_selection_title"),
            description=self.t("workspace_memory_no_selection_description"),
            action_text=self.t("add"),
            action_callback=self.clear_form
        )
        self.detail_empty_state.grid(row=0, column=0, rowspan=5, sticky="nsew", pady=SPACING_MEDIUM)
        self.detail_editor_widgets = [
            self.type_row,
            self.content_box,
            self.importance_row,
            self.enabled_switch,
            self.status
        ]
        self.hide_detail_editor()

        self.footer = FixedFooter(self)
        self.footer.grid(row=2, column=0, columnspan=2, sticky="ew", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_LARGE))
        self.build_buttons()

    def build_buttons(self):
        actions = [
            (self.t("add"), self.clear_form, SecondaryButton),
            (self.t("save"), self.save_memory, PrimaryButton),
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
        self.more_actions_menu.add_command(label=self.t("delete"), command=self.delete_memory)
        self.more_actions_menu.add_separator()
        self.more_actions_menu.add_command(label=self.t("export_memory"), command=self.export_memory_entry)
        self.more_actions_menu.add_command(label=self.t("import_memory"), command=self.import_memory_entry)

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

    def attach_text_menu(self, widget):
        menu = Menu(widget, tearoff=0)
        menu.add_command(label=self.t("edit_cut"), command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label=self.t("edit_copy"), command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label=self.t("edit_paste"), command=lambda: widget.event_generate("<<Paste>>"))
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

    @staticmethod
    def delete_selection(widget):
        try:
            widget.delete("sel.first", "sel.last")
        except Exception:
            return

    @staticmethod
    def select_all_text(widget):
        try:
            widget.tag_add("sel", "1.0", "end")
            widget.mark_set("insert", "end")
        except Exception:
            return
        return "break"

    def memory_type_labels(self):
        return {
            "preference": self.t("memory_type_preference"),
            "fact": self.t("memory_type_fact"),
            "instruction": self.t("memory_type_instruction"),
            "project": self.t("memory_type_project"),
            "temporary": self.t("memory_type_temporary")
        }

    def importance_labels(self):
        return {
            "low": self.t("memory_importance_low"),
            "normal": self.t("memory_importance_normal"),
            "high": self.t("memory_importance_high")
        }

    def memory_type_label(self, value):
        return self.memory_type_labels().get(str(value or "fact"), str(value or "fact"))

    def memory_type_value(self, label):
        labels = self.memory_type_labels()
        for value, text in labels.items():
            if label == text:
                return value
        return str(label or "fact")

    def importance_label(self, value):
        return self.importance_labels().get(str(value or "normal"), str(value or "normal"))

    def importance_value(self, label):
        labels = self.importance_labels()
        for value, text in labels.items():
            if label == text:
                return value
        return str(label or "normal")

    def memory_type_options(self):
        return [self.memory_type_label(value) for value in ("preference", "fact", "instruction", "project", "temporary")]

    def importance_options(self):
        return [self.importance_label(value) for value in ("low", "normal", "high")]

    def type_filter_options(self):
        return [self.t("memory_window_all_types")] + self.memory_type_options()

    def importance_filter_options(self):
        return [self.t("memory_window_all_importance")] + self.importance_options()

    def enabled_filter_options(self):
        return [self.t("memory_window_all_status"), self.t("enabled"), self.t("disabled")]

    def selected_type_filter(self):
        selected = self.type_filter.get()
        return None if selected == self.t("memory_window_all_types") else self.memory_type_value(selected)

    def selected_importance_filter(self):
        selected = self.importance_filter.get()
        return None if selected == self.t("memory_window_all_importance") else self.importance_value(selected)

    def selected_enabled_filter(self):
        selected = self.enabled_filter.get()
        if selected == self.t("enabled"):
            return True
        if selected == self.t("disabled"):
            return False
        return None

    def search_memory_list(self):
        self.refresh_memory_list(self.memory_search_entry.get())
        self.logger.info("Memory searched")

    def refresh_memory_list(self, keyword=""):
        self.records = self.search_memories(
            self.memory_store.list_memories(),
            keyword,
            memory_type=self.selected_type_filter(),
            importance=self.selected_importance_filter(),
            enabled=self.selected_enabled_filter()
        )
        self.logger.info(f"Memory loaded: {len(self.records)}")
        labels = [
            f"{self.memory_type_label(item.get('type', 'fact'))} | {item.get('content', '')[:45]} | "
            f"{self.importance_label(item.get('importance', 'normal'))} | "
            f"{self.t('enabled') if item.get('enabled', True) else self.t('disabled')} | "
            f"{item.get('updated_time', '').replace('T', ' ')}"
            for item in self.records
        ]
        empty_label = self.t("memory_window_no_memories")
        self.list_box.configure(values=labels or [empty_label])
        self.list_box.set(self.t("memory_select_memory") if labels else empty_label)
    def apply_memory_filters(self, _value=None):
        self.refresh_memory_list(self.memory_search_entry.get())

    def select_memory(self, value):
        values = self.list_box.cget("values")
        index = values.index(value) if value in values else -1
        if index < 0 or index >= len(self.records):
            self.selected_id["value"] = None
            self.is_creating_memory = False
            self.hide_detail_editor()
            return
        item = self.records[index]
        self.selected_id["value"] = item.get("id")
        self.is_creating_memory = False
        self.show_detail_editor()
        self.type_box.set(self.memory_type_label(item.get("type", "fact")))
        self.importance_box.set(self.importance_label(item.get("importance", "normal")))
        self.enabled_var.set(bool(item.get("enabled", True)))
        self.content_box.delete("1.0", "end")
        self.content_box.insert("1.0", item.get("content", ""))

    def clear_form(self):
        self.selected_id["value"] = None
        self.is_creating_memory = True
        self.show_detail_editor()
        self.type_box.set(self.memory_type_label("fact"))
        self.importance_box.set(self.importance_label("normal"))
        self.enabled_var.set(True)
        self.content_box.delete("1.0", "end")
        self.status.set_status("disabled", "")

    def hide_detail_editor(self):
        for widget in self.detail_editor_widgets:
            widget.grid_remove()
        self.detail_empty_state.grid()

    def show_detail_editor(self):
        self.detail_empty_state.grid_remove()
        for widget in self.detail_editor_widgets:
            widget.grid()

    def save_memory(self):
        content = self.content_box.get("1.0", "end").strip()
        if not content:
            self.status.set_status("warning", self.t("memory_window_enter_content"))
            return
        if self.selected_id["value"]:
            self.memory_store.update(
                self.selected_id["value"],
                self.memory_type_value(self.type_box.get()),
                content,
                self.importance_value(self.importance_box.get())
            )
            self.memory_store.set_enabled(self.selected_id["value"], self.enabled_var.get())
            self.logger.info("Memory updated")
            self.status.set_status("healthy", self.t("memory_window_updated"))
        else:
            self.memory_store.create(
                self.memory_type_value(self.type_box.get()),
                content,
                self.importance_value(self.importance_box.get())
            )
            self.logger.info("Memory created")
            self.status.set_status("healthy", self.t("memory_window_created"))
        self.clear_form()
        self.refresh_memory_list()

    def toggle_memory(self):
        if not self.selected_id["value"]:
            return
        self.memory_store.set_enabled(self.selected_id["value"], self.enabled_var.get())
        self.logger.info("Memory enabled changed")
        self.status.set_status("healthy", self.t("memory_window_status_updated"))
        self.refresh_memory_list(self.memory_search_entry.get())

    def delete_memory(self):
        if not self.selected_id["value"]:
            return
        if not messagebox.askyesno(self.t("memory_window_delete_memory"), self.t("memory_window_delete_confirm"), parent=self):
            return
        self.memory_store.delete(self.selected_id["value"])
        self.logger.info("Memory deleted")
        self.status.set_status("disabled", self.t("memory_window_deleted"))
        self.clear_form()
        self.refresh_memory_list()

    def export_memory_entry(self):
        self.status.set_status("warning", self.t("memory_window_export_service_note"))
        self.logger.info("Memory export entry opened")

    def import_memory_entry(self):
        self.status.set_status("warning", self.t("memory_window_import_service_note"))
        self.logger.info("Memory import entry opened")

    def close(self):
        if self.close_callback:
            self.close_callback()

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
    StatusLabel
)


class MemoryWindow(ctk.CTkToplevel):
    def __init__(self, parent, *, memory_store, search_memories, text, translate, logger, on_close=None):
        super().__init__(parent)
        self.memory_store = memory_store
        self.search_memories = search_memories
        self.text = text
        self.t = translate
        self.logger = logger
        self.on_close_callback = on_close
        self.records = []
        self.selected_id = {"value": None}

        self.title(self.t("memory"))
        self.geometry("1100x820")
        self.minsize(980, 720)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.build()
        self.refresh_memory_list()

    def build(self):
        ctk.CTkLabel(self, text=self.t("memory"), font=FONT_TITLE).pack(
            anchor="w",
            padx=SPACING_LARGE + SPACING_SMALL,
            pady=(SPACING_LARGE, SPACING_MEDIUM)
        )

        search_card = SectionCard(self, self.t("memory_window_search_memories"))
        search_card.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_MEDIUM))
        search_row = FormRow(search_card.body, self.t("memory_window_search_memories"))
        search_row.pack(fill="x", pady=SPACING_SMALL)
        self.memory_search_entry = search_row.add_entry("")
        PrimaryButton(
            search_row.control_frame,
            text=self.t("memory_window_search"),
            width=FORM_CONTROL_WIDTH // 3,
            command=self.search_memory_list
        ).pack(side="left", padx=(SPACING_SMALL, 0))

        filter_card = SectionCard(self, self.t("memory_window_filters"))
        filter_card.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_MEDIUM))
        filter_row = FormRow(filter_card.body, self.t("filter"))
        filter_row.pack(fill="x", pady=SPACING_SMALL)
        self.type_filter = filter_row.add_option(self.type_filter_options(), self.t("memory_window_all_types"), width=FORM_CONTROL_WIDTH // 2 + SPACING_LARGE)
        self.importance_filter = filter_row.add_option(self.importance_filter_options(), self.t("memory_window_all_importance"), width=FORM_CONTROL_WIDTH // 2 + SPACING_LARGE)
        self.enabled_filter = filter_row.add_option(self.enabled_filter_options(), self.t("memory_window_all_status"), width=FORM_CONTROL_WIDTH // 2)
        self.type_filter.configure(command=self.apply_memory_filters)
        self.importance_filter.configure(command=self.apply_memory_filters)
        self.enabled_filter.configure(command=self.apply_memory_filters)

        list_card = SectionCard(self, self.t("memory"))
        list_card.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_MEDIUM))
        self.list_box = ctk.CTkOptionMenu(list_card.body, values=[self.t("memory_window_no_memories")], width=FORM_CONTROL_WIDTH * 2 + FORM_CONTROL_WIDTH // 2)
        self.list_box.pack(fill="x", pady=SPACING_SMALL)
        self.list_box.configure(command=self.select_memory)

        form_card = SectionCard(self, self.t("memory_window_detail"))
        form_card.pack(fill="both", expand=True, padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_MEDIUM))
        type_row = FormRow(form_card.body, self.t("type"))
        type_row.pack(fill="x", pady=SPACING_SMALL)
        self.type_box = type_row.add_option(self.memory_type_options(), self.memory_type_label("fact"))
        self.content_box = ctk.CTkTextbox(form_card.body, height=120, wrap="word")
        self.content_box.pack(fill="both", expand=True, pady=(SPACING_SMALL, SPACING_MEDIUM))
        self.attach_text_menu(self.content_box)
        importance_row = FormRow(form_card.body, self.t("memory_window_importance"))
        importance_row.pack(fill="x", pady=SPACING_SMALL)
        self.importance_box = importance_row.add_option(self.importance_options(), self.importance_label("normal"))
        self.enabled_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            form_card.body,
            text=self.t("memory_window_enable_memory"),
            variable=self.enabled_var,
            command=self.toggle_memory
        ).pack(anchor="w", pady=(0, SPACING_MEDIUM))
        self.status = StatusLabel(form_card.body, status="disabled", text="")
        self.status.pack(anchor="w", pady=(0, SPACING_SMALL))

        self.footer = FixedFooter(self)
        self.footer.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_LARGE))
        self.build_buttons()

    def build_buttons(self):
        actions = [
            (self.t("add"), self.clear_form, SecondaryButton),
            (self.t("save"), self.save_memory, PrimaryButton),
            (self.t("delete"), self.delete_memory, DangerButton),
            (self.t("export_memory"), self.export_memory_entry, SecondaryButton),
            (self.t("import_memory"), self.import_memory_entry, SecondaryButton),
            (self.t("close"), self.close, SecondaryButton)
        ]
        for index, (label, command, button_factory) in enumerate(actions):
            button_factory(self.footer.buttons, text=label, command=command).grid(
                row=index // 3,
                column=index % 3,
                sticky="ew",
                padx=SPACING_SMALL,
                pady=SPACING_SMALL
            )
        for column in range(3):
            self.footer.buttons.grid_columnconfigure(column, weight=1)

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
        self.list_box.set(labels[0] if labels else empty_label)

    def apply_memory_filters(self, _value=None):
        self.refresh_memory_list(self.memory_search_entry.get())

    def select_memory(self, value):
        values = self.list_box.cget("values")
        index = values.index(value) if value in values else -1
        if index < 0 or index >= len(self.records):
            self.selected_id["value"] = None
            return
        item = self.records[index]
        self.selected_id["value"] = item.get("id")
        self.type_box.set(self.memory_type_label(item.get("type", "fact")))
        self.importance_box.set(self.importance_label(item.get("importance", "normal")))
        self.enabled_var.set(bool(item.get("enabled", True)))
        self.content_box.delete("1.0", "end")
        self.content_box.insert("1.0", item.get("content", ""))

    def clear_form(self):
        self.selected_id["value"] = None
        self.type_box.set(self.memory_type_label("fact"))
        self.importance_box.set(self.importance_label("normal"))
        self.enabled_var.set(True)
        self.content_box.delete("1.0", "end")
        self.status.set_status("disabled", "")

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
        self.destroy()
        if self.on_close_callback:
            self.on_close_callback()

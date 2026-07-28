import customtkinter as ctk
from tkinter import messagebox

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
        self.geometry("760x600")
        self.minsize(620, 480)
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
        self.type_box = type_row.add_option(["preference", "fact", "project", "temporary"], "fact")
        self.content_box = ctk.CTkTextbox(form_card.body, height=120, wrap="word")
        self.content_box.pack(fill="both", expand=True, pady=(SPACING_SMALL, SPACING_MEDIUM))
        importance_row = FormRow(form_card.body, self.t("memory_window_importance"))
        importance_row.pack(fill="x", pady=SPACING_SMALL)
        self.importance_box = importance_row.add_option(["low", "normal", "high"], "normal")
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
            (self.text["add"], self.clear_form, SecondaryButton),
            (self.text["save"], self.save_memory, PrimaryButton),
            (self.text["delete"], self.delete_memory, DangerButton),
            (self.t("export_memory"), self.export_memory_entry, SecondaryButton),
            (self.t("import_memory"), self.import_memory_entry, SecondaryButton),
            (self.text["close"], self.close, SecondaryButton)
        ]
        for index, (label, command, button_factory) in enumerate(actions):
            button_factory(self.footer.buttons, text=label, command=command).pack(side="left", expand=True, fill="x", padx=SPACING_SMALL)

    def type_filter_options(self):
        return [self.t("memory_window_all_types"), "preference", "fact", "project", "temporary"]

    def importance_filter_options(self):
        return [self.t("memory_window_all_importance"), "low", "normal", "high"]

    def enabled_filter_options(self):
        return [self.t("memory_window_all_status"), self.text["enabled"], self.text["disabled"]]

    def selected_type_filter(self):
        selected = self.type_filter.get()
        return None if selected == self.t("memory_window_all_types") else selected

    def selected_importance_filter(self):
        selected = self.importance_filter.get()
        return None if selected == self.t("memory_window_all_importance") else selected

    def selected_enabled_filter(self):
        selected = self.enabled_filter.get()
        if selected == self.text["enabled"]:
            return True
        if selected == self.text["disabled"]:
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
            f"{item.get('type', 'fact')} | {item.get('content', '')[:45]} | "
            f"{item.get('importance', 'normal')} | "
            f"{self.text['enabled'] if item.get('enabled', True) else self.text['disabled']} | "
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
        self.type_box.set(item.get("type", "fact"))
        self.importance_box.set(item.get("importance", "normal"))
        self.enabled_var.set(bool(item.get("enabled", True)))
        self.content_box.delete("1.0", "end")
        self.content_box.insert("1.0", item.get("content", ""))

    def clear_form(self):
        self.selected_id["value"] = None
        self.type_box.set("fact")
        self.importance_box.set("normal")
        self.enabled_var.set(True)
        self.content_box.delete("1.0", "end")
        self.status.set_status("disabled", "")

    def save_memory(self):
        content = self.content_box.get("1.0", "end").strip()
        if not content:
            self.status.set_status("warning", self.t("memory_window_enter_content"))
            return
        if self.selected_id["value"]:
            self.memory_store.update(self.selected_id["value"], self.type_box.get(), content, self.importance_box.get())
            self.memory_store.set_enabled(self.selected_id["value"], self.enabled_var.get())
            self.logger.info("Memory updated")
            self.status.set_status("healthy", self.t("memory_window_updated"))
        else:
            self.memory_store.create(self.type_box.get(), content, self.importance_box.get())
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

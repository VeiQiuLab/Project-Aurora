import customtkinter as ctk
from tkinter import messagebox

from modules.ui_theme import FONT_TITLE, status_color
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

        self.title(self.text["memory"])
        self.geometry("760x600")
        self.minsize(620, 480)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.build()
        self.refresh_memory_list()

    def build(self):
        ctk.CTkLabel(self, text=self.text["memory"], font=FONT_TITLE).pack(anchor="w", padx=25, pady=(20, 12))

        search_card = SectionCard(self, "Search memories")
        search_card.pack(fill="x", padx=25, pady=(0, 10))
        search_row = FormRow(search_card.body, "Search memories")
        search_row.pack(fill="x", pady=6)
        self.memory_search_entry = search_row.add_entry("")
        PrimaryButton(search_row.control_frame, text="Search", width=80, command=self.search_memory_list).pack(side="left", padx=(6, 0))

        filter_card = SectionCard(self, "Memory Filters")
        filter_card.pack(fill="x", padx=25, pady=(0, 10))
        filter_row = FormRow(filter_card.body, "Filter")
        filter_row.pack(fill="x", pady=6)
        self.type_filter = filter_row.add_option(["All Types", "preference", "fact", "project", "temporary"], "All Types", width=150)
        self.importance_filter = filter_row.add_option(["All Importance", "low", "normal", "high"], "All Importance", width=150)
        self.enabled_filter = filter_row.add_option(["All Status", "Enabled", "Disabled"], "All Status", width=120)
        self.type_filter.configure(command=self.apply_memory_filters)
        self.importance_filter.configure(command=self.apply_memory_filters)
        self.enabled_filter.configure(command=self.apply_memory_filters)

        list_card = SectionCard(self, self.t("memory"))
        list_card.pack(fill="x", padx=25, pady=(0, 12))
        self.list_box = ctk.CTkOptionMenu(list_card.body, values=["No memories available"], width=680)
        self.list_box.pack(fill="x", pady=6)
        self.list_box.configure(command=self.select_memory)

        form_card = SectionCard(self, "Memory Detail")
        form_card.pack(fill="both", expand=True, padx=25, pady=(0, 10))
        type_row = FormRow(form_card.body, self.text["type"])
        type_row.pack(fill="x", pady=6)
        self.type_box = type_row.add_option(["preference", "fact", "project", "temporary"], "fact")
        self.content_box = ctk.CTkTextbox(form_card.body, height=120, wrap="word")
        self.content_box.pack(fill="both", expand=True, pady=(2, 10))
        importance_row = FormRow(form_card.body, self.text["importance"])
        importance_row.pack(fill="x", pady=6)
        self.importance_box = importance_row.add_option(["low", "normal", "high"], "normal")
        self.enabled_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            form_card.body,
            text="Enable Memory",
            variable=self.enabled_var,
            command=self.toggle_memory
        ).pack(anchor="w", pady=(0, 10))
        self.status = StatusLabel(form_card.body, status="disabled", text="")
        self.status.pack(anchor="w", pady=(0, 8))

        self.footer = FixedFooter(self)
        self.footer.pack(fill="x", padx=25, pady=(0, 20))
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
            button_factory(self.footer.buttons, text=label, command=command).pack(side="left", expand=True, fill="x", padx=4)

    def search_memory_list(self):
        self.refresh_memory_list(self.memory_search_entry.get())
        self.logger.info("Memory searched")

    def refresh_memory_list(self, keyword=""):
        selected_type = self.type_filter.get()
        selected_importance = self.importance_filter.get()
        selected_enabled = self.enabled_filter.get()
        self.records = self.search_memories(
            self.memory_store.list_memories(),
            keyword,
            memory_type=None if selected_type == "All Types" else selected_type,
            importance=None if selected_importance == "All Importance" else selected_importance,
            enabled=None if selected_enabled == "All Status" else selected_enabled == "Enabled"
        )
        self.logger.info(f"Memory loaded: {len(self.records)}")
        labels = [
            f"{item.get('type', 'fact')} | {item.get('content', '')[:45]} | "
            f"{item.get('importance', 'normal')} | "
            f"{'Enabled' if item.get('enabled', True) else 'Disabled'} | "
            f"{item.get('updated_time', '').replace('T', ' ')}"
            for item in self.records
        ]
        self.list_box.configure(values=labels or ["No memories available"])
        self.list_box.set(labels[0] if labels else "No memories available")

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
            self.status.set_status("warning", "Please enter memory content.")
            return
        if self.selected_id["value"]:
            self.memory_store.update(self.selected_id["value"], self.type_box.get(), content, self.importance_box.get())
            self.memory_store.set_enabled(self.selected_id["value"], self.enabled_var.get())
            self.logger.info("Memory updated")
            self.status.set_status("healthy", "Memory updated.")
        else:
            self.memory_store.create(self.type_box.get(), content, self.importance_box.get())
            self.logger.info("Memory created")
            self.status.set_status("healthy", "Memory created.")
        self.clear_form()
        self.refresh_memory_list()

    def toggle_memory(self):
        if not self.selected_id["value"]:
            return
        self.memory_store.set_enabled(self.selected_id["value"], self.enabled_var.get())
        self.logger.info("Memory enabled changed")
        self.status.set_status("healthy", "Memory status updated.")
        self.refresh_memory_list(self.memory_search_entry.get())

    def delete_memory(self):
        if not self.selected_id["value"]:
            return
        if not messagebox.askyesno("Delete Memory", "Delete selected memory?", parent=self):
            return
        self.memory_store.delete(self.selected_id["value"])
        self.logger.info("Memory deleted")
        self.status.set_status("disabled", "Memory deleted.")
        self.clear_form()
        self.refresh_memory_list()

    def export_memory_entry(self):
        self.status.set_status("warning", "Memory export should be handled by MemoryStore service.")
        self.logger.info("Memory export entry opened")

    def import_memory_entry(self):
        self.status.set_status("warning", "Memory import should be handled by MemoryStore service.")
        self.logger.info("Memory import entry opened")

    def close(self):
        self.destroy()
        if self.on_close_callback:
            self.on_close_callback()

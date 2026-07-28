import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from modules.ui_theme import FONT_SMALL, FONT_TITLE, status_color
from widgets.ui_components import (
    DangerButton,
    FixedFooter,
    FormRow,
    PrimaryButton,
    SecondaryButton,
    SectionCard,
    StatusLabel
)


class KnowledgeWindow(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        *,
        knowledge_store,
        settings,
        text,
        translate,
        logger,
        version,
        retrieval_summary,
        on_close=None
    ):
        super().__init__(parent)
        self.knowledge_store = knowledge_store
        self.settings = settings
        self.text = text
        self.t = translate
        self.logger = logger
        self.version = version
        self.retrieval_summary = retrieval_summary
        self.on_close_callback = on_close
        self.knowledge_records = []
        self.visible_records = []
        self.backup_records = []
        self.selected_record = {"record": None}
        self.selected_backup = {"record": None}
        self.current_keyword = {"value": ""}
        self.preview_state = {"content": "", "matches": [], "current": -1, "keyword": ""}

        self.title(self.t("knowledge_base"))
        self.geometry("900x760")
        self.minsize(760, 640)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.build()
        self.refresh_backup_history()
        self.refresh_knowledge_list()

    def build(self):
        ctk.CTkLabel(
            self,
            text=self.t("knowledge_base"),
            font=FONT_TITLE
        ).pack(anchor="w", padx=25, pady=(20, 12))

        search_card = SectionCard(self, self.t("search_knowledge"))
        search_card.pack(fill="x", padx=25, pady=(0, 10))
        search_row = FormRow(search_card.body, self.t("search_knowledge"))
        search_row.pack(fill="x", pady=6)
        self.search_entry = search_row.add_entry("")
        self.enabled_filter = search_row.add_option(["All", "Enabled", "Disabled", "Error"], self.stored_filter(), width=130)
        self.search_button = PrimaryButton(search_row.control_frame, text="Search", width=90, command=self.search_knowledge_list)
        self.search_button.pack(side="left", padx=(6, 6))
        self.clear_search_button = SecondaryButton(search_row.control_frame, text="Clear Search", width=110, command=self.clear_search)
        self.clear_search_button.pack(side="left")
        self.enabled_filter.configure(command=self.change_enabled_filter)

        sort_card = SectionCard(self, "Sort")
        sort_card.pack(fill="x", padx=25, pady=(0, 8))
        sort_row = FormRow(sort_card.body, "Sort")
        sort_row.pack(fill="x", pady=6)
        self.sort_field = sort_row.add_option(
            ["Updated Time", "File Name", "File Type", "File Size", "Added Time", "Characters", "Enabled"],
            self.settings.get("knowledge.sort_field", "Updated Time"),
            width=160
        )
        self.sort_direction = sort_row.add_option(
            ["Descending", "Ascending"],
            self.settings.get("knowledge.sort_direction", "Descending"),
            width=130
        )
        self.search_result_label = StatusLabel(sort_row.control_frame, status="disabled", text="")
        self.search_result_label.pack(side="left", padx=(8, 0))
        self.sort_field.configure(command=self.sort_knowledge_list)
        self.sort_direction.configure(command=self.sort_knowledge_list)

        status_card = SectionCard(self, self.t("knowledge_status"))
        status_card.pack(fill="x", padx=25, pady=(0, 8))
        self.stats_label = StatusLabel(status_card.body, status="disabled", text="", wraplength=820, justify="left", anchor="w")
        self.stats_label.pack(anchor="w")
        self.index_status_label = StatusLabel(status_card.body, status="disabled", text="", wraplength=820, justify="left", anchor="w")
        self.index_status_label.pack(anchor="w", pady=(6, 0))

        list_card = SectionCard(self, self.t("knowledge_documents"))
        list_card.pack(fill="x", padx=25, pady=(0, 12))
        self.list_box = ctk.CTkOptionMenu(list_card.body, values=["No knowledge files available"], width=680)
        self.list_box.pack(fill="x", pady=6)
        self.list_box.configure(command=self.select_knowledge)

        detail_card = SectionCard(self, "Preview")
        detail_card.pack(fill="both", expand=True, padx=25, pady=(0, 10))
        self.detail_box = ctk.CTkTextbox(detail_card.body, height=250, wrap="word")
        self.detail_box.pack(fill="both", expand=True)
        self.detail_box.configure(state="disabled")

        preview_row = FormRow(detail_card.body, self.t("search_in_preview"))
        preview_row.pack(fill="x", pady=(8, 0))
        self.preview_search_entry = preview_row.add_entry("")
        self.preview_search_label = StatusLabel(preview_row.control_frame, status="disabled", text="Matches: 0")
        self.preview_search_label.pack(side="left", padx=(6, 6))
        PrimaryButton(preview_row.control_frame, text="Search", width=85, command=self.search_preview_content).pack(side="left", padx=(0, 6))
        SecondaryButton(preview_row.control_frame, text="Next Match", width=105, command=self.next_preview_match).pack(side="left", padx=(0, 6))
        SecondaryButton(preview_row.control_frame, text="Clear", width=75, command=self.clear_preview_search).pack(side="left")

        retrieval_card = SectionCard(self, "Retrieval Test")
        retrieval_card.pack(fill="x", padx=25, pady=(0, 10))
        retrieval_row = FormRow(retrieval_card.body, self.t("knowledge_test_prompt"))
        retrieval_row.pack(fill="x", pady=6)
        self.retrieval_entry = retrieval_row.add_entry("")
        PrimaryButton(retrieval_row.control_frame, text="Test Retrieval", width=120, command=self.test_retrieval).pack(side="left", padx=(6, 0))

        backup_card = SectionCard(self, "Backup")
        backup_card.pack(fill="x", padx=25, pady=(0, 10))
        self.backup_selector = ctk.CTkOptionMenu(
            backup_card.body,
            values=["No backups available"],
            width=500,
            command=self.select_backup
        )
        self.backup_selector.pack(side="left", fill="x", expand=True, padx=(0, 6))
        SecondaryButton(backup_card.body, text="Restore Backup", width=130, command=self.restore_knowledge_backup).pack(side="left", padx=(0, 6))
        DangerButton(backup_card.body, text="Delete Backup", width=120, command=self.delete_knowledge_backup).pack(side="left")

        self.footer = FixedFooter(self)
        self.footer.pack(fill="x", padx=25, pady=(0, 20))
        self.build_buttons()

    def build_buttons(self):
        for column in range(3):
            self.footer.buttons.grid_columnconfigure(column, weight=1)
        actions = [
            ("Add Knowledge", self.add_knowledge, PrimaryButton),
            ("Delete Knowledge", self.delete_knowledge, DangerButton),
            ("Toggle Enabled", self.toggle_knowledge_enabled, SecondaryButton),
            ("Preview", self.preview_knowledge, SecondaryButton),
            ("Refresh", self.refresh_knowledge_list, SecondaryButton),
            ("Create Backup", self.create_knowledge_backup, SecondaryButton),
            ("Export", self.export_knowledge, SecondaryButton),
            ("Import", self.import_knowledge, SecondaryButton),
            ("Health Check", self.health_check_knowledge, PrimaryButton),
            ("Repair Metadata", self.repair_knowledge_metadata, SecondaryButton),
            ("Index Status", self.show_index_status, SecondaryButton),
            ("Rebuild Index", self.rebuild_vector_index, PrimaryButton),
            (self.text["close"], self.close, SecondaryButton)
        ]
        for index, (label_text, command, button_factory) in enumerate(actions):
            button_factory(self.footer.buttons, text=label_text, command=command).grid(
                row=index // 3,
                column=index % 3,
                sticky="ew",
                padx=4,
                pady=4
            )

    def stored_filter(self):
        stored_filter = self.settings.get("knowledge.enabled_filter", "All")
        if stored_filter == "Enabled Only":
            stored_filter = "Enabled"
        elif stored_filter == "Disabled Only":
            stored_filter = "Disabled"
        if stored_filter not in {"All", "Enabled", "Disabled", "Error"}:
            stored_filter = "All"
        return stored_filter

    def format_size(self, size):
        try:
            value = int(size)
        except (TypeError, ValueError):
            value = 0
        if value >= 1024 * 1024:
            return f"{value / 1024 / 1024:.1f} MB"
        if value >= 1024:
            return f"{value / 1024:.1f} KB"
        return f"{value} B"

    def knowledge_label(self, record):
        status = {
            "OK": "OK",
            "Missing File": "Missing File",
            "Invalid Knowledge File": "Invalid Knowledge File",
            "Read Error": "Read Error"
        }.get(record.get("status", "OK"), "Read Error")
        enabled_text = status if status != "OK" else ("Enabled" if record.get("enabled", True) else "Disabled")
        embedding_state = self.knowledge_store.embedding_state(record)
        embedding_text = embedding_state.get("status", record.get("embedding_status", "Not Indexed"))
        vector_text = "Ready" if embedding_state.get("has_embedding") and not embedding_state.get("stale") else embedding_text
        return (
            f"{record.get('file_name', 'Unknown')}\n"
            f"{record.get('file_type', '').upper()} | "
            f"{self.format_size(record.get('file_size', 0))} | "
            f"{enabled_text} | "
            f"Embedding: {embedding_text} | "
            f"Vector: {vector_text} | "
            f"{record.get('added_time', '')} | "
            f"Updated: {record.get('updated_time', '')}"
        )

    def backup_label(self, record):
        return (
            f"{record.get('name', 'Unknown')}\n"
            f"Created: {record.get('created_time', '') or 'Unknown'} | "
            f"Version: {record.get('app_version', record.get('backup_version', 'Unknown'))} | "
            f"Size: {self.format_size(record.get('file_size', 0))} | "
            f"Status: {record.get('status', 'OK')}"
        )

    def set_detail(self, text):
        self.detail_box.configure(state="normal")
        self.detail_box.delete("1.0", "end")
        self.detail_box.insert("end", text)
        self.detail_box.configure(state="disabled")

    def show_detail(self, record):
        if not record:
            self.selected_record["record"] = None
            self.set_detail("No knowledge file selected.")
            return
        self.selected_record["record"] = record
        enabled_text = "Yes" if record.get("enabled", True) else "No"
        embedding_state = self.knowledge_store.embedding_state(record)
        vector_text = "Ready" if embedding_state.get("has_embedding") and not embedding_state.get("stale") else embedding_state.get("status", "Not Indexed")
        self.set_detail(
            f"File: {record.get('file_name', '')}\n"
            f"Type: {record.get('file_type', '')}\n"
            f"Size: {self.format_size(record.get('file_size', 0))}\n"
            f"Added: {record.get('added_time', '')}\n"
            f"Updated: {record.get('updated_time', '')}\n"
            f"Characters: {record.get('character_count', len(str(record.get('content', ''))))}\n"
            f"Retrievable: {'Yes' if self.knowledge_store.valid_for_retrieval(record) else 'No'}\n"
            f"Enabled: {enabled_text}\n"
            f"Status: {record.get('status', 'OK')}\n"
            f"Embedding Status: {embedding_state.get('status', record.get('embedding_status', 'Not Indexed'))}\n"
            f"Embedding Model: {record.get('embedding_model', '') or 'None'}\n"
            f"Embedding Updated: {record.get('embedding_updated_time', '') or 'Never'}\n"
            f"Embedding Dimensions: {record.get('embedding_dimensions', 0)}\n"
            f"Vector Index Status: {vector_text}\n"
            f"Needs Reindex: {'Yes' if embedding_state.get('needs_reindex') else 'No'}\n"
            f"Index Reason: {embedding_state.get('reason', '') or 'OK'}\n"
            f"Source Path: {record.get('source_path', '') or 'Unknown'}\n"
            f"Stored Path: {record.get('stored_path', '')}\n\n"
            "Click Preview to load a limited content preview."
        )

    def update_stats(self):
        stats = self.knowledge_store.health()
        index_health = stats.get("vector_index", {})
        self.stats_label.configure(
            text=(
                f"{self.t('knowledge_status')}: {self.text['enabled'] if self.settings.get('knowledge.enabled', True) else self.text['disabled']}\n"
                f"Documents: {stats['total']} | TXT: {stats['txt']} | Markdown: {stats['md']} | PDF: {stats['pdf']}\n"
                f"Enabled: {stats['enabled']} | Disabled: {stats['disabled']} | Retrievable: {stats['retrievable']}\n"
                f"{self.t('indexed')}: {stats.get('embedding_indexed', 0)} | "
                f"Stale: {stats.get('embedding_stale', 0)} | "
                f"Needs Reindex: {stats.get('embedding_needs_reindex', 0)}"
            ),
            text_color=status_color("disabled")
        )
        self.index_status_label.configure(
            text=(
                f"{self.t('vector_status')}: {'Present' if index_health.get('exists') else 'Missing'}\n"
                f"Entries: {index_health.get('entries', 0)} | Indexed: {index_health.get('indexed', 0)} | "
                f"Missing: {index_health.get('missing', 0)} | Invalid: {index_health.get('invalid', 0)} | "
                f"Orphaned: {index_health.get('orphaned', 0)} | "
                f"Updated: {index_health.get('updated_time', '') or 'Never'}"
            ),
            text_color=status_color("disabled")
        )

    def filter_records(self, records, keyword):
        keyword = keyword.strip().casefold()
        selected_filter = self.enabled_filter.get()
        filtered = []
        for item in records:
            enabled = bool(item.get("enabled", True))
            status = str(item.get("status", "OK"))
            if selected_filter == "Enabled" and (not enabled or status != "OK"):
                continue
            if selected_filter == "Disabled" and enabled:
                continue
            if selected_filter == "Error" and status == "OK":
                continue
            if keyword and not (
                keyword in str(item.get("file_name", "")).casefold()
                or keyword in str(item.get("file_type", "")).casefold()
                or keyword in str(item.get("content", "")).casefold()
            ):
                continue
            filtered.append(item)
        return filtered

    def sort_records(self, records):
        field = self.sort_field.get()
        reverse = self.sort_direction.get() == "Descending"

        def sort_key(item):
            if field == "File Name":
                return str(item.get("file_name", "")).casefold()
            if field == "File Type":
                return str(item.get("file_type", "")).casefold()
            if field == "File Size":
                return int(item.get("file_size", 0) or 0)
            if field == "Added Time":
                return str(item.get("added_time", ""))
            if field == "Characters":
                return int(item.get("character_count", 0) or 0)
            if field == "Enabled":
                return 1 if item.get("enabled", True) else 0
            return str(item.get("updated_time", ""))

        return sorted(records, key=sort_key, reverse=reverse)

    def refresh_knowledge_list(self):
        self.set_detail("Loading knowledge files...")

        def load_records():
            try:
                loaded_records = self.knowledge_store.list_items()
                filtered_records = self.filter_records(loaded_records, self.current_keyword["value"])
                error_message = None
            except Exception as error:
                loaded_records = []
                filtered_records = []
                error_message = str(error)

            def update_records():
                if not self.winfo_exists():
                    return
                if error_message:
                    self.set_detail(f"Knowledge load failed: {error_message}")
                    self.logger.error(f"Knowledge load failed: {error_message}")
                    return
                self.knowledge_records = loaded_records
                self.visible_records = self.sort_records(filtered_records)
                labels = [self.knowledge_label(item) for item in self.visible_records]
                self.list_box.configure(values=labels or ["No knowledge files available"])
                self.list_box.set(labels[0] if labels else "No knowledge files available")
                self.update_stats()
                search_text = self.current_keyword["value"] or "None"
                self.search_result_label.configure(
                    text=(
                        f"Search: {search_text} | Filter: {self.enabled_filter.get()} | "
                        f"Results: {len(self.visible_records)} / {len(self.knowledge_records)}"
                    ),
                    text_color=status_color("disabled")
                )
                self.show_detail(self.visible_records[0] if self.visible_records else None)
                self.logger.info(f"Knowledge loaded: {len(self.knowledge_records)}")

            self.after(0, update_records)

        threading.Thread(target=load_records, daemon=True).start()

    def select_knowledge(self, value):
        record = next((item for item in self.visible_records if self.knowledge_label(item) == value), None)
        self.show_detail(record)

    def search_knowledge_list(self):
        self.current_keyword["value"] = self.search_entry.get().strip()
        self.settings.set("knowledge.enabled_filter", self.enabled_filter.get())
        self.refresh_knowledge_list()
        self.logger.info("Knowledge searched")

    def clear_search(self):
        self.search_entry.delete(0, "end")
        self.current_keyword["value"] = ""
        self.enabled_filter.set("All")
        self.settings.set("knowledge.enabled_filter", "All")
        self.refresh_knowledge_list()
        self.logger.info("Knowledge search cleared")

    def change_enabled_filter(self, _value):
        self.settings.set("knowledge.enabled_filter", self.enabled_filter.get())
        self.refresh_knowledge_list()

    def sort_knowledge_list(self, _value=None):
        self.settings.set("knowledge.sort_field", self.sort_field.get())
        self.settings.set("knowledge.sort_direction", self.sort_direction.get())
        self.refresh_knowledge_list()
        self.logger.info("Knowledge list sorted")

    def add_knowledge(self):
        file_path = filedialog.askopenfilename(
            parent=self,
            title="Add Knowledge",
            filetypes=[
                ("Knowledge files", "*.txt *.md *.pdf"),
                ("Text files", "*.txt"),
                ("Markdown files", "*.md"),
                ("PDF files", "*.pdf")
            ]
        )
        if not file_path:
            return
        self.set_detail("Adding knowledge file...")
        self.run_store_action(
            lambda: self.knowledge_store.add_file(file_path),
            lambda _result: (self.refresh_knowledge_list(), self.logger.info("Knowledge added")),
            "Knowledge add failed"
        )

    def delete_knowledge(self):
        record = self.selected_record["record"]
        if record is None:
            return
        if not messagebox.askyesno("Delete Knowledge", "Delete selected knowledge file?", parent=self):
            return
        self.run_store_action(
            lambda: self.knowledge_store.delete(record["id"]),
            lambda _result: (self.refresh_knowledge_list(), self.logger.info("Knowledge deleted")),
            "Knowledge delete failed"
        )

    def toggle_knowledge_enabled(self):
        record = self.selected_record["record"]
        if record is None:
            self.set_detail("No knowledge file selected.")
            return
        new_value = not bool(record.get("enabled", True))
        self.run_store_action(
            lambda: self.knowledge_store.set_enabled(record["id"], new_value),
            lambda result: (
                self.selected_record.update({"record": result}),
                self.refresh_knowledge_list(),
                self.logger.info("Knowledge enabled" if new_value else "Knowledge disabled")
            ),
            "Knowledge enabled change failed"
        )

    def backup_directory(self):
        configured = Path(str(self.settings.get("knowledge.backup_path", "data/knowledge/backups")))
        if configured.is_absolute():
            return configured
        return Path(__file__).resolve().parent.parent / configured

    def refresh_backup_history(self):
        self.backup_records = self.knowledge_store.list_backups(self.backup_directory())
        labels = [self.backup_label(item) for item in self.backup_records]
        self.backup_selector.configure(values=labels or ["No backups available"])
        self.backup_selector.set(labels[0] if labels else "No backups available")
        self.selected_backup["record"] = self.backup_records[0] if self.backup_records else None

    def select_backup(self, value):
        self.selected_backup["record"] = next(
            (item for item in self.backup_records if self.backup_label(item) == value),
            None
        )

    def knowledge_config_snapshot(self):
        return {
            "enabled": self.settings.get("knowledge.enabled", True),
            "max_results": self.settings.get("knowledge.max_results", 3),
            "preview_limit": self.settings.get("knowledge.preview_limit", 5000),
            "sort_field": self.settings.get("knowledge.sort_field", "Updated Time"),
            "sort_direction": self.settings.get("knowledge.sort_direction", "Descending"),
            "backup_path": self.settings.get("knowledge.backup_path", "data/knowledge/backups"),
            "max_backup_count": self.settings.get("knowledge.max_backup_count", 10)
        }

    def restore_knowledge_config(self, config):
        for key in ("enabled", "max_results", "preview_limit", "sort_field", "sort_direction", "backup_path", "max_backup_count"):
            if key in config:
                self.settings.set(f"knowledge.{key}", config[key])

    def create_knowledge_backup(self):
        self.set_detail("Creating Knowledge backup...")
        self.run_store_action(
            lambda: self.knowledge_store.create_backup(
                self.backup_directory(),
                config=self.knowledge_config_snapshot(),
                app_version=self.version,
                max_backup_count=self.settings.get("knowledge.max_backup_count", 10)
            ),
            self.finish_create_backup,
            "Knowledge backup create failed"
        )

    def finish_create_backup(self, result):
        self.refresh_backup_history()
        cleanup_note = "\nBackup count exceeds max_backup_count. Consider deleting old backups." if result.get("cleanup_required") else ""
        self.set_detail(
            "Knowledge backup created\n\n"
            f"File: {result.get('path', '')}\n"
            f"Backup Count: {result.get('backup_count', 0)} / {result.get('max_backup_count', 10)}"
            f"{cleanup_note}"
        )
        self.logger.info("Knowledge backup created")

    def delete_knowledge_backup(self):
        record = self.selected_backup["record"]
        if record is None:
            self.set_detail("No backup selected.")
            return
        if not messagebox.askyesno("Delete Backup", "Delete selected Knowledge backup?", parent=self):
            return
        self.set_detail("Deleting Knowledge backup...")
        self.run_store_action(
            lambda: self.knowledge_store.delete_backup(record["path"]),
            lambda result: (self.refresh_backup_history(), self.set_detail(f"Knowledge backup deleted:\n{result}"), self.logger.info("Knowledge backup deleted")),
            "Knowledge backup delete failed"
        )

    def restore_knowledge_backup(self):
        record = self.selected_backup["record"]
        if record is None:
            self.set_detail("No backup selected.")
            return
        if record.get("status") != "OK":
            self.set_detail(record.get("status", "Invalid backup format."))
            self.logger.error("Knowledge backup restore failed")
            return
        if not messagebox.askyesno("Restore Backup", "Restore selected Knowledge backup?", parent=self):
            return
        self.set_detail("Restoring Knowledge backup...")

        def action():
            result = self.knowledge_store.import_backup(record["path"], current_version=self.version)
            self.restore_knowledge_config(result.get("config", {}))
            return result

        self.run_store_action(action, self.finish_restore_backup, "Knowledge backup restore failed")

    def finish_restore_backup(self, result):
        self.refresh_knowledge_list()
        self.refresh_backup_history()
        migration_note = "\nBackup migration may be required." if result.get("migration_required") else ""
        if result.get("migration_required"):
            self.logger.info("Knowledge backup migration required")
        self.set_detail(
            "Knowledge backup restored\n\n"
            f"Imported: {result.get('imported', 0)} file(s)\n"
            f"Current Version: {result.get('current_version', self.version)}\n"
            f"Backup Version: {result.get('app_version', 'Unknown')}"
            f"{migration_note}"
        )
        self.logger.info("Knowledge backup restored")

    def export_knowledge(self):
        default_dir = self.backup_directory()
        target = filedialog.asksaveasfilename(
            parent=self,
            title="Export Knowledge",
            initialdir=str(default_dir),
            initialfile="Aurora_Knowledge_Backup.json",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")]
        )
        if not target:
            return
        self.set_detail("Exporting Knowledge...")
        self.run_store_action(
            lambda: self.knowledge_store.export_backup(target, config=self.knowledge_config_snapshot(), app_version=self.version),
            lambda result: (self.refresh_backup_history(), self.set_detail(f"Knowledge exported:\n{result}"), self.logger.info("Knowledge exported")),
            "Knowledge export failed"
        )

    def import_knowledge(self):
        source = filedialog.askopenfilename(parent=self, title="Import Knowledge", filetypes=[("JSON", "*.json")])
        if not source:
            return
        self.set_detail("Importing Knowledge...")

        def action():
            result = self.knowledge_store.import_backup(source, current_version=self.version)
            self.restore_knowledge_config(result.get("config", {}))
            return result

        self.run_store_action(action, self.finish_import, "Knowledge import failed")

    def finish_import(self, result):
        self.refresh_knowledge_list()
        self.refresh_backup_history()
        migration_note = "\nBackup migration may be required." if result.get("migration_required") else ""
        if result.get("migration_required"):
            self.logger.info("Knowledge backup migration required")
        self.set_detail(f"Knowledge imported: {result.get('imported', 0)} file(s){migration_note}")
        self.logger.info("Knowledge imported")

    def health_check_knowledge(self):
        self.set_detail("Checking Knowledge Health...")
        self.run_store_action(
            lambda: self.knowledge_store.health_with_backups(self.backup_directory()),
            self.finish_health_check,
            "Knowledge health check failed"
        )

    def finish_health_check(self, health):
        self.set_detail(
            "Knowledge Health\n\n"
            f"Total Files: {health.get('total', 0)}\n"
            f"Enabled Files: {health.get('enabled', 0)}\n"
            f"Disabled Files: {health.get('disabled', 0)}\n"
            f"TXT Files: {health.get('txt', 0)}\n"
            f"Markdown Files: {health.get('md', 0)}\n"
            f"PDF Files: {health.get('pdf', 0)}\n"
            f"Retrievable Files: {health.get('retrievable', 0)}\n"
            f"Total Characters: {health.get('characters', 0)}\n"
            f"Missing Files: {health.get('missing', 0)}\n"
            f"Metadata Errors: {health.get('metadata_errors', 0)}\n"
            f"Embedding Indexed: {health.get('embedding_indexed', 0)}\n"
            f"Embedding Not Indexed: {health.get('embedding_not_indexed', 0)}\n"
            f"Embedding Stale: {health.get('embedding_stale', 0)}\n"
            f"Embedding Invalid: {health.get('embedding_invalid', 0)}\n"
            f"Embedding Needs Reindex: {health.get('embedding_needs_reindex', 0)}\n"
            f"Vector Index Entries: {health.get('vector_index', {}).get('entries', 0)}\n"
            f"Vector Index Missing: {health.get('vector_index', {}).get('missing', 0)}\n"
            f"Vector Index Stale: {health.get('vector_index', {}).get('stale', 0)}\n"
            f"Vector Index Invalid: {health.get('vector_index', {}).get('invalid', 0)}\n"
            f"Vector Index Orphaned: {health.get('vector_index', {}).get('orphaned', 0)}\n"
            f"Backups: {health.get('backup_count', 0)}\n"
            f"Last Backup: {health.get('last_backup_time', 'None')}\n"
            f"Latest Backup Version: {health.get('latest_backup_version', 'None')}"
        )
        self.logger.info("Knowledge health checked")

    def show_index_status(self):
        self.set_detail("Checking Vector Index...")

        def action():
            records = self.knowledge_store.list_items()
            return {"records": records, "health": self.knowledge_store.vector_index_health(records)}

        self.run_store_action(action, self.finish_index_status, "Knowledge vector index check failed")

    def finish_index_status(self, result):
        records = result.get("records", [])
        health = result.get("health", {})
        self.set_detail(
            "Vector Index Status\n\n"
            f"Knowledge Enabled: {'Yes' if self.settings.get('knowledge.enabled', True) else 'No'}\n"
            f"Documents: {len(records)}\n"
            f"Index File: {health.get('path', '')}\n"
            f"Exists: {'Yes' if health.get('exists') else 'No'}\n"
            f"Format: {health.get('format', '')}\n"
            f"Version: {health.get('version', '')}\n"
            f"Updated: {health.get('updated_time', '') or 'Never'}\n"
            f"Entries: {health.get('entries', 0)}\n"
            f"Indexed: {health.get('indexed', 0)}\n"
            f"Missing: {health.get('missing', 0)}\n"
            f"Stale: {health.get('stale', 0)}\n"
            f"Invalid: {health.get('invalid', 0)}\n"
            f"Orphaned: {health.get('orphaned', 0)}\n"
            f"Needs Reindex: {health.get('needs_reindex', 0)}"
        )
        self.logger.info("Knowledge vector index checked")

    def rebuild_vector_index(self):
        if not messagebox.askyesno("Rebuild Vector Index", "Rebuild Knowledge vector index now?", parent=self):
            return
        self.set_detail("Rebuilding Vector Index...")

        def action():
            result = self.knowledge_store.build_vector_index()
            return {"result": result, "health": self.knowledge_store.vector_index_health()}

        self.run_store_action(action, self.finish_rebuild_vector_index, "Knowledge vector index rebuild failed")

    def finish_rebuild_vector_index(self, payload):
        result = payload.get("result", {})
        health = payload.get("health", {})
        self.refresh_knowledge_list()
        self.set_detail(
            "Vector Index Rebuilt\n\n"
            f"Indexed: {result.get('indexed', 0)}\n"
            f"Errors: {len(result.get('errors', []))}\n"
            f"Index File: {result.get('index_file', '')}\n"
            f"Entries: {health.get('entries', 0)}\n"
            f"Needs Reindex: {health.get('needs_reindex', 0)}"
        )
        self.logger.info("Knowledge vector index rebuilt")

    def repair_knowledge_metadata(self):
        self.set_detail("Repairing Knowledge Metadata...")
        self.run_store_action(
            self.knowledge_store.repair_metadata,
            lambda result: (self.refresh_knowledge_list(), self.set_detail(f"Knowledge metadata repaired\n\nRecords repaired: {result.get('repaired', 0)}\nErrors: {len(result.get('errors', []))}"), self.logger.info("Knowledge metadata repaired"), self.logger.info("Knowledge repair completed")),
            "Knowledge repair failed"
        )

    def preview_knowledge(self):
        record = self.selected_record["record"]
        if record is None:
            self.set_detail("No knowledge file selected.")
            return
        self.set_detail("Loading preview...")
        self.run_store_action(
            lambda: self.knowledge_store.preview_details(record["id"], limit=self.settings.get("knowledge.preview_limit", 5000)),
            self.finish_preview,
            "Knowledge preview failed"
        )

    def finish_preview(self, preview):
        self.preview_state["content"] = preview.get("content", "")
        self.preview_state["matches"] = []
        self.preview_state["current"] = -1
        self.preview_state["keyword"] = ""
        self.preview_search_label.configure(text="Matches: 0")
        truncated_note = "\nContent preview truncated." if preview.get("truncated") else ""
        self.set_detail(
            f"Preview: {preview.get('file_name', '')}\n"
            f"Type: {preview.get('file_type', '')}\n"
            f"Characters: {preview.get('character_count', 0)}\n"
            f"Preview Characters: {preview.get('preview_count', 0)}\n"
            f"Truncated: {'Yes' if preview.get('truncated') else 'No'}"
            f"{truncated_note}\n\n"
            f"{preview.get('content', '')}"
        )
        self.logger.info("Knowledge preview opened")

    def show_preview_match(self):
        matches = self.preview_state["matches"]
        current = self.preview_state["current"]
        if not matches or current < 0:
            self.preview_search_label.configure(text="Matches: 0")
            return
        position = matches[current]
        self.preview_search_label.configure(
            text=f"Matches: {len(matches)} | Current: {current + 1} / {len(matches)} | Position: {position}"
        )

    def search_preview_content(self):
        keyword = self.preview_search_entry.get().strip()
        self.preview_state["keyword"] = keyword
        self.preview_state["matches"] = self.knowledge_store.search_preview(self.preview_state["content"], keyword)
        self.preview_state["current"] = 0 if self.preview_state["matches"] else -1
        self.show_preview_match()
        self.logger.info("Knowledge preview searched")

    def next_preview_match(self):
        if not self.preview_state["matches"]:
            self.show_preview_match()
            return
        self.preview_state["current"] = (self.preview_state["current"] + 1) % len(self.preview_state["matches"])
        self.show_preview_match()
        self.logger.info("Knowledge preview next match")

    def clear_preview_search(self):
        self.preview_search_entry.delete(0, "end")
        self.preview_state["matches"] = []
        self.preview_state["current"] = -1
        self.preview_state["keyword"] = ""
        self.preview_search_label.configure(text="Matches: 0")
        self.logger.info("Knowledge preview search cleared")

    def test_retrieval(self):
        prompt = self.retrieval_entry.get().strip()
        if not prompt:
            self.set_detail("Please enter a test prompt.")
            return
        self.set_detail("Testing retrieval...")

        def action():
            try:
                max_results = max(0, int(self.settings.get("knowledge.max_results", 3)))
            except (TypeError, ValueError):
                max_results = 3
            items = self.knowledge_store.list_items()
            return self.retrieval_summary(
                prompt,
                items,
                max_results=max_results,
                knowledge_enabled=self.settings.get("knowledge.enabled", True)
            )

        self.run_store_action(action, self.finish_retrieval_test, "Knowledge retrieval test failed")

    def finish_retrieval_test(self, summary):
        results = summary.get("results", [])
        lines = [
            "Summary",
            f"Prompt: {summary.get('prompt', '')}",
            f"Knowledge Enabled: {'Yes' if summary.get('knowledge_enabled') else 'No'}",
            f"Maximum Knowledge Results: {summary.get('max_results', 0)}",
            f"Matched Count: {summary.get('matched_count', 0)}",
            f"Injected Count: {summary.get('injected_count', 0)}",
            ""
        ]
        if not summary.get("knowledge_enabled"):
            lines.append("Knowledge Retrieval is disabled in Settings.")
        elif not summary.get("enabled_available"):
            lines.append("No enabled knowledge files available.")
        elif not results:
            lines.append("No knowledge matched this prompt.")
        else:
            lines.append("Matched:")
            for item in results:
                lines.extend([
                    f"\n{item.get('file_name', 'Unknown')}",
                    f"Enabled: {'Yes' if item.get('enabled') else 'No'}",
                    f"Status: {item.get('status', 'OK')}",
                    f"Score: {item.get('score', 0)}",
                    f"Matched Keywords: {', '.join(item.get('keywords', [])) or 'None'}"
                ])
                if item.get("line"):
                    lines.append(f"Line: {item.get('line')}")
                lines.extend([
                    f"Character Range: {item.get('start', 0)} - {item.get('end', 0)}",
                    f"Snippet:\n{item.get('snippet', '') or 'No text snippet available.'}",
                    f"Injected: {'Yes' if item.get('injected') else 'No'}"
                ])
        self.set_detail("\n".join(lines))
        self.logger.info("Knowledge retrieval tested")
        self.logger.info("Knowledge retrieval explained")

    def run_store_action(self, action, on_success, error_prefix):
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
                    self.set_detail(f"{error_prefix}: {error_message}")
                    self.logger.error(f"{error_prefix}: {error_message}")
                    return
                on_success(result)

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def close(self):
        self.destroy()
        if self.on_close_callback:
            self.on_close_callback()

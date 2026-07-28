import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from modules.ui_theme import (
    FORM_CONTROL_WIDTH,
    FORM_LABEL_WRAP,
    FONT_SMALL,
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


class KnowledgeWindow(ctk.CTkToplevel):
    FILTER_OPTIONS = ["All", "Enabled", "Disabled", "Error"]
    SORT_FIELDS = ["Updated Time", "File Name", "File Type", "File Size", "Added Time", "Characters", "Enabled"]
    SORT_DIRECTIONS = ["Descending", "Ascending"]

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
        ).pack(
            anchor="w",
            padx=SPACING_LARGE + SPACING_SMALL,
            pady=(SPACING_LARGE, SPACING_MEDIUM)
        )

        search_card = SectionCard(self, self.t("search_knowledge"))
        search_card.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_MEDIUM))
        search_row = FormRow(search_card.body, self.t("search_knowledge"))
        search_row.pack(fill="x", pady=SPACING_SMALL)
        self.search_entry = search_row.add_entry("")
        self.enabled_filter = search_row.add_option(self.FILTER_OPTIONS, self.stored_filter(), width=FORM_CONTROL_WIDTH // 2)
        self.search_button = PrimaryButton(
            search_row.control_frame,
            text=self.t("knowledge_window_search"),
            width=FORM_CONTROL_WIDTH // 3,
            command=self.search_knowledge_list
        )
        self.search_button.pack(side="left", padx=(SPACING_SMALL, SPACING_SMALL))
        self.clear_search_button = SecondaryButton(
            search_row.control_frame,
            text=self.t("knowledge_window_clear_search"),
            width=FORM_CONTROL_WIDTH // 2,
            command=self.clear_search
        )
        self.clear_search_button.pack(side="left")
        self.enabled_filter.configure(command=self.change_enabled_filter)

        sort_card = SectionCard(self, self.t("knowledge_window_sort"))
        sort_card.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_SMALL))
        sort_row = FormRow(sort_card.body, self.t("knowledge_window_sort"))
        sort_row.pack(fill="x", pady=SPACING_SMALL)
        self.sort_field = sort_row.add_option(
            self.SORT_FIELDS,
            self.settings.get("knowledge.sort_field", "Updated Time"),
            width=FORM_CONTROL_WIDTH // 2 + SPACING_LARGE
        )
        self.sort_direction = sort_row.add_option(
            self.SORT_DIRECTIONS,
            self.settings.get("knowledge.sort_direction", "Descending"),
            width=FORM_CONTROL_WIDTH // 2
        )
        self.search_result_label = StatusLabel(sort_row.control_frame, status="disabled", text="")
        self.search_result_label.pack(side="left", padx=(SPACING_SMALL, 0))
        self.sort_field.configure(command=self.sort_knowledge_list)
        self.sort_direction.configure(command=self.sort_knowledge_list)

        status_card = SectionCard(self, self.t("knowledge_status"))
        status_card.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_SMALL))
        self.stats_label = StatusLabel(status_card.body, status="disabled", text="", wraplength=FORM_LABEL_WRAP * 2, justify="left", anchor="w")
        self.stats_label.pack(anchor="w")
        self.index_status_label = StatusLabel(status_card.body, status="disabled", text="", wraplength=FORM_LABEL_WRAP * 2, justify="left", anchor="w")
        self.index_status_label.pack(anchor="w", pady=(SPACING_SMALL, 0))

        list_card = SectionCard(self, self.t("knowledge_documents"))
        list_card.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_MEDIUM))
        self.list_box = ctk.CTkOptionMenu(
            list_card.body,
            values=[self.t("knowledge_window_no_files")],
            width=FORM_CONTROL_WIDTH * 2 + FORM_CONTROL_WIDTH // 2
        )
        self.list_box.pack(fill="x", pady=SPACING_SMALL)
        self.list_box.configure(command=self.select_knowledge)

        detail_card = SectionCard(self, self.t("knowledge_window_preview"))
        detail_card.pack(fill="both", expand=True, padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_MEDIUM))
        self.detail_box = ctk.CTkTextbox(detail_card.body, height=250, wrap="word")
        self.detail_box.pack(fill="both", expand=True)
        self.detail_box.configure(state="disabled")

        preview_row = FormRow(detail_card.body, self.t("search_in_preview"))
        preview_row.pack(fill="x", pady=(SPACING_SMALL, 0))
        self.preview_search_entry = preview_row.add_entry("")
        self.preview_search_label = StatusLabel(preview_row.control_frame, status="disabled", text=self.matches_text(0))
        self.preview_search_label.pack(side="left", padx=(SPACING_SMALL, SPACING_SMALL))
        PrimaryButton(
            preview_row.control_frame,
            text=self.t("knowledge_window_search"),
            width=FORM_CONTROL_WIDTH // 3,
            command=self.search_preview_content
        ).pack(side="left", padx=(0, SPACING_SMALL))
        SecondaryButton(
            preview_row.control_frame,
            text=self.t("knowledge_window_next_match"),
            width=FORM_CONTROL_WIDTH // 2,
            command=self.next_preview_match
        ).pack(side="left", padx=(0, SPACING_SMALL))
        SecondaryButton(
            preview_row.control_frame,
            text=self.t("clear"),
            width=FORM_CONTROL_WIDTH // 3,
            command=self.clear_preview_search
        ).pack(side="left")

        retrieval_card = SectionCard(self, self.t("knowledge_window_retrieval_test"))
        retrieval_card.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_MEDIUM))
        retrieval_row = FormRow(retrieval_card.body, self.t("knowledge_test_prompt"))
        retrieval_row.pack(fill="x", pady=SPACING_SMALL)
        self.retrieval_entry = retrieval_row.add_entry("")
        PrimaryButton(
            retrieval_row.control_frame,
            text=self.t("knowledge_window_test_retrieval"),
            width=FORM_CONTROL_WIDTH // 2,
            command=self.test_retrieval
        ).pack(side="left", padx=(SPACING_SMALL, 0))

        backup_card = SectionCard(self, self.t("knowledge_window_backup"))
        backup_card.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_MEDIUM))
        self.backup_selector = ctk.CTkOptionMenu(
            backup_card.body,
            values=[self.t("knowledge_window_no_backups")],
            width=FORM_CONTROL_WIDTH * 2,
            command=self.select_backup
        )
        self.backup_selector.pack(side="left", fill="x", expand=True, padx=(0, SPACING_SMALL))
        SecondaryButton(
            backup_card.body,
            text=self.t("knowledge_window_restore_backup"),
            width=FORM_CONTROL_WIDTH // 2,
            command=self.restore_knowledge_backup
        ).pack(side="left", padx=(0, SPACING_SMALL))
        DangerButton(
            backup_card.body,
            text=self.t("knowledge_window_delete_backup"),
            width=FORM_CONTROL_WIDTH // 2,
            command=self.delete_knowledge_backup
        ).pack(side="left")

        self.footer = FixedFooter(self)
        self.footer.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_LARGE))
        self.build_buttons()

    def build_buttons(self):
        for column in range(3):
            self.footer.buttons.grid_columnconfigure(column, weight=1)
        actions = [
            (self.t("knowledge_window_add_knowledge"), self.add_knowledge, PrimaryButton),
            (self.t("knowledge_window_delete_knowledge"), self.delete_knowledge, DangerButton),
            (self.t("knowledge_window_toggle_enabled"), self.toggle_knowledge_enabled, SecondaryButton),
            (self.t("knowledge_window_preview"), self.preview_knowledge, SecondaryButton),
            (self.t("refresh"), self.refresh_knowledge_list, SecondaryButton),
            (self.t("knowledge_window_create_backup"), self.create_knowledge_backup, SecondaryButton),
            (self.t("knowledge_window_export"), self.export_knowledge, SecondaryButton),
            (self.t("knowledge_window_import"), self.import_knowledge, SecondaryButton),
            (self.t("health_check"), self.health_check_knowledge, PrimaryButton),
            (self.t("library_page_metadata_repair"), self.repair_knowledge_metadata, SecondaryButton),
            (self.t("knowledge_window_index_status"), self.show_index_status, SecondaryButton),
            (self.t("library_page_rebuild_index"), self.rebuild_vector_index, PrimaryButton),
            (self.text["close"], self.close, SecondaryButton)
        ]
        for index, (label_text, command, button_factory) in enumerate(actions):
            button_factory(self.footer.buttons, text=label_text, command=command).grid(
                row=index // 3,
                column=index % 3,
                sticky="ew",
                padx=SPACING_SMALL,
                pady=SPACING_SMALL
            )

    def yes_no(self, value):
        return self.text["yes"] if value else self.text["no"]

    def unknown_text(self):
        return self.t("settings_window_unknown_status")

    def none_text(self):
        return self.t("none")

    def never_text(self):
        return self.t("knowledge_window_never")

    def ok_text(self):
        return self.t("ok")

    def status_text(self, status):
        return {
            "OK": self.ok_text(),
            "Missing File": self.t("knowledge_window_status_missing_file"),
            "Invalid Knowledge File": self.t("knowledge_window_status_invalid_file"),
            "Read Error": self.t("knowledge_window_status_read_error"),
            "Not Indexed": self.t("knowledge_window_not_indexed"),
            "Ready": self.t("knowledge_window_ready")
        }.get(str(status), str(status))

    def matches_text(self, count, current=None, total=None, position=None):
        if current is None:
            return self.t("knowledge_window_matches").format(count=count)
        return self.t("knowledge_window_matches_position").format(
            count=count,
            current=current,
            total=total,
            position=position
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
        enabled_text = self.status_text(status) if status != "OK" else (self.text["enabled"] if record.get("enabled", True) else self.text["disabled"])
        embedding_state = self.knowledge_store.embedding_state(record)
        embedding_text = embedding_state.get("status", record.get("embedding_status", "Not Indexed"))
        vector_text = self.status_text("Ready") if embedding_state.get("has_embedding") and not embedding_state.get("stale") else self.status_text(embedding_text)
        return (
            f"{record.get('file_name', self.unknown_text())}\n"
            f"{record.get('file_type', '').upper()} | "
            f"{self.format_size(record.get('file_size', 0))} | "
            f"{enabled_text} | "
            f"{self.t('embedding')}: {self.status_text(embedding_text)} | "
            f"{self.t('vector')}: {vector_text} | "
            f"{record.get('added_time', '')} | "
            f"{self.t('knowledge_window_updated')}: {record.get('updated_time', '')}"
        )

    def backup_label(self, record):
        return (
            f"{record.get('name', self.unknown_text())}\n"
            f"{self.t('created')}: {record.get('created_time', '') or self.unknown_text()} | "
            f"{self.t('version')}: {record.get('app_version', record.get('backup_version', self.unknown_text()))} | "
            f"{self.t('size')}: {self.format_size(record.get('file_size', 0))} | "
            f"{self.t('status')}: {self.status_text(record.get('status', 'OK'))}"
        )

    def set_detail(self, text):
        self.detail_box.configure(state="normal")
        self.detail_box.delete("1.0", "end")
        self.detail_box.insert("end", text)
        self.detail_box.configure(state="disabled")

    def show_detail(self, record):
        if not record:
            self.selected_record["record"] = None
            self.set_detail(self.t("knowledge_window_no_file_selected"))
            return
        self.selected_record["record"] = record
        enabled_text = self.yes_no(record.get("enabled", True))
        embedding_state = self.knowledge_store.embedding_state(record)
        vector_text = self.status_text("Ready") if embedding_state.get("has_embedding") and not embedding_state.get("stale") else self.status_text(embedding_state.get("status", "Not Indexed"))
        self.set_detail(
            f"{self.t('knowledge_window_file')}: {record.get('file_name', '')}\n"
            f"{self.t('type')}: {record.get('file_type', '')}\n"
            f"{self.t('size')}: {self.format_size(record.get('file_size', 0))}\n"
            f"{self.t('knowledge_window_added')}: {record.get('added_time', '')}\n"
            f"{self.t('knowledge_window_updated')}: {record.get('updated_time', '')}\n"
            f"{self.t('characters')}: {record.get('character_count', len(str(record.get('content', ''))))}\n"
            f"{self.t('knowledge_window_retrievable')}: {self.yes_no(self.knowledge_store.valid_for_retrieval(record))}\n"
            f"{self.t('enabled')}: {enabled_text}\n"
            f"{self.t('status')}: {self.status_text(record.get('status', 'OK'))}\n"
            f"{self.t('knowledge_window_embedding_status')}: {self.status_text(embedding_state.get('status', record.get('embedding_status', 'Not Indexed')))}\n"
            f"{self.t('embedding_model')}: {record.get('embedding_model', '') or self.none_text()}\n"
            f"{self.t('knowledge_window_embedding_updated')}: {record.get('embedding_updated_time', '') or self.never_text()}\n"
            f"{self.t('knowledge_window_embedding_dimensions')}: {record.get('embedding_dimensions', 0)}\n"
            f"{self.t('knowledge_window_vector_index_status')}: {vector_text}\n"
            f"{self.t('knowledge_window_needs_reindex')}: {self.yes_no(embedding_state.get('needs_reindex'))}\n"
            f"{self.t('knowledge_window_index_reason')}: {embedding_state.get('reason', '') or self.ok_text()}\n"
            f"{self.t('knowledge_window_source_path')}: {record.get('source_path', '') or self.unknown_text()}\n"
            f"{self.t('knowledge_window_stored_path')}: {record.get('stored_path', '')}\n\n"
            f"{self.t('knowledge_window_preview_hint')}"
        )

    def update_stats(self):
        stats = self.knowledge_store.health()
        index_health = stats.get("vector_index", {})
        self.stats_label.configure(
            text=(
                f"{self.t('knowledge_status')}: {self.text['enabled'] if self.settings.get('knowledge.enabled', True) else self.text['disabled']}\n"
                f"{self.t('documents')}: {stats['total']} | TXT: {stats['txt']} | Markdown: {stats['md']} | PDF: {stats['pdf']}\n"
                f"{self.text['enabled']}: {stats['enabled']} | {self.text['disabled']}: {stats['disabled']} | {self.t('knowledge_window_retrievable')}: {stats['retrievable']}\n"
                f"{self.t('indexed')}: {stats.get('embedding_indexed', 0)} | "
                f"{self.t('knowledge_window_stale')}: {stats.get('embedding_stale', 0)} | "
                f"{self.t('knowledge_window_needs_reindex')}: {stats.get('embedding_needs_reindex', 0)}"
            ),
            text_color=status_color("disabled")
        )
        self.index_status_label.configure(
            text=(
                f"{self.t('vector_status')}: {self.t('present') if index_health.get('exists') else self.t('missing')}\n"
                f"{self.t('entries')}: {index_health.get('entries', 0)} | {self.t('indexed')}: {index_health.get('indexed', 0)} | "
                f"{self.t('missing')}: {index_health.get('missing', 0)} | {self.t('invalid')}: {index_health.get('invalid', 0)} | "
                f"{self.t('orphaned')}: {index_health.get('orphaned', 0)} | "
                f"{self.t('knowledge_window_updated')}: {index_health.get('updated_time', '') or self.never_text()}"
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
        self.set_detail(self.t("knowledge_window_loading_files"))

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
                    self.set_detail(f"{self.t('knowledge_window_load_failed')}: {error_message}")
                    self.logger.error(f"Knowledge load failed: {error_message}")
                    return
                self.knowledge_records = loaded_records
                self.visible_records = self.sort_records(filtered_records)
                labels = [self.knowledge_label(item) for item in self.visible_records]
                empty_label = self.t("knowledge_window_no_files")
                self.list_box.configure(values=labels or [empty_label])
                self.list_box.set(labels[0] if labels else empty_label)
                self.update_stats()
                search_text = self.current_keyword["value"] or self.none_text()
                self.search_result_label.configure(
                    text=(
                        f"{self.t('knowledge_window_search')}: {search_text} | {self.t('filter')}: {self.enabled_filter.get()} | "
                        f"{self.t('results')}: {len(self.visible_records)} / {len(self.knowledge_records)}"
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
            title=self.t("knowledge_window_add_knowledge"),
            filetypes=[
                (self.t("knowledge_window_filetype_knowledge"), "*.txt *.md *.pdf"),
                (self.t("knowledge_window_filetype_text"), "*.txt"),
                (self.t("knowledge_window_filetype_markdown"), "*.md"),
                (self.t("knowledge_window_filetype_pdf"), "*.pdf")
            ]
        )
        if not file_path:
            return
        self.set_detail(self.t("knowledge_window_adding_file"))
        self.run_store_action(
            lambda: self.knowledge_store.add_file(file_path),
            lambda _result: (self.refresh_knowledge_list(), self.logger.info("Knowledge added")),
            self.t("knowledge_window_add_failed")
        )

    def delete_knowledge(self):
        record = self.selected_record["record"]
        if record is None:
            return
        if not messagebox.askyesno(self.t("knowledge_window_delete_knowledge"), self.t("knowledge_window_delete_confirm"), parent=self):
            return
        self.run_store_action(
            lambda: self.knowledge_store.delete(record["id"]),
            lambda _result: (self.refresh_knowledge_list(), self.logger.info("Knowledge deleted")),
            self.t("knowledge_window_delete_failed")
        )

    def toggle_knowledge_enabled(self):
        record = self.selected_record["record"]
        if record is None:
            self.set_detail(self.t("knowledge_window_no_file_selected"))
            return
        new_value = not bool(record.get("enabled", True))
        self.run_store_action(
            lambda: self.knowledge_store.set_enabled(record["id"], new_value),
            lambda result: (
                self.selected_record.update({"record": result}),
                self.refresh_knowledge_list(),
                self.logger.info("Knowledge enabled" if new_value else "Knowledge disabled")
            ),
            self.t("knowledge_window_enabled_change_failed")
        )

    def backup_directory(self):
        configured = Path(str(self.settings.get("knowledge.backup_path", "data/knowledge/backups")))
        if configured.is_absolute():
            return configured
        return Path(__file__).resolve().parent.parent / configured

    def refresh_backup_history(self):
        self.backup_records = self.knowledge_store.list_backups(self.backup_directory())
        labels = [self.backup_label(item) for item in self.backup_records]
        empty_label = self.t("knowledge_window_no_backups")
        self.backup_selector.configure(values=labels or [empty_label])
        self.backup_selector.set(labels[0] if labels else empty_label)
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
        self.set_detail(self.t("knowledge_window_creating_backup"))
        self.run_store_action(
            lambda: self.knowledge_store.create_backup(
                self.backup_directory(),
                config=self.knowledge_config_snapshot(),
                app_version=self.version,
                max_backup_count=self.settings.get("knowledge.max_backup_count", 10)
            ),
            self.finish_create_backup,
            self.t("knowledge_window_backup_create_failed")
        )

    def finish_create_backup(self, result):
        self.refresh_backup_history()
        cleanup_note = f"\n{self.t('knowledge_window_backup_cleanup_note')}" if result.get("cleanup_required") else ""
        self.set_detail(
            f"{self.t('knowledge_window_backup_created')}\n\n"
            f"{self.t('file')}: {result.get('path', '')}\n"
            f"{self.t('knowledge_window_backup_count')}: {result.get('backup_count', 0)} / {result.get('max_backup_count', 10)}"
            f"{cleanup_note}"
        )
        self.logger.info("Knowledge backup created")

    def delete_knowledge_backup(self):
        record = self.selected_backup["record"]
        if record is None:
            self.set_detail(self.t("knowledge_window_no_backup_selected"))
            return
        if not messagebox.askyesno(self.t("knowledge_window_delete_backup"), self.t("knowledge_window_delete_backup_confirm"), parent=self):
            return
        self.set_detail(self.t("knowledge_window_deleting_backup"))
        self.run_store_action(
            lambda: self.knowledge_store.delete_backup(record["path"]),
            lambda result: (self.refresh_backup_history(), self.set_detail(f"{self.t('knowledge_window_backup_deleted')}:\n{result}"), self.logger.info("Knowledge backup deleted")),
            self.t("knowledge_window_backup_delete_failed")
        )

    def restore_knowledge_backup(self):
        record = self.selected_backup["record"]
        if record is None:
            self.set_detail(self.t("knowledge_window_no_backup_selected"))
            return
        if record.get("status") != "OK":
            self.set_detail(self.status_text(record.get("status", self.t("knowledge_window_invalid_backup"))))
            self.logger.error("Knowledge backup restore failed")
            return
        if not messagebox.askyesno(self.t("knowledge_window_restore_backup"), self.t("knowledge_window_restore_backup_confirm"), parent=self):
            return
        self.set_detail(self.t("knowledge_window_restoring_backup"))

        def action():
            result = self.knowledge_store.import_backup(record["path"], current_version=self.version)
            self.restore_knowledge_config(result.get("config", {}))
            return result

        self.run_store_action(action, self.finish_restore_backup, self.t("knowledge_window_backup_restore_failed"))

    def finish_restore_backup(self, result):
        self.refresh_knowledge_list()
        self.refresh_backup_history()
        migration_note = f"\n{self.t('knowledge_window_backup_migration_note')}" if result.get("migration_required") else ""
        if result.get("migration_required"):
            self.logger.info("Knowledge backup migration required")
        self.set_detail(
            f"{self.t('knowledge_window_backup_restored')}\n\n"
            f"{self.t('imported')}: {result.get('imported', 0)} {self.t('files')}\n"
            f"{self.t('current_version')}: {result.get('current_version', self.version)}\n"
            f"{self.t('backup_version')}: {result.get('app_version', self.unknown_text())}"
            f"{migration_note}"
        )
        self.logger.info("Knowledge backup restored")

    def export_knowledge(self):
        default_dir = self.backup_directory()
        target = filedialog.asksaveasfilename(
            parent=self,
            title=self.t("knowledge_window_export"),
            initialdir=str(default_dir),
            initialfile="Aurora_Knowledge_Backup.json",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")]
        )
        if not target:
            return
        self.set_detail(self.t("knowledge_window_exporting"))
        self.run_store_action(
            lambda: self.knowledge_store.export_backup(target, config=self.knowledge_config_snapshot(), app_version=self.version),
            lambda result: (self.refresh_backup_history(), self.set_detail(f"{self.t('knowledge_window_exported')}:\n{result}"), self.logger.info("Knowledge exported")),
            self.t("knowledge_window_export_failed")
        )

    def import_knowledge(self):
        source = filedialog.askopenfilename(parent=self, title=self.t("knowledge_window_import"), filetypes=[("JSON", "*.json")])
        if not source:
            return
        self.set_detail(self.t("knowledge_window_importing"))

        def action():
            result = self.knowledge_store.import_backup(source, current_version=self.version)
            self.restore_knowledge_config(result.get("config", {}))
            return result

        self.run_store_action(action, self.finish_import, self.t("knowledge_window_import_failed"))

    def finish_import(self, result):
        self.refresh_knowledge_list()
        self.refresh_backup_history()
        migration_note = f"\n{self.t('knowledge_window_backup_migration_note')}" if result.get("migration_required") else ""
        if result.get("migration_required"):
            self.logger.info("Knowledge backup migration required")
        self.set_detail(f"{self.t('knowledge_window_imported')}: {result.get('imported', 0)} {self.t('files')}{migration_note}")
        self.logger.info("Knowledge imported")

    def health_check_knowledge(self):
        self.set_detail(self.t("knowledge_window_checking_health"))
        self.run_store_action(
            lambda: self.knowledge_store.health_with_backups(self.backup_directory()),
            self.finish_health_check,
            self.t("knowledge_window_health_failed")
        )

    def finish_health_check(self, health):
        self.set_detail(
            f"{self.t('knowledge_window_health')}\n\n"
            f"{self.t('total_files')}: {health.get('total', 0)}\n"
            f"{self.t('enabled_files')}: {health.get('enabled', 0)}\n"
            f"{self.t('disabled_files')}: {health.get('disabled', 0)}\n"
            f"TXT {self.t('files')}: {health.get('txt', 0)}\n"
            f"Markdown {self.t('files')}: {health.get('md', 0)}\n"
            f"PDF {self.t('files')}: {health.get('pdf', 0)}\n"
            f"{self.t('retrievable_files')}: {health.get('retrievable', 0)}\n"
            f"{self.t('total_characters')}: {health.get('characters', 0)}\n"
            f"{self.t('missing_files')}: {health.get('missing', 0)}\n"
            f"{self.t('metadata_errors')}: {health.get('metadata_errors', 0)}\n"
            f"{self.t('embedding_indexed')}: {health.get('embedding_indexed', 0)}\n"
            f"{self.t('embedding_not_indexed')}: {health.get('embedding_not_indexed', 0)}\n"
            f"{self.t('embedding_stale')}: {health.get('embedding_stale', 0)}\n"
            f"{self.t('embedding_invalid')}: {health.get('embedding_invalid', 0)}\n"
            f"{self.t('embedding_needs_reindex')}: {health.get('embedding_needs_reindex', 0)}\n"
            f"{self.t('vector_index_entries')}: {health.get('vector_index', {}).get('entries', 0)}\n"
            f"{self.t('vector_index_missing')}: {health.get('vector_index', {}).get('missing', 0)}\n"
            f"{self.t('vector_index_stale')}: {health.get('vector_index', {}).get('stale', 0)}\n"
            f"{self.t('vector_index_invalid')}: {health.get('vector_index', {}).get('invalid', 0)}\n"
            f"{self.t('vector_index_orphaned')}: {health.get('vector_index', {}).get('orphaned', 0)}\n"
            f"{self.t('backups')}: {health.get('backup_count', 0)}\n"
            f"{self.t('last_backup')}: {health.get('last_backup_time', self.none_text())}\n"
            f"{self.t('latest_backup_version')}: {health.get('latest_backup_version', self.none_text())}"
        )
        self.logger.info("Knowledge health checked")

    def show_index_status(self):
        self.set_detail(self.t("knowledge_window_checking_index"))

        def action():
            records = self.knowledge_store.list_items()
            return {"records": records, "health": self.knowledge_store.vector_index_health(records)}

        self.run_store_action(action, self.finish_index_status, self.t("knowledge_window_index_check_failed"))

    def finish_index_status(self, result):
        records = result.get("records", [])
        health = result.get("health", {})
        self.set_detail(
            f"{self.t('knowledge_window_vector_index_status')}\n\n"
            f"{self.t('knowledge_enable')}: {self.yes_no(self.settings.get('knowledge.enabled', True))}\n"
            f"{self.t('documents')}: {len(records)}\n"
            f"{self.t('index_file')}: {health.get('path', '')}\n"
            f"{self.t('exists')}: {self.yes_no(health.get('exists'))}\n"
            f"{self.t('format')}: {health.get('format', '')}\n"
            f"{self.t('version')}: {health.get('version', '')}\n"
            f"{self.t('knowledge_window_updated')}: {health.get('updated_time', '') or self.never_text()}\n"
            f"{self.t('entries')}: {health.get('entries', 0)}\n"
            f"{self.t('indexed')}: {health.get('indexed', 0)}\n"
            f"{self.t('missing')}: {health.get('missing', 0)}\n"
            f"{self.t('knowledge_window_stale')}: {health.get('stale', 0)}\n"
            f"{self.t('invalid')}: {health.get('invalid', 0)}\n"
            f"{self.t('orphaned')}: {health.get('orphaned', 0)}\n"
            f"{self.t('knowledge_window_needs_reindex')}: {health.get('needs_reindex', 0)}"
        )
        self.logger.info("Knowledge vector index checked")

    def rebuild_vector_index(self):
        if not messagebox.askyesno(self.t("library_page_rebuild_index"), self.t("knowledge_window_rebuild_index_confirm"), parent=self):
            return
        self.set_detail(self.t("knowledge_window_rebuilding_index"))

        def action():
            result = self.knowledge_store.build_vector_index()
            return {"result": result, "health": self.knowledge_store.vector_index_health()}

        self.run_store_action(action, self.finish_rebuild_vector_index, self.t("knowledge_window_index_rebuild_failed"))

    def finish_rebuild_vector_index(self, payload):
        result = payload.get("result", {})
        health = payload.get("health", {})
        self.refresh_knowledge_list()
        self.set_detail(
            f"{self.t('knowledge_window_index_rebuilt')}\n\n"
            f"{self.t('indexed')}: {result.get('indexed', 0)}\n"
            f"{self.t('errors')}: {len(result.get('errors', []))}\n"
            f"{self.t('index_file')}: {result.get('index_file', '')}\n"
            f"{self.t('entries')}: {health.get('entries', 0)}\n"
            f"{self.t('knowledge_window_needs_reindex')}: {health.get('needs_reindex', 0)}"
        )
        self.logger.info("Knowledge vector index rebuilt")

    def repair_knowledge_metadata(self):
        self.set_detail(self.t("knowledge_window_repairing_metadata"))
        self.run_store_action(
            self.knowledge_store.repair_metadata,
            lambda result: (self.refresh_knowledge_list(), self.set_detail(f"{self.t('knowledge_window_metadata_repaired')}\n\n{self.t('records_repaired')}: {result.get('repaired', 0)}\n{self.t('errors')}: {len(result.get('errors', []))}"), self.logger.info("Knowledge metadata repaired"), self.logger.info("Knowledge repair completed")),
            self.t("knowledge_window_repair_failed")
        )

    def preview_knowledge(self):
        record = self.selected_record["record"]
        if record is None:
            self.set_detail(self.t("knowledge_window_no_file_selected"))
            return
        self.set_detail(self.t("knowledge_window_loading_preview"))
        self.run_store_action(
            lambda: self.knowledge_store.preview_details(record["id"], limit=self.settings.get("knowledge.preview_limit", 5000)),
            self.finish_preview,
            self.t("knowledge_window_preview_failed")
        )

    def finish_preview(self, preview):
        self.preview_state["content"] = preview.get("content", "")
        self.preview_state["matches"] = []
        self.preview_state["current"] = -1
        self.preview_state["keyword"] = ""
        self.preview_search_label.configure(text=self.matches_text(0))
        truncated_note = f"\n{self.t('knowledge_window_preview_truncated')}" if preview.get("truncated") else ""
        self.set_detail(
            f"{self.t('knowledge_window_preview')}: {preview.get('file_name', '')}\n"
            f"{self.t('type')}: {preview.get('file_type', '')}\n"
            f"{self.t('characters')}: {preview.get('character_count', 0)}\n"
            f"{self.t('preview_characters')}: {preview.get('preview_count', 0)}\n"
            f"{self.t('truncated')}: {self.yes_no(preview.get('truncated'))}"
            f"{truncated_note}\n\n"
            f"{preview.get('content', '')}"
        )
        self.logger.info("Knowledge preview opened")

    def show_preview_match(self):
        matches = self.preview_state["matches"]
        current = self.preview_state["current"]
        if not matches or current < 0:
            self.preview_search_label.configure(text=self.matches_text(0))
            return
        position = matches[current]
        self.preview_search_label.configure(
            text=self.matches_text(len(matches), current=current + 1, total=len(matches), position=position)
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
        self.preview_search_label.configure(text=self.matches_text(0))
        self.logger.info("Knowledge preview search cleared")

    def test_retrieval(self):
        prompt = self.retrieval_entry.get().strip()
        if not prompt:
            self.set_detail(self.t("knowledge_window_enter_prompt"))
            return
        self.set_detail(self.t("knowledge_window_testing_retrieval"))

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

        self.run_store_action(action, self.finish_retrieval_test, self.t("knowledge_window_retrieval_failed"))

    def finish_retrieval_test(self, summary):
        results = summary.get("results", [])
        lines = [
            self.t("summary"),
            f"{self.t('prompt')}: {summary.get('prompt', '')}",
            f"{self.t('knowledge_enable')}: {self.yes_no(summary.get('knowledge_enabled'))}",
            f"{self.t('maximum_knowledge_results')}: {summary.get('max_results', 0)}",
            f"{self.t('matched_count')}: {summary.get('matched_count', 0)}",
            f"{self.t('injected_count')}: {summary.get('injected_count', 0)}",
            ""
        ]
        if not summary.get("knowledge_enabled"):
            lines.append(self.t("knowledge_window_retrieval_disabled"))
        elif not summary.get("enabled_available"):
            lines.append(self.t("knowledge_window_no_enabled_files"))
        elif not results:
            lines.append(self.t("knowledge_window_no_match"))
        else:
            lines.append(f"{self.t('matched')}:")
            for item in results:
                lines.extend([
                    f"\n{item.get('file_name', self.unknown_text())}",
                    f"{self.t('enabled')}: {self.yes_no(item.get('enabled'))}",
                    f"{self.t('status')}: {self.status_text(item.get('status', 'OK'))}",
                    f"{self.t('score')}: {item.get('score', 0)}",
                    f"{self.t('matched_keywords')}: {', '.join(item.get('keywords', [])) or self.none_text()}"
                ])
                if item.get("line"):
                    lines.append(f"{self.t('line')}: {item.get('line')}")
                lines.extend([
                    f"{self.t('character_range')}: {item.get('start', 0)} - {item.get('end', 0)}",
                    f"{self.t('snippet')}:\n{item.get('snippet', '') or self.t('knowledge_window_no_snippet')}",
                    f"{self.t('injected')}: {self.yes_no(item.get('injected'))}"
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

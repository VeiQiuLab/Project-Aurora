import customtkinter as ctk
from tkinter import messagebox

from modules.ui_theme import (
    FORM_CONTROL_WIDTH,
    FORM_LABEL_WRAP,
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


class ConversationBrowserWindow(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        *,
        conversation_manager,
        text,
        translate,
        logger,
        get_active_conversation_id,
        clear_active_conversation_id,
        continue_conversation_callback,
        on_close=None
    ):
        super().__init__(parent)
        self.manager = conversation_manager
        self.text = text
        self.t = translate
        self.logger = logger
        self.get_active_conversation_id = get_active_conversation_id
        self.clear_active_conversation_id = clear_active_conversation_id
        self.continue_conversation_callback = continue_conversation_callback
        self.on_close_callback = on_close
        self.records = []
        self.selected_record = {"record": None}

        self.title(self.t("conversation_browser"))
        self.geometry("860x680")
        self.minsize(720, 560)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.build()
        self.refresh()

    def build(self):
        ctk.CTkLabel(
            self,
            text=self.t("conversation_browser"),
            font=FONT_TITLE
        ).pack(anchor="w", padx=SPACING_LARGE + SPACING_SMALL, pady=(SPACING_LARGE, SPACING_MEDIUM))

        self.summary_row = ctk.CTkFrame(self, fg_color="transparent")
        self.summary_row.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_SMALL))
        self.summary_label = StatusLabel(
            self.summary_row,
            status="disabled",
            text="",
            wraplength=FORM_LABEL_WRAP * 2,
            justify="left",
            anchor="w"
        )
        self.summary_label.pack(anchor="w")

        search_card = SectionCard(self, self.t("chat_window_search"))
        search_card.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_MEDIUM))
        search_row = FormRow(search_card.body, self.t("conversation_browser_search_title"))
        search_row.pack(fill="x", pady=SPACING_SMALL)
        self.search_entry = search_row.add_entry("")

        self.search_button = PrimaryButton(
            search_row.control_frame,
            text=self.t("chat_window_search"),
            width=FORM_CONTROL_WIDTH // 3,
            command=self.search
        )
        self.search_button.pack(side="left", padx=(SPACING_SMALL, SPACING_SMALL))
        self.clear_button = SecondaryButton(
            search_row.control_frame,
            text=self.t("clear"),
            width=FORM_CONTROL_WIDTH // 3,
            command=self.clear_search
        )
        self.clear_button.pack(side="left")

        list_card = SectionCard(self, self.t("chat_page_conversations"))
        list_card.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_MEDIUM))
        self.conversation_selector = ctk.CTkOptionMenu(
            list_card.body,
            values=[self.t("chat_page_no_conversations")],
            width=FORM_CONTROL_WIDTH * 2 + FORM_CONTROL_WIDTH // 2,
            command=self.select_conversation
        )
        self.conversation_selector.pack(fill="x", pady=SPACING_SMALL)

        detail_card = SectionCard(self, self.t("memory_page_view_detail"))
        detail_card.pack(fill="both", expand=True, padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_MEDIUM))
        self.detail_box = ctk.CTkTextbox(detail_card.body, height=260, wrap="word")
        self.detail_box.pack(fill="both", expand=True)
        self.detail_box.configure(state="disabled")

        self.footer = FixedFooter(self)
        self.footer.pack(fill="x", padx=SPACING_LARGE + SPACING_SMALL, pady=(0, SPACING_LARGE))
        self.build_buttons()

    def build_buttons(self):
        for column in range(3):
            self.footer.buttons.grid_columnconfigure(column, weight=1)

        actions = [
            (self.t("conversation_browser_open"), self.open_conversation, SecondaryButton),
            (self.t("conversation_browser_continue_chat"), self.continue_conversation, PrimaryButton),
            (self.t("conversation_browser_rename"), self.rename_conversation, SecondaryButton),
            (self.t("delete"), self.delete_conversation, DangerButton),
            (self.t("refresh"), lambda: self.refresh(self.search_entry.get()), SecondaryButton),
            (self.t("close"), self.close, SecondaryButton)
        ]
        for index, (label_text, command, button_factory) in enumerate(actions):
            button_factory(
                self.footer.buttons,
                text=label_text,
                command=command
            ).grid(
                row=index // 3,
                column=index % 3,
                sticky="ew",
                padx=SPACING_SMALL,
                pady=SPACING_SMALL
            )

    def format_time(self, value):
        return str(value or "").replace("T", " ").replace("+00:00", " UTC") or self.t("settings_window_unknown_status")

    def message_count(self, record):
        try:
            data = self.manager.load(record["id"])
            return len([item for item in data.get("messages", []) if item.get("role") != "system"])
        except Exception:
            return 0

    def browser_label(self, record):
        count = self.message_count(record)
        status = self.t("conversation_browser_current") if record.get("id") == self.get_active_conversation_id() else self.t("conversation_browser_saved")
        return (
            f"{record.get('title', self.t('chat_window_new_conversation'))}\n"
            f"{self.t('created')}: {self.format_time(record.get('created_at'))} | "
            f"{self.t('knowledge_window_updated')}: {self.format_time(record.get('updated_at'))} | "
            f"{self.t('conversation_browser_messages')}: {count} | "
            f"{self.t('status')}: {status}"
        )

    def set_detail(self, text):
        self.detail_box.configure(state="normal")
        self.detail_box.delete("1.0", "end")
        self.detail_box.insert("end", text)
        self.detail_box.configure(state="disabled")

    def show_detail(self, record):
        self.selected_record["record"] = record
        if record is None:
            self.set_detail(self.t("conversation_browser_no_selected"))
            return
        try:
            data = self.manager.load(record["id"])
            messages = [item for item in data.get("messages", []) if item.get("role") != "system"]
            preview = []
            for item in messages[-6:]:
                role = self.t("chat_window_user_label") if item.get("role") == "user" else "Aurora"
                preview.append(f"{role}: {str(item.get('content', ''))[:300]}")
            status = self.t("conversation_browser_current") if record.get("id") == self.get_active_conversation_id() else self.t("conversation_browser_saved")
            self.set_detail(
                f"{self.t('conversation_browser_id')}: {data.get('id', '')}\n"
                f"{self.t('title')}: {data.get('title', self.t('chat_window_new_conversation'))}\n"
                f"{self.t('created')}: {self.format_time(data.get('created_at'))}\n"
                f"{self.t('knowledge_window_updated')}: {self.format_time(data.get('updated_at'))}\n"
                f"{self.t('conversation_browser_message_count')}: {len(messages)}\n"
                f"{self.t('model_name')}: {data.get('model', '') or self.t('settings_window_unknown_status')}\n"
                f"{self.t('status')}: {status}\n\n"
                f"{self.t('conversation_browser_recent_messages')}\n\n"
                f"{chr(10).join(preview) if preview else self.t('conversation_browser_no_messages')}"
            )
        except Exception as error:
            self.set_detail(f"{self.t('conversation_browser_load_failed')}: {error}")

    def refresh(self, keyword=""):
        keyword = str(keyword or "").strip().casefold()
        loaded = self.manager.list_conversations()
        if keyword:
            loaded = [
                item for item in loaded
                if keyword in str(item.get("title", "")).casefold()
            ]
        self.records = sorted(loaded, key=lambda item: item.get("updated_at", ""), reverse=True)
        labels = [self.browser_label(item) for item in self.records]
        empty_label = self.t("chat_page_no_conversations")
        self.conversation_selector.configure(values=labels or [empty_label])
        self.conversation_selector.set(labels[0] if labels else empty_label)
        latest = self.format_time(self.records[0].get("updated_at")) if self.records else self.t("none")
        current = self.get_active_conversation_id() or self.t("none")
        self.summary_label.configure(
            text=f"{self.t('total')}: {len(self.manager.list_conversations())} | {self.t('conversation_browser_current')}: {current} | {self.t('conversation_browser_latest_updated')}: {latest}",
            text_color=status_color("disabled")
        )
        self.show_detail(self.records[0] if self.records else None)
        self.logger.info("Conversation browser refreshed")

    def select_conversation(self, value):
        record = next((item for item in self.records if self.browser_label(item) == value), None)
        self.show_detail(record)

    def search(self):
        self.refresh(self.search_entry.get())
        self.logger.info("Conversation browser searched")

    def clear_search(self):
        self.search_entry.delete(0, "end")
        self.refresh()

    def open_conversation(self):
        record = self.selected_record["record"]
        if record is None:
            self.set_detail(self.t("conversation_browser_no_selected"))
            return
        self.show_detail(record)
        self.logger.info("Conversation opened")

    def continue_conversation(self):
        record = self.selected_record["record"]
        if record is None:
            self.set_detail(self.t("conversation_browser_no_selected"))
            return
        self.continue_conversation_callback(record["id"])
        self.logger.info("Conversation continued")

    def rename_conversation(self):
        record = self.selected_record["record"]
        if record is None:
            self.set_detail(self.t("conversation_browser_no_selected"))
            return
        dialog = ctk.CTkInputDialog(text=self.t("chat_window_rename_prompt"), title=self.t("conversation_browser_rename"))
        title = dialog.get_input()
        if not title or not title.strip():
            return
        try:
            self.manager.rename(record["id"], title)
            self.refresh(self.search_entry.get())
            self.logger.info("Conversation renamed")
        except Exception as error:
            self.set_detail(f"{self.t('conversation_browser_rename_failed')}: {error}")
            self.logger.error(f"Conversation rename failed: {error}")

    def delete_conversation(self):
        record = self.selected_record["record"]
        if record is None:
            self.set_detail(self.t("conversation_browser_no_selected"))
            return
        if not messagebox.askyesno(self.t("conversation_browser_delete"), self.t("chat_window_delete_chat_message"), parent=self):
            return
        try:
            self.manager.delete(record["id"])
            if self.get_active_conversation_id() == record["id"]:
                self.clear_active_conversation_id()
            self.refresh(self.search_entry.get())
            self.logger.info("Conversation deleted")
        except Exception as error:
            self.set_detail(f"{self.t('conversation_browser_delete_failed')}: {error}")
            self.logger.error(f"Conversation delete failed: {error}")

    def close(self):
        self.destroy()
        if self.on_close_callback:
            self.on_close_callback()

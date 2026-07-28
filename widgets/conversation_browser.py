import customtkinter as ctk
from tkinter import messagebox

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

        self.title("Conversation Browser")
        self.geometry("860x680")
        self.minsize(720, 560)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.build()
        self.refresh()

    def build(self):
        ctk.CTkLabel(
            self,
            text="Conversation Browser",
            font=FONT_TITLE
        ).pack(anchor="w", padx=25, pady=(20, 12))

        self.summary_row = ctk.CTkFrame(self, fg_color="transparent")
        self.summary_row.pack(fill="x", padx=25, pady=(0, 8))
        self.summary_label = StatusLabel(
            self.summary_row,
            status="disabled",
            text="",
            wraplength=800,
            justify="left",
            anchor="w"
        )
        self.summary_label.pack(anchor="w")

        search_card = SectionCard(self, "Search")
        search_card.pack(fill="x", padx=25, pady=(0, 10))
        search_row = FormRow(search_card.body, "Search conversation title")
        search_row.pack(fill="x", pady=6)
        self.search_entry = search_row.add_entry("")

        self.search_button = PrimaryButton(
            search_row.control_frame,
            text="Search",
            width=90,
            command=self.search
        )
        self.search_button.pack(side="left", padx=(6, 6))
        self.clear_button = SecondaryButton(
            search_row.control_frame,
            text="Clear",
            width=80,
            command=self.clear_search
        )
        self.clear_button.pack(side="left")

        list_card = SectionCard(self, "Conversations")
        list_card.pack(fill="x", padx=25, pady=(0, 10))
        self.conversation_selector = ctk.CTkOptionMenu(
            list_card.body,
            values=["No conversations available"],
            width=700,
            command=self.select_conversation
        )
        self.conversation_selector.pack(fill="x", pady=6)

        detail_card = SectionCard(self, "Details")
        detail_card.pack(fill="both", expand=True, padx=25, pady=(0, 10))
        self.detail_box = ctk.CTkTextbox(detail_card.body, height=260, wrap="word")
        self.detail_box.pack(fill="both", expand=True)
        self.detail_box.configure(state="disabled")

        self.footer = FixedFooter(self)
        self.footer.pack(fill="x", padx=25, pady=(0, 20))
        self.build_buttons()

    def build_buttons(self):
        for column in range(3):
            self.footer.buttons.grid_columnconfigure(column, weight=1)

        actions = [
            ("Open", self.open_conversation, SecondaryButton),
            ("Continue Chat", self.continue_conversation, PrimaryButton),
            ("Rename", self.rename_conversation, SecondaryButton),
            ("Delete", self.delete_conversation, DangerButton),
            ("Refresh", lambda: self.refresh(self.search_entry.get()), SecondaryButton),
            (self.text["close"], self.close, SecondaryButton)
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
                padx=4,
                pady=4
            )

    def format_time(self, value):
        return str(value or "").replace("T", " ").replace("+00:00", " UTC") or "Unknown"

    def message_count(self, record):
        try:
            data = self.manager.load(record["id"])
            return len([item for item in data.get("messages", []) if item.get("role") != "system"])
        except Exception:
            return 0

    def browser_label(self, record):
        count = self.message_count(record)
        status = "Current" if record.get("id") == self.get_active_conversation_id() else "Saved"
        return (
            f"{record.get('title', 'New Conversation')}\n"
            f"Created: {self.format_time(record.get('created_at'))} | "
            f"Updated: {self.format_time(record.get('updated_at'))} | "
            f"Messages: {count} | "
            f"Status: {status}"
        )

    def set_detail(self, text):
        self.detail_box.configure(state="normal")
        self.detail_box.delete("1.0", "end")
        self.detail_box.insert("end", text)
        self.detail_box.configure(state="disabled")

    def show_detail(self, record):
        self.selected_record["record"] = record
        if record is None:
            self.set_detail("No conversation selected.")
            return
        try:
            data = self.manager.load(record["id"])
            messages = [item for item in data.get("messages", []) if item.get("role") != "system"]
            preview = []
            for item in messages[-6:]:
                role = "You" if item.get("role") == "user" else "Aurora"
                preview.append(f"{role}: {str(item.get('content', ''))[:300]}")
            status = "Current" if record.get("id") == self.get_active_conversation_id() else "Saved"
            self.set_detail(
                f"Conversation ID: {data.get('id', '')}\n"
                f"Title: {data.get('title', 'New Conversation')}\n"
                f"Created: {self.format_time(data.get('created_at'))}\n"
                f"Updated: {self.format_time(data.get('updated_at'))}\n"
                f"Message Count: {len(messages)}\n"
                f"Model: {data.get('model', '') or 'Unknown'}\n"
                f"Status: {status}\n\n"
                "Recent Messages\n\n"
                f"{chr(10).join(preview) if preview else 'No messages.'}"
            )
        except Exception as error:
            self.set_detail(f"Conversation load failed: {error}")

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
        self.conversation_selector.configure(values=labels or ["No conversations available"])
        self.conversation_selector.set(labels[0] if labels else "No conversations available")
        latest = self.format_time(self.records[0].get("updated_at")) if self.records else "None"
        current = self.get_active_conversation_id() or "None"
        self.summary_label.configure(
            text=f"Total: {len(self.manager.list_conversations())} | Current: {current} | Latest Updated: {latest}",
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
            self.set_detail("No conversation selected.")
            return
        self.show_detail(record)
        self.logger.info("Conversation opened")

    def continue_conversation(self):
        record = self.selected_record["record"]
        if record is None:
            self.set_detail("No conversation selected.")
            return
        self.continue_conversation_callback(record["id"])
        self.logger.info("Conversation continued")

    def rename_conversation(self):
        record = self.selected_record["record"]
        if record is None:
            self.set_detail("No conversation selected.")
            return
        dialog = ctk.CTkInputDialog(text="Enter conversation title:", title="Rename Conversation")
        title = dialog.get_input()
        if not title or not title.strip():
            return
        try:
            self.manager.rename(record["id"], title)
            self.refresh(self.search_entry.get())
            self.logger.info("Conversation renamed")
        except Exception as error:
            self.set_detail(f"Conversation rename failed: {error}")
            self.logger.error(f"Conversation rename failed: {error}")

    def delete_conversation(self):
        record = self.selected_record["record"]
        if record is None:
            self.set_detail("No conversation selected.")
            return
        if not messagebox.askyesno("Delete Conversation", "Delete selected conversation?", parent=self):
            return
        try:
            self.manager.delete(record["id"])
            if self.get_active_conversation_id() == record["id"]:
                self.clear_active_conversation_id()
            self.refresh(self.search_entry.get())
            self.logger.info("Conversation deleted")
        except Exception as error:
            self.set_detail(f"Conversation delete failed: {error}")
            self.logger.error(f"Conversation delete failed: {error}")

    def close(self):
        self.destroy()
        if self.on_close_callback:
            self.on_close_callback()

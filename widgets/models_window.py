import threading

import customtkinter as ctk

from modules.ui_theme import FONT_NORMAL, FONT_NORMAL_BOLD, FONT_SMALL, FONT_TITLE
from widgets.ui_components import (
    FixedFooter,
    FormRow,
    PrimaryButton,
    SecondaryButton,
    SectionCard,
    StatusLabel
)


class ModelsWindow(ctk.CTkToplevel):
    """Ollama model list window backed by an external model fetcher."""

    def __init__(
        self,
        parent,
        *,
        text,
        translate,
        logger,
        model_fetcher,
        settings_get,
        on_close=None
    ):
        super().__init__(parent)
        self.text = text
        self.t = translate
        self.logger = logger
        self.model_fetcher = model_fetcher
        self.settings_get = settings_get
        self.on_close_callback = on_close
        self.columns = [
            (self.text["name"], "name", 220),
            (self.text["id"], "model_id", 180),
            (self.text["size"], "size", 110),
            (self.text["modified"], "modified", 240)
        ]

        self.title(self.text["models"])
        self.geometry("860x560")
        self.minsize(700, 420)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.build()
        self.refresh_models()

    def build(self):
        ctk.CTkLabel(self, text=self.t("ollama_models_title"), font=FONT_TITLE).pack(
            anchor="w", padx=25, pady=(20, 12)
        )

        status_card = SectionCard(self, self.t("status_overview"))
        status_card.pack(fill="x", padx=25, pady=(0, 10))
        chat_row = FormRow(status_card.body, self.text["chat_model"])
        chat_row.pack(fill="x", pady=6)
        self.chat_model_label = StatusLabel(
            chat_row.control_frame,
            status="disabled",
            text=str(self.settings_get("chat_model", ""))
        )
        self.chat_model_label.pack(side="left")
        embedding_row = FormRow(status_card.body, self.text["embedding_model"])
        embedding_row.pack(fill="x", pady=6)
        self.embedding_model_label = StatusLabel(
            embedding_row.control_frame,
            status="disabled",
            text=str(self.settings_get("embedding_model", ""))
        )
        self.embedding_model_label.pack(side="left")
        count_row = FormRow(status_card.body, self.t("models"))
        count_row.pack(fill="x", pady=6)
        self.count_label = StatusLabel(count_row.control_frame, status="disabled", text="--")
        self.count_label.pack(side="left")
        self.status_label = StatusLabel(status_card.body, status="disabled", text=self.text["checking"], anchor="w", justify="left")
        self.status_label.pack(fill="x", pady=(8, 0))

        list_card = SectionCard(self, self.text["models"])
        list_card.pack(fill="both", expand=True, padx=25, pady=(0, 10))
        self.model_table = ctk.CTkScrollableFrame(list_card.body)
        self.model_table.pack(fill="both", expand=True)
        self.render_header()

        self.footer = FixedFooter(self)
        self.footer.pack(fill="x", padx=25, pady=(0, 20))
        self.refresh_button = PrimaryButton(
            self.footer.buttons,
            text=self.text["refresh"],
            command=self.refresh_models
        )
        self.refresh_button.pack(side="left", expand=True, fill="x", padx=(0, 6))
        SecondaryButton(
            self.footer.buttons,
            text=self.text["close"],
            command=self.close
        ).pack(side="left", expand=True, fill="x", padx=(6, 0))

    def render_header(self):
        for index, (label, _field, width) in enumerate(self.columns):
            self.model_table.grid_columnconfigure(index, weight=1)
            ctk.CTkLabel(
                self.model_table,
                text=label,
                width=width,
                anchor="w",
                font=FONT_NORMAL_BOLD
            ).grid(row=0, column=index, padx=8, pady=(8, 6), sticky="w")

    def clear_rows(self):
        for widget in self.model_table.winfo_children():
            info = widget.grid_info()
            if str(info.get("row", "")) not in {"", "0"}:
                widget.destroy()

    def update_model_rows(self, records):
        if not self.winfo_exists():
            return
        self.clear_rows()
        self.chat_model_label.set_status("disabled", str(self.settings_get("chat_model", "")))
        self.embedding_model_label.set_status("disabled", str(self.settings_get("embedding_model", "")))
        self.count_label.set_status("healthy" if records else "warning", str(len(records)))
        if not records:
            ctk.CTkLabel(
                self.model_table,
                text=self.text["no_models"],
                font=FONT_NORMAL,
                text_color=self.count_label.cget("text_color")
            ).grid(row=1, column=0, columnspan=len(self.columns), padx=8, pady=20)
            self.status_label.set_status("warning", self.text["no_models"])
            return
        for row_index, record in enumerate(records, start=1):
            for column_index, (_label, field, width) in enumerate(self.columns):
                ctk.CTkLabel(
                    self.model_table,
                    text=record.get(field, ""),
                    width=width,
                    anchor="w",
                    font=FONT_SMALL
                ).grid(row=row_index, column=column_index, padx=8, pady=6, sticky="w")
        self.status_label.set_status("healthy", f"{len(records)} {self.text['models']}")
        self.logger.info(f"Models loaded: {len(records)}")

    def refresh_models(self):
        self.refresh_button.configure(state="disabled", text=self.text["checking"])
        self.status_label.set_status("disabled", self.text["checking"])

        def load_model_rows():
            try:
                loaded_records = self.model_fetcher()
            except Exception as error:
                self.logger.error(f"Model loading failed: {error}")
                loaded_records = []

            def finish():
                if not self.winfo_exists():
                    return
                self.update_model_rows(loaded_records)
                self.refresh_button.configure(state="normal", text=self.text["refresh"])

            try:
                self.after(0, finish)
            except Exception:
                return

        threading.Thread(target=load_model_rows, daemon=True).start()

    def close(self):
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()

import threading
from datetime import datetime

import customtkinter as ctk

from modules.ui_theme import FONT_SMALL, FONT_TITLE
from widgets.ui_components import (
    FixedFooter,
    FormRow,
    PrimaryButton,
    SecondaryButton,
    SectionCard,
    StatusLabel
)


class HealthWindow(ctk.CTkToplevel):
    """System health report window backed by system_self_check()."""

    def __init__(
        self,
        parent,
        *,
        text,
        translate,
        logger,
        system_self_check,
        on_close=None
    ):
        super().__init__(parent)
        self.text = text
        self.t = translate
        self.logger = logger
        self.system_self_check = system_self_check
        self.on_close_callback = on_close
        self.rows = {}
        self.check_state = {"running": False}

        self.title(self.text["health_dashboard"])
        self.geometry("720x640")
        self.minsize(620, 520)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.build()
        self.refresh()

    def build(self):
        ctk.CTkLabel(self, text=self.text["health_dashboard"], font=FONT_TITLE).pack(
            anchor="w", padx=25, pady=(20, 12)
        )

        self.summary_card = SectionCard(self, self.t("status_overview"))
        self.summary_card.pack(fill="x", padx=25, pady=(0, 10))
        for key, label in (
            ("overall", self.text["status"]),
            ("healthy", "Healthy"),
            ("warnings", "Warning"),
            ("errors", "Error"),
            ("last_check", "Last Check Time"),
        ):
            self.add_row(self.summary_card.body, key, label)

        self.items_card = SectionCard(self, self.text["health_dashboard"])
        self.items_card.pack(fill="both", expand=True, padx=25, pady=(0, 10))
        self.items_frame = ctk.CTkScrollableFrame(self.items_card.body)
        self.items_frame.pack(fill="both", expand=True)

        self.detail_card = SectionCard(self, "Self Check")
        self.detail_card.pack(fill="x", padx=25, pady=(0, 10))
        self.detail_box = ctk.CTkTextbox(self.detail_card.body, height=120, wrap="word", font=FONT_SMALL)
        self.detail_box.pack(fill="x")
        self.detail_box.configure(state="disabled")

        self.footer = FixedFooter(self)
        self.footer.pack(fill="x", padx=25, pady=(0, 20))
        self.refresh_button = PrimaryButton(
            self.footer.buttons,
            text=self.text["refresh"],
            command=self.refresh
        )
        self.refresh_button.pack(side="left", expand=True, fill="x", padx=(0, 6))
        SecondaryButton(
            self.footer.buttons,
            text=self.text["close"],
            command=self.close
        ).pack(side="left", expand=True, fill="x", padx=(6, 0))

    def add_row(self, parent, key, label):
        row = FormRow(parent, label)
        row.pack(fill="x", pady=6)
        value = StatusLabel(row.control_frame, status="disabled", text="--")
        value.pack(side="left")
        self.rows[key] = value
        return value

    def set_row(self, key, text, status=None):
        if key in self.rows:
            self.rows[key].set_status(status or text, text=text)

    def set_detail(self, text):
        self.detail_box.configure(state="normal")
        self.detail_box.delete("1.0", "end")
        self.detail_box.insert("1.0", text or "--")
        self.detail_box.configure(state="disabled")

    def clear_items(self):
        for child in self.items_frame.winfo_children():
            child.destroy()

    def add_item_row(self, item):
        name = item.get("name", "--")
        status = item.get("status", "Warning")
        message = item.get("message", "")
        row = FormRow(self.items_frame, name)
        row.pack(fill="x", pady=5)
        value = StatusLabel(row.control_frame, status=status, text=status)
        value.pack(side="left")
        detail = ctk.CTkLabel(
            self.items_frame,
            text=message,
            font=FONT_SMALL,
            anchor="w",
            justify="left",
            wraplength=560
        )
        detail.pack(fill="x", padx=(8, 0), pady=(0, 6))

    def apply_report(self, report, checked_at):
        self.set_row("overall", report.get("status", "Error"), report.get("status", "Error"))
        self.set_row("healthy", str(report.get("healthy", 0)), "healthy")
        self.set_row("warnings", str(report.get("warnings", 0)), "warning")
        self.set_row("errors", str(report.get("errors", 0)), "error" if report.get("errors", 0) else "healthy")
        self.set_row("last_check", checked_at, "healthy")

        self.clear_items()
        for item in report.get("items", []):
            self.add_item_row(item)

        detail_lines = [
            f"{item.get('name', '--')}: {item.get('status', '--')} - {item.get('message', '')}"
            for item in report.get("items", [])
        ]
        self.set_detail("\n".join(detail_lines))

    def refresh(self):
        if self.check_state["running"]:
            return
        self.check_state["running"] = True
        self.refresh_button.configure(state="disabled", text=self.text["checking"])
        for row in self.rows.values():
            row.set_status("disabled", self.text["checking"])
        self.logger.info("Health dashboard check started")

        def run_check():
            try:
                report = self.system_self_check(timeout=3)
                error_message = None
            except Exception as error:
                report = {
                    "status": "Error",
                    "healthy": 0,
                    "warnings": 0,
                    "errors": 1,
                    "items": []
                }
                error_message = str(error)
            checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            def finish():
                if not self.winfo_exists():
                    return
                if error_message:
                    self.logger.error(f"Health dashboard check failed: {error_message}")
                    self.set_detail(error_message)
                else:
                    self.logger.info("Health dashboard check completed")
                self.apply_report(report, checked_at)
                self.check_state["running"] = False
                self.refresh_button.configure(state="normal", text=self.text["refresh"])

            try:
                self.after(0, finish)
            except Exception:
                return

        threading.Thread(target=run_check, daemon=True).start()

    def close(self):
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()

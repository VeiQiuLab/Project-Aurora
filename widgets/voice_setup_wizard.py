"""Explicit, non-installing setup flow for Aurora's optional Voice feature."""

from __future__ import annotations

import threading
from tkinter import messagebox

import customtkinter as ctk

from modules.dependency_actions import WHISPER_MODEL_OPTIONS, download_whisper_model
from modules.i18n import t as i18n_t
from modules.runtime_display import localized_runtime_item
from modules.runtime_dependencies import RuntimeDependencyManager
from modules.ui_theme import COLOR_ERROR, COLOR_MUTED, COLOR_SUCCESS, FONT_NORMAL, FONT_SMALL, SPACING_MEDIUM, SPACING_SMALL
from widgets.ui_components import PrimaryButton, SecondaryButton, SectionCard


VOICE_SETUP_KEYS = ("stt", "whisper_model", "tts", "playback", "ffmpeg", "microphone")


def voice_setup_state(report):
    """Return the product state without exposing individual failures as alerts."""

    voice = report.get("voice", {}) if isinstance(report, dict) else {}
    if not voice.get("enabled"):
        return "disabled"
    return "ready" if voice.get("ready") else "configure"


class VoiceSetupWizard(ctk.CTkToplevel):
    """Guided Voice readiness view; never installs Python packages."""

    def __init__(self, parent, *, settings, runtime_manager=None, logger=None, translate=None):
        super().__init__(parent)
        self.settings = settings
        self.runtime_manager = runtime_manager or RuntimeDependencyManager(settings)
        self.logger = logger
        self.t = translate or i18n_t
        self.report = None
        self.rows = {}
        self._disposed = False
        self._checking = False
        self._downloading = False

        self.title(self.t("voice_setup_title"))
        self.geometry("720x620")
        self.minsize(620, 520)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=SPACING_MEDIUM, pady=SPACING_MEDIUM)
        ctk.CTkLabel(
            self.body,
            text=self.t("voice_setup_intro"),
            font=FONT_NORMAL,
            text_color=COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=650,
        ).pack(fill="x", pady=(0, SPACING_MEDIUM))

        checklist = SectionCard(self.body, self.t("voice_setup_checklist"))
        checklist.pack(fill="x", pady=(0, SPACING_MEDIUM))
        for key in VOICE_SETUP_KEYS:
            row = ctk.CTkFrame(checklist.body, fg_color="transparent")
            row.pack(fill="x", pady=3)
            row.grid_columnconfigure(1, weight=1)
            display = localized_runtime_item({"key": key, "name": key}, self.t)
            ctk.CTkLabel(row, text=display["name"], font=FONT_NORMAL, width=150, anchor="w").grid(row=0, column=0, sticky="w")
            status = ctk.CTkLabel(row, text=self.t("runtime_status_checking"), font=FONT_SMALL, text_color=COLOR_MUTED, anchor="w")
            status.grid(row=0, column=1, sticky="w")
            self.rows[key] = status

        self.notice = ctk.CTkLabel(
            self.body,
            text=self.t("voice_setup_runtime_notice"),
            font=FONT_SMALL,
            text_color=COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=650,
        )
        self.notice.pack(fill="x", pady=(0, SPACING_MEDIUM))

        self.model_card = SectionCard(self.body, self.t("voice_setup_model_title"))
        self.model_card.pack(fill="x", pady=(0, SPACING_MEDIUM))
        self.tier_labels = {
            self.t(f"runtime_whisper_tier_{key}"): key for key in WHISPER_MODEL_OPTIONS
        }
        self.tier = ctk.StringVar(value=self.t("runtime_whisper_tier_recommended"))
        self.tier_menu = ctk.CTkOptionMenu(
            self.model_card.body,
            values=list(self.tier_labels),
            variable=self.tier,
            width=220,
            command=self._update_model_description,
        )
        self.tier_menu.pack(anchor="w")
        self.model_description = ctk.CTkLabel(
            self.model_card.body,
            text="",
            font=FONT_SMALL,
            text_color=COLOR_MUTED,
            anchor="w",
            justify="left",
        )
        self.model_description.pack(fill="x", pady=(SPACING_SMALL, 0))
        self.download_button = SecondaryButton(
            self.model_card.body,
            text=self.t("runtime_download_whisper"),
            command=self._download_model,
        )
        self.download_button.pack(anchor="w", pady=(SPACING_MEDIUM, 0))
        self._update_model_description(self.tier.get())

        actions = ctk.CTkFrame(self.body, fg_color="transparent")
        actions.pack(fill="x")
        self.recheck_button = PrimaryButton(actions, text=self.t("runtime_check_again"), command=self.recheck)
        self.recheck_button.pack(side="left")
        SecondaryButton(actions, text=self.t("close"), command=self.destroy).pack(side="right")
        self.recheck()

    def _after(self, callback):
        if self._disposed:
            return

        def guarded():
            if self._disposed:
                return
            try:
                if self.winfo_exists():
                    callback()
            except Exception:
                return

        try:
            self.after(0, guarded)
        except Exception:
            return

    def _update_model_description(self, label):
        tier = self.tier_labels.get(str(label), "recommended")
        option = WHISPER_MODEL_OPTIONS[tier]
        self.model_description.configure(
            text=self.t("voice_setup_model_description").format(
                model=option["model"],
                size=self.t(f"runtime_whisper_size_{tier}"),
            )
        )

    def recheck(self):
        if self._checking or self._downloading:
            return
        self._checking = True
        self.recheck_button.configure(state="disabled", text=self.t("checking"))

        def worker():
            try:
                report = self.runtime_manager.check(timeout=1.0)
            except Exception as error:
                report = None
                if self.logger:
                    self.logger.error(f"Voice Setup check failed: {type(error).__name__}: {error}")

            def finish():
                self._checking = False
                self.recheck_button.configure(state="normal", text=self.t("runtime_check_again"))
                if report is None:
                    self.notice.configure(text=self.t("runtime_check_failed"), text_color=COLOR_ERROR)
                    return
                self.report = report
                self._render(report)

            self._after(finish)

        threading.Thread(target=worker, daemon=True).start()

    def _render(self, report):
        items = report.get("items_by_key", {})
        for key, label in self.rows.items():
            item = items.get(key, {})
            display = localized_runtime_item(item, self.t)
            ready = item.get("status") == "Ready"
            label.configure(
                text=display["status"],
                text_color=COLOR_SUCCESS if ready else COLOR_MUTED,
            )
        state = voice_setup_state(report)
        notice_key = {
            "disabled": "voice_setup_disabled",
            "ready": "voice_setup_ready",
            "configure": "voice_setup_incomplete",
        }[state]
        self.notice.configure(
            text=self.t(notice_key),
            text_color=COLOR_SUCCESS if state == "ready" else COLOR_MUTED,
        )
        stt_ready = items.get("stt", {}).get("status") == "Ready"
        whisper_ready = items.get("whisper_model", {}).get("status") == "Ready"
        can_download = state != "disabled" and stt_ready and not whisper_ready
        self.model_card.pack(fill="x", pady=(0, SPACING_MEDIUM)) if can_download else self.model_card.pack_forget()
        self.download_button.configure(state="normal" if can_download else "disabled")

    def _download_model(self):
        if not self.report or voice_setup_state(self.report) == "disabled":
            return
        tier = self.tier_labels.get(self.tier.get(), "recommended")
        option = WHISPER_MODEL_OPTIONS[tier]
        confirmed = messagebox.askyesno(
            self.t("runtime_download_whisper_title"),
            self.t("runtime_download_whisper_prompt").format(
                tier=self.t(f"runtime_whisper_tier_{tier}"),
                model=option["model"],
                size=self.t(f"runtime_whisper_size_{tier}"),
                reason=self.t(f"runtime_whisper_reason_{tier}"),
            ),
            parent=self,
        )
        if not confirmed:
            return
        self._downloading = True
        self.download_button.configure(state="disabled", text=self.t("runtime_downloading"))

        def worker():
            result = download_whisper_model(option["model"], confirmed=True)

            def finish():
                self._downloading = False
                self.download_button.configure(text=self.t("runtime_download_whisper"))
                self.notice.configure(
                    text=(self.t("runtime_model_downloaded").format(model=f"Whisper {option['model']}") if result.ok else self.t("runtime_action_failed")),
                    text_color=COLOR_SUCCESS if result.ok else COLOR_ERROR,
                )
                self.recheck()

            self._after(finish)

        threading.Thread(target=worker, daemon=True).start()

    def destroy(self):
        if self._disposed:
            return
        self._disposed = True
        try:
            self.grab_release()
        except Exception:
            pass
        super().destroy()

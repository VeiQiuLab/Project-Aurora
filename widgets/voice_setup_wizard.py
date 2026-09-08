"""Explicit, non-installing setup flow for Aurora's optional Voice feature."""

from __future__ import annotations

import threading
import webbrowser
from tkinter import filedialog, messagebox

import customtkinter as ctk

from modules.dependency_actions import (
    FFMPEG_DOWNLOAD_URL,
    WHISPER_MODEL_OPTIONS,
    download_whisper_model,
    select_whisper_model,
)
from modules.experience.audio.device_discovery import (
    device_choice_map,
    enumerate_dshow_audio_devices,
    select_voice_input_device,
)
from modules.i18n import t as i18n_t
from modules.runtime_display import localized_runtime_item
from modules.runtime_state import shared_runtime_state
from modules.ui_theme import COLOR_ERROR, COLOR_MUTED, COLOR_SUCCESS, FONT_NORMAL, FONT_SMALL, SPACING_MEDIUM, SPACING_SMALL
from widgets.ui_components import PrimaryButton, SecondaryButton, SectionCard


VOICE_SETUP_KEYS = ("stt", "whisper_model", "tts", "tts_service", "playback", "ffmpeg", "microphone")


def voice_setup_plan(report):
    """Return only actions required by this machine's current Voice state."""

    if voice_setup_state(report) == "disabled":
        return []
    items = report.get("items_by_key", {})
    plan = []
    runtimes_missing = any(items.get(key, {}).get("available") is not True for key in ("stt", "tts"))
    playback = items.get("playback", {})
    runtimes_missing = runtimes_missing or playback.get("data", {}).get("runtime_available") is False
    if runtimes_missing:
        plan.append("full_build")
    if items.get("stt", {}).get("available") is True and items.get("whisper_model", {}).get("available") is not True:
        plan.append("whisper_model")
    if items.get("ffmpeg", {}).get("available") is not True:
        plan.append("ffmpeg")
    if items.get("microphone", {}).get("available") is not True:
        plan.append("microphone")
    if items.get("tts", {}).get("available") is True and items.get("tts_service", {}).get("available") is not True:
        plan.append("tts_service")
    if playback.get("data", {}).get("runtime_available") is True and playback.get("available") is not True:
        plan.append("playback")
    return plan


def voice_setup_state(report):
    """Return the product state without exposing individual failures as alerts."""

    voice = report.get("voice", {}) if isinstance(report, dict) else {}
    if not voice.get("enabled"):
        return "disabled"
    return "ready" if voice.get("ready") else "configure"


class VoiceSetupWizard(ctk.CTkToplevel):
    """Guided Voice readiness view; never installs Python packages."""

    def __init__(self, parent, *, settings, runtime_manager=None, runtime_state=None, logger=None, translate=None, on_close=None):
        super().__init__(parent)
        self.settings = settings
        self.runtime_state = runtime_state or shared_runtime_state(settings, parent, runtime_manager)
        self.logger = logger
        self.on_close = on_close
        self.t = translate or i18n_t
        self.report = None
        self.rows = {}
        self._disposed = False
        self._checking = False
        self._downloading = False

        self.title(self.t("voice_setup_title"))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
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

        self.plan_card = SectionCard(self.body, self.t("voice_setup_plan_title"))
        self.plan_card.pack(fill="x", pady=(0, SPACING_MEDIUM))
        self.plan_body = self.plan_card.body

        self.model_card = SectionCard(self.body, self.t("voice_setup_model_title"))
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

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=SPACING_MEDIUM, pady=(0, SPACING_MEDIUM))
        self.recheck_button = PrimaryButton(actions, text=self.t("runtime_check_again"), command=self.recheck)
        self.recheck_button.pack(side="left")
        SecondaryButton(actions, text=self.t("close"), command=self.destroy).pack(side="right")
        self._unsubscribe = self.runtime_state.subscribe(self._on_snapshot)

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
        if not self._downloading:
            self.runtime_state.refresh()

    def _on_snapshot(self, snapshot):
        if self._disposed:
            return
        self._checking = snapshot.checking
        self.recheck_button.configure(state="disabled" if snapshot.checking else "normal",
                                      text=self.t("checking" if snapshot.checking else "runtime_check_again"))
        self.report = snapshot.report
        self._render(self.report)
        if snapshot.checking:
            self.notice.configure(text=self.t("runtime_checking"), text_color=COLOR_MUTED)
            for row in self.rows.values():
                row.configure(text=self.t("runtime_status_checking"), text_color=COLOR_MUTED)
            self.download_button.configure(state="disabled")
        elif snapshot.error or snapshot.restart_required:
            self.notice.configure(text=self.t("runtime_check_failed" if snapshot.error else "runtime_native_restart"),
                                  text_color=COLOR_MUTED)

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
        for child in self.plan_body.winfo_children():
            child.destroy()
        plan = voice_setup_plan(report)
        for action in plan:
            ctk.CTkLabel(
                self.plan_body,
                text=self.t(f"voice_setup_plan_{action}"),
                anchor="w",
                justify="left",
                wraplength=610,
                font=FONT_SMALL,
            ).pack(fill="x", pady=(0, SPACING_SMALL))
            if action == "full_build":
                SecondaryButton(self.plan_body, text=self.t("voice_setup_full_build_help"), command=self._full_build_help).pack(anchor="w", pady=(0, SPACING_SMALL))
            elif action == "ffmpeg":
                row = ctk.CTkFrame(self.plan_body, fg_color="transparent")
                row.pack(fill="x", pady=(0, SPACING_SMALL))
                SecondaryButton(row, text=self.t("voice_setup_ffmpeg_download"), command=lambda: webbrowser.open(FFMPEG_DOWNLOAD_URL)).pack(side="left")
                SecondaryButton(row, text=self.t("voice_setup_ffmpeg_select"), command=self._choose_ffmpeg).pack(side="left", padx=SPACING_SMALL)
            elif action == "microphone":
                SecondaryButton(self.plan_body, text=self.t("voice_choose_device"), command=self._choose_microphone).pack(anchor="w", pady=(0, SPACING_SMALL))
        if plan:
            self.plan_card.pack(fill="x", pady=(0, SPACING_MEDIUM))
        else:
            self.plan_card.pack_forget()
        stt_ready = items.get("stt", {}).get("status") == "Ready"
        whisper_ready = items.get("whisper_model", {}).get("status") == "Ready"
        can_download = state != "disabled" and stt_ready and not whisper_ready
        self.model_card.pack(fill="x", pady=(0, SPACING_MEDIUM)) if can_download else self.model_card.pack_forget()
        self.download_button.configure(state="normal" if can_download else "disabled")

    def _download_model(self):
        if self._downloading or not self.report or "whisper_model" not in voice_setup_plan(self.report):
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
                if result and result.ok:
                    try:
                        select_whisper_model(self.settings, option["model"])
                    except Exception:
                        self.notice.configure(text=self.t("runtime_action_failed"), text_color=COLOR_ERROR)
                        self.recheck()
                        return
                self.download_button.configure(text=self.t("runtime_download_whisper"))
                self.notice.configure(
                    text=(self.t("runtime_model_downloaded").format(model=f"Whisper {option['model']}") if result and result.ok else self.t("runtime_action_failed")),
                    text_color=COLOR_SUCCESS if result and result.ok else COLOR_ERROR,
                )
                self.recheck()

            self._after(finish)

        threading.Thread(target=worker, daemon=True).start()

    def _full_build_help(self):
        messagebox.showinfo(self.t("voice_setup_title"), self.t("voice_setup_full_build_instructions"), parent=self)

    def _choose_ffmpeg(self):
        path = filedialog.askopenfilename(parent=self, title=self.t("voice_setup_ffmpeg_select"), filetypes=[("FFmpeg", "ffmpeg.exe")])
        if path:
            try:
                self.settings.set("voice.recorder.ffmpeg_path", path)
            except Exception:
                self.notice.configure(text=self.t("runtime_action_failed"), text_color=COLOR_ERROR)
                return
            self.recheck()

    def _choose_microphone(self):
        if self._checking or self._downloading:
            return
        def worker():
            try:
                devices = enumerate_dshow_audio_devices(str(self.settings.get("voice.recorder.ffmpeg_path", "ffmpeg")))
            except Exception:
                self._after(lambda: self.notice.configure(text=self.t("voice_device_not_found"), text_color=COLOR_ERROR))
                return
            def finish():
                choices = device_choice_map(devices, default_label=self.t("voice_windows_default_input"), fallback_label=self.t("runtime_item_microphone"))
                window = ctk.CTkToplevel(self)
                window.title(self.t("voice_choose_device"))
                window.geometry("560x160")
                window.transient(self)
                selected = ctk.StringVar(value=next(iter(choices)))
                ctk.CTkOptionMenu(window, values=list(choices), variable=selected, width=500).pack(padx=SPACING_MEDIUM, pady=SPACING_MEDIUM)
                def save():
                    try:
                        select_voice_input_device(self.settings, choices[selected.get()], display_name=selected.get())
                    except Exception:
                        messagebox.showerror(self.t("voice_setup_title"), self.t("runtime_action_failed"), parent=window)
                        return
                    window.destroy()
                    self.grab_set()
                    self.recheck()
                PrimaryButton(window, text=self.t("save"), command=save).pack(anchor="e", padx=SPACING_MEDIUM)
                def close_picker():
                    window.destroy()
                    if not self._disposed:
                        self.grab_set()
                window.protocol("WM_DELETE_WINDOW", close_picker)
                window.grab_set()
            self._after(finish)
        threading.Thread(target=worker, daemon=True).start()

    def destroy(self):
        if self._downloading:
            self.notice.configure(text=self.t("voice_setup_wait_download"), text_color=COLOR_MUTED)
            return
        if self._disposed:
            return
        self._disposed = True
        self._unsubscribe()
        self.runtime_state.refresh()
        try:
            self.grab_release()
        except Exception:
            pass
        super().destroy()
        if callable(self.on_close):
            self.on_close()

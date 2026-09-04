"""Settings UI for read-only runtime checks and explicit repair actions."""

from __future__ import annotations

import json
import threading
from tkinter import messagebox

import customtkinter as ctk

from modules.dependency_actions import (
    OllamaPullTask,
    RECOMMENDED_EMBEDDING_MODEL,
    WHISPER_MODEL_OPTIONS,
    download_whisper_model,
    open_official_ollama_download,
)
from modules.i18n import t as i18n_t
from modules.runtime_display import localized_runtime_item
from modules.runtime_dependencies import (
    RuntimeDependencyManager,
    persist_manual_model_selection,
)
from modules.ui_theme import COLOR_ERROR, COLOR_MUTED, COLOR_SUCCESS, COLOR_WARNING, FONT_NORMAL, FONT_SMALL, SPACING_MEDIUM, SPACING_SMALL
from widgets.ui_components import PrimaryButton, SecondaryButton, SectionCard


_STATUS_COLORS = {
    "Ready": COLOR_SUCCESS,
    "Missing": COLOR_ERROR,
    "Offline": COLOR_WARNING,
    "Optional": COLOR_MUTED,
    "Degraded": COLOR_WARNING,
}

_DOMAIN_ITEMS = ("core", "local_ai", "knowledge", "voice")
_VISIBLE_ITEMS = (
    "ollama",
    "local_ai_service",
    "chat_model",
    "embedding_model",
    "ffmpeg",
    "stt",
    "whisper_model",
    "tts",
    "playback",
)


class DependencyCenter(ctk.CTkFrame):
    """One non-blocking view over :class:`RuntimeDependencyManager`."""

    def __init__(
        self,
        parent,
        *,
        settings,
        service_manager=None,
        open_settings_callback=None,
        runtime_manager=None,
        logger=None,
        translate=None,
        **kwargs,
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.settings = settings
        self.service_manager = service_manager
        self.open_settings_callback = open_settings_callback
        self.runtime_manager = runtime_manager or RuntimeDependencyManager(settings)
        self.logger = logger
        self.t = translate or i18n_t
        self.report = None
        self.rows = {}
        self.domain_rows = {}
        self.pull_task = None
        self.cancel_event = None
        self.whisper_button = None
        self.whisper_tier = None
        self.voice_actions = None
        self._disposed = False
        self._check_running = False
        self._whisper_running = False
        self._build()
        self.check_again()

    def _build(self):
        summary = SectionCard(self, self.t("runtime_title"))
        summary.pack(fill="x", pady=(0, SPACING_MEDIUM))
        ctk.CTkLabel(
            summary.body,
            text=self.t("runtime_intro"),
            font=FONT_NORMAL,
            text_color=COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=720,
        ).pack(fill="x", pady=(0, SPACING_SMALL))

        for key in _DOMAIN_ITEMS:
            row = ctk.CTkFrame(summary.body, fg_color="transparent")
            row.pack(fill="x", pady=3)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=self.t(f"runtime_domain_{key}"), font=FONT_NORMAL, anchor="w", width=150).grid(row=0, column=0, sticky="w")
            status = ctk.CTkLabel(row, text=self.t("runtime_status_checking"), font=FONT_SMALL, text_color=COLOR_MUTED, anchor="w")
            status.grid(row=0, column=1, sticky="w", padx=(SPACING_SMALL, SPACING_SMALL))
            detail = ctk.CTkLabel(row, text="", font=FONT_SMALL, text_color=COLOR_MUTED, anchor="e", wraplength=380)
            detail.grid(row=0, column=2, sticky="e")
            self.domain_rows[key] = (status, detail)

        components = SectionCard(self, self.t("runtime_component_details"))
        components.pack(fill="x", pady=(0, SPACING_MEDIUM))
        for key in _VISIBLE_ITEMS:
            row = ctk.CTkFrame(components.body, fg_color="transparent")
            row.pack(fill="x", pady=3)
            row.grid_columnconfigure(1, weight=1)
            placeholder = {"key": key, "name": key}
            name = localized_runtime_item(placeholder, self.t)["name"]
            ctk.CTkLabel(row, text=name, font=FONT_NORMAL, anchor="w", width=150).grid(row=0, column=0, sticky="w")
            status = ctk.CTkLabel(row, text=self.t("runtime_status_checking"), font=FONT_SMALL, text_color=COLOR_MUTED, anchor="w")
            status.grid(row=0, column=1, sticky="w", padx=(SPACING_SMALL, SPACING_SMALL))
            detail = ctk.CTkLabel(row, text="", font=FONT_SMALL, text_color=COLOR_MUTED, anchor="e", wraplength=380)
            detail.grid(row=0, column=2, sticky="e")
            self.rows[key] = (status, detail)

        self.message = ctk.CTkLabel(
            summary.body,
            text="",
            font=FONT_SMALL,
            text_color=COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=720,
        )
        self.message.pack(fill="x", pady=(SPACING_SMALL, 0))

        actions = ctk.CTkFrame(summary.body, fg_color="transparent")
        actions.pack(fill="x", pady=(SPACING_MEDIUM, 0))
        self.check_button = PrimaryButton(actions, text=self.t("runtime_check_again"), command=self.check_again)
        self.check_button.pack(side="left", padx=(0, SPACING_SMALL))
        self.reevaluate_button = SecondaryButton(
            actions,
            text=self.t("runtime_reevaluate"),
            command=lambda: self.check_again(reevaluate=True),
        )
        self.reevaluate_button.pack(side="left", padx=(0, SPACING_SMALL))
        self.install_button = SecondaryButton(actions, text=self.t("runtime_install_download"), command=self.install_or_download)
        self.install_button.pack(side="left", padx=(0, SPACING_SMALL))
        self.configure_button = SecondaryButton(actions, text=self.t("runtime_configure"), command=self.configure)
        self.configure_button.pack(side="left", padx=(0, SPACING_SMALL))
        self.repair_button = SecondaryButton(actions, text=self.t("runtime_repair"), command=self.repair)
        self.repair_button.pack(side="left", padx=(0, SPACING_SMALL))
        self.diagnostics_button = SecondaryButton(actions, text=self.t("runtime_diagnostics"), command=self.show_diagnostics)
        self.diagnostics_button.pack(side="left")

        optional = SectionCard(self, self.t("runtime_optional_features"))
        optional.pack(fill="x")
        ctk.CTkLabel(
            optional.body,
            text=self.t("runtime_optional_features_hint"),
            font=FONT_SMALL,
            text_color=COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=720,
        ).pack(fill="x")
        self.embedding_button = SecondaryButton(
            optional.body,
            text=self.t("runtime_download_embedding"),
            command=self.download_embedding,
        )
        self.embedding_button.pack(anchor="w", pady=(SPACING_MEDIUM, 0))

        self.voice_configure_button = SecondaryButton(
            optional.body,
            text=self.t("runtime_configure_voice"),
            command=self.configure,
        )
        self.voice_configure_button.pack(anchor="w", pady=(SPACING_MEDIUM, 0))
        self.voice_actions = ctk.CTkFrame(optional.body, fg_color="transparent")
        self.voice_actions.pack(fill="x", pady=(SPACING_MEDIUM, 0))
        self.whisper_tier = ctk.StringVar(value="recommended")
        ctk.CTkOptionMenu(
            self.voice_actions,
            values=list(WHISPER_MODEL_OPTIONS),
            variable=self.whisper_tier,
            width=180,
        ).pack(side="left", padx=(0, SPACING_SMALL))
        self.whisper_button = SecondaryButton(
            self.voice_actions,
            text=self.t("runtime_download_whisper"),
            command=self.download_whisper,
        )
        self.whisper_button.pack(side="left")
        if not bool(self.settings.get("voice.enabled", False)):
            self.voice_actions.pack_forget()

    def _after(self, callback):
        if self._disposed:
            return

        def guarded_callback():
            if self._disposed:
                return
            try:
                if self.winfo_exists():
                    callback()
            except Exception as error:
                if not self._disposed and self.logger:
                    self.logger.error(f"Dependency Center UI update failed: {error}")

        try:
            self.after(0, guarded_callback)
        except Exception:
            return

    def check_again(self, reevaluate=False):
        if self._disposed or self._check_running or self.pull_task is not None:
            return
        self._check_running = True
        self.check_button.configure(state="disabled", text=self.t("checking"))
        self.reevaluate_button.configure(state="disabled")
        self.install_button.configure(state="disabled")
        self.repair_button.configure(state="disabled")
        self.embedding_button.configure(state="disabled")
        self.whisper_button.configure(state="disabled")
        self.message.configure(text=self.t("runtime_checking"), text_color=COLOR_MUTED)

        def worker():
            try:
                if reevaluate:
                    report = self.runtime_manager.check(
                        timeout=1.0,
                        reevaluate_models=True,
                    )
                else:
                    report = self.runtime_manager.check(timeout=1.0)
            except Exception as error:
                report = None
                error_text = self.t("runtime_check_failed")
                if self.logger:
                    self.logger.error(
                        f"Dependency Center check failed: {type(error).__name__}: {error}"
                    )

            def finish():
                self._check_running = False
                self.check_button.configure(state="normal", text=self.t("runtime_check_again"))
                self.reevaluate_button.configure(state="normal")
                self.install_button.configure(state="normal")
                self.repair_button.configure(state="normal")
                self.embedding_button.configure(state="normal")
                if not self._whisper_running:
                    self.whisper_button.configure(state="normal")
                if report is None:
                    self.message.configure(text=error_text, text_color=COLOR_ERROR)
                    return
                self.report = report
                self._render_report(report)

            self._after(finish)

        threading.Thread(target=worker, daemon=True).start()

    def _render_report(self, report):
        items = report.get("items_by_key", {})
        domains = report.get("domains", {})
        for key, labels in self.domain_rows.items():
            item = domains.get(key, {})
            display = localized_runtime_item(item, self.t)
            status = str(item.get("status") or "Degraded")
            labels[0].configure(
                text=display["status"],
                text_color=_STATUS_COLORS.get(status, COLOR_MUTED),
            )
            labels[1].configure(text=display["detail"], text_color=COLOR_MUTED)
        for key, labels in self.rows.items():
            item = items.get(key, {})
            status = str(item.get("status") or "Optional")
            display = localized_runtime_item(item, self.t)
            labels[0].configure(text=display["status"], text_color=_STATUS_COLORS.get(status, COLOR_MUTED))
            labels[1].configure(text=display["detail"], text_color=COLOR_MUTED)
        overall = str(report.get("status") or "Degraded")
        self.message.configure(
            text=self.t(
                "runtime_overall_ready"
                if overall == "Ready"
                else "runtime_overall_not_ready"
            ),
            text_color=_STATUS_COLORS.get(overall, COLOR_MUTED),
        )
        embedding_ready = items.get("embedding_model", {}).get("status") == "Ready"
        self.embedding_button.configure(
            text=self.t("runtime_embedding_installed") if embedding_ready else self.t("runtime_download_embedding"),
            state="disabled" if embedding_ready else "normal",
        )
        voice_enabled = bool(report.get("voice", {}).get("enabled"))
        if not self._whisper_running:
            stt_ready = items.get("stt", {}).get("status") == "Ready"
            whisper_ready = items.get("whisper_model", {}).get("status") == "Ready"
            show_whisper_action = voice_enabled and stt_ready and not whisper_ready
            if show_whisper_action:
                self.voice_actions.pack(fill="x", pady=(SPACING_MEDIUM, 0))
            else:
                self.voice_actions.pack_forget()
            self.whisper_button.configure(
                text=(self.t("runtime_status_ready") if whisper_ready else self.t("runtime_download_whisper")),
                state="normal" if show_whisper_action else "disabled",
            )

    def configure(self):
        if callable(self.open_settings_callback):
            self.open_settings_callback()
        else:
            self.message.configure(text=self.t("runtime_open_settings_hint"), text_color=COLOR_MUTED)

    def install_or_download(self):
        if self.report is None:
            self.message.configure(text=self.t("runtime_run_check_first"), text_color=COLOR_WARNING)
            return
        report = self.report or {}
        ollama = report.get("ollama", {})
        state = ollama.get("state")
        if state == "Not Installed":
            confirmed = messagebox.askyesno(
                self.t("runtime_install_ollama_title"),
                self.t("runtime_install_ollama_prompt"),
                parent=self.winfo_toplevel(),
            )
            result = open_official_ollama_download(confirmed=confirmed)
            self.message.configure(text=self._action_result_text(result, "ollama"), text_color=COLOR_SUCCESS if result.ok else COLOR_MUTED)
            return
        if state == "Installed / Server Offline":
            self.message.configure(text=self.t("runtime_ollama_offline_action"), text_color=COLOR_WARNING)
            return
        recommendation = report.get("recommendation", {})
        if not recommendation.get("download_required"):
            self.message.configure(
                text=self.t("runtime_chat_model_ready_action"),
                text_color=COLOR_SUCCESS,
            )
            return
        if not recommendation.get("can_download", True):
            self.message.configure(text=self.t("runtime_disk_space_insufficient"), text_color=COLOR_ERROR)
            return
        model = str(recommendation.get("model") or "")
        size = recommendation.get("approximate_download_gb")
        confirmed = messagebox.askyesno(
            self.t("runtime_download_chat_title"),
            self.t("runtime_download_chat_prompt").format(
                model=model,
                size=size,
                reason=self.t("runtime_recommendation_reason"),
            ),
            parent=self.winfo_toplevel(),
        )
        if confirmed:
            self._start_pull(model, kind="Chat")

    def download_embedding(self):
        if self.report is None:
            self.message.configure(text=self.t("runtime_run_check_first"), text_color=COLOR_WARNING)
            return
        report = self.report or {}
        if report.get("ollama", {}).get("state") != "Server Ready":
            self.message.configure(text=self.t("runtime_start_ollama_before_embedding"), text_color=COLOR_WARNING)
            return
        confirmed = messagebox.askyesno(
            self.t("runtime_download_embedding_title"),
            self.t("runtime_download_embedding_prompt"),
            parent=self.winfo_toplevel(),
        )
        if confirmed:
            self._start_pull(RECOMMENDED_EMBEDDING_MODEL, kind="Embedding")

    def download_whisper(self):
        if self.report is None:
            self.message.configure(text=self.t("runtime_run_check_first"), text_color=COLOR_WARNING)
            return
        if not self.report.get("voice", {}).get("enabled"):
            self.message.configure(text=self.t("runtime_voice_off_action"), text_color=COLOR_WARNING)
            return
        if self.report.get("items_by_key", {}).get("stt", {}).get("status") != "Ready":
            self.message.configure(
                text=self.t("runtime_install_stt_first"),
                text_color=COLOR_WARNING,
            )
            return
        tier = str(self.whisper_tier.get() if self.whisper_tier is not None else "recommended")
        option = WHISPER_MODEL_OPTIONS.get(tier, WHISPER_MODEL_OPTIONS["recommended"])
        confirmed = messagebox.askyesno(
            self.t("runtime_download_whisper_title"),
            self.t("runtime_download_whisper_prompt").format(
                tier=self.t(f"runtime_whisper_tier_{tier}"),
                model=option["model"],
                size=self.t(f"runtime_whisper_size_{tier}"),
                reason=self.t(f"runtime_whisper_reason_{tier}"),
            ),
            parent=self.winfo_toplevel(),
        )
        if not confirmed:
            return
        self._whisper_running = True
        self.whisper_button.configure(state="disabled", text=self.t("runtime_downloading"))
        self.message.configure(text=self.t("runtime_downloading_model").format(model=f"Whisper {option['model']}"), text_color=COLOR_MUTED)

        def worker():
            result = download_whisper_model(option["model"], confirmed=True)

            def finish():
                self._whisper_running = False
                self.whisper_button.configure(state="normal", text=self.t("runtime_download_whisper"))
                self.message.configure(text=self._action_result_text(result, "whisper"), text_color=COLOR_SUCCESS if result.ok else COLOR_ERROR)
                if result.ok:
                    self.check_again()

            self._after(finish)

        threading.Thread(target=worker, daemon=True).start()

    def _start_pull(self, model, *, kind):
        if self.pull_task is not None:
            return
        executable = str((self.report or {}).get("ollama", {}).get("executable_path") or "ollama")
        task = OllamaPullTask(model, ollama_executable=executable)
        cancel_event = threading.Event()
        self.pull_task = task
        self.cancel_event = cancel_event
        self.install_button.configure(text=self.t("cancel"), command=self.cancel_download, state="normal")
        self.check_button.configure(state="disabled")
        self.reevaluate_button.configure(state="disabled")
        self.repair_button.configure(state="disabled")
        self.embedding_button.configure(state="disabled")
        self.whisper_button.configure(state="disabled")
        self.message.configure(text=self.t("runtime_starting_model_download").format(model=model), text_color=COLOR_MUTED)

        def progress(line):
            summary = str(line).strip().replace("\r", " ")[-180:]
            if summary:
                if self.logger:
                    self.logger.info(f"Model download progress: {summary}")
                self._after(
                    lambda: self.message.configure(
                        text=self.t("runtime_downloading_model").format(model=model),
                        text_color=COLOR_MUTED,
                    )
                )

        def worker():
            result = task.run(confirmed=True, progress=progress, cancel_event=cancel_event)
            selection_error = ""
            if result.ok:
                try:
                    self._persist_model_selection(kind, model)
                except Exception as error:
                    selection_error = str(error).strip().splitlines()[0][:180]

            def finish():
                self.install_button.configure(text=self.t("runtime_install_download"), command=self.install_or_download, state="normal")
                self.check_button.configure(state="normal")
                self.reevaluate_button.configure(state="normal")
                self.repair_button.configure(state="normal")
                self.embedding_button.configure(state="normal")
                if not self._whisper_running:
                    self.whisper_button.configure(state="normal")
                color = COLOR_SUCCESS if result.ok else (COLOR_MUTED if result.status == "cancelled" else COLOR_ERROR)
                message = self._action_result_text(result, str(kind).casefold(), model=model)
                if selection_error:
                    message = self.t("runtime_selection_save_failed")
                    color = COLOR_WARNING
                self.message.configure(text=message, text_color=color)
                self.pull_task = None
                self.cancel_event = None
                if result.ok:
                    self.check_again()

            self._after(finish)

        threading.Thread(target=worker, daemon=True).start()

    def _persist_model_selection(self, kind, model):
        persist_manual_model_selection(
            self.settings,
            model,
            kind="embedding" if str(kind).casefold() == "embedding" else "chat",
        )

    def cancel_download(self):
        if self.cancel_event is not None:
            self.cancel_event.set()
        if self.pull_task is not None:
            self.pull_task.cancel()
        self.message.configure(text=self.t("runtime_cancelling_download"), text_color=COLOR_WARNING)

    def repair(self):
        if self.report is None:
            self.message.configure(text=self.t("runtime_run_check_first"), text_color=COLOR_WARNING)
            return
        if self.service_manager is None:
            self.message.configure(text=self.t("runtime_repair_unavailable"), text_color=COLOR_WARNING)
            return
        state = (self.report or {}).get("ollama", {}).get("state")
        if state == "Server Ready":
            self.message.configure(text=self.t("runtime_ollama_already_ready"), text_color=COLOR_SUCCESS)
            return
        if state == "Not Installed":
            self.install_or_download()
            return
        self.message.configure(text=self.t("runtime_starting_ollama"), text_color=COLOR_MUTED)

        def event_handler(event):
            if isinstance(event, dict):
                return
            messages = {
                "online": (self.t("runtime_ollama_already_ready"), COLOR_SUCCESS),
                "starting": (self.t("runtime_starting_ollama"), COLOR_MUTED),
                "started": (self.t("runtime_ollama_started"), COLOR_SUCCESS),
                "existing_process_offline": (self.t("runtime_ollama_existing_offline"), COLOR_WARNING),
                "command_not_found": (self.t("runtime_ollama_missing"), COLOR_ERROR),
                "failed": (self.t("runtime_ollama_start_failed"), COLOR_ERROR),
            }
            text, color = messages.get(event, (self.t("runtime_action_failed"), COLOR_MUTED))
            self._after(lambda: self.message.configure(text=text, text_color=color))
            if event in {"online", "started"}:
                self._after(self.check_again)

        self.service_manager.start_ollama(
            self.settings.get("services.ollama.command", "ollama serve"),
            self.settings.get("ollama.host", "http://127.0.0.1:11434"),
            callback=event_handler,
        )

    def show_diagnostics(self):
        window = ctk.CTkToplevel(self)
        window.title(self.t("runtime_diagnostics"))
        window.geometry("760x520")
        window.transient(self.winfo_toplevel())
        textbox = ctk.CTkTextbox(window, wrap="word")
        textbox.pack(fill="both", expand=True, padx=SPACING_MEDIUM, pady=SPACING_MEDIUM)
        payload = self.report or {"status": self.t("runtime_not_checked")}
        textbox.insert("1.0", json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        textbox.configure(state="disabled")

    def _action_result_text(self, result, kind, *, model=""):
        status = str(getattr(result, "status", "error") or "error")
        if status == "success":
            if kind == "ollama":
                return self.t("runtime_ollama_download_page_opened")
            return self.t("runtime_model_downloaded").format(model=model or kind)
        if status == "cancelled":
            return self.t("runtime_download_cancelled")
        if status == "confirmation_required":
            return self.t("runtime_confirmation_required")
        return self.t("runtime_action_failed")

    def destroy(self):
        if self._disposed:
            return
        self._disposed = True
        if self.cancel_event is not None:
            self.cancel_event.set()
        if self.pull_task is not None:
            self.pull_task.cancel()
        super().destroy()

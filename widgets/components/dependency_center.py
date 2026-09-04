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

_VISIBLE_ITEMS = (
    ("ollama", "Ollama"),
    ("local_ai_service", "Local AI Service"),
    ("chat_model", "Chat Model"),
    ("embedding_model", "Embedding"),
    ("ffmpeg", "FFmpeg"),
    ("stt", "STT"),
    ("whisper_model", "Whisper Model"),
    ("tts", "TTS"),
    ("playback", "Playback"),
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
        **kwargs,
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.settings = settings
        self.service_manager = service_manager
        self.open_settings_callback = open_settings_callback
        self.runtime_manager = runtime_manager or RuntimeDependencyManager(settings)
        self.logger = logger
        self.report = None
        self.rows = {}
        self.pull_task = None
        self.cancel_event = None
        self.whisper_button = None
        self.whisper_tier = None
        self._disposed = False
        self._check_running = False
        self._whisper_running = False
        self._build()
        self.check_again()

    def _build(self):
        summary = SectionCard(self, "Runtime / Dependencies")
        summary.pack(fill="x", pady=(0, SPACING_MEDIUM))
        ctk.CTkLabel(
            summary.body,
            text="Aurora Core remains available when local AI or optional Voice components are missing.",
            font=FONT_NORMAL,
            text_color=COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=720,
        ).pack(fill="x", pady=(0, SPACING_SMALL))

        for key, name in _VISIBLE_ITEMS:
            row = ctk.CTkFrame(summary.body, fg_color="transparent")
            row.pack(fill="x", pady=3)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=name, font=FONT_NORMAL, anchor="w", width=150).grid(row=0, column=0, sticky="w")
            status = ctk.CTkLabel(row, text="Checking", font=FONT_SMALL, text_color=COLOR_MUTED, anchor="w")
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
        self.check_button = PrimaryButton(actions, text="Check Again", command=self.check_again)
        self.check_button.pack(side="left", padx=(0, SPACING_SMALL))
        self.reevaluate_button = SecondaryButton(
            actions,
            text="Re-evaluate",
            command=lambda: self.check_again(reevaluate=True),
        )
        self.reevaluate_button.pack(side="left", padx=(0, SPACING_SMALL))
        self.install_button = SecondaryButton(actions, text="Install / Download", command=self.install_or_download)
        self.install_button.pack(side="left", padx=(0, SPACING_SMALL))
        self.configure_button = SecondaryButton(actions, text="Configure", command=self.configure)
        self.configure_button.pack(side="left", padx=(0, SPACING_SMALL))
        self.repair_button = SecondaryButton(actions, text="Repair", command=self.repair)
        self.repair_button.pack(side="left", padx=(0, SPACING_SMALL))
        self.diagnostics_button = SecondaryButton(actions, text="Diagnostics", command=self.show_diagnostics)
        self.diagnostics_button.pack(side="left")

        optional = SectionCard(self, "Optional local features")
        optional.pack(fill="x")
        ctk.CTkLabel(
            optional.body,
            text=(
                "Semantic Knowledge search may use nomic-embed-text. Chat, Memory, and the current token/relevance "
                "RAG path continue without it. Voice models are downloaded only when you explicitly enable Voice."
            ),
            font=FONT_SMALL,
            text_color=COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=720,
        ).pack(fill="x")
        self.embedding_button = SecondaryButton(
            optional.body,
            text="Download Embedding (Optional)",
            command=self.download_embedding,
        )
        self.embedding_button.pack(anchor="w", pady=(SPACING_MEDIUM, 0))

        voice_actions = ctk.CTkFrame(optional.body, fg_color="transparent")
        voice_actions.pack(fill="x", pady=(SPACING_MEDIUM, 0))
        self.whisper_tier = ctk.StringVar(value="recommended")
        ctk.CTkOptionMenu(
            voice_actions,
            values=list(WHISPER_MODEL_OPTIONS),
            variable=self.whisper_tier,
            width=180,
        ).pack(side="left", padx=(0, SPACING_SMALL))
        self.whisper_button = SecondaryButton(
            voice_actions,
            text="Download Whisper Model",
            command=self.download_whisper,
        )
        self.whisper_button.pack(side="left")

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
        self.check_button.configure(state="disabled", text="Checking...")
        self.reevaluate_button.configure(state="disabled")
        self.install_button.configure(state="disabled")
        self.repair_button.configure(state="disabled")
        self.embedding_button.configure(state="disabled")
        self.whisper_button.configure(state="disabled")
        self.message.configure(text="Checking the local runtime...", text_color=COLOR_MUTED)

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
                error_text = (
                    "Runtime checks could not be completed. Try Check Again or open Diagnostics."
                )
                if self.logger:
                    self.logger.error(
                        f"Dependency Center check failed: {type(error).__name__}: {error}"
                    )

            def finish():
                self._check_running = False
                self.check_button.configure(state="normal", text="Check Again")
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
        for key, labels in self.rows.items():
            item = items.get(key, {})
            status = str(item.get("status") or "Optional")
            detail = str(item.get("detail") or "Not checked")
            labels[0].configure(text=status, text_color=_STATUS_COLORS.get(status, COLOR_MUTED))
            labels[1].configure(text=detail, text_color=COLOR_MUTED)
        overall = str(report.get("status") or "Degraded")
        self.message.configure(
            text=f"Aurora Core: Ready · Overall optional runtime: {overall}",
            text_color=_STATUS_COLORS.get(overall, COLOR_MUTED),
        )
        if not self._whisper_running:
            stt_ready = items.get("stt", {}).get("status") == "Ready"
            self.whisper_button.configure(state="normal" if stt_ready else "disabled")

    def configure(self):
        if callable(self.open_settings_callback):
            self.open_settings_callback()
        else:
            self.message.configure(text="Open the full Settings editor to configure paths and providers.", text_color=COLOR_MUTED)

    def install_or_download(self):
        if self.report is None:
            self.message.configure(text="Run Check Again before choosing an action.", text_color=COLOR_WARNING)
            return
        report = self.report or {}
        ollama = report.get("ollama", {})
        state = ollama.get("state")
        if state == "Not Installed":
            confirmed = messagebox.askyesno(
                "Install Ollama",
                "Aurora will open Ollama's official Windows download page. Continue?",
                parent=self.winfo_toplevel(),
            )
            result = open_official_ollama_download(confirmed=confirmed)
            self.message.configure(text=result.message, text_color=COLOR_SUCCESS if result.ok else COLOR_MUTED)
            return
        if state == "Installed / Server Offline":
            self.message.configure(text="Ollama is installed but offline. Choose Repair to start it safely.", text_color=COLOR_WARNING)
            return
        recommendation = report.get("recommendation", {})
        if not recommendation.get("download_required"):
            self.message.configure(
                text="Aurora is using a compatible installed Chat model. Choose Configure to change the selection mode.",
                text_color=COLOR_SUCCESS,
            )
            return
        if not recommendation.get("can_download", True):
            self.message.configure(text="Not enough confirmed free disk space for this model.", text_color=COLOR_ERROR)
            return
        model = str(recommendation.get("model") or "")
        size = recommendation.get("approximate_download_gb")
        reason = str(recommendation.get("reason") or "")
        confirmed = messagebox.askyesno(
            "Download Chat Model",
            f"Model: {model}\nApproximate download: {size} GB\nReason: {reason}\n\nDownload now?",
            parent=self.winfo_toplevel(),
        )
        if confirmed:
            self._start_pull(model, kind="Chat")

    def download_embedding(self):
        if self.report is None:
            self.message.configure(text="Run Check Again before choosing an action.", text_color=COLOR_WARNING)
            return
        report = self.report or {}
        if report.get("ollama", {}).get("state") != "Server Ready":
            self.message.configure(text="Start the Ollama service before downloading an embedding model.", text_color=COLOR_WARNING)
            return
        confirmed = messagebox.askyesno(
            "Download Optional Embedding Model",
            "Knowledge semantic search requires an embedding model.\n\nRecommended: nomic-embed-text (about 274 MB)\n\nDownload now?",
            parent=self.winfo_toplevel(),
        )
        if confirmed:
            self._start_pull(RECOMMENDED_EMBEDDING_MODEL, kind="Embedding")

    def download_whisper(self):
        if self.report is None:
            self.message.configure(text="Run Check Again before choosing an action.", text_color=COLOR_WARNING)
            return
        if self.report.get("items_by_key", {}).get("stt", {}).get("status") != "Ready":
            self.message.configure(
                text="Install the optional Faster-Whisper runtime before downloading a Whisper model.",
                text_color=COLOR_WARNING,
            )
            return
        tier = str(self.whisper_tier.get() if self.whisper_tier is not None else "recommended")
        option = WHISPER_MODEL_OPTIONS.get(tier, WHISPER_MODEL_OPTIONS["recommended"])
        confirmed = messagebox.askyesno(
            "Download Optional Whisper Model",
            f"Tier: {tier}\nModel: {option['model']}\nApproximate size: {option['size']}\nReason: {option['reason']}\n\nDownload now?",
            parent=self.winfo_toplevel(),
        )
        if not confirmed:
            return
        self._whisper_running = True
        self.whisper_button.configure(state="disabled", text="Downloading...")
        self.message.configure(text=f"Downloading Whisper {option['model']}...", text_color=COLOR_MUTED)

        def worker():
            result = download_whisper_model(option["model"], confirmed=True)

            def finish():
                self._whisper_running = False
                self.whisper_button.configure(state="normal", text="Download Whisper Model")
                self.message.configure(text=result.message, text_color=COLOR_SUCCESS if result.ok else COLOR_ERROR)
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
        self.install_button.configure(text="Cancel", command=self.cancel_download, state="normal")
        self.check_button.configure(state="disabled")
        self.reevaluate_button.configure(state="disabled")
        self.repair_button.configure(state="disabled")
        self.embedding_button.configure(state="disabled")
        self.whisper_button.configure(state="disabled")
        self.message.configure(text=f"Starting {kind} model download: {model}", text_color=COLOR_MUTED)

        def progress(line):
            summary = str(line).strip().replace("\r", " ")[-180:]
            if summary:
                self._after(lambda value=summary: self.message.configure(text=value, text_color=COLOR_MUTED))

        def worker():
            result = task.run(confirmed=True, progress=progress, cancel_event=cancel_event)
            selection_error = ""
            if result.ok:
                try:
                    self._persist_model_selection(kind, model)
                except Exception as error:
                    selection_error = str(error).strip().splitlines()[0][:180]

            def finish():
                self.install_button.configure(text="Install / Download", command=self.install_or_download, state="normal")
                self.check_button.configure(state="normal")
                self.reevaluate_button.configure(state="normal")
                self.repair_button.configure(state="normal")
                self.embedding_button.configure(state="normal")
                if not self._whisper_running:
                    self.whisper_button.configure(state="normal")
                color = COLOR_SUCCESS if result.ok else (COLOR_MUTED if result.status == "cancelled" else COLOR_ERROR)
                message = result.message
                if selection_error:
                    message = f"{result.message} Configure the selected model manually: {selection_error}"
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
        self.message.configure(text="Cancelling the Aurora-owned download...", text_color=COLOR_WARNING)

    def repair(self):
        if self.report is None:
            self.message.configure(text="Run Check Again before attempting repair.", text_color=COLOR_WARNING)
            return
        if self.service_manager is None:
            self.message.configure(text="Automatic repair is unavailable; configure Ollama and check again.", text_color=COLOR_WARNING)
            return
        state = (self.report or {}).get("ollama", {}).get("state")
        if state == "Server Ready":
            self.message.configure(text="Ollama is already ready; no second process was started.", text_color=COLOR_SUCCESS)
            return
        if state == "Not Installed":
            self.install_or_download()
            return
        self.message.configure(text="Starting the installed Ollama service...", text_color=COLOR_MUTED)

        def event_handler(event):
            if isinstance(event, dict):
                return
            messages = {
                "online": ("Ollama is already ready.", COLOR_SUCCESS),
                "starting": ("Starting the installed Ollama service...", COLOR_MUTED),
                "started": ("Ollama started by Aurora.", COLOR_SUCCESS),
                "existing_process_offline": ("An existing Ollama process is offline. Aurora did not start a duplicate; restart Ollama manually.", COLOR_WARNING),
                "command_not_found": ("Ollama executable could not be found.", COLOR_ERROR),
                "failed": ("Ollama did not become ready. Check Diagnostics and retry.", COLOR_ERROR),
            }
            text, color = messages.get(event, (str(event), COLOR_MUTED))
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
        window.title("Runtime Diagnostics")
        window.geometry("760x520")
        window.transient(self.winfo_toplevel())
        textbox = ctk.CTkTextbox(window, wrap="word")
        textbox.pack(fill="both", expand=True, padx=SPACING_MEDIUM, pady=SPACING_MEDIUM)
        payload = self.report or {"status": "Not checked"}
        textbox.insert("1.0", json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        textbox.configure(state="disabled")

    def destroy(self):
        if self._disposed:
            return
        self._disposed = True
        if self.cancel_event is not None:
            self.cancel_event.set()
        if self.pull_task is not None:
            self.pull_task.cancel()
        super().destroy()

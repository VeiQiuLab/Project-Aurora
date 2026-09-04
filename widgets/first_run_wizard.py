"""First-run UI for a safe, optional local-AI setup."""

from __future__ import annotations

import threading
from tkinter import messagebox

import customtkinter as ctk

from modules.dependency_actions import OllamaPullTask, open_official_ollama_download
from modules.first_run import FIRST_RUN_STEPS, FirstRunController, empty_runtime_report
from modules.runtime_dependencies import RuntimeDependencyManager
from modules.runtime_display import localized_runtime_item
from modules.ui_theme import (
    COLOR_ERROR,
    COLOR_MUTED,
    COLOR_SUCCESS,
    COLOR_WARNING,
    FONT_APP_TITLE,
    FONT_NORMAL,
    FONT_SMALL,
    FONT_TITLE,
    SPACING_LARGE,
    SPACING_MEDIUM,
    SPACING_SMALL,
)
from widgets.ui_components import FixedFooter, PrimaryButton, SecondaryButton, SectionCard, StatusLabel


_STATUS_STYLE = {
    "Ready": "healthy",
    "Missing": "error",
    "Offline": "warning",
    "Optional": "disabled",
    "Degraded": "warning",
}


class FirstRunWizard(ctk.CTkToplevel):
    """Guide first-time users without making optional dependencies blockers."""

    def __init__(
        self,
        parent,
        *,
        release,
        build,
        translate,
        settings_get,
        on_complete,
        logger,
        runtime_manager=None,
        service_manager=None,
    ):
        super().__init__(parent)
        self.release = release
        self.build = build
        self.t = translate
        self.settings_get = settings_get
        self.on_complete = on_complete
        self.logger = logger
        self.runtime_manager = runtime_manager or RuntimeDependencyManager(_SettingsView(settings_get))
        self.service_manager = service_manager
        self.controller = FirstRunController(
            empty_runtime_report(),
            configured_chat_model=str(settings_get("chat_model", "") or ""),
            configured_embedding_model=str(settings_get("embedding_model", "") or ""),
        )
        self.check_running = False
        self.has_checked = False
        self.pull_task = None
        self.cancel_event = None
        self.download_button = None
        self.cancel_button = None
        self.model_variable = None
        self._finished = False
        self._disposed = False

        self.title(self._text("first_run_window_title"))
        self.geometry("780x650")
        self.minsize(680, 580)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.skip_and_finish)
        self.grab_set()
        self._build_ui()
        self.logger.info("First Run Wizard opened")
        self.render()

    def _text(self, key):
        value = str(self.t(key))
        return key if value == key else value

    def _build_ui(self):
        self.container = ctk.CTkFrame(self)
        self.container.pack(fill="both", expand=True, padx=SPACING_LARGE, pady=SPACING_LARGE)
        self.title_label = ctk.CTkLabel(self.container, text="", font=FONT_TITLE, anchor="w")
        self.title_label.pack(fill="x", pady=(0, SPACING_MEDIUM))
        self.content = ctk.CTkScrollableFrame(self.container, fg_color="transparent")
        self.content.pack(fill="both", expand=True)
        self.footer = FixedFooter(self.container)
        self.footer.pack(fill="x", pady=(SPACING_MEDIUM, 0))
        self.back_button = SecondaryButton(self.footer.buttons, text=self._text("back"), command=self.previous_step, width=110)
        self.back_button.pack(side="left")
        self.skip_button = SecondaryButton(
            self.footer.buttons,
            text=self._text("first_run_skip_for_now"),
            command=self.skip_and_finish,
            width=140,
        )
        self.skip_button.pack(side="right", padx=(SPACING_SMALL, 0))
        self.next_button = PrimaryButton(self.footer.buttons, text=self._text("next"), command=self.next_step, width=110)
        self.next_button.pack(side="right")

    def _clear(self):
        self.download_button = None
        self.cancel_button = None
        self.model_variable = None
        for child in self.content.winfo_children():
            child.destroy()

    def _card(self, title, description=None):
        card = SectionCard(self.content, title)
        card.pack(fill="x", pady=(0, SPACING_MEDIUM))
        if description:
            ctk.CTkLabel(
                card.body,
                text=description,
                font=FONT_NORMAL,
                text_color=COLOR_MUTED,
                anchor="w",
                justify="left",
                wraplength=690,
            ).pack(fill="x", pady=(0, SPACING_SMALL))
        return card

    def _row(self, parent, name, value, *, color=COLOR_MUTED):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=3)
        row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row, text=name, font=FONT_NORMAL, anchor="w", width=180).grid(row=0, column=0, sticky="w")
        label = ctk.CTkLabel(row, text=str(value), font=FONT_SMALL, text_color=color, anchor="w", justify="left", wraplength=470)
        label.grid(row=0, column=1, sticky="w", padx=(SPACING_SMALL, 0))
        return label

    def render(self):
        self._clear()
        step = self.controller.step
        if step == "welcome":
            self._render_welcome()
        elif step == "environment":
            self._render_environment()
        elif step == "local_model":
            self._render_local_model()
        else:
            self._render_complete()
        self._refresh_navigation()

    def _render_welcome(self):
        self.title_label.configure(text=self._text("first_run_welcome_title"))
        card = self._card("Aurora")
        ctk.CTkLabel(card.body, text="Aurora", font=FONT_APP_TITLE, anchor="w").pack(fill="x", pady=(0, SPACING_SMALL))
        self._row(card.body, self._text("first_run_version"), f"{self.release} · {self.build}", color=COLOR_SUCCESS)
        ctk.CTkLabel(
            card.body,
            text=self._text("first_run_local_first_message"),
            font=FONT_NORMAL,
            anchor="w",
            justify="left",
            wraplength=690,
        ).pack(fill="x", pady=(SPACING_MEDIUM, 0))

    def _render_environment(self):
        self.title_label.configure(text=self._text("first_run_environment_title"))
        card = self._card(
            self._text("first_run_environment_title"),
            self._text("first_run_environment_hint"),
        )
        for item in self.controller.environment_items():
            status = str(item.get("status") or "Degraded")
            display = localized_runtime_item(item, self.t)
            row = ctk.CTkFrame(card.body, fg_color="transparent")
            row.pack(fill="x", pady=4)
            row.grid_columnconfigure(2, weight=1)
            ctk.CTkLabel(row, text=display["name"], font=FONT_NORMAL, anchor="w", width=170).grid(row=0, column=0, sticky="w")
            StatusLabel(row, status=_STATUS_STYLE.get(status, "warning"), text=display["status"], anchor="w", justify="left", width=90).grid(row=0, column=1, sticky="w")
            ctk.CTkLabel(row, text=display["detail"], font=FONT_SMALL, text_color=COLOR_MUTED, anchor="e", justify="right", wraplength=380).grid(row=0, column=2, sticky="e")
        PrimaryButton(card.body, text=self._text("first_run_check_again"), command=self.refresh_environment).pack(anchor="w", pady=(SPACING_MEDIUM, 0))
        if not self.check_running and not self.has_checked:
            self.refresh_environment()

    def _render_local_model(self):
        self.title_label.configure(text=self._text("first_run_local_model_title"))
        hardware = self.controller.hardware()
        hardware_card = self._card(self._text("first_run_hardware"))
        self._row(hardware_card.body, "RAM", self._format_gb(hardware.get("ram_gb")))
        self._row(hardware_card.body, "CPU", hardware.get("cpu") or self._text("first_run_unknown"))
        self._row(hardware_card.body, self._text("first_run_cpu_cores"), hardware.get("logical_cores") or self._text("first_run_unknown"))
        self._row(hardware_card.body, "GPU", hardware.get("gpu") or self._text("first_run_unknown"))
        vram = self._text("first_run_unknown") if hardware.get("vram_gb") is None else self._format_gb(hardware.get("vram_gb"))
        self._row(hardware_card.body, "VRAM", vram)
        self._row(hardware_card.body, self._text("first_run_free_disk"), self._format_gb(hardware.get("disk_free_gb")))

        recommendation = self.controller.recommendation()
        model_card = self._card(
            self._text("first_run_existing_chat_model"),
            self._text("first_run_existing_chat_hint"),
        )
        tier = str(recommendation.get("tier") or "Lightweight").casefold()
        self._row(model_card.body, self._text("first_run_tier"), f"{self._text(f'first_run_tier_{tier}')} · {recommendation.get('parameter_range')}", color=COLOR_SUCCESS)
        self._row(model_card.body, self._text("model"), recommendation.get("model") or "")
        self._row(
            model_card.body,
            self._text("first_run_download"),
            (
                self._text("first_run_already_installed")
                if not recommendation.get("download_required", True)
                else self._text("first_run_approx_download").format(size=recommendation.get("approximate_download_gb"))
            ),
        )
        reason_code = str(recommendation.get("reason_code") or "lightweight")
        self._row(model_card.body, self._text("first_run_why"), self._text(f"first_run_reason_{reason_code}"))
        for warning_code in recommendation.get("warning_codes", []):
            self._row(model_card.body, self._text("first_run_warning"), self._text(f"first_run_warning_{warning_code}"), color=COLOR_WARNING)

        existing = self.controller.existing_chat_names()
        if existing:
            self._row(
                model_card.body,
                self._text("first_run_recommended_existing"),
                self.controller.selected_chat_model,
                color=COLOR_SUCCESS,
            )
            selector = ctk.CTkFrame(model_card.body, fg_color="transparent")
            selector.pack(fill="x", pady=(SPACING_MEDIUM, SPACING_SMALL))
            self.model_variable = ctk.StringVar(value=self.controller.selected_chat_model or existing[0])
            ctk.CTkOptionMenu(selector, values=existing, variable=self.model_variable, width=330).pack(side="left", padx=(0, SPACING_SMALL))
            SecondaryButton(selector, text=self._text("first_run_choose_model"), command=self.use_existing_model).pack(side="left")
        else:
            self._row(model_card.body, self._text("first_run_existing"), self._text("first_run_no_chat_model"), color=COLOR_WARNING)

        actions = ctk.CTkFrame(model_card.body, fg_color="transparent")
        actions.pack(fill="x", pady=(SPACING_SMALL, 0))
        if existing:
            PrimaryButton(
                actions,
                text=self._text("first_run_use_automatically").format(model=self.controller.selected_chat_model),
                command=self.use_automatically,
            ).pack(side="left", padx=(0, SPACING_SMALL))
        self.download_button = SecondaryButton(
            actions,
            text=self._text("first_run_download_another") if existing else self._text("first_run_download_recommended"),
            command=self.choose_another if existing else self.download_recommended,
        )
        self.download_button.pack(side="left", padx=(0, SPACING_SMALL))
        if not existing:
            SecondaryButton(
                actions,
                text=self._text("first_run_choose_another"),
                command=self.choose_another,
            ).pack(side="left", padx=(0, SPACING_SMALL))
        SecondaryButton(actions, text=self._text("first_run_skip_for_now"), command=self.skip_model_setup).pack(side="left")
        self.cancel_button = SecondaryButton(actions, text=self._text("first_run_cancel_download"), command=self.cancel_download)
        if self.pull_task is not None:
            self.cancel_button.pack(side="right")
        if not recommendation.get("can_download", True):
            self.download_button.configure(state="disabled")

        state = self.controller.report.get("ollama", {}).get("state")
        if state == "Not Installed":
            install_card = self._card("Ollama", self._text("first_run_ollama_not_installed"))
            SecondaryButton(install_card.body, text=self._text("first_run_open_ollama_download"), command=self.open_ollama_download).pack(anchor="w")
        elif state == "Installed / Server Offline":
            service_card = self._card("Ollama", self._text("first_run_ollama_offline"))
            SecondaryButton(service_card.body, text=self._text("first_run_start_ollama"), command=self.start_ollama).pack(anchor="w")

    def _render_complete(self):
        self.title_label.configure(text=self._text("first_run_complete_title"))
        card = self._card(self._text("runtime_domain_core"), self._text("first_run_complete_hint"))
        self._row(card.body, self._text("first_run_core"), self._text("runtime_status_ready"), color=COLOR_SUCCESS)
        selected = self.controller.selected_chat_model if self.controller.model_decision in {"auto", "use_existing", "downloaded"} else self._text("first_run_skipped")
        self._row(card.body, self._text("chat_model"), selected)
        self._row(card.body, self._text("runtime_item_embedding"), self.controller.selected_embedding_model or self._text("first_run_optional_unchanged"))
        self._row(card.body, self._text("runtime_domain_voice"), self._text("first_run_optional_later"))

    def _format_gb(self, value):
        try:
            return f"{float(value):g} GB"
        except (TypeError, ValueError):
            return self._text("first_run_unknown")

    def _refresh_navigation(self):
        downloading = self.pull_task is not None
        self.back_button.configure(
            state="disabled"
            if self.controller.step_index == 0 or downloading
            else "normal"
        )
        self.next_button.configure(
            text=self._text("finish") if self.controller.step == "complete" else self._text("next"),
            state="disabled" if downloading or self.check_running else "normal",
        )
        # Environment probes are optional and may involve slow device drivers;
        # Skip must always remain available so they can never block Core.
        self.skip_button.configure(state="disabled" if downloading else "normal")

    def refresh_environment(self):
        if self.check_running:
            return
        self.check_running = True
        self.footer.message.configure(text=self._text("runtime_checking"), text_color=COLOR_MUTED)

        def worker():
            try:
                report = self.runtime_manager.check(timeout=1.0)
            except Exception as error:
                report = empty_runtime_report()
                message = self._text("first_run_environment_failed")
                if self.logger:
                    self.logger.error(
                        f"First Run environment check failed: {type(error).__name__}: {error}"
                    )
            else:
                message = self._text("first_run_environment_complete")

            def finish():
                self.check_running = False
                self.has_checked = True
                self.controller.apply_report(report)
                self.footer.message.configure(text=message, text_color=COLOR_SUCCESS if report.get("core_ready") else COLOR_WARNING)
                self.render()

            self._after(finish)

        threading.Thread(target=worker, daemon=True).start()

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
                    self.logger.error(f"First Run UI update failed: {error}")

        try:
            self.after(0, guarded_callback)
        except Exception:
            return

    def previous_step(self):
        if self.pull_task is None:
            self.controller.previous_step()
            self.render()

    def next_step(self):
        if self.pull_task is not None:
            return
        if self.controller.step == "complete":
            self.finish()
            return
        self.controller.next_step()
        self.render()

    def skip_model_setup(self):
        self.controller.skip_model_setup()
        self.controller.step_index = FIRST_RUN_STEPS.index("complete")
        self.render()

    def use_existing_model(self):
        try:
            self.controller.use_existing_model(self.model_variable.get() if self.model_variable is not None else "")
        except ValueError:
            self.footer.message.configure(text=self._text("first_run_invalid_chat_model"), text_color=COLOR_ERROR)
            return
        self.footer.message.configure(text=self._text("first_run_existing_selected"), text_color=COLOR_SUCCESS)

    def use_automatically(self):
        try:
            model = self.controller.use_automatically()
        except ValueError:
            self.footer.message.configure(text=self._text("first_run_invalid_chat_model"), text_color=COLOR_ERROR)
            return
        self.footer.message.configure(
            text=self._text("first_run_auto_selected").format(model=model),
            text_color=COLOR_SUCCESS,
        )

    def download_recommended(self):
        self._confirm_and_download(self.controller.recommendation().get("model"))

    def choose_another(self):
        dialog = ctk.CTkInputDialog(
            text=self._text("first_run_enter_model"),
            title=self._text("first_run_choose_another_title"),
        )
        value = dialog.get_input()
        if value:
            self._confirm_and_download(value)

    def _confirm_and_download(self, model):
        state = self.controller.report.get("ollama", {}).get("state")
        if state != "Server Ready":
            self.footer.message.configure(text=self._text("first_run_ollama_required"), text_color=COLOR_WARNING)
            return
        try:
            plan = self.controller.prepare_download(model)
        except ValueError:
            self.footer.message.configure(text=self._text("first_run_invalid_chat_model"), text_color=COLOR_ERROR)
            return
        confirmed = messagebox.askyesno(
            self._text("first_run_confirm_download_title"),
            self._text("first_run_confirm_download_prompt").format(
                model=plan.model,
                size=plan.approximate_size,
                reason=self._text("runtime_recommendation_reason"),
            ),
            parent=self,
        )
        if not confirmed:
            self.controller.mark_download_result("confirmation_required", "Download not started.")
            self.footer.message.configure(text=self._text("first_run_download_not_started"), text_color=COLOR_MUTED)
            return
        executable = str(self.controller.report.get("ollama", {}).get("executable_path") or "ollama")
        self.pull_task = OllamaPullTask(plan.model, ollama_executable=executable)
        self.cancel_event = threading.Event()
        self.controller.mark_download_started(plan.model)
        self.render()
        self.footer.message.configure(text=self._text("runtime_downloading_model").format(model=plan.model), text_color=COLOR_MUTED)

        def progress(line):
            text = str(line).replace("\r", " ").strip()[-180:]
            if text:
                if self.logger:
                    self.logger.info(f"Model download progress: {text}")
                self._after(lambda: self.footer.message.configure(text=self._text("runtime_downloading_model").format(model=plan.model), text_color=COLOR_MUTED))

        def worker():
            result = self.pull_task.run(confirmed=True, progress=progress, cancel_event=self.cancel_event)

            def finish_download():
                self.controller.mark_download_result(result.status, result.message)
                self.pull_task = None
                self.cancel_event = None
                self.footer.message.configure(
                    text=(
                        self._text("runtime_model_downloaded").format(model=plan.model)
                        if result.ok
                        else self._text("runtime_download_cancelled")
                        if result.status == "cancelled"
                        else self._text("runtime_action_failed")
                    ),
                    text_color=COLOR_SUCCESS if result.ok else (COLOR_MUTED if result.status == "cancelled" else COLOR_ERROR),
                )
                if result.ok:
                    self.refresh_environment()
                self.render()

            self._after(finish_download)

        threading.Thread(target=worker, daemon=True).start()

    def cancel_download(self):
        if self.cancel_event is not None:
            self.cancel_event.set()
        if self.pull_task is not None:
            self.pull_task.cancel()
        self.footer.message.configure(text=self._text("runtime_cancelling_download"), text_color=COLOR_WARNING)

    def open_ollama_download(self):
        confirmed = messagebox.askyesno(
            self._text("runtime_install_ollama_title"),
            self._text("first_run_open_ollama_prompt"),
            parent=self,
        )
        result = open_official_ollama_download(confirmed=confirmed)
        self.footer.message.configure(
            text=self._text("runtime_ollama_download_page_opened") if result.ok else self._text("runtime_action_failed"),
            text_color=COLOR_SUCCESS if result.ok else COLOR_MUTED,
        )

    def start_ollama(self):
        if self.service_manager is None:
            self.footer.message.configure(text=self._text("first_run_open_ollama_manually"), text_color=COLOR_WARNING)
            return
        self.footer.message.configure(text=self._text("runtime_starting_ollama"), text_color=COLOR_MUTED)

        def callback(event):
            if isinstance(event, dict):
                return
            messages = {
                "online": self._text("runtime_ollama_already_ready"),
                "starting": self._text("runtime_starting_ollama"),
                "started": self._text("runtime_ollama_started"),
                "existing_process_offline": self._text("runtime_ollama_existing_offline"),
                "command_not_found": self._text("runtime_ollama_missing"),
                "failed": self._text("runtime_ollama_start_failed"),
            }
            self._after(lambda: self.footer.message.configure(text=messages.get(event, self._text("runtime_action_failed")), text_color=COLOR_SUCCESS if event in {"online", "started"} else COLOR_WARNING))
            if event in {"online", "started"}:
                self._after(self.refresh_environment)

        self.service_manager.start_ollama(
            self.settings_get("services.ollama.command", "ollama serve"),
            self.settings_get("ollama.host", "http://127.0.0.1:11434"),
            callback=callback,
        )

    def skip_and_finish(self):
        if self.pull_task is not None:
            self.footer.message.configure(text=self._text("first_run_cancel_before_close"), text_color=COLOR_WARNING)
            return
        self.controller.skip_model_setup()
        self.finish()

    def finish(self):
        if self._finished:
            return
        self._finished = True
        updates = self.controller.completion_updates()
        try:
            self.on_complete(updates, self)
        except Exception:
            self._finished = False
            self.footer.message.configure(text=self._text("first_run_save_failed"), text_color=COLOR_ERROR)

    def destroy(self):
        if self._disposed:
            return
        self._disposed = True
        if self.cancel_event is not None:
            self.cancel_event.set()
        if self.pull_task is not None:
            self.pull_task.cancel()
        super().destroy()


class _SettingsView:
    """Adapt a settings getter callback to RuntimeDependencyManager's interface."""

    def __init__(self, getter):
        self._getter = getter

    def get(self, key, default=None):
        return self._getter(key, default)

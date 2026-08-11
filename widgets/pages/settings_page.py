import subprocess
import threading
from pathlib import Path

import customtkinter as ctk

from modules.app_paths import CONVERSATIONS_DIR, KNOWLEDGE_DIR, MEMORY_DIR, PERSONA_DIR
from modules.experience.audio.device_discovery import (
    AudioDeviceDiscoveryError,
    enumerate_dshow_audio_devices,
    resolve_voice_input_device,
    select_voice_input_device,
)
from modules.experience.voice.dependency_manager import check_dependencies, install_dependencies
from modules.ui_theme import (
    COLOR_ERROR,
    COLOR_MUTED,
    COLOR_SUCCESS,
    FONT_HEADER,
    FONT_NORMAL,
    FONT_NORMAL_BOLD,
    FONT_SMALL,
    FONT_TITLE,
    SPACING_LARGE,
    SPACING_MEDIUM,
    SPACING_SMALL
)
from modules.version import BUILD_DATE, VERSION
from widgets.components.knowledge_panel import KnowledgePanel
from widgets.components.memory_panel import MemoryPanel
from widgets.components.persona_panel import PersonaPanel
from widgets.ui_components import PrimaryButton, SecondaryButton, SectionCard


class SettingsPage(ctk.CTkFrame):
    """Chat-first Settings hub with grouped product settings."""

    CATEGORIES = [
        ("ai", "AI"),
        ("voice", "Voice"),
        ("appearance", "Appearance"),
        ("data", "Data"),
        ("developer", "Developer")
    ]

    def __init__(
        self,
        parent,
        *,
        translate,
        settings,
        text,
        persona_store=None,
        memory_store=None,
        search_memories=None,
        knowledge_store=None,
        version=VERSION,
        retrieval_summary=None,
        final_prompt_preview_callback=None,
        open_settings_callback=None,
        settings_status_provider=None,
        logger=None,
        **kwargs
    ):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)
        self.t = translate
        self.settings = settings
        self.text = text
        self.persona_store = persona_store
        self.memory_store = memory_store
        self.search_memories = search_memories
        self.knowledge_store = knowledge_store
        self.version = version
        self.retrieval_summary = retrieval_summary
        self.final_prompt_preview_callback = final_prompt_preview_callback
        self.open_settings_callback = open_settings_callback
        self.settings_status_provider = settings_status_provider
        self.logger = logger
        self.category_buttons = {}
        self.voice_environment_rows = {}
        self.voice_environment_status = None
        self.voice_environment_button = None
        self.voice_device_label = None
        self.voice_device_status = None
        self.current_category = "ai"
        self.active_panel = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build()
        self.show_category(self.current_category)

    def _build(self):
        self.sidebar = ctk.CTkFrame(self, width=220)
        self.sidebar.grid(row=0, column=0, sticky="nsw", padx=(0, SPACING_MEDIUM))
        self.sidebar.grid_propagate(False)

        for category_id, label in self.CATEGORIES:
            button = SecondaryButton(
                self.sidebar,
                text=label,
                command=lambda value=category_id: self.show_category(value),
                anchor="w"
            )
            button.pack(fill="x", padx=SPACING_SMALL, pady=SPACING_SMALL)
            self.category_buttons[category_id] = button

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(1, weight=1)

        self.header = ctk.CTkFrame(self.content, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", pady=(0, SPACING_MEDIUM))
        self.header.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(self.header, text="", font=FONT_TITLE, anchor="w")
        self.title_label.grid(row=0, column=0, sticky="w")

        self.body = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)

    def use_external_sidebar(self):
        self.sidebar.grid_remove()
        self.content.grid(row=0, column=0, sticky="nsew")
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)

    def show_category(self, category_id):
        self.current_category = category_id
        self._clear_body()
        title = dict(self.CATEGORIES).get(category_id, "Settings")
        self.title_label.configure(text=title)
        builders = {
            "ai": self._build_ai,
            "voice": self._build_voice,
            "appearance": self._build_appearance,
            "data": self._build_data,
            "developer": self._build_developer
        }
        builders.get(category_id, self._build_ai)()
        self._refresh_category_buttons()
        if self.logger:
            self.logger.info(f"Settings page category selected: {category_id}")

    def refresh_status(self):
        return None

    def open_settings_editor(self):
        if callable(self.open_settings_callback):
            self.open_settings_callback()
            if self.logger:
                self.logger.info("Settings page opened existing SettingsWindow")

    def _clear_body(self):
        self.active_panel = None
        for child in self.body.winfo_children():
            child.destroy()

    def _refresh_category_buttons(self):
        for category_id, button in self.category_buttons.items():
            selected = category_id == self.current_category
            button.configure(font=FONT_HEADER if selected else FONT_NORMAL)

    def _card(self, title, description=None):
        card = SectionCard(self.body, title)
        card.grid(row=len(self.body.winfo_children()), column=0, sticky="ew", pady=(0, SPACING_MEDIUM))
        if description:
            ctk.CTkLabel(
                card.body,
                text=description,
                font=FONT_NORMAL,
                text_color=COLOR_MUTED,
                anchor="w",
                justify="left",
                wraplength=720
            ).pack(fill="x", pady=(0, SPACING_SMALL))
        return card

    def _setting_row(self, parent, label, value):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=SPACING_SMALL)
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(row, text=label, font=FONT_NORMAL, anchor="w").grid(row=0, column=0, sticky="w")
        value_label = ctk.CTkLabel(row, text=str(value), font=FONT_SMALL, text_color=COLOR_MUTED, anchor="e")
        value_label.grid(
            row=0,
            column=1,
            sticky="e"
        )
        return value_label

    def _action_button(self, parent, text, command):
        SecondaryButton(parent, text=text, command=command, anchor="w").pack(fill="x", pady=SPACING_SMALL)

    def _build_ai(self):
        card = self._card("模型设置", "模型、Persona、Memory 与 Knowledge/RAG 统一放在 AI 设置下。")
        self._setting_row(card.body, "Chat Model", self.settings.get("chat_model", ""))
        self._setting_row(card.body, "Embedding Model", self.settings.get("embedding_model", ""))
        self._setting_row(card.body, "Ollama", self.settings.get("ollama.host", ""))
        self._action_button(card.body, "打开模型设置", self.open_settings_editor)

        tools = self._card("AI 能力")
        self._action_button(tools.body, "Persona", self._show_persona_panel)
        self._action_button(tools.body, "Memory", self._show_memory_panel)
        self._action_button(tools.body, "Knowledge / RAG", self._show_knowledge_panel)

    def _build_voice(self):
        card = self._card("Voice", "麦克风、STT、TTS 与播放设置保留现有配置兼容。")
        self._setting_row(card.body, "Voice Enabled", self.settings.get("voice.enabled", False))
        self.voice_device_label = self._setting_row(
            card.body,
            "当前输入设备",
            self._current_voice_device_text()
        )
        device_actions = ctk.CTkFrame(card.body, fg_color="transparent")
        device_actions.pack(fill="x", pady=(0, SPACING_SMALL))
        SecondaryButton(device_actions, text="选择设备", command=self._choose_voice_input_device).pack(
            side="left",
            padx=(0, SPACING_SMALL)
        )
        SecondaryButton(device_actions, text="开始测试", command=self._test_voice_input_device).pack(side="left")
        self.voice_device_status = ctk.CTkLabel(
            card.body,
            text="",
            font=FONT_SMALL,
            text_color=COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=720
        )
        self.voice_device_status.pack(fill="x", pady=(0, SPACING_SMALL))
        self._setting_row(card.body, "STT", self.settings.get("voice.stt.provider", "Faster Whisper"))
        self._setting_row(card.body, "TTS", self.settings.get("voice.tts.provider", "Default"))
        self._setting_row(card.body, "Playback", self.settings.get("voice.playback.device", "Default"))
        self._action_button(card.body, "打开 Voice 设置", self.open_settings_editor)

        environment = self._card("Voice Environment")
        self.voice_environment_rows = {}
        for category in ("STT", "TTS", "Audio", "FFmpeg"):
            row = ctk.CTkFrame(environment.body, fg_color="transparent")
            row.pack(fill="x", pady=SPACING_SMALL)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(row, text=f"{category}:", font=FONT_NORMAL, anchor="w").grid(
                row=0,
                column=0,
                sticky="w"
            )
            label = ctk.CTkLabel(row, text="Checking", font=FONT_SMALL, text_color=COLOR_MUTED, anchor="e")
            label.grid(row=0, column=1, sticky="e")
            self.voice_environment_rows[category] = label

        self.voice_environment_status = ctk.CTkLabel(
            environment.body,
            text="",
            font=FONT_SMALL,
            text_color=COLOR_MUTED,
            anchor="w",
            justify="left",
            wraplength=720
        )
        self.voice_environment_status.pack(fill="x", pady=(SPACING_SMALL, 0))
        self.voice_environment_button = PrimaryButton(
            environment.body,
            text="安装语音组件",
            command=self._install_voice_dependencies
        )
        self.voice_environment_button.pack(anchor="w", pady=(SPACING_MEDIUM, 0))
        self._refresh_voice_environment()

    def _build_appearance(self):
        card = self._card("Appearance", "主题、语言和窗口设置集中在外观设置中。")
        self._setting_row(card.body, "主题", self.settings.get("theme", "blue"))
        self._setting_row(card.body, "外观", self.settings.get("appearance", "System"))
        self._setting_row(card.body, "语言", self.settings.get("language", "zh_CN"))
        window_size = f"{self.settings.get('window.width', '')} x {self.settings.get('window.height', '')}"
        self._setting_row(card.body, "窗口", window_size)
        self._action_button(card.body, "打开外观设置", self.open_settings_editor)

    def _build_data(self):
        card = self._card("Data", "会话、Memory 与 Knowledge 数据入口集中在这里。")
        self._setting_row(card.body, "会话数据", CONVERSATIONS_DIR)
        self._setting_row(card.body, "Memory 数据", MEMORY_DIR)
        self._setting_row(card.body, "Knowledge 数据", KNOWLEDGE_DIR)
        self._setting_row(card.body, "Persona 数据", PERSONA_DIR)

        actions = self._card("数据管理")
        self._action_button(actions.body, "Memory 数据", self._show_memory_panel)
        self._action_button(actions.body, "Knowledge 数据", self._show_knowledge_panel)

    def _build_developer(self):
        card = self._card("")
        logo = ctk.CTkFrame(card.body, width=72, height=72, corner_radius=36, fg_color="#111827")
        logo.pack(anchor="center", pady=(SPACING_SMALL, SPACING_MEDIUM))
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="A", font=(FONT_TITLE[0], 34, "bold"), text_color="white").pack(expand=True)

        ctk.CTkLabel(card.body, text="Project Aurora", font=FONT_TITLE).pack(anchor="center")
        ctk.CTkLabel(card.body, text="Private AI companion", font=FONT_NORMAL, text_color=COLOR_MUTED).pack(
            anchor="center",
            pady=(0, SPACING_LARGE)
        )
        self._setting_row(card.body, "Version", VERSION)
        self._setting_row(card.body, "Build Date", BUILD_DATE)
        self._setting_row(card.body, "Git", self._git_info())

        changelog = self._recent_changelog()
        if changelog:
            ctk.CTkLabel(card.body, text="更新日志", font=FONT_NORMAL_BOLD, anchor="w").pack(
                fill="x",
                pady=(SPACING_MEDIUM, SPACING_SMALL)
            )
            ctk.CTkLabel(
                card.body,
                text=changelog,
                font=FONT_SMALL,
                text_color=COLOR_MUTED,
                anchor="w",
                justify="left",
                wraplength=720
            ).pack(fill="x")

        actions = self._card("开发者入口")
        self._action_button(actions.body, "打开完整设置 / 调试日志入口", self.open_settings_editor)

    def _current_voice_device_text(self):
        configured = str(self.settings.get("voice.recorder.device_name", "") or "").strip()
        cached = str(self.settings.get("voice.recorder.last_successful_device_guid", "") or "").strip()
        keyword = str(self.settings.get("voice.recorder.preferred_device_keyword", "") or "").strip()
        return configured or cached or (f"Default / {keyword}" if keyword else "Windows 默认输入设备")

    def _set_voice_device_status(self, text, status="disabled"):
        if self.voice_device_status is None:
            return
        colors = {
            "healthy": COLOR_SUCCESS,
            "error": COLOR_ERROR,
            "warning": COLOR_ERROR,
            "disabled": COLOR_MUTED,
        }
        self.voice_device_status.configure(text=text, text_color=colors.get(status, COLOR_MUTED))

    def _refresh_voice_device_label(self):
        if self.voice_device_label is not None:
            self.voice_device_label.configure(text=self._current_voice_device_text())

    def _choose_voice_input_device(self):
        ffmpeg_path = str(self.settings.get("voice.recorder.ffmpeg_path", "ffmpeg") or "ffmpeg")
        try:
            devices = enumerate_dshow_audio_devices(ffmpeg_path)
        except AudioDeviceDiscoveryError as error:
            self._set_voice_device_status(str(error), "error")
            return

        window = ctk.CTkToplevel(self)
        window.title("选择麦克风")
        window.geometry("560x180")
        window.transient(self.winfo_toplevel())
        window.grab_set()

        values = [device.device_name for device in devices]
        selected = ctk.StringVar(value=values[0] if values else "")
        ctk.CTkLabel(window, text="当前输入设备", font=FONT_NORMAL).pack(
            anchor="w",
            padx=SPACING_MEDIUM,
            pady=(SPACING_MEDIUM, SPACING_SMALL)
        )
        ctk.CTkOptionMenu(window, values=values, variable=selected, width=500).pack(
            fill="x",
            padx=SPACING_MEDIUM,
            pady=(0, SPACING_MEDIUM)
        )

        def save_selection():
            select_voice_input_device(self.settings, selected.get())
            self._refresh_voice_device_label()
            self._set_voice_device_status(f"已选择: {selected.get()}", "healthy")
            window.grab_release()
            window.destroy()

        PrimaryButton(window, text="保存", command=save_selection).pack(anchor="e", padx=SPACING_MEDIUM)

    def _test_voice_input_device(self):
        self._set_voice_device_status("正在检测麦克风设备...", "disabled")

        def run_test():
            try:
                device = resolve_voice_input_device(self.settings)
                result = {"ok": True, "message": f"麦克风可用: {device}"}
            except Exception as error:
                result = {"ok": False, "message": str(error)}

            def finish():
                self._refresh_voice_device_label()
                self._set_voice_device_status(result["message"], "healthy" if result["ok"] else "error")

            self.after(0, finish)

        threading.Thread(target=run_test, daemon=True).start()

    def _refresh_voice_environment(self, report=None):
        report = report or check_dependencies(self.settings)
        categories = report.get("categories", {})
        for category, label in self.voice_environment_rows.items():
            items = categories.get(category, [])
            missing = [item for item in items if not item.get("ready")]
            if missing:
                names = ", ".join(item.get("name", "") for item in missing)
                label.configure(text=f"Missing: {names}", text_color=COLOR_ERROR)
            else:
                label.configure(text="✓ Ready", text_color=COLOR_SUCCESS)

        missing_names = [item.get("name", "") for item in report.get("missing", [])]
        if missing_names:
            message = "Voice dependency missing:\n- " + "\n- ".join(missing_names)
            self.voice_environment_status.configure(text=message, text_color=COLOR_ERROR)
            self.voice_environment_button.pack(anchor="w", pady=(SPACING_MEDIUM, 0))
            self.voice_environment_button.configure(state="normal", text="安装语音组件")
        else:
            self.voice_environment_status.configure(text="Voice environment ready.", text_color=COLOR_SUCCESS)
            self.voice_environment_button.pack_forget()

    def _install_voice_dependencies(self):
        if self.voice_environment_button is None:
            return
        self.voice_environment_button.configure(state="disabled", text="安装中...")
        if self.voice_environment_status is not None:
            self.voice_environment_status.configure(text="正在使用当前 Python 环境安装语音组件...", text_color=COLOR_MUTED)

        def run_install():
            result = install_dependencies(self.settings)
            if self.logger:
                if result.get("success"):
                    self.logger.info("Voice dependency installation completed")
                else:
                    self.logger.error(f"Voice dependency installation failed: {result.get('stderr', '')}")

            def finish():
                self._refresh_voice_environment(result.get("report"))
                if not result.get("success") and self.voice_environment_status is not None:
                    error = str(result.get("stderr") or "Voice dependency installation failed.").strip()
                    skipped = result.get("skipped") or []
                    if skipped:
                        error = f"{error}\nManual install required: {', '.join(skipped)}"
                    self.voice_environment_status.configure(text=error, text_color=COLOR_ERROR)

            self.after(0, finish)

        threading.Thread(target=run_install, daemon=True).start()

    def _show_persona_panel(self):
        if self.persona_store is None:
            return
        self._mount_panel(
            lambda parent: PersonaPanel(
                parent,
                persona_store=self.persona_store,
                settings=self.settings,
                translate=self.t,
                logger=self.logger,
                final_prompt_preview_callback=self.final_prompt_preview_callback,
                show_close_button=False,
                show_header_title=False
            )
        )

    def _show_memory_panel(self):
        if self.memory_store is None or self.search_memories is None:
            return
        self._mount_panel(
            lambda parent: MemoryPanel(
                parent,
                memory_store=self.memory_store,
                search_memories=self.search_memories,
                translate=self.t,
                logger=self.logger,
                show_close_button=False,
                show_header_title=False
            )
        )

    def _show_knowledge_panel(self):
        if self.knowledge_store is None:
            return
        self._mount_panel(
            lambda parent: KnowledgePanel(
                parent,
                knowledge_store=self.knowledge_store,
                settings=self.settings,
                text=self.text,
                translate=self.t,
                logger=self.logger,
                version=self.version,
                retrieval_summary=self.retrieval_summary,
                show_close_button=False,
                show_header_title=False
            )
        )

    def _mount_panel(self, factory):
        self._clear_body()
        holder = ctk.CTkFrame(self.body, fg_color="transparent")
        holder.grid(row=0, column=0, sticky="nsew")
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_rowconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)
        self.active_panel = factory(holder)
        self.active_panel.grid(row=0, column=0, sticky="nsew")

    def _git_info(self):
        root = Path(__file__).resolve().parents[2]
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False
            ).stdout.strip()
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False
            ).stdout.strip()
        except Exception:
            return "Unavailable"
        if commit and branch:
            return f"{branch} @ {commit}"
        return commit or branch or "Unavailable"

    def _recent_changelog(self):
        path = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ""
        entries = []
        for line in lines:
            text = line.strip()
            if text.startswith("- "):
                entries.append(text)
            if len(entries) >= 4:
                break
        return "\n".join(entries)

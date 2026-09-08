"""User-authorized installers and model downloads.

Nothing in this module runs at import time.  Every network or subprocess action
requires an explicit ``confirmed=True`` from the UI/controller that obtained the
user's consent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import queue
import os
import re
import subprocess
import threading
from typing import Callable, Iterable
import webbrowser
from uuid import uuid4


OLLAMA_WINDOWS_DOWNLOAD_URL = "https://ollama.com/download/windows"
FFMPEG_DOWNLOAD_URL = "https://ffmpeg.org/download.html#build-windows"
RECOMMENDED_EMBEDDING_MODEL = "nomic-embed-text"

CHAT_MODEL_OPTIONS = {
    "lightweight": {
        "model": "qwen3:4b",
        "size": "about 2.6 GB",
        "reason": "A practical starting point for lower-memory Windows PCs.",
    },
    "balanced": {
        "model": "qwen3:8b",
        "size": "about 5.2 GB",
        "reason": "A balanced local model for mainstream PCs.",
    },
    "quality": {
        "model": "qwen3:14b",
        "size": "about 9.3 GB",
        "reason": "Higher quality when memory and disk headroom are available.",
    },
}

WHISPER_MODEL_OPTIONS = {
    "lightweight": {
        "model": "tiny",
        "size": "about 75 MB",
        "reason": "Fastest local speech recognition with the smallest download.",
    },
    "recommended": {
        "model": "small",
        "size": "about 500 MB",
        "reason": "A practical accuracy and performance balance.",
    },
    "higher_quality": {
        "model": "medium",
        "size": "about 1.5 GB",
        "reason": "Better recognition when the PC has sufficient resources.",
    },
}

_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?$")
_WHISPER_DOWNLOAD_LOCK = threading.Lock()


@dataclass(frozen=True)
class ActionResult:
    status: str
    message: str
    command: tuple[str, ...] = ()
    returncode: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "success"


def validate_ollama_model_name(model: str) -> str:
    """Return a normalized Ollama model reference or reject unsafe input."""

    value = str(model or "").strip()
    if not value or not _MODEL_NAME.fullmatch(value) or ".." in value:
        raise ValueError("Invalid Ollama model name.")
    return value


def open_official_ollama_download(*, confirmed: bool, opener=webbrowser.open) -> ActionResult:
    """Open the official Windows installer page only after a user action."""

    if not confirmed:
        return ActionResult("confirmation_required", "User confirmation is required.")
    try:
        opened = bool(opener(OLLAMA_WINDOWS_DOWNLOAD_URL))
    except Exception:
        opened = False
    if not opened:
        return ActionResult("error", "Unable to open the official Ollama download page.")
    return ActionResult("success", "Official Ollama download page opened.")


class OllamaPullTask:
    """One cancellable, Aurora-owned ``ollama pull`` process."""

    def __init__(
        self,
        model: str,
        *,
        ollama_executable: str = "ollama",
        popen_factory=subprocess.Popen,
    ):
        self.model = validate_ollama_model_name(model)
        self.command = (str(ollama_executable), "pull", self.model)
        self._popen_factory = popen_factory
        self._process = None
        self._lock = threading.Lock()

    def cancel(self) -> bool:
        """Terminate only the pull process created by this task."""

        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            return False
        try:
            process.terminate()
            return True
        except OSError:
            return False

    def run(
        self,
        *,
        confirmed: bool,
        progress: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ActionResult:
        if not confirmed:
            return ActionResult("confirmation_required", "User confirmation is required.", self.command)
        if cancel_event is not None and cancel_event.is_set():
            return ActionResult("cancelled", "Download cancelled.", self.command)

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = self._popen_factory(
                list(self.command),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=creationflags,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError) as error:
            return ActionResult("error", _safe_error(error, "Unable to start Ollama."), self.command)

        with self._lock:
            self._process = process

        messages: queue.Queue[str | None] = queue.Queue()

        def read_output():
            stream = process.stdout
            if stream is not None:
                try:
                    for line in iter(stream.readline, ""):
                        messages.put(line.rstrip())
                except (OSError, ValueError):
                    pass
            messages.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        reader_done = False
        cancelled = False
        while process.poll() is None or not reader_done:
            if cancel_event is not None and cancel_event.is_set() and not cancelled:
                cancelled = self.cancel()
            try:
                item = messages.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                reader_done = True
            elif item and callable(progress):
                progress(item)

        returncode = process.wait()
        with self._lock:
            self._process = None
        if cancelled or (cancel_event is not None and cancel_event.is_set()):
            return ActionResult("cancelled", "Download cancelled.", self.command, returncode)
        if returncode != 0:
            return ActionResult("error", "Ollama could not download the model. Check Diagnostics and retry.", self.command, returncode)
        return ActionResult("success", f"Model downloaded: {self.model}", self.command, returncode)


def download_whisper_model(
    model: str,
    *,
    confirmed: bool,
    downloader: Callable[[str], object] | None = None,
    cancel_event: threading.Event | None = None,
) -> ActionResult:
    """Download a faster-whisper model only after explicit confirmation.

    The real downloader is imported lazily so a missing optional STT runtime can
    never prevent Aurora Core from importing or starting.
    """

    allowed = {item["model"] for item in WHISPER_MODEL_OPTIONS.values()}
    normalized = str(model or "").strip().lower()
    if normalized not in allowed:
        return ActionResult("error", "Unsupported Whisper model choice.")
    if not confirmed:
        return ActionResult("confirmation_required", "User confirmation is required.")
    if cancel_event is not None and cancel_event.is_set():
        return ActionResult("cancelled", "Download cancelled.")
    if downloader is None:
        try:
            from faster_whisper.utils import download_model
            from modules.voice_models import managed_model_path, model_download_directory, publish_model_integrity, valid_model_directory

            def downloader(name):
                target = managed_model_path(name)
                if valid_model_directory(target):
                    return str(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                staging = target.with_name(name + ".download")
                # A completed but corrupt staged file may be trusted by Hub's
                # timestamp cache. Keep it for recovery and retry into a fresh
                # staging directory. Incomplete Hub downloads remain resumable.
                if (staging / "model.bin").is_file() and not valid_model_directory(staging):
                    os.replace(staging, staging.with_name(staging.name + ".invalid-" + uuid4().hex))
                download_model(name, output_dir=model_download_directory(staging))
                publish_model_integrity(staging)
                if target.exists():
                    os.replace(target, target.with_name(name + ".invalid-" + uuid4().hex))
                os.replace(staging, target)
                return str(target)
        except (ImportError, OSError):
            return ActionResult("error", "Faster-Whisper is not installed.")
    try:
        # Multiple UI entry points must not publish the same staging directory
        # concurrently. Failed downloads remain resumable on an explicit retry.
        with _WHISPER_DOWNLOAD_LOCK:
            downloader(normalized)
    except Exception as error:
        return ActionResult("error", _safe_error(error, "Whisper model download failed."))
    if cancel_event is not None and cancel_event.is_set():
        return ActionResult("cancelled", "Download cancelled.")
    return ActionResult("success", f"Whisper model downloaded: {normalized}")


def select_whisper_model(settings, model: str) -> None:
    """Select the successfully downloaded tier for both diagnostics and STT."""

    allowed = {item["model"] for item in WHISPER_MODEL_OPTIONS.values()}
    if model not in allowed:
        raise ValueError("Unsupported Whisper model choice")
    if hasattr(settings, "update_many"):
        settings.update_many({"voice.stt.model_size": model}, save=True)
    elif isinstance(settings, dict):
        settings.setdefault("voice", {}).setdefault("stt", {})["model_size"] = model
    else:
        settings.set("voice.stt.model_size", model)


def _safe_error(error: BaseException, fallback: str) -> str:
    """Short user-facing errors without tracebacks or multiline command output."""

    message = str(error).strip().splitlines()[0] if str(error).strip() else fallback
    return message[:240]


def model_option(tier: str) -> dict:
    return dict(CHAT_MODEL_OPTIONS.get(str(tier), CHAT_MODEL_OPTIONS["balanced"]))


def whisper_options() -> Iterable[dict]:
    return (dict(item) for item in WHISPER_MODEL_OPTIONS.values())

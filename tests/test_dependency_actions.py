import threading

import pytest

from modules.dependency_actions import (
    OLLAMA_WINDOWS_DOWNLOAD_URL,
    OllamaPullTask,
    download_whisper_model,
    open_official_ollama_download,
    validate_ollama_model_name,
)


class _FakeStream:
    def __init__(self, lines=()):
        self._lines = iter([f"{line}\n" for line in lines] + [""])

    def readline(self):
        return next(self._lines)


class _FakeProcess:
    def __init__(self, lines=(), returncode=0):
        self.stdout = _FakeStream(lines)
        self.returncode = returncode
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 1


class _EmptyStream:
    def readline(self):
        return ""


class _RunningProcess:
    def __init__(self):
        self.stdout = _EmptyStream()
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 1


def test_model_download_never_starts_without_confirmation():
    calls = []
    task = OllamaPullTask("qwen3:8b", popen_factory=lambda *args, **kwargs: calls.append((args, kwargs)))

    result = task.run(confirmed=False)

    assert result.status == "confirmation_required"
    assert calls == []


def test_confirmed_model_download_uses_argument_list_without_shell():
    captured = {}

    def popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return _FakeProcess(["pulling manifest", "success"])

    progress = []
    result = OllamaPullTask("qwen3:8b", popen_factory=popen).run(confirmed=True, progress=progress.append)

    assert result.ok
    assert captured["command"] == ["ollama", "pull", "qwen3:8b"]
    assert captured["shell"] is False
    assert progress == ["pulling manifest", "success"]


@pytest.mark.parametrize("value", ["--help", "model name", "name;calc", "../model", ""])
def test_unsafe_model_names_are_rejected(value):
    with pytest.raises(ValueError):
        validate_ollama_model_name(value)


def test_embedding_download_requires_same_explicit_confirmation():
    calls = []
    task = OllamaPullTask("nomic-embed-text", popen_factory=lambda *args, **kwargs: calls.append((args, kwargs)))

    result = task.run(confirmed=False)

    assert result.status == "confirmation_required"
    assert calls == []


def test_whisper_download_requires_confirmation():
    calls = []

    denied = download_whisper_model("small", confirmed=False, downloader=calls.append)
    allowed = download_whisper_model("small", confirmed=True, downloader=calls.append)

    assert denied.status == "confirmation_required"
    assert allowed.ok
    assert calls == ["small"]


def test_cancelled_before_start_does_not_launch_process():
    calls = []
    cancelled = threading.Event()
    cancelled.set()
    task = OllamaPullTask("qwen3:4b", popen_factory=lambda *args, **kwargs: calls.append((args, kwargs)))

    result = task.run(confirmed=True, cancel_event=cancelled)

    assert result.status == "cancelled"
    assert calls == []


def test_active_download_cancel_terminates_only_its_owned_process():
    process = _RunningProcess()
    started = threading.Event()
    cancel_event = threading.Event()
    result = {}

    def popen(*_args, **_kwargs):
        started.set()
        return process

    task = OllamaPullTask("qwen3:4b", popen_factory=popen)
    worker = threading.Thread(
        target=lambda: result.setdefault(
            "value", task.run(confirmed=True, cancel_event=cancel_event)
        )
    )
    worker.start()
    assert started.wait(1)
    cancel_event.set()
    assert task.cancel() is True
    worker.join(1)

    assert not worker.is_alive()
    assert process.terminated is True
    assert result["value"].status == "cancelled"


def test_official_installer_action_opens_only_trusted_url_after_confirmation():
    opened = []

    denied = open_official_ollama_download(confirmed=False, opener=opened.append)
    allowed = open_official_ollama_download(confirmed=True, opener=lambda url: opened.append(url) or True)

    assert denied.status == "confirmation_required"
    assert allowed.ok
    assert opened == [OLLAMA_WINDOWS_DOWNLOAD_URL]

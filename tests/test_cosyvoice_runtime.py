import queue
import re
import subprocess
from pathlib import Path

import pytest

from aurora_voice_node.runtime import CosyVoiceRuntime, CosyVoiceRuntimeConfig, RuntimeUnavailable
from aurora_voice_node.wav_utils import inspect_wav
from wav_helpers import make_float_wav, make_wav


class FakeStdout:
    def __init__(self):
        self._bytes = queue.Queue()

    def feed(self, data):
        for byte in data:
            self._bytes.put(bytes((byte,)))

    def close(self):
        self._bytes.put(None)

    def read(self, _size):
        return self._bytes.get(timeout=2)


class FakeStdin:
    def __init__(self, process):
        self.process = process
        self.pending = b""

    def write(self, data):
        self.pending += data
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            self.process.handle(line.decode("utf-8"))
        return len(data)

    def flush(self):
        return None


class FakeProcess:
    _next_pid = 100

    def __init__(self, command):
        type(self)._next_pid += 1
        self.pid = type(self)._next_pid
        self.command = command
        self.alive = True
        self.exit_code = None
        self.stdout = FakeStdout()
        self.stdin = FakeStdin(self)
        self.audio_id = 0
        self.stdout.feed(b"Loading model done\n> ")

    def handle(self, line):
        if line == "/exit":
            self.alive = False
            self.exit_code = 0
            self.stdout.close()
        elif line.startswith("/save "):
            match = re.match(r'^/save "(.+)" (\d+)$', line)
            assert match is not None
            path, audio_id = match.groups()
            Path(path).write_bytes(make_wav())
            self.stdout.feed(f"Saved audio {audio_id} to {path}\n> ".encode())
        elif line.startswith("/delete "):
            self.stdout.feed(f"Deleted audio {line.split()[-1]}.\n> ".encode())
        else:
            self.audio_id += 1
            self.stdout.feed(
                f"Generated audio {self.audio_id} (0.01s, rtf=0.10), seed=1.\n> ".encode()
            )

    def poll(self):
        return None if self.alive else self.exit_code

    def wait(self, timeout=None):
        if self.alive:
            raise subprocess.TimeoutExpired(self.command, timeout)
        return self.exit_code

    def terminate(self):
        self.alive = False
        self.exit_code = -15
        self.stdout.close()

    def kill(self):
        self.terminate()


class FakeProcessFactory:
    def __init__(self):
        self.processes = []

    def __call__(self, command, **_kwargs):
        process = FakeProcess(command)
        self.processes.append(process)
        return process


class FailingSynthesisProcess(FakeProcess):
    def handle(self, line):
        if line.startswith("/"):
            super().handle(line)
            return
        self.stdout.feed(b"CUDA out of memory\n")
        self.alive = False
        self.exit_code = 7
        self.stdout.close()


class FloatWavProcess(FakeProcess):
    def handle(self, line):
        if line.startswith("/save "):
            match = re.match(r'^/save "(.+)" (\d+)$', line)
            assert match is not None
            path, audio_id = match.groups()
            Path(path).write_bytes(make_float_wav((-1.0, 0.0, 1.0), sample_rate=48000))
            self.stdout.feed(f"Saved audio {audio_id} to {path}\n> ".encode())
            return
        super().handle(line)


def runtime_config(tmp_path):
    cli = tmp_path / "cosyvoice-cli"
    model = tmp_path / "model.gguf"
    prompt = tmp_path / "prompt.gguf"
    for path in (cli, model, prompt):
        path.write_bytes(b"test")
    return CosyVoiceRuntimeConfig(
        cli_path=cli,
        model_path=model,
        prompt_speech_path=prompt,
        backend="cuda0",
        output_directory=tmp_path / "output",
        startup_timeout_seconds=1,
        synthesis_timeout_seconds=1,
    )


def test_interactive_process_is_reused_for_same_speed(tmp_path):
    factory = FakeProcessFactory()
    runtime = CosyVoiceRuntime(runtime_config(tmp_path), process_factory=factory)
    try:
        first = runtime.synthesize("first", 1.0)
        second = runtime.synthesize("second", 1.0)
    finally:
        runtime.stop()

    assert first == make_wav()
    assert second == make_wav()
    assert len(factory.processes) == 1
    assert factory.processes[0].command.count("--interactive") == 1
    assert factory.processes[0].command[-2:] == ["--backend", "cuda0"]


def test_speed_change_performs_one_controlled_restart(tmp_path):
    factory = FakeProcessFactory()
    runtime = CosyVoiceRuntime(runtime_config(tmp_path), process_factory=factory)
    try:
        runtime.synthesize("normal", 1.0)
        runtime.synthesize("faster", 1.2)
        health = runtime.health()
    finally:
        runtime.stop()

    assert len(factory.processes) == 2
    assert factory.processes[0].command[factory.processes[0].command.index("--speed") + 1] == "1"
    assert factory.processes[1].command[factory.processes[1].command.index("--speed") + 1] == "1.2"
    assert health["available"] is True
    assert health["restart_count"] == 1
    assert health["startup_output_tail"] == "Loading model done\n> "


def test_missing_runtime_file_is_reported_by_health(tmp_path):
    config = runtime_config(tmp_path)
    config.model_path.unlink()
    runtime = CosyVoiceRuntime(config)

    with pytest.raises(RuntimeUnavailable, match="model file is unavailable"):
        runtime.start()

    health = runtime.health()
    assert health["available"] is False
    assert health["state"] == "failed"
    assert health["last_error"] == "model file is unavailable"


def test_unexpected_exit_preserves_cli_output_in_health(tmp_path):
    runtime = CosyVoiceRuntime(
        runtime_config(tmp_path),
        process_factory=lambda command, **_kwargs: FailingSynthesisProcess(command),
    )

    with pytest.raises(RuntimeUnavailable, match="exit_code=7"):
        runtime.synthesize("trigger failure", 1.0)

    runtime._reader_thread.join(1)
    health = runtime.health()
    assert health["available"] is False
    assert health["state"] == "failed"
    assert "code 7" in health["last_error"]
    assert "CUDA out of memory" in health["last_error"]


def test_runtime_normalizes_saved_float32_wav_to_pcm16(tmp_path):
    runtime = CosyVoiceRuntime(
        runtime_config(tmp_path),
        process_factory=lambda command, **_kwargs: FloatWavProcess(command),
    )
    try:
        audio = runtime.synthesize("float output", 1.0)
    finally:
        runtime.stop()

    info = inspect_wav(audio)
    assert info.format_tag == 1
    assert info.bits_per_sample == 16
    assert info.sample_rate == 48000
    assert info.channels == 1

import io
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from aurora_voice_node.runtime import RuntimeSynthesisError, RuntimeTimedOut
from aurora_voice_node.server_runtime import CosyVoiceServerRuntime, CosyVoiceServerRuntimeConfig
from wav_helpers import make_wav


class FakeProcess:
    _next_pid = 5000

    def __init__(self, command):
        type(self)._next_pid += 1
        self.pid = type(self)._next_pid
        self.command = command
        self.stdout = io.BytesIO(b"CUDA0 ready\n")
        self.alive = True
        self.exit_code = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self.alive else self.exit_code

    def wait(self, timeout=None):
        if self.alive:
            raise subprocess.TimeoutExpired(self.command, timeout)
        return self.exit_code

    def terminate(self):
        self.terminated = True
        self.alive = False
        self.exit_code = 0

    def kill(self):
        self.killed = True
        self.alive = False
        self.exit_code = -9


class FakeProcessFactory:
    def __init__(self):
        self.processes = []

    def __call__(self, command, **_kwargs):
        process = FakeProcess(command)
        self.processes.append(process)
        return process


class StubbornProcess(FakeProcess):
    def terminate(self):
        self.terminated = True


class StubbornProcessFactory(FakeProcessFactory):
    def __call__(self, command, **_kwargs):
        process = StubbornProcess(command)
        self.processes.append(process)
        return process


class UpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path != "/healthz":
            self.send_error(404)
            return
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.requests.append(payload)
        if not payload["stream"]:
            body = make_wav()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/pcm")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        chunk = b"\1\0" * 100
        self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii") + chunk + b"\r\n")
        if not self.server.incomplete:
            self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        if self.server.incomplete:
            self.close_connection = True

    def log_message(self, *_args):
        return


@pytest.fixture
def upstream_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    server.requests = []
    server.incomplete = False
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(2)


def runtime_config(tmp_path, port):
    server = tmp_path / "cosyvoice-server.exe"
    model = tmp_path / "model.gguf"
    prompt = tmp_path / "prompt.gguf"
    for path in (server, model, prompt):
        path.write_bytes(b"test")
    return CosyVoiceServerRuntimeConfig(
        server_path=server,
        model_path=model,
        prompt_speech_path=prompt,
        backend="cuda0",
        backend_path=tmp_path,
        internal_port=port,
        startup_timeout_seconds=1,
        synthesis_timeout_seconds=1,
        shutdown_timeout_seconds=0.1,
    )


def test_server_runtime_uses_loopback_and_reuses_pid_across_speed_changes(tmp_path, upstream_server):
    factory = FakeProcessFactory()
    runtime = CosyVoiceServerRuntime(
        runtime_config(tmp_path, upstream_server.server_port), process_factory=factory
    )
    try:
        runtime.start()
        pid = runtime.health()["pid"]
        wav = runtime.synthesize("完整请求", 1.0)
        with runtime.stream_pcm("流式请求", 1.25) as stream:
            pcm = b"".join(stream)
        health = runtime.health()
    finally:
        runtime.stop()

    assert wav == make_wav()
    assert pcm == b"\1\0" * 100
    assert len(factory.processes) == 1
    command = factory.processes[0].command
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == str(upstream_server.server_port)
    assert health["pid"] == pid
    assert health["restart_count"] == 0
    assert health["backend"] == "server"
    assert health["streaming"] is True
    assert [request["speed"] for request in upstream_server.requests] == [1.0, 1.25]
    assert factory.processes[0].terminated is True


def test_upstream_incomplete_response_is_an_explicit_failure(tmp_path, upstream_server):
    upstream_server.incomplete = True
    runtime = CosyVoiceServerRuntime(
        runtime_config(tmp_path, upstream_server.server_port), process_factory=FakeProcessFactory()
    )
    try:
        with runtime.stream_pcm("失败", 1.0) as stream:
            with pytest.raises(RuntimeSynthesisError, match="incomplete PCM"):
                b"".join(stream)
    finally:
        runtime.stop()


def test_closing_stream_releases_runtime_lease(tmp_path, upstream_server):
    runtime = CosyVoiceServerRuntime(
        runtime_config(tmp_path, upstream_server.server_port), process_factory=FakeProcessFactory()
    )
    try:
        stream = runtime.stream_pcm("取消", 1.0)
        stream.close()
        assert runtime.synthesize("后续", 1.0) == make_wav()
    finally:
        runtime.stop()


def test_process_exit_is_reported_by_health(tmp_path, upstream_server):
    factory = FakeProcessFactory()
    runtime = CosyVoiceServerRuntime(
        runtime_config(tmp_path, upstream_server.server_port), process_factory=factory
    )
    runtime.start()
    factory.processes[0].alive = False
    factory.processes[0].exit_code = 7

    health = runtime.health()

    assert health["available"] is False
    assert health["state"] == "failed"
    assert health["pid"] is None
    assert "code 7" in health["last_error"]


def test_startup_timeout_terminates_child(tmp_path):
    factory = FakeProcessFactory()
    config = runtime_config(tmp_path, 9)
    config = CosyVoiceServerRuntimeConfig(
        **{**config.__dict__, "startup_timeout_seconds": 0.1}
    )
    runtime = CosyVoiceServerRuntime(config, process_factory=factory)

    with pytest.raises(RuntimeTimedOut, match="startup timed out"):
        runtime.start()

    assert factory.processes[0].terminated is True
    assert runtime.health()["available"] is False


def test_shutdown_uses_kill_fallback_for_stubborn_child(tmp_path, upstream_server):
    factory = StubbornProcessFactory()
    runtime = CosyVoiceServerRuntime(
        runtime_config(tmp_path, upstream_server.server_port), process_factory=factory
    )
    runtime.start()

    runtime.stop()

    assert factory.processes[0].terminated is True
    assert factory.processes[0].killed is True
    assert runtime.health()["state"] == "stopped"

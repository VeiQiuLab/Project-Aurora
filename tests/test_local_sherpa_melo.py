import io
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import contextmanager

from modules.experience.voice.providers.local_sherpa_melo import LocalSherpaMeloProvider
from modules.experience.voice.models import VoiceOptions


def pcm():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(44100)
        audio.writeframes(b"\x01\x00" * 441)
    return output.getvalue()


@contextmanager
def broker(delay=0, content=None):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            import json
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, payload, self.headers.get("Authorization")))
            data = b"{}" if self.path == "/cancel" else pcm() if content is None else content
            if self.path == "/synthesize": time.sleep(delay)
            self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers()
            try: self.wfile.write(data)
            except OSError: pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f"http://127.0.0.1:{server.server_port}", calls
    finally: server.shutdown(); server.server_close(); thread.join()


def provider(endpoint):
    result = LocalSherpaMeloProvider(endpoint, "a" * 64)
    result.bind("generation-1", 2)
    return result


def test_artifact_and_existing_identity_contract():
    with broker() as (endpoint, calls):
        result = provider(endpoint).synthesize("你好", VoiceOptions(voice="old-edge-voice"))
        assert result.diagnostics["success"] is True
        assert result.audio_bytes == pcm() and result.audio_path is None
        assert calls[0][1]["generation_id"] == "generation-1" and calls[0][1]["revision"] == 2
        assert calls[0][1]["speaker"] == "melo-fixed-0"
        assert calls[0][2] == "Bearer " + "a" * 64


def test_cancel_returns_before_inference_and_sends_matching_identity():
    with broker(delay=.8) as (endpoint, calls):
        cancel = threading.Event()
        timer = threading.Timer(.05, cancel.set); timer.start()
        start = time.monotonic()
        result = provider(endpoint).synthesize("你好", cancel_event=cancel)
        assert time.monotonic() - start < .4
        assert result.diagnostics["reason"] == "cancelled" and result.audio_bytes is None
        assert calls[-1][:2] == ("/cancel", {"generation_id": "generation-1", "revision": 2})
        timer.join()


def test_timeout_discards_completion_and_invalid_wav_is_rejected():
    with broker(delay=.3) as (endpoint, calls):
        result = provider(endpoint).synthesize("你好", timeout_seconds=.05)
        assert result.diagnostics["reason"] == "timeout"
        assert calls[-1][0] == "/cancel"
    with broker(content=b"not a WAV") as (endpoint, _):
        assert provider(endpoint).synthesize("你好").diagnostics["success"] is False


def test_missing_runtime_has_no_edge_or_remote_fallback():
    result = provider("").synthesize("你好")
    assert result.diagnostics["reason"] == "connection_failed"
    assert result.audio_bytes is None
    assert provider("http://0.0.0.0:1234").synthesize("你好").diagnostics["success"] is False


def test_settings_keep_edge_default_and_accept_local(tmp_path):
    import json
    from modules.settings_service import SettingsService
    path = tmp_path / "settings.json"
    owner = SettingsService(path)
    assert owner.snapshot().get("voice.tts.provider") == "edge_tts"
    owner.apply_patch({"voice.tts.provider": "edge_tts"}, owner.revision)
    reloaded = SettingsService(path)
    assert reloaded.snapshot().get("voice.tts.provider") == "edge_tts"
    reloaded.apply_patch({"voice.tts.provider": "local_sherpa_melo"}, reloaded.revision)
    assert json.loads(path.read_text())["voice"]["tts"]["provider"] == "local_sherpa_melo"


def test_local_provider_voice_status_is_valid_in_published_json_schema():
    import json
    from pathlib import Path
    from jsonschema import Draft202012Validator
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "prototype/aurora-v4/contracts/ipc-v1.schema.json").read_text(encoding="utf-8"))
    message = dict(protocol="aurora-ipc", version=1, type="voice.changed", payload=dict(
        revision=1, state="preparing", enabled=True, provider="local_sherpa_melo",
        generation_id="g1", error_code=""))
    Draft202012Validator(schema).validate(message)

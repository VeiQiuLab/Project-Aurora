"""Guard the opt-in benchmark input bridge; no model/GPU is required."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import wave

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "voice_feasibility_fixture",
    ROOT / "scripts/voice_feasibility_sidecar/production_sidecar/server.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def fixture_root():
    output = ROOT / "tests/output"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fixture-test-", dir=output) as directory:
        yield Path(directory)


def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x00" * 2400)
    return buffer.getvalue()


@pytest.mark.parametrize("bad", ["digest", "outside"])
def test_fixture_rejects_invalid_handoff(fixture_root, tmp_path, bad):
    path = (tmp_path if bad == "outside" else fixture_root) / "input.wav"
    data = wav_bytes()
    path.write_bytes(data)
    errors = []
    done = threading.Event()

    def execute():
        try:
            MODULE.CompletedWavFixture(fixture_root).synthesize(
                "测试", None, timeout_seconds=2, cancel_event=done)
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=execute)
    worker.start()
    try:
        request = wait_request(fixture_root)
        receipt = dict(request_id=request["request_id"], wav=str(path),
                       sha256="wrong" if bad == "digest" else hashlib.sha256(data).hexdigest())
        (fixture_root / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        worker.join(2)
        assert not worker.is_alive()
        assert isinstance(errors[0], ValueError)
    finally:
        done.set()
        worker.join(2)


def wait_request(root):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if (root / "request.json").is_file():
            return json.loads((root / "request.json").read_text(encoding="utf-8"))
        time.sleep(.005)
    raise AssertionError("No benchmark input request")


def test_fixture_is_request_local_and_returns_real_bytes(fixture_root):
    data = wav_bytes()
    path = fixture_root / "input.wav"
    path.write_bytes(data)
    done = threading.Event()
    results = []
    (fixture_root / "receipt.json").write_text(json.dumps({"request_id": "old"}), encoding="utf-8")
    worker = threading.Thread(target=lambda: results.append(
        MODULE.CompletedWavFixture(fixture_root).synthesize(
            "你好", None, timeout_seconds=2, cancel_event=done)))
    worker.start()
    try:
        request = wait_request(fixture_root)
        assert request["text"] == "你好"
        assert worker.is_alive()  # stale receipt was not consumed
        receipt = dict(request_id=request["request_id"], wav=str(path),
                       sha256=hashlib.sha256(data).hexdigest())
        temporary = fixture_root / "receipt.tmp"
        temporary.write_text(json.dumps(receipt), encoding="utf-8")
        temporary.replace(fixture_root / "receipt.json")
        worker.join(2)
        assert not worker.is_alive()
        assert results[0].audio_bytes == data
        assert results[0].duration_ms == 100
        assert results[0].diagnostics["benchmark_wav_fixture"] is True
    finally:
        done.set()
        worker.join(2)


def test_fixture_cancel_and_deadline(fixture_root):
    fixture = MODULE.CompletedWavFixture(fixture_root)
    cancelled = threading.Event()
    cancelled.set()
    assert fixture.synthesize("测试", None, timeout_seconds=1,
                              cancel_event=cancelled).diagnostics["reason"] == "cancelled"
    with pytest.raises(TimeoutError):
        fixture.synthesize("测试", None, timeout_seconds=.01,
                           cancel_event=threading.Event())


def test_fixture_never_uses_user_data(tmp_path):
    with pytest.raises(ValueError, match="tests/output"):
        MODULE.CompletedWavFixture(tmp_path)


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows extended drive prefix")
def test_fixture_extended_windows_path_has_same_identity(fixture_root):
    assert MODULE.canonical("\\\\?\\" + str(fixture_root)) == fixture_root
    assert MODULE.CompletedWavFixture("\\\\?\\" + str(fixture_root)).root == fixture_root

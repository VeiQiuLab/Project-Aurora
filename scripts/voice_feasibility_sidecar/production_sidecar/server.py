"""Opt-in benchmark DI only; not a Local provider or production sidecar.

The external offline probe synthesizes the actual completed assistant text.
Only a request-matched WAV is supplied through VoiceExecution's existing test
factory. Existing production orchestration, private IPC and Rust Audio remain
unchanged. No runtime/model management is implemented here.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
import uuid
import wave


def canonical(path):
    value = str(Path(path).resolve(strict=True))
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


ROOT = canonical(__file__).parents[3]


class CompletedWavFixture:
    def __init__(self, root):
        self.root = canonical(root)
        if not self.root.is_relative_to(ROOT / "tests" / "output"):
            raise ValueError("Fixture evidence must stay in tests/output")

    def synthesize(self, text, _options, *, timeout_seconds, cancel_event):
        from modules.experience.voice.models import SpeechResult

        request_id = uuid.uuid4().hex
        request = dict(request_id=request_id, text=text,
                       requested_monotonic=time.monotonic())
        temporary = self.root / "request.tmp"
        temporary.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.root / "request.json")
        deadline = time.monotonic() + timeout_seconds
        while not cancel_event.wait(.02):
            if time.monotonic() >= deadline:
                raise TimeoutError("Benchmark input deadline")
            receipt_path = self.root / "receipt.json"
            if not receipt_path.is_file():
                continue
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("request_id") != request_id:
                continue
            path = canonical(receipt["wav"])
            if not path.is_relative_to(self.root.parent):
                raise ValueError("WAV outside benchmark output")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != receipt["sha256"]:
                raise ValueError("WAV digest mismatch")
            with wave.open(io.BytesIO(data)) as audio:
                if (audio.getcomptype() != "NONE" or audio.getsampwidth() != 2
                        or audio.getnframes() <= 0):
                    raise ValueError("Invalid benchmark PCM16")
                duration_ms = round(audio.getnframes() / audio.getframerate() * 1000)
            return SpeechResult(audio_bytes=data, duration_ms=duration_ms,
                                diagnostics={"success": True,
                                             "benchmark_wav_fixture": True})
        return SpeechResult(diagnostics={"success": False, "reason": "cancelled"})


def main():
    root = canonical(os.environ["AURORA_BENCH_HANDOFF"])
    CompletedWavFixture(root)  # fail before readiness, not after expensive measurements
    sys.path.insert(0, str(ROOT / "prototype/aurora-v4/sidecar"))
    from production_sidecar.voice import VoiceExecution
    original = VoiceExecution.__init__

    def fixture_factory(*_):
        try:
            return CompletedWavFixture(root)
        except Exception as error:
            print("BENCH_FIXTURE_ERROR " + type(error).__name__ + ": " + str(error), file=sys.stderr, flush=True)
            raise

    def benchmark_init(self, *args, **kwargs):
        kwargs["router_factory"] = fixture_factory
        original(self, *args, **kwargs)

    VoiceExecution.__init__ = benchmark_init
    print("BENCH_COMPLETED_WAV_FIXTURE enabled", file=sys.stderr, flush=True)
    if os.environ.get("AURORA_BENCH_STRICT") == "true":
        # Controlled residency experiment only: no post-turn title inference.
        # The production-semantics playback experiment MUST leave this off.
        from production_sidecar.post_turn import PostTurnCoordinator
        PostTurnCoordinator.schedule = lambda *_args, **_kwargs: False
        print("BENCH_STRICT post_turn_disabled_for_measurement", file=sys.stderr, flush=True)
    from production_sidecar.server import main as production_main
    return production_main()


if __name__ == "__main__":
    raise SystemExit(main())

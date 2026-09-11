"""Exercise Remote CosyVoice streaming through the real orchestration boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import sleep


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.experience.audio import FakePlayback, FakeRecorder
from modules.experience.voice.fake import FakeSpeechToTextProvider
from modules.experience.voice.integration import create_voice_runtime
from modules.experience.voice.models import AudioInput, TranscriptionResult


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Remote CosyVoice streaming through VoiceOrchestrator."
    )
    parser.add_argument("--url", required=True, help="Aurora Voice Node base URL")
    parser.add_argument("--text", required=True, help="Complete UTF-8 text to speak")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--prebuffer-ms", type=float, default=250.0)
    parser.add_argument("--max-buffer-ms", type=float, default=2000.0)
    parser.add_argument("--device")
    parser.add_argument("--request-timeout", type=float, default=120.0)
    parser.add_argument("--playback-timeout", type=float, default=300.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repeat < 1:
        raise SystemExit("--repeat must be at least 1")
    device = _parse_device(args.device)
    settings = {
        "voice": {
            "enabled": True,
            "tts": {
                "provider": "remote_cosyvoice",
                "timeout_seconds": args.request_timeout,
                "streaming_enabled": True,
                "remote_cosyvoice": {"url": args.url},
            },
            "playback": {
                "backend": "pygame",
                "wait_for_completion": True,
                "timeout_seconds": args.playback_timeout,
                "streaming": {
                    "prebuffer_ms": args.prebuffer_ms,
                    "max_buffer_ms": args.max_buffer_ms,
                    "device": device,
                },
            },
        }
    }
    runtime = create_voice_runtime(
        settings,
        recorder=FakeRecorder(AudioInput(kind="bytes", data=b"orchestrator-smoke")),
        stt_provider=FakeSpeechToTextProvider(TranscriptionResult(text="smoke")),
        text_input_handler=lambda _text: args.text,
        playback=FakePlayback(auto_complete=True),
    )
    assert runtime is not None
    results = []
    exit_code = 0
    runtime_closed = False
    try:
        for index in range(args.repeat):
            if not runtime.start_voice_session():
                raise RuntimeError("VoiceOrchestrator rejected a new active session")
            try:
                while runtime.session_running:
                    sleep(0.05)
            except KeyboardInterrupt:
                runtime.cancel_voice_session()
            result = runtime.wait_for_session(10.0)
            if result is None:
                raise TimeoutError("VoiceOrchestrator did not return a terminal result")
            results.append(
                {
                    "request": index + 1,
                    "success": result.success,
                    "cancelled": result.cancelled,
                    "stage": result.stage,
                    "diagnostics": result.diagnostics,
                }
            )
            if result.cancelled:
                exit_code = 130
                break
            if not result.success:
                exit_code = 1
                break
    finally:
        runtime_closed = runtime.close()
    print(
        json.dumps(
            {
                "status": (
                    "cancelled"
                    if exit_code == 130
                    else "completed" if exit_code == 0 else "failed"
                ),
                "requests": results,
                "runtime_closed": runtime_closed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return exit_code


def _parse_device(value: str | None) -> object | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    try:
        return int(value)
    except ValueError:
        return value


if __name__ == "__main__":
    raise SystemExit(main())

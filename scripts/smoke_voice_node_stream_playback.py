"""Play Remote CosyVoice streaming PCM directly through the default output device."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import monotonic
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.experience.audio import StreamingPlaybackController
from modules.experience.voice.models import VoiceOptions
from modules.experience.voice.providers.remote_cosyvoice import RemoteCosyVoiceProvider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream Remote CosyVoice PCM into a sounddevice RawOutputStream."
    )
    parser.add_argument("--url", required=True, help="Aurora Voice Node base URL")
    parser.add_argument("--text", required=True, help="UTF-8 text to synthesize and play")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--prebuffer-ms", type=float, default=250.0)
    parser.add_argument("--max-buffer-ms", type=float, default=2000.0)
    parser.add_argument(
        "--device",
        help="Optional sounddevice output device index or name; defaults to system output",
    )
    parser.add_argument("--request-timeout", type=float, default=120.0)
    parser.add_argument("--playback-timeout", type=float, default=300.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base_url = args.url.rstrip("/")
    request_started_wall = datetime.now(timezone.utc).astimezone().isoformat()
    request_started = monotonic()
    health_before: dict[str, object] = {}
    speech = None
    session = None
    try:
        health_before = _health(base_url)
        provider = RemoteCosyVoiceProvider(
            base_url,
            default_timeout_seconds=args.request_timeout,
        )
        speech = provider.synthesize_stream(
            args.text,
            VoiceOptions(rate=args.speed),
            timeout_seconds=args.request_timeout,
        )
        metadata_received = monotonic()
        if speech.diagnostics.get("success") is not True or not speech.metadata:
            print(
                json.dumps(
                    {
                        "status": "provider_failed",
                        "request_started_at": request_started_wall,
                        "provider_diagnostics": speech.diagnostics,
                        "health_before": health_before,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1

        controller = StreamingPlaybackController(
            prebuffer_ms=args.prebuffer_ms,
            max_buffer_ms=args.max_buffer_ms,
            device=_parse_device(args.device),
        )
        session = controller.play(
            speech,
            request_start_monotonic=request_started,
            provider_metadata_monotonic=metadata_received,
        )
        report = session.wait(args.playback_timeout)
    except KeyboardInterrupt:
        cancel_started = monotonic()
        if session is not None:
            session.cancel()
            session.close()
            try:
                report = session.wait(5.0)
                metrics = dict(report.diagnostics.get("metrics", {}))
                status = report.status
            except TimeoutError:
                metrics = dict(session.diagnostics_snapshot().get("metrics", {}))
                status = "cancel_incomplete"
            alive = set(session.threads_alive())
            cancel_output = {
                "status": status,
                "cancel_requested_monotonic": metrics.get(
                    "cancel_requested_monotonic"
                ),
                "cancel_completed_monotonic": metrics.get(
                    "cancel_completed_monotonic"
                ),
                "cancel_latency_ms": metrics.get("cancel_latency_ms"),
                "handler_latency_ms": round(
                    (monotonic() - cancel_started) * 1000.0, 3
                ),
                "producer_thread_alive": "aurora-streaming-pcm-producer" in alive,
                "playback_thread_alive": "aurora-streaming-playback-manager" in alive,
                "provider_closed": session.provider_closed,
                "audio_stream_stopped": session.audio_stream_stopped,
                "session_metrics": metrics,
            }
        else:
            if speech is not None:
                speech.cancel()
            cancel_output = {
                "status": "cancelled",
                "cancel_requested_monotonic": cancel_started,
                "cancel_completed_monotonic": monotonic(),
                "cancel_latency_ms": round((monotonic() - cancel_started) * 1000.0, 3),
                "producer_thread_alive": False,
                "playback_thread_alive": False,
                "provider_closed": speech is not None,
                "audio_stream_stopped": True,
            }
        print(json.dumps(cancel_output, ensure_ascii=False, indent=2))
        return 130
    except Exception as error:
        if session is not None:
            session.cancel()
        elif speech is not None:
            speech.cancel()
        print(f"Streaming playback failed: {error}", file=sys.stderr)
        return 1
    finally:
        if session is not None:
            session.close()
        elif speech is not None:
            speech.close()

    health_after = _health(base_url)
    metrics = dict(report.diagnostics.get("metrics", {}))
    output = {
        "status": report.status,
        "request_started_at": request_started_wall,
        "metadata": dict(speech.metadata),
        "timings_ms": {
            "provider_metadata": _elapsed_ms(
                request_started, metrics.get("provider_metadata_monotonic")
            ),
            "first_pcm": _elapsed_ms(
                request_started, metrics.get("first_pcm_received_monotonic")
            ),
            "playback_start": _elapsed_ms(
                request_started, metrics.get("playback_start_monotonic")
            ),
            "first_audio_submission": metrics.get(
                "request_to_first_audio_submission_ms"
            ),
            "upstream_end": _elapsed_ms(
                request_started, metrics.get("upstream_end_monotonic")
            ),
            "playback_end": _elapsed_ms(
                request_started, metrics.get("playback_end_monotonic")
            ),
        },
        "audio_duration_ms": metrics.get("audio_duration_ms"),
        "wall_duration_ms": metrics.get("wall_duration_ms"),
        "received_pcm_bytes": metrics.get("received_pcm_bytes"),
        "played_pcm_bytes": metrics.get("played_pcm_bytes"),
        "prebuffer_ms": metrics.get("prebuffer_ms"),
        "max_buffer_ms": metrics.get("max_buffer_ms"),
        "buffer_peak_bytes": metrics.get("buffer_peak_bytes"),
        "buffer_low_watermark": metrics.get("buffer_low_watermark"),
        "underrun_count": metrics.get("underrun_count"),
        "underrun_frames": metrics.get("underrun_frames"),
        "device_underflow_count": metrics.get("device_underflow_count"),
        "producer_error": metrics.get("producer_error"),
        "playback_error": metrics.get("playback_error"),
        "provider_diagnostics": speech.diagnostics,
        "health_before": health_before,
        "health_after": health_after,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if report.success else 1


def _health(base_url: str) -> dict[str, object]:
    request = Request(f"{base_url}/health", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=5.0) as response:
            return json.loads(response.read(64 * 1024).decode("utf-8"))
    except Exception as error:
        return {"status": "unavailable", "error": f"{type(error).__name__}: {error}"}


def _parse_device(value: str | None) -> object | None:
    if value is None or not value.strip():
        return None
    stripped = value.strip()
    try:
        return int(stripped)
    except ValueError:
        return stripped


def _elapsed_ms(start: float, value: object) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return round((float(value) - start) * 1000.0, 3)


if __name__ == "__main__":
    raise SystemExit(main())

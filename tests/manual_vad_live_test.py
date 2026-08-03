"""Manual Sony INZONE H9 VAD calibration test.

This script intentionally exercises only the FFmpeg audio source and RMS VAD.
It does not enter the voice session, recorder, STT, or TTS pipeline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from threading import Event

# Direct script execution puts only ``tests`` on sys.path. Add the project
# root before importing project modules; ``python -m`` already does this.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.experience.audio.ffmpeg_source import FFmpegAudioFrameSource
from modules.experience.audio.frame_pipeline import AudioFrameBuffer
from modules.experience.audio.vad import RMSVADAdapter, VoiceActivityType


DEFAULT_FFMPEG = (
    "C:\\Users\\X\\AppData\\Local\\Microsoft\\WinGet\\Packages\\"
    "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\\"
    "ffmpeg-8.1.2-full_build\\bin\\ffmpeg.exe"
)
DEFAULT_DEVICE = (
    r"@device_cm_{33D9A762-90C8-11D0-BD43-00A0C911CE86}"
    r"\wave_{E882568F-106B-470C-8733-C4292EF55D58}"
)


def _trigger_type(metrics: dict[str, object], *, threshold: float, peak_threshold: float) -> str | None:
    rms = float(metrics.get("rms", 0.0))
    peak = float(metrics.get("peak_amplitude", 0.0))
    rms_triggered = rms >= threshold
    peak_triggered = peak >= peak_threshold
    if rms_triggered and peak_triggered:
        return "rms_and_peak"
    if rms_triggered:
        return "rms"
    if peak_triggered:
        return "peak"
    return None


def run(args: argparse.Namespace) -> dict[str, object]:
    buffer = AudioFrameBuffer(max_duration_ms=1500)
    source = FFmpegAudioFrameSource(
        device_name=args.device,
        buffer=buffer,
        sample_rate=args.sample_rate,
        channels=args.channels,
        frame_duration_ms=args.frame_duration_ms,
        ffmpeg_path=args.ffmpeg,
    )
    source_start_time = time.time()
    first_frame_time: float | None = None
    voice_started_time: float | None = None
    result: dict[str, object] = {
        "source_start_time": source_start_time,
        "first_frame_time": None,
        "voice_started_time": None,
        "elapsed_ms": None,
        "frames_checked": 0,
        "above_threshold_frames": 0,
        "max_rms": 0.0,
        "max_peak": 0.0,
        "trigger_type": None,
        "trigger_failure_reason": None,
        "threshold": args.threshold,
        "peak_threshold": args.peak_threshold,
        "minimum_active_frames": args.minimum_active_frames,
        "device": args.device,
        "ffmpeg": args.ffmpeg,
    }

    try:
        source.start()
        stabilization_started = time.monotonic()
        while first_frame_time is None and time.monotonic() - stabilization_started < args.stabilization_seconds:
            snapshot = buffer.snapshot()
            if snapshot:
                first_frame_time = snapshot[0].timestamp
                break
            time.sleep(0.02)

        remaining = args.stabilization_seconds - (time.monotonic() - stabilization_started)
        if remaining > 0:
            time.sleep(remaining)

        result["first_frame_time"] = first_frame_time
        print("请保持安静", flush=True)
        for count in range(5, 0, -1):
            print(count, flush=True)
            time.sleep(1)
        print("开始检测，请说话！", flush=True)

        reader = buffer.subscribe(pre_roll_ms=0)
        vad = RMSVADAdapter(
            reader,
            threshold=args.threshold,
            peak_threshold=args.peak_threshold,
            frame_duration_ms=args.frame_duration_ms,
            minimum_active_duration_ms=(
                args.minimum_active_frames * args.frame_duration_ms
            ),
        )
        print("VAD listening started", flush=True)
        print("Waiting for voice...", flush=True)
        event = vad.wait_for_voice(Event(), args.timeout_seconds)
        result["elapsed_ms"] = int((time.time() - source_start_time) * 1000)
        diagnostics = (
            event.diagnostics if event is not None else vad.last_wait_diagnostics
        )
        metrics = dict(diagnostics.get("metrics", {}))
        result.update(
            {
                "frames_checked": metrics.get("frames_checked", 0),
                "above_threshold_frames": metrics.get("above_threshold_frames", 0),
                "max_rms": metrics.get("max_rms", 0.0),
                "max_peak": metrics.get("max_peak", 0.0),
                "trigger_failure_reason": metrics.get("trigger_failure_reason"),
            }
        )
        if event is not None and event.event_type is VoiceActivityType.STARTED:
            voice_started_time = event.timestamp
            result["voice_started_time"] = voice_started_time
            result["trigger_type"] = _trigger_type(
                metrics,
                threshold=args.threshold,
                peak_threshold=args.peak_threshold,
            )
        elif not result["trigger_failure_reason"]:
            result["trigger_failure_reason"] = diagnostics.get("reason")
    except Exception as error:
        result["trigger_failure_reason"] = f"{type(error).__name__}: {error}"
    finally:
        source.stop()

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual Sony INZONE H9 RMS VAD validation")
    parser.add_argument("--ffmpeg", default=DEFAULT_FFMPEG)
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--frame-duration-ms", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=0.014)
    parser.add_argument("--peak-threshold", type=float, default=0.03)
    parser.add_argument("--minimum-active-frames", type=int, default=5)
    parser.add_argument("--stabilization-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not Path(args.ffmpeg).exists() and args.ffmpeg != "ffmpeg":
        raise SystemExit(f"FFmpeg not found: {args.ffmpeg}")
    print(json.dumps(run(args), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

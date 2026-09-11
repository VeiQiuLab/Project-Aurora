"""Measure Aurora framed PCM streaming and save each request as PCM16 WAV."""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aurora_voice_node.stream_protocol import CONTENT_TYPE, StreamFrameDecoder  # noqa: E402


def base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise argparse.ArgumentTypeError("URL must be an HTTP(S) base URL")
    return normalized


def get_health(url: str, timeout: float) -> dict[str, object]:
    with urlopen(url + "/health", timeout=min(timeout, 10.0)) as response:
        return json.loads(response.read().decode("utf-8"))


def output_path(base: Path, index: int, count: int) -> Path:
    if count == 1:
        return base
    return base.with_name(f"{base.stem}-{index}{base.suffix or '.wav'}")


def run_stream(url: str, text: str, speed: float, timeout: float, output: Path) -> dict[str, object]:
    request = Request(
        url + "/tts/stream",
        data=json.dumps({"text": text, "speed": speed}, ensure_ascii=False).encode("utf-8"),
        headers={"Accept": CONTENT_TYPE, "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    decoder = StreamFrameDecoder()
    pcm = bytearray()
    metadata_at = None
    first_audio_at = None
    end_at = None
    frame_times: list[float] = []
    metadata: dict[str, object] | None = None
    end: dict[str, object] | None = None
    with urlopen(request, timeout=timeout) as response:
        headers_at = time.perf_counter()
        content_type = response.headers.get("Content-Type", "")
        if content_type != CONTENT_TYPE:
            raise RuntimeError(f"unexpected Content-Type: {content_type}")
        while end_at is None:
            reader = getattr(response, "read1", None)
            data = reader(8192) if callable(reader) else response.read(8192)
            if not data:
                decoder.finish()
                break
            for frame in decoder.feed(data):
                now = time.perf_counter()
                if frame.frame_type == "M":
                    metadata_at = now
                    metadata = frame.data
                elif frame.frame_type == "A":
                    if first_audio_at is None:
                        first_audio_at = now
                    frame_times.append(now)
                    pcm.extend(frame.payload)
                elif frame.frame_type == "X":
                    raise RuntimeError(
                        f"stream error {frame.data.get('code')}: {frame.data.get('message')}"
                    )
                elif frame.frame_type == "E":
                    end_at = now
                    end = frame.data
                    break
    if metadata is None or first_audio_at is None or end_at is None or end is None:
        raise RuntimeError("stream did not provide metadata, audio, and normal END")
    decoder.finish()
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(int(metadata["channels"]))
        wav.setsampwidth(int(metadata["bits_per_sample"]) // 8)
        wav.setframerate(int(metadata["sample_rate"]))
        wav.writeframes(pcm)
    intervals = [later - earlier for earlier, later in zip(frame_times, frame_times[1:])]
    sample_rate = int(metadata["sample_rate"])
    channels = int(metadata["channels"])
    total_samples = len(pcm) // (channels * 2)
    return {
        "speed": speed,
        "request_started_at": started_at,
        "response_headers_ms": round((headers_at - started) * 1000, 3),
        "metadata_ms": round((metadata_at - started) * 1000, 3),
        "first_audio_ms": round((first_audio_at - started) * 1000, 3),
        "end_ms": round((end_at - started) * 1000, 3),
        "pcm_bytes": len(pcm),
        "total_samples": total_samples,
        "audio_duration_seconds": round(total_samples / sample_rate, 3),
        "audio_frames": len(frame_times),
        "max_frame_interval_ms": round(max(intervals, default=0.0) * 1000, 3),
        "sample_rate": sample_rate,
        "channels": channels,
        "end": end,
        "output": str(output.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Aurora Voice Node PCM streaming")
    parser.add_argument("--url", type=base_url, required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--second-speed", type=float)
    parser.add_argument("--requests", type=int, choices=(1, 2), default=2)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    health_before = get_health(args.url, args.timeout)
    runtime_before = health_before.get("runtime", {})
    if not isinstance(runtime_before, dict) or runtime_before.get("available") is not True:
        raise SystemExit(f"Voice Node runtime is unavailable: {health_before}")
    if runtime_before.get("streaming") is not True:
        raise SystemExit(f"Voice Node runtime does not advertise streaming: {health_before}")
    speeds = [args.speed]
    if args.requests == 2:
        speeds.append(args.second_speed if args.second_speed is not None else args.speed)
    results = []
    for index, speed in enumerate(speeds, start=1):
        results.append(
            run_stream(
                args.url,
                args.text,
                speed,
                args.timeout,
                output_path(args.output, index, len(speeds)),
            )
        )
    health_after = get_health(args.url, args.timeout)
    runtime_after = health_after.get("runtime", {})
    pids = [runtime_before.get("pid"), runtime_after.get("pid")]
    if pids[0] is None or pids[0] != pids[1]:
        raise SystemExit(f"cosyvoice-server PID changed during smoke test: {pids}")
    print(
        json.dumps(
            {
                "runtime_pid": pids[0],
                "restart_count_before": runtime_before.get("restart_count"),
                "restart_count_after": runtime_after.get("restart_count"),
                "requests": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

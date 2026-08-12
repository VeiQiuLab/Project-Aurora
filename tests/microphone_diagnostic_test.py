"""Diagnose the real microphone before running STT or the Voice Runtime.

Run with a working Windows CPython 3.12 interpreter:
    <python-3.12> tests\\microphone_diagnostic_test.py

The script records five seconds of int16 mono audio and writes:
    tests/output/microphone_test.wav
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path
from threading import Event, Lock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "tests" / "output" / "microphone_test.wav"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aurora real microphone diagnostic")
    parser.add_argument("--device-index", type=int, default=None)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument(
        "--energy-threshold",
        type=float,
        default=0.001,
        help="Normalized average absolute amplitude required to continue to STT.",
    )
    return parser


def _device_name(device: dict) -> str:
    return str(device.get("name", "<unknown>"))


def _flatten_int16(frames: list[object]) -> bytes:
    return b"".join(frame.tobytes() for frame in frames)


def _energy_stats(raw_audio: bytes) -> tuple[float, float, float]:
    if not raw_audio:
        return 0.0, 0.0, 0.0
    samples = memoryview(raw_audio).cast("h")
    if not samples:
        return 0.0, 0.0, 0.0
    normalized = [abs(sample) / 32768.0 for sample in samples]
    return min(normalized), max(normalized), sum(normalized) / len(normalized)


def run(args: argparse.Namespace) -> int:
    try:
        import sounddevice as sd
    except ImportError as error:
        print(f"FAILED: sounddevice unavailable: {error}")
        return 2

    if args.sample_rate <= 0 or args.channels <= 0 or args.duration <= 0:
        print("FAILED: sample rate, channels, and duration must be positive")
        return 2

    try:
        device_index = args.device_index
        if device_index is None:
            default_device = sd.default.device
            device_index = int(default_device[0]) if isinstance(default_device, (list, tuple)) else int(default_device)
        device = sd.query_devices(device_index)
    except Exception as error:
        print(f"FAILED: input device lookup: {error}")
        return 3

    max_input_channels = int(device.get("max_input_channels", 0))
    if max_input_channels < args.channels:
        print(
            "FAILED: input device does not provide enough channels "
            f"(requested={args.channels}, available={max_input_channels})"
        )
        return 3

    print(f"device_index: {device_index}")
    print(f"device_name: {_device_name(device)}")
    print(f"sample_rate: {args.sample_rate}")
    print(f"channels: {args.channels}")
    print("format: int16 PCM")
    print(f"device_default_sample_rate: {device.get('default_samplerate', 'unknown')}")
    print(f"device_max_input_channels: {max_input_channels}")
    print("Speak now...")

    frames: list[object] = []
    frames_lock = Lock()
    callback_error: list[str] = []
    finished = Event()

    def callback(indata, frame_count, _time_info, status) -> None:
        if status:
            callback_error.append(str(status))
        with frames_lock:
            frames.append(indata.copy())
        if frame_count <= 0:
            finished.set()

    try:
        with sd.InputStream(
            device=device_index,
            samplerate=args.sample_rate,
            channels=args.channels,
            dtype="int16",
            callback=callback,
        ):
            print("device opened")
            print("recording_started")
            time.sleep(args.duration)
            print("recording_finished")
    except Exception as error:
        print(f"FAILED: audio stream could not be opened or recorded: {error}")
        return 4

    with frames_lock:
        captured_frames = list(frames)
    raw_audio = _flatten_int16(captured_frames)
    frame_count = sum(len(frame) for frame in captured_frames)
    duration_seconds = frame_count / args.sample_rate if args.sample_rate else 0.0
    min_volume, max_volume, average_volume = _energy_stats(raw_audio)

    print(f"frames: {frame_count}")
    print(f"duration_seconds: {duration_seconds:.3f}")
    print(f"min_volume: {min_volume:.6f}")
    print(f"max_volume: {max_volume:.6f}")
    print(f"average_volume: {average_volume:.6f}")
    if callback_error:
        print(f"stream_status: {'; '.join(callback_error)}")

    output_path = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(args.channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(args.sample_rate)
            wav_file.writeframes(raw_audio)
    except Exception as error:
        print(f"FAILED: WAV save: {error}")
        return 5

    print(f"wav_saved: {output_path}")
    if not raw_audio or max_volume <= 0.0 or average_volume < args.energy_threshold:
        print("No voice signal detected")
        print("STT not started")
        return 6

    print("voice energy detected")
    print("microphone diagnostic: PASS")
    print("STT may be started as the next isolated test")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))

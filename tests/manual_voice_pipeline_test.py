"""Manual end-to-end voice pipeline validation for Sony INZONE H9.

This script is intentionally standalone. It coordinates the existing runtime
boundaries without changing VoiceOrchestrator, VoiceSession, or UI code.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from threading import Event
import wave

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.experience.audio.ffmpeg_source import FFmpegAudioFrameSource
from modules.experience.audio.frame_pipeline import AudioFrameBuffer
from modules.experience.audio.frame_recorder import FrameRecorder
from modules.experience.audio.playback import PlaybackEvent, PlaybackEventType
from modules.experience.audio.real_playback import RealPlaybackController
from modules.experience.audio.vad import RMSVADAdapter, VoiceActivityType
from modules.experience.state import CompanionState, CompanionStateStore
from modules.experience.voice.models import VoiceOptions
from modules.experience.voice.providers.edge_tts import EdgeTTSProvider
from modules.experience.voice.providers.faster_whisper import FasterWhisperProvider


DEFAULT_FFMPEG = (
    "C:\\Users\\X\\AppData\\Local\\Microsoft\\WinGet\\Packages\\"
    "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\\"
    "ffmpeg-8.1.2-full_build\\bin\\ffmpeg.exe"
)
DEFAULT_DEVICE = (
    r"@device_cm_{33D9A762-90C8-11D0-BD43-00A0C911CE86}"
    r"\wave_{E882568F-106B-470C-8733-C4292EF55D58}"
)
DEFAULT_RESPONSE = "你好，我是 Aurora，很高兴和你进行这次语音测试。"


def _transition(store: CompanionStateStore, state: CompanionState, reason: str) -> None:
    result = store.transition(state, reason=reason, source="manual_voice_pipeline_test")
    if not result.success:
        raise RuntimeError(f"state transition failed: {result.diagnostics}")


def _wav_info(path: str) -> dict[str, object]:
    audio_path = Path(path)
    with wave.open(str(audio_path), "rb") as wav_file:
        frames = wav_file.getnframes()
        rate = wav_file.getframerate()
        return {
            "path": str(audio_path),
            "bytes": audio_path.stat().st_size,
            "frames": frames,
            "sample_rate": rate,
            "channels": wav_file.getnchannels(),
            "duration_ms": int(frames / rate * 1000) if rate else 0,
        }


def run(args: argparse.Namespace) -> dict[str, object]:
    buffer = AudioFrameBuffer(max_duration_ms=1500)
    source = FFmpegAudioFrameSource(
        device_name=args.device,
        buffer=buffer,
        sample_rate=args.sample_rate,
        channels=1,
        frame_duration_ms=args.frame_duration_ms,
        ffmpeg_path=args.ffmpeg,
    )
    store = CompanionStateStore()
    playback = RealPlaybackController()
    playback_completed = Event()
    playback_events: list[str] = []
    playback_started_at: float | None = None
    playback_completed_at: float | None = None
    source_start_time = time.time()
    result: dict[str, object] = {
        "source_start_time": source_start_time,
        "vad_latency_ms": None,
        "recording_duration_ms": None,
        "wav": None,
        "stt_text": None,
        "stt_language": None,
        "stt_latency_ms": None,
        "tts_latency_ms": None,
        "playback_started": False,
        "playback_completed": False,
        "playback_events": playback_events,
        "final_state": None,
        "errors": [],
    }

    def on_playback_event(event: PlaybackEvent) -> None:
        nonlocal playback_started_at, playback_completed_at
        playback_events.append(event.event_type.value)
        if event.event_type is PlaybackEventType.STARTED:
            playback_started_at = event.timestamp
            result["playback_started"] = True
            print("Playback Started", flush=True)
        elif event.event_type is PlaybackEventType.COMPLETED:
            playback_completed_at = event.timestamp
            result["playback_completed"] = True
            playback_completed.set()
            print("Playback Completed", flush=True)
        elif event.event_type is PlaybackEventType.FAILED:
            result["errors"].append(event.error or "playback failed")
            playback_completed.set()
            print(f"Playback Failed: {event.error}", flush=True)

    playback.subscribe(on_playback_event)
    try:
        source.start()
        print("Audio source started", flush=True)
        time.sleep(args.stabilization_seconds)
        print("请保持安静", flush=True)
        for count in range(5, 0, -1):
            print(count, flush=True)
            time.sleep(1)
        print("开始检测，请说话！", flush=True)

        vad_reader = buffer.subscribe(pre_roll_ms=0)
        vad = RMSVADAdapter(
            vad_reader,
            threshold=args.threshold,
            peak_threshold=args.peak_threshold,
            frame_duration_ms=args.frame_duration_ms,
            minimum_active_duration_ms=args.minimum_active_frames * args.frame_duration_ms,
        )
        _transition(store, CompanionState.LISTENING, "manual_vad_listening")
        print("VAD listening started", flush=True)
        print("Waiting for voice...", flush=True)
        vad_started = time.perf_counter()
        event = vad.wait_for_voice(Event(), args.vad_timeout_seconds)
        result["vad_latency_ms"] = int((time.perf_counter() - vad_started) * 1000)
        if event is None or event.event_type is not VoiceActivityType.STARTED:
            metrics = dict(vad.last_wait_diagnostics.get("metrics", {}))
            result["vad"] = metrics
            result["errors"].append(
                metrics.get("trigger_failure_reason", "VOICE_STARTED not detected")
            )
            return result

        result["vad"] = dict(event.diagnostics.get("metrics", {}))
        _transition(store, CompanionState.TRANSCRIBING, "manual_vad_started")

        recorder_reader = buffer.subscribe(pre_roll_ms=args.pre_roll_ms)
        recorder = FrameRecorder(
            recorder_reader,
            output_dir=args.output_dir,
            min_duration_ms=args.minimum_recording_ms,
            max_duration_ms=args.recording_seconds * 1000,
        )
        recorder.start()
        recording_started = time.perf_counter()
        time.sleep(args.recording_seconds)
        audio_input = recorder.stop()
        result["recording_duration_ms"] = int((time.perf_counter() - recording_started) * 1000)
        result["wav"] = _wav_info(audio_input.path)
        print(f"WAV: {audio_input.path} ({result['wav']['bytes']} bytes)", flush=True)

        stt = FasterWhisperProvider(
            model_size=args.model_size,
            device=args.stt_device,
            compute_type=args.compute_type,
            language="zh",
        )
        stt_started = time.perf_counter()
        transcription = stt.transcribe(audio_input)
        result["stt_latency_ms"] = int((time.perf_counter() - stt_started) * 1000)
        result["stt_text"] = transcription.text
        result["stt_language"] = transcription.language
        print(f"STT result: {transcription.text}", flush=True)
        if not transcription.diagnostics.get("success", True):
            result["errors"].append(dict(transcription.diagnostics))
            return result

        _transition(store, CompanionState.THINKING, "manual_text_input_started")

        def text_input_handler(text: str) -> str:
            print(f"text_input_handler received: {text}", flush=True)
            return args.response

        response_text = text_input_handler(transcription.text)
        result["response_text"] = response_text
        _transition(store, CompanionState.SPEAKING, "manual_tts_started")
        tts = EdgeTTSProvider(default_voice=args.voice)
        tts_started = time.perf_counter()
        speech = tts.synthesize(
            response_text,
            VoiceOptions(voice=args.voice, language="zh_CN"),
        )
        result["tts_latency_ms"] = int((time.perf_counter() - tts_started) * 1000)
        result["tts"] = {
            "audio_path": speech.audio_path,
            "mime_type": speech.mime_type,
            "diagnostics": dict(speech.diagnostics),
        }
        if not speech.diagnostics.get("success", True) or not speech.audio_path:
            result["errors"].append(dict(speech.diagnostics))
            return result

        playback.play(speech)
        if not playback_completed.wait(args.playback_timeout_seconds):
            result["errors"].append("playback timeout")
        if playback_started_at is not None and playback_completed_at is not None:
            result["playback_latency_ms"] = int(
                (playback_completed_at - playback_started_at) * 1000
            )
    except Exception as error:
        result["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        try:
            source.stop()
        finally:
            try:
                playback.shutdown()
            except Exception:
                pass
            store.force_idle(reason="manual_pipeline_finished", source="manual_voice_pipeline_test")
            result["final_state"] = store.current_state.value
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual Aurora real voice pipeline validation")
    parser.add_argument("--ffmpeg", default=DEFAULT_FFMPEG)
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--frame-duration-ms", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=0.014)
    parser.add_argument("--peak-threshold", type=float, default=0.03)
    parser.add_argument("--minimum-active-frames", type=int, default=5)
    parser.add_argument("--stabilization-seconds", type=float, default=5.0)
    parser.add_argument("--vad-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--pre-roll-ms", type=int, default=500)
    parser.add_argument("--recording-seconds", type=int, default=4)
    parser.add_argument("--minimum-recording-ms", type=int, default=750)
    parser.add_argument("--playback-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--model-size", default="tiny")
    parser.add_argument("--stt-device", default="auto")
    parser.add_argument("--compute-type", default="auto")
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    parser.add_argument("--response", default=DEFAULT_RESPONSE)
    parser.add_argument("--output-dir", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

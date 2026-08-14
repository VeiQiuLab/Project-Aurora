"""Repeatable real-device Voice Runtime harness.

This harness deliberately uses the real microphone, Faster-Whisper, Ollama
stream_chat, SentenceSplitter, TTSQueue, Edge-TTS, and pygame playback.
It does not replace production providers with test doubles.

Run with the system interpreter:
    C:\\Users\\X\\AppData\\Local\\Programs\\Python\\Python312\\python.exe tests\\real_voice_runtime_harness.py

Speak one request per round. The harness interrupts after playback starts and
immediately starts the next round. Use --record-seconds to control the time
available for each spoken request.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import threading
import time
from pathlib import Path
from threading import Event
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.chat import ChatSession, stream_chat
from modules.experience.audio.playback import PlaybackEvent, PlaybackEventType
from modules.experience.audio.recorder import MicrophoneRecorder
from modules.experience.audio.real_playback import RealPlaybackController
from modules.experience.state import CompanionStateStore
from modules.experience.voice.models import SpeechResult
from modules.experience.voice.orchestrator import VoiceOrchestrator
from modules.experience.voice.providers.edge_tts import EdgeTTSProvider
from modules.experience.voice.providers.faster_whisper import FasterWhisperProvider
from modules.logger import logger
from modules.settings import settings


class TimedMicrophoneRecorder:
    """Use the physical microphone for a fixed recording window."""

    def __init__(self, output_dir: Path, *, record_seconds: float, device=None):
        self._record_seconds = max(float(record_seconds), 0.5)
        self._recorder = MicrophoneRecorder(
            output_dir=output_dir,
            device=device,
            min_duration_ms=250,
        )

    def start(self) -> None:
        self._recorder.start()

    def stop(self):
        time.sleep(self._record_seconds)
        return self._recorder.stop()

    def cancel(self) -> None:
        self._recorder.cancel()


class VoiceLogCollector(logging.Handler):
    """Collect lifecycle records without changing the application logger."""

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.records: list[str] = []
        self.stale_discards = 0

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if "[VOICE]" in message:
            self.records.append(message)
        if "discard_stale" in message:
            self.stale_discards += 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aurora real Voice Runtime interrupt harness")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--record-seconds", type=float, default=4.0)
    parser.add_argument("--playback-wait-seconds", type=float, default=120.0)
    parser.add_argument("--interrupt-delay-seconds", type=float, default=0.15)
    parser.add_argument("--model", default=None)
    parser.add_argument("--stt-model-size", default=None)
    parser.add_argument("--stt-device", default=None)
    parser.add_argument("--compute-type", default=None)
    parser.add_argument("--voice", default=None)
    parser.add_argument("--device", default=None)
    parser.add_argument(
        "--instruction-suffix",
        default="请用较长的中文回答，分成多个完整句子。",
    )
    return parser


def run_round(
    index: int,
    args: argparse.Namespace,
    store: CompanionStateStore,
    playback: RealPlaybackController,
    output_dir: Path,
    collector: VoiceLogCollector,
) -> dict[str, object]:
    session_id = uuid4().hex
    generation_id = uuid4().hex
    cancel_event = Event()
    playback_started = Event()
    playback_events: list[str] = []
    state_transitions: list[dict[str, str]] = []
    started_at = time.monotonic()
    interrupt_at: float | None = None

    def on_state(event) -> None:
        state_transitions.append(
            {
                "from": event.previous_state.value,
                "to": event.current_state.value,
                "reason": event.reason,
            }
        )

    def on_playback(event: PlaybackEvent) -> None:
        playback_events.append(event.event_type.value)
        if event.event_type is PlaybackEventType.STARTED:
            playback_started.set()

    store.subscribe(on_state)
    playback.subscribe(on_playback)

    model = args.model or settings.get("chat_model", "")
    stt = FasterWhisperProvider(
        model_size=args.stt_model_size or settings.get("voice.stt.model_size", "small"),
        device=args.stt_device or settings.get("voice.stt.device", "auto"),
        compute_type=args.compute_type or settings.get("voice.stt.compute_type", "auto"),
    )
    tts = EdgeTTSProvider(
        default_voice=args.voice or settings.get("voice.tts.voice", "zh-CN-XiaoxiaoNeural")
    )
    recorder = TimedMicrophoneRecorder(
        output_dir=output_dir,
        record_seconds=args.record_seconds,
        device=args.device,
    )

    def stream_handler(prompt: str, *, on_chunk, cancel_event: Event) -> str:
        response_parts: list[str] = []
        session = ChatSession("You are Aurora, a helpful local AI companion.")
        request_prompt = f"{prompt}\n{args.instruction_suffix}"

        def handle_chunk(chunk: str) -> None:
            response_parts.append(chunk)
            on_chunk(chunk)

        stream_chat(model, request_prompt, session, handle_chunk, cancel_event)
        return "".join(response_parts).strip()

    orchestrator = VoiceOrchestrator(
        recorder=recorder,
        stt_provider=stt,
        tts_provider=tts,
        playback=playback,
        state_store=store,
        text_input_handler=lambda text: text,
        stream_text_input_handler=stream_handler,
        cancel_event=cancel_event,
        wait_for_playback_completion=True,
        playback_timeout_seconds=args.playback_wait_seconds,
    )
    orchestrator.set_generation_context(session_id, generation_id)

    result_holder: dict[str, object] = {}

    def run_pipeline() -> None:
        result_holder["result"] = orchestrator.run()

    thread = threading.Thread(target=run_pipeline, name=f"aurora-real-voice-{index}", daemon=True)
    thread.start()
    playback_started.wait(args.playback_wait_seconds)
    if playback_started.is_set():
        time.sleep(max(args.interrupt_delay_seconds, 0.0))
        interrupt_at = time.monotonic()
        orchestrator.cancel()
    else:
        orchestrator.cancel()
    thread.join(args.playback_wait_seconds)

    result = result_holder.get("result")
    elapsed = lambda value: None if value is None else int((value - started_at) * 1000)
    return {
        "round": index,
        "session_id": session_id,
        "generation_id": generation_id,
        "result": {
            "success": getattr(result, "success", False),
            "cancelled": getattr(result, "cancelled", False),
            "stage": getattr(result, "stage", "missing"),
        },
        "thread_alive_after_join": thread.is_alive(),
        "state_transitions": state_transitions,
        "interrupt_elapsed_ms": elapsed(interrupt_at),
        "playback_events": playback_events,
        "stale_discard_count_total": collector.stale_discards,
        "t0_t9": {
            "T0_start": 0,
            "T6_playback_start": "observed" if playback_started.is_set() else None,
            "T7_interrupt": elapsed(interrupt_at),
            "T9_thread_joined": not thread.is_alive(),
        },
    }


def main() -> int:
    args = build_parser().parse_args()
    if args.rounds < 1:
        raise SystemExit("--rounds must be positive")

    collector = VoiceLogCollector()
    logger.logger.addHandler(collector)
    store = CompanionStateStore()
    playback = RealPlaybackController()
    results: list[dict[str, object]] = []
    started_at = time.monotonic()

    print(f"system_python={sys.executable}", flush=True)
    print(f"ollama_model={args.model or settings.get('chat_model', '')}", flush=True)
    print("real_microphone=true real_stt=true real_ollama=true real_edge_tts=true real_pygame=true", flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix="aurora-real-voice-") as temp_dir:
            output_dir = Path(temp_dir)
            for index in range(1, args.rounds + 1):
                print(f"round={index}/{args.rounds} speak_now=true", flush=True)
                results.append(run_round(index, args, store, playback, output_dir, collector))
                print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    finally:
        playback.shutdown()
        logger.logger.removeHandler(collector)

    summary = {
        "rounds": len(results),
        "completed_rounds": sum(1 for item in results if item["result"]["cancelled"]),
        "playback_started_rounds": sum(
            1 for item in results if item["t0_t9"]["T6_playback_start"] == "observed"
        ),
        "thread_residue_rounds": sum(1 for item in results if item["thread_alive_after_join"]),
        "stale_discard_count": collector.stale_discards,
        "elapsed_seconds": round(time.monotonic() - started_at, 2),
        "final_state": store.current_state.value,
    }
    print("summary=" + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["thread_residue_rounds"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

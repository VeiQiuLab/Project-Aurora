"""Real Ollama-to-Remote-CosyVoice incremental speech smoke.

This script intentionally uses fake recorder/STT boundaries so the supplied
prompt is deterministic. Ollama, RemoteCosyVoiceProvider, the Voice Node, the
streaming playback controller, and the selected sound device are all real.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.chat import ChatSession, StreamingRequestHandle, stream_chat
from modules.experience.audio import FakePlayback, FakeRecorder
from modules.experience.voice.fake import FakeSpeechToTextProvider
from modules.experience.voice.integration import create_voice_runtime
from modules.experience.voice.models import AudioInput, TranscriptionResult
from modules.experience.voice.sentence_splitter import SentenceSplitter
from modules.settings import settings


DEFAULT_PROMPT = (
    "请用中文解释本地大模型如何把逐字生成的回答交给远程语音系统，"
    "要求写五个自然、完整、长度适中的句子，并使用正常中文标点。"
)
RECOVERY_PROMPT = "只回复：恢复成功。"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Aurora Voice Node base URL")
    parser.add_argument(
        "--model",
        default=str(
            settings.get("resolved_chat_model", "")
            or settings.get("chat_model", "")
            or "qwen3.5:9b"
        ).strip(),
        help="Installed Ollama model; defaults to Aurora's selected model.",
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--prebuffer-ms", type=float, default=250.0)
    parser.add_argument("--max-buffer-ms", type=float, default=2000.0)
    parser.add_argument("--device")
    parser.add_argument("--request-timeout", type=float, default=120.0)
    parser.add_argument("--playback-timeout", type=float, default=300.0)
    parser.add_argument(
        "--cancel-after-first-audio",
        action="store_true",
        help="Cancel N after its first audio submission, then run an N+1 recovery.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.model:
        raise SystemExit("No Ollama chat model selected; pass --model MODEL.")

    stt = FakeSpeechToTextProvider(TranscriptionResult(text=args.prompt))
    chat_session = ChatSession()
    segments: list[str] = []
    llm_runs: list[dict[str, object]] = []

    def stream_handler(prompt: str, *, on_chunk, cancel_event: Event) -> str:
        parts: list[str] = []
        preview_splitter = SentenceSplitter()
        diagnostics: dict[str, object] = {}
        handle = StreamingRequestHandle(cancel_event, diagnostics)
        llm_runs.append(diagnostics)

        def forward(chunk: str) -> None:
            parts.append(chunk)
            segments.extend(preview_splitter.feed(chunk))
            on_chunk(chunk)

        status = stream_chat(
            args.model,
            prompt,
            chat_session,
            forward,
            cancel_event,
            request_handle=handle,
        )
        if status != "completed" and not cancel_event.is_set():
            raise RuntimeError(f"Ollama streaming ended with status {status!r}")
        if status == "completed":
            segments.extend(preview_splitter.flush())
        else:
            preview_splitter.clear()
        return "".join(parts).strip()

    runtime = create_voice_runtime(
        _settings(args),
        recorder=FakeRecorder(AudioInput(kind="bytes", data=b"stage-b-smoke")),
        stt_provider=stt,
        text_input_handler=lambda text: text,
        stream_text_input_handler=stream_handler,
        playback=FakePlayback(auto_complete=True),
    )
    assert runtime is not None
    reports: list[dict[str, object]] = []
    exit_code = 0
    runtime_closed = False
    try:
        with patch("modules.memory.MemoryStore.queue_candidates", return_value=[]):
            first = _run_once(
                runtime,
                segments,
                cancel_after_first_audio=args.cancel_after_first_audio,
                timeout_seconds=args.playback_timeout,
            )
            reports.append(first)
            if args.cancel_after_first_audio:
                if first["status"] != "cancelled":
                    exit_code = 1
                else:
                    stt.result = TranscriptionResult(text=RECOVERY_PROMPT)
                    recovery = _run_once(
                        runtime,
                        segments,
                        cancel_after_first_audio=False,
                        timeout_seconds=args.playback_timeout,
                    )
                    recovery["recovery_response_ok"] = (
                        "恢复成功" in str(recovery.get("response_text", ""))
                    )
                    reports.append(recovery)
                    if (
                        recovery["status"] != "completed"
                        or not recovery["recovery_response_ok"]
                    ):
                        exit_code = 1
            elif not first.get("first_audio_before_llm_complete", False):
                exit_code = 1
    except KeyboardInterrupt:
        runtime.cancel_voice_session()
        result = runtime.wait_for_session(10.0)
        reports.append(
            {
                "status": "cancelled",
                "stage": getattr(result, "stage", "cancelled"),
                "source": "KeyboardInterrupt",
            }
        )
        exit_code = 130
    finally:
        runtime_closed = runtime.close()
    if not runtime_closed and exit_code == 0:
        exit_code = 1

    print(
        json.dumps(
            {
                "status": (
                    "cancelled"
                    if exit_code == 130
                    else "completed" if exit_code == 0 else "failed"
                ),
                "model": args.model,
                "voice_node_url": args.url,
                "requests": reports,
                "ollama_transport": llm_runs,
                "runtime_closed": runtime_closed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return exit_code


def _run_once(
    runtime,
    segments: list[str],
    *,
    cancel_after_first_audio: bool,
    timeout_seconds: float,
) -> dict[str, object]:
    segment_offset = len(segments)
    if not runtime.start_voice_session():
        raise RuntimeError("Voice Runtime rejected a new active session")
    cancel_requested = False
    deadline = monotonic() + max(float(timeout_seconds), 1.0)
    while runtime.session_running:
        if monotonic() >= deadline:
            runtime.cancel_voice_session()
            raise TimeoutError("Stage B smoke did not finish before the timeout")
        if cancel_after_first_audio and not cancel_requested:
            context = runtime.orchestrator._streaming_playback_context
            if context is not None:
                live = context[1].diagnostics_snapshot()
                metrics = live.get("metrics", {})
                if metrics.get("first_audio_submission_monotonic") is not None:
                    cancel_requested = runtime.cancel_voice_session()
                    continue
        sleep(0.02)

    result = runtime.wait_for_session(10.0)
    if result is None:
        raise TimeoutError("Voice Runtime returned no terminal result")
    metrics = dict(result.diagnostics.get("metrics", {}))
    trace = dict(result.diagnostics.get("trace", {}))
    timing = dict(trace.get("turn_timing", {}))
    segment_diagnostics = [dict(item) for item in trace.get("streaming_segments", [])]
    first_audio = timing.get("first_audio_submission_monotonic")
    llm_complete = timing.get("llm_complete_monotonic")
    lead_ms = (
        None
        if not isinstance(first_audio, (int, float))
        or not isinstance(llm_complete, (int, float))
        else round((llm_complete - first_audio) * 1000.0, 3)
    )
    return {
        "status": "cancelled" if result.cancelled else "completed" if result.success else "failed",
        "stage": result.stage,
        "session_id": runtime.orchestrator.session_id,
        "generation_id": runtime.orchestrator.generation_id,
        "response_text": result.response_text,
        "segments": [
            {"segment_index": index, "preview": text[:80]}
            for index, text in enumerate(segments[segment_offset:])
        ],
        "streaming_provider": metrics.get("tts_provider"),
        "first_llm_chunk_monotonic": timing.get("first_llm_chunk_monotonic"),
        "first_segment_emit_monotonic": timing.get("first_sentence_emit_monotonic"),
        "first_tts_start_monotonic": timing.get("first_tts_start_monotonic"),
        "first_pcm_received_monotonic": timing.get("first_pcm_received_monotonic"),
        "first_audio_submission_monotonic": first_audio,
        "llm_complete_monotonic": llm_complete,
        "final_segment_emit_monotonic": timing.get("final_segment_emit_monotonic"),
        "final_playback_end_monotonic": timing.get("final_playback_end_monotonic"),
        "first_audio_before_llm_complete": metrics.get(
            "first_audio_before_llm_complete"
        ),
        "llm_complete_minus_first_audio_ms": lead_ms,
        "per_segment": segment_diagnostics,
        "speech_lifecycle": trace.get("speech_segments", []),
        "cancel_requested": cancel_requested,
    }


def _settings(args: argparse.Namespace) -> dict[str, object]:
    return {
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
                    "device": _parse_device(args.device),
                },
            },
        }
    }


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

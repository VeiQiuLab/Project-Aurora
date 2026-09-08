"""Explicit frozen-distribution check, without starting application services.

No recording, install, settings writes or downloads by default. Network/model
and playback smoke operations require separate command-line opt-ins.
"""
from __future__ import annotations

import argparse
import importlib
from importlib import metadata
import json
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice-runtime-check", type=Path, required=True)
    parser.add_argument("--voice-enabled", action="store_true")
    parser.add_argument("--download-whisper", choices=("tiny", "small", "medium"))
    parser.add_argument("--model", choices=("tiny", "small", "medium"), default="tiny")
    parser.add_argument("--tts-smoke", action="store_true")
    parser.add_argument("--playback-smoke", action="store_true")
    parser.add_argument("--stt-audio", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args(argv)
    output = args.voice_runtime_check.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    root = Path(getattr(sys, "_MEIPASS", sys.prefix)).resolve()
    report = {"frozen": bool(getattr(sys, "frozen", False)), "executable": sys.executable, "python": sys.version, "sys_path": list(sys.path), "components": {}}

    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for name, dist in (("faster_whisper", "faster-whisper"), ("ctranslate2", "ctranslate2"), ("edge_tts", "edge-tts"), ("pygame", "pygame"), ("sounddevice", "sounddevice"), ("av", "av")):
        try:
            module = importlib.import_module(name)
            origin = Path(module.__file__).resolve()
            report["components"][name] = {"ready": True, "version": metadata.version(dist), "origin": str(origin), "inside_package": origin.is_relative_to(root)}
        except Exception as error:
            report["components"][name] = {"ready": False, "error_type": type(error).__name__, "detail": str(error)}
        save()
    from modules.runtime_dependencies import RuntimeDependencyManager
    settings = {"voice": {"enabled": args.voice_enabled, "stt": {"model_size": args.download_whisper or args.model}, "recorder": {"ffmpeg_path": args.ffmpeg}}}
    manager = RuntimeDependencyManager(settings)
    report["before"] = manager.check_voice_requirements(timeout=10)
    save()
    if args.download_whisper:
        from modules.dependency_actions import download_whisper_model
        result = download_whisper_model(args.download_whisper, confirmed=True)
        report["download"] = {"ok": result.ok, "status": result.status, "message": result.message}
        report["after_download"] = manager.check_voice_requirements(timeout=10)
        save()
    speech_path = args.stt_audio
    if args.tts_smoke:
        from modules.experience.voice.providers.edge_tts import EdgeTTSProvider
        result = EdgeTTSProvider(output_dir=output.parent / "audio", max_retries=0).synthesize("你好，这是 Aurora 语音测试。", timeout_seconds=30)
        report["tts"] = {"audio_path": result.audio_path, "diagnostics": result.diagnostics}
        if result.audio_path:
            speech_path = Path(result.audio_path)
        save()
    if speech_path and speech_path.is_file():
        from modules.experience.voice.integration import _create_stt
        from modules.experience.voice.models import AudioInput
        result = _create_stt(settings).transcribe(AudioInput(kind="file", path=str(speech_path), language_hint="zh"), timeout_seconds=90)
        report["stt"] = {"text": result.text, "diagnostics": result.diagnostics}
        save()
        if args.playback_smoke:
            try:
                from threading import Event
                from modules.experience.audio.real_playback import RealPlaybackController
                from modules.experience.audio.playback import PlaybackEventType
                from modules.experience.voice.models import SpeechResult
                controller = RealPlaybackController()
                finished = Event()
                events = []
                def on_event(event):
                    events.append(event.event_type.value)
                    if event.event_type in {PlaybackEventType.COMPLETED, PlaybackEventType.FAILED}:
                        finished.set()
                controller.subscribe(on_event)
                controller.play(SpeechResult(audio_path=str(speech_path), mime_type="audio/mpeg"))
                finished.wait(30)
                report["playback"] = {"completed": PlaybackEventType.COMPLETED.value in events, "events": events, "audible_requires_human_confirmation": True}
                controller.stop()
                controller.shutdown()
            except Exception as error:
                report["playback"] = {"completed": False, "error_type": type(error).__name__}
            save()
    return 0

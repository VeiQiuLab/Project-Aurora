"""Minimal blocking HTTP API for the optional Aurora Voice Node."""

from __future__ import annotations

import argparse
import json
import math
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Sequence

from .runtime import (
    CosyVoiceRuntime,
    CosyVoiceRuntimeConfig,
    RuntimeSynthesisError,
    RuntimeTimedOut,
    RuntimeUnavailable,
)
from .wav_utils import inspect_wav, normalize_to_pcm16_wav


MAX_REQUEST_BYTES = 1024 * 1024


class VoiceNodeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], runtime: Any) -> None:
        super().__init__(server_address, VoiceNodeRequestHandler)
        self.runtime = runtime


class VoiceNodeRequestHandler(BaseHTTPRequestHandler):
    server_version = "AuroraVoiceNode/1"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send_error(404, "not_found", "endpoint not found")
            return
        try:
            runtime_health = self.server.runtime.health()
        except Exception as error:
            runtime_health = {
                "available": False,
                "state": "failed",
                "process_running": False,
                "last_error": f"health check failed: {type(error).__name__}",
            }
        available = isinstance(runtime_health, dict) and runtime_health.get("available") is True
        self._send_json(
            200,
            {
                "service": "aurora-voice-node",
                "status": "ready" if available else "degraded",
                "runtime": runtime_health,
            },
        )

    def do_POST(self) -> None:
        if self.path != "/tts":
            self._send_error(404, "not_found", "endpoint not found")
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._send_error(415, "unsupported_media_type", "Content-Type must be application/json")
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_error(400, "invalid_request", "Content-Length must be an integer")
            return
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_error(400, "invalid_request", "request body size is invalid")
            return
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_error(400, "invalid_json", "request body must be valid UTF-8 JSON")
            return
        if not isinstance(payload, dict):
            self._send_error(400, "invalid_request", "request body must be a JSON object")
            return

        text = payload.get("text")
        speed = payload.get("speed", 1.0)
        if not isinstance(text, str) or not text.strip():
            self._send_error(400, "invalid_text", "text must be a non-empty string")
            return
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(float(speed)):
            self._send_error(400, "invalid_speed", "speed must be a finite number")
            return
        if not 0 < float(speed) <= 4.0:
            self._send_error(400, "invalid_speed", "speed must be greater than zero and at most 4.0")
            return

        try:
            audio = self.server.runtime.synthesize(text, float(speed))
        except ValueError as error:
            self._send_error(400, "invalid_text", str(error))
            return
        except RuntimeTimedOut as error:
            self._send_error(504, "runtime_timeout", str(error))
            return
        except RuntimeUnavailable as error:
            self._send_error(503, "runtime_unavailable", str(error))
            return
        except RuntimeSynthesisError as error:
            self._send_error(500, "synthesis_failed", str(error))
            return
        except Exception as error:
            self._send_error(500, "internal_error", f"Voice Node synthesis failed: {type(error).__name__}")
            return
        try:
            audio = normalize_to_pcm16_wav(audio)
            inspect_wav(audio)
        except ValueError as error:
            self._send_error(500, "invalid_wav", str(error))
            return
        self._send_bytes(200, audio, "audio/wav")

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("voice-node: " + (format % args) + "\n")

    def _send_error(self, status: int, code: str, message: str) -> None:
        self._send_json(status, {"error": {"code": code, "message": message}})

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return


def create_server(runtime: Any, *, host: str = "localhost", port: int = 0) -> VoiceNodeServer:
    return VoiceNodeServer((host, int(port)), runtime)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aurora Voice Node (blocking WAV HTTP API)")
    parser.add_argument("--host", default="localhost", help="listen address; use 0.0.0.0 explicitly for LAN")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cli", type=Path, required=True, help="cosyvoice-cli executable")
    parser.add_argument("--model", type=Path, required=True, help="CosyVoice3 GGUF model")
    parser.add_argument("--prompt-speech", type=Path, required=True, help="pre-encoded prompt_speech GGUF")
    parser.add_argument("--backend", default=None, help="cosyvoice backend name, for example cuda0")
    parser.add_argument("--backend-path", type=Path, default=None)
    parser.add_argument("--working-directory", type=Path, default=None)
    parser.add_argument("--output-directory", type=Path, default=None)
    parser.add_argument("--startup-timeout", type=float, default=120.0)
    parser.add_argument("--synthesis-timeout", type=float, default=120.0)
    parser.add_argument("--initial-speed", type=float, default=1.0)
    parser.add_argument(
        "--runtime-arg",
        action="append",
        default=[],
        help="extra cosyvoice-cli argument; repeat and use --runtime-arg=--name for flags",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = CosyVoiceRuntimeConfig(
        cli_path=args.cli,
        model_path=args.model,
        prompt_speech_path=args.prompt_speech,
        backend=args.backend,
        backend_path=args.backend_path,
        working_directory=args.working_directory,
        output_directory=args.output_directory,
        startup_timeout_seconds=args.startup_timeout,
        synthesis_timeout_seconds=args.synthesis_timeout,
        extra_args=tuple(args.runtime_arg),
    )
    runtime = CosyVoiceRuntime(config)
    try:
        runtime.start(args.initial_speed)
    except (RuntimeUnavailable, RuntimeTimedOut) as error:
        print(f"Voice Node started in degraded state: {error}", file=sys.stderr, flush=True)

    server = create_server(runtime, host=args.host, port=args.port)
    listen_host, listen_port = server.server_address[:2]
    print(f"Aurora Voice Node listening on {listen_host}:{listen_port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

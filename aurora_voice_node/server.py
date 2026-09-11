"""Blocking WAV and framed PCM HTTP API for the optional Aurora Voice Node."""

from __future__ import annotations

import argparse
import json
import math
import select
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import Any, Sequence

from .runtime import (
    CosyVoiceRuntime,
    CosyVoiceRuntimeConfig,
    RuntimeSynthesisError,
    RuntimeTimedOut,
    RuntimeUnavailable,
)
from .server_runtime import CosyVoiceServerRuntime, CosyVoiceServerRuntimeConfig
from .stream_protocol import CONTENT_TYPE, encode_frame, encode_json_frame, metadata_payload
from .wav_utils import inspect_wav, normalize_to_pcm16_wav


MAX_REQUEST_BYTES = 1024 * 1024
PCM_FRAME_BYTES = 4096


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
                "backend": "unknown",
                "available": False,
                "state": "failed",
                "process_running": False,
                "streaming": False,
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
        if self.path not in {"/tts", "/tts/stream"}:
            self._send_error(404, "not_found", "endpoint not found")
            return
        request = self._read_tts_request()
        if request is None:
            return
        text, speed = request
        if self.path == "/tts/stream":
            self._handle_stream(text, speed)
        else:
            self._handle_wav(text, speed)

    def _handle_wav(self, text: str, speed: float) -> None:
        try:
            audio = self.server.runtime.synthesize(text, speed)
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

    def _handle_stream(self, text: str, speed: float) -> None:
        stream_factory = getattr(self.server.runtime, "stream_pcm", None)
        if not callable(stream_factory):
            self._send_error(501, "streaming_unsupported", "selected runtime does not support streaming")
            return
        try:
            upstream = stream_factory(text, speed)
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
            self._send_error(500, "internal_error", f"Voice Node streaming failed: {type(error).__name__}")
            return

        try:
            health = self.server.runtime.health()
        except Exception as error:
            upstream.close()
            self._send_error(500, "runtime_health_failed", f"runtime health failed: {type(error).__name__}")
            return
        sample_rate = int(health.get("sample_rate", 24000))
        channels = int(health.get("channels", 1))
        if channels != 1 or sample_rate <= 0:
            upstream.close()
            self._send_error(500, "invalid_runtime_format", "runtime PCM format is unsupported")
            return

        response_started = False
        monitor_stop = Event()
        client_disconnected = Event()
        monitor = Thread(
            target=self._monitor_client_disconnect,
            args=(upstream, monitor_stop, client_disconnected),
            daemon=True,
        )
        monitor.start()
        try:
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE)
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            response_started = True
            self._write_http_chunk(
                encode_json_frame("M", metadata_payload(sample_rate=sample_rate, channels=channels))
            )

            buffer = bytearray()
            total_bytes = 0
            audio_frames = 0
            with upstream:
                for chunk in upstream:
                    if client_disconnected.is_set():
                        raise ConnectionResetError("Voice Node client disconnected")
                    if not chunk:
                        continue
                    buffer.extend(chunk)
                    while len(buffer) >= PCM_FRAME_BYTES:
                        audio = bytes(buffer[:PCM_FRAME_BYTES])
                        del buffer[:PCM_FRAME_BYTES]
                        self._write_http_chunk(encode_frame("A", audio))
                        total_bytes += len(audio)
                        audio_frames += 1
                if len(buffer) % (channels * 2):
                    raise RuntimeSynthesisError("upstream PCM ended with an unaligned sample")
                if buffer:
                    audio = bytes(buffer)
                    self._write_http_chunk(encode_frame("A", audio))
                    total_bytes += len(audio)
                    audio_frames += 1
            if audio_frames == 0:
                raise RuntimeSynthesisError("upstream PCM stream contained no audio")
            self._write_http_chunk(
                encode_json_frame(
                    "E",
                    {
                        "total_samples": total_bytes // (channels * 2),
                        "audio_frames": audio_frames,
                    },
                )
            )
            self._write_http_chunk(b"")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            upstream.close()
            self.close_connection = True
        except RuntimeTimedOut as error:
            upstream.close()
            if response_started:
                self._finish_stream_error("runtime_timeout", str(error))
        except (RuntimeSynthesisError, RuntimeUnavailable, OSError) as error:
            upstream.close()
            if response_started:
                self._finish_stream_error("upstream_failed", str(error))
        except Exception as error:
            upstream.close()
            if response_started:
                self._finish_stream_error(
                    "internal_error", f"Voice Node streaming failed: {type(error).__name__}"
                )
        finally:
            monitor_stop.set()
            monitor.join(0.5)

    def _read_tts_request(self) -> tuple[str, float] | None:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._send_error(415, "unsupported_media_type", "Content-Type must be application/json")
            return None
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_error(400, "invalid_request", "Content-Length must be an integer")
            return None
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_error(400, "invalid_request", "request body size is invalid")
            return None
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_error(400, "invalid_json", "request body must be valid UTF-8 JSON")
            return None
        if not isinstance(payload, dict):
            self._send_error(400, "invalid_request", "request body must be a JSON object")
            return None
        text = payload.get("text")
        speed = payload.get("speed", 1.0)
        if not isinstance(text, str) or not text.strip():
            self._send_error(400, "invalid_text", "text must be a non-empty string")
            return None
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(float(speed)):
            self._send_error(400, "invalid_speed", "speed must be a finite number")
            return None
        if not 0 < float(speed) <= 4.0:
            self._send_error(400, "invalid_speed", "speed must be greater than zero and at most 4.0")
            return None
        return text, float(speed)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("voice-node: " + (format % args) + "\n")

    def _finish_stream_error(self, code: str, message: str) -> None:
        try:
            self._write_http_chunk(encode_json_frame("X", {"code": code, "message": message}))
            self._write_http_chunk(b"")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    def _monitor_client_disconnect(self, upstream: Any, stop: Event, disconnected: Event) -> None:
        while not stop.is_set():
            try:
                readable, _, _ = select.select((self.connection,), (), (), 0.1)
                if not readable:
                    continue
                data = self.connection.recv(1, socket.MSG_PEEK)
                if data:
                    stop.wait(0.05)
                    continue
            except (OSError, ValueError):
                pass
            disconnected.set()
            upstream.close()
            self.close_connection = True
            return

    def _write_http_chunk(self, body: bytes) -> None:
        if not body:
            self.wfile.write(b"0\r\n\r\n")
        else:
            self.wfile.write(f"{len(body):X}\r\n".encode("ascii"))
            self.wfile.write(body)
            self.wfile.write(b"\r\n")
        self.wfile.flush()

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
    parser = argparse.ArgumentParser(description="Aurora Voice Node HTTP API")
    parser.add_argument("--host", default="localhost", help="listen address; use 0.0.0.0 explicitly for LAN")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--runtime-backend", choices=("cli", "server"), default="cli")
    parser.add_argument("--cli", type=Path, help="legacy cosyvoice-cli executable")
    parser.add_argument("--server", type=Path, help="cosyvoice-server executable")
    parser.add_argument("--model", type=Path, required=True, help="CosyVoice3 GGUF model")
    parser.add_argument("--prompt-speech", type=Path, required=True, help="pre-encoded prompt_speech GGUF")
    parser.add_argument("--served-model-name", default="aurora-cosyvoice3")
    parser.add_argument("--voice", default="aurora")
    parser.add_argument("--backend", default=None, help="cosyvoice backend name, for example cuda0")
    parser.add_argument("--backend-path", type=Path, default=None)
    parser.add_argument("--working-directory", type=Path, default=None)
    parser.add_argument("--output-directory", type=Path, default=None)
    parser.add_argument("--internal-port", type=int, default=0)
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--startup-timeout", type=float, default=120.0)
    parser.add_argument("--synthesis-timeout", type=float, default=120.0)
    parser.add_argument("--shutdown-timeout", type=float, default=5.0)
    parser.add_argument("--initial-speed", type=float, default=1.0)
    parser.add_argument(
        "--runtime-arg",
        action="append",
        default=[],
        help="extra runtime argument; repeat and use --runtime-arg=--name for flags",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.runtime_backend == "server":
        if args.server is None:
            parser.error("--server is required when --runtime-backend=server")
        config = CosyVoiceServerRuntimeConfig(
            server_path=args.server,
            model_path=args.model,
            prompt_speech_path=args.prompt_speech,
            served_model_name=args.served_model_name,
            voice=args.voice,
            backend=args.backend,
            backend_path=args.backend_path,
            working_directory=args.working_directory,
            internal_port=args.internal_port,
            sample_rate=args.sample_rate,
            startup_timeout_seconds=args.startup_timeout,
            synthesis_timeout_seconds=args.synthesis_timeout,
            shutdown_timeout_seconds=args.shutdown_timeout,
            extra_args=tuple(args.runtime_arg),
        )
        runtime: Any = CosyVoiceServerRuntime(config)
    else:
        if args.cli is None:
            parser.error("--cli is required when --runtime-backend=cli")
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
        if args.runtime_backend == "server":
            runtime.start()
        else:
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

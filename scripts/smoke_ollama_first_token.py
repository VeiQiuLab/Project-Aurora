"""Measure Ollama first model output and first visible content without printing it."""

import argparse
import json
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.chat import DEFAULT_SYSTEM_CONTEXT, ChatSession, StreamingRequestHandle, stream_chat
from modules.ollama_request_policy import thinking_payload_value
from modules.settings import settings


DEFAULT_PROMPT = "只回复：测试成功。"
def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=str(
            settings.get("resolved_chat_model", "")
            or settings.get("chat_model", "")
            or ""
        ).strip(),
        help="Installed Ollama model (for example qwen3.5:9b).",
    )
    parser.add_argument("--runs", type=int, default=3, help="Runs per selected mode.")
    parser.add_argument(
        "--mode",
        choices=("minimal", "aurora", "both"),
        default="both",
        help="Minimal context, Aurora production payload path, or both.",
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument(
        "--think",
        choices=("default", "on", "off"),
        default="default",
        help="Omit think, send think=true, or send think=false.",
    )
    parser.add_argument(
        "--aurora-session-json",
        type=Path,
        help="Optional saved Aurora conversation JSON containing a messages list.",
    )
    parser.add_argument(
        "--skip-ollama-ps",
        action="store_true",
        help="Do not collect the optional ollama ps snapshots.",
    )
    return parser.parse_args()


def load_aurora_messages(path):
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    messages = payload.get("messages") if isinstance(payload, dict) else payload
    if not isinstance(messages, list):
        raise ValueError("Aurora session JSON must contain a messages list")
    return messages


def ollama_ps_snapshot(label):
    try:
        result = subprocess.run(
            ["ollama", "ps"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return {
            "type": "ollama_ps",
            "label": label,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except (OSError, subprocess.SubprocessError) as error:
        return {"type": "ollama_ps", "label": label, "error": str(error)}


def make_session(mode, aurora_messages):
    if mode == "minimal":
        return ChatSession("You are a concise assistant.")
    session = ChatSession(DEFAULT_SYSTEM_CONTEXT)
    if aurora_messages is not None:
        session.replace(aurora_messages)
    return session


def concise_report(mode, run_index, think_mode, diagnostics, status, visible_chars, error):
    names = (
        "chat_request_start_monotonic",
        "payload_ready_monotonic",
        "urlopen_start_monotonic",
        "response_headers_monotonic",
        "first_raw_line_monotonic",
        "first_json_message_monotonic",
        "first_model_output_monotonic",
        "first_nonempty_content_monotonic",
        "stream_end_monotonic",
        "request_to_payload_ms",
        "payload_to_urlopen_ms",
        "urlopen_to_headers_ms",
        "request_to_headers_ms",
        "headers_to_first_raw_line_ms",
        "first_raw_to_first_content_ms",
        "request_to_first_model_output_ms",
        "request_to_first_content_ms",
        "stream_total_ms",
        "load_duration_ms",
        "prompt_eval_duration_ms",
        "eval_duration_ms",
        "total_duration_ms",
        "prompt_eval_count",
        "eval_count",
        "message_count",
        "approx_input_chars",
        "approx_input_tokens",
        "system_chars",
        "history_chars",
        "current_user_chars",
        "reasoning_chars",
        "ollama_think_mode",
        "ollama_keep_alive",
    )
    report = {
        "type": "run_summary",
        "mode": mode,
        "run_index": run_index,
        "think_mode": think_mode,
        "think_payload_value": thinking_payload_value(think_mode),
        "request_start": diagnostics.get("chat_request_start_monotonic"),
        "headers_time": diagnostics.get("response_headers_monotonic"),
        "first_raw_line": diagnostics.get("first_raw_line_monotonic"),
        "first_model_output": diagnostics.get("first_model_output_monotonic"),
        "first_content": diagnostics.get("first_nonempty_content_monotonic"),
        "stream_end": diagnostics.get("stream_end_monotonic"),
        "headers_to_first_raw_ms": diagnostics.get("headers_to_first_raw_line_ms"),
        "input_chars": diagnostics.get("approx_input_chars"),
        **{name: diagnostics.get(name) for name in names},
        "visible_content_chars": visible_chars,
        "status": status,
        "error": error,
    }
    return report


def run_once(model, prompt, mode, run_index, aurora_messages, think_mode="default"):
    stop_event = threading.Event()
    diagnostics = {}
    handle = StreamingRequestHandle(stop_event, diagnostics)
    visible_chars = 0

    def on_chunk(chunk):
        nonlocal visible_chars
        visible_chars += len(chunk)

    def observe_raw_line(observation):
        print(json.dumps({
            "type": "raw_line",
            "mode": mode,
            "run_index": run_index,
            **observation,
        }, ensure_ascii=False), flush=True)

    status = "failed"
    error = ""
    try:
        result = stream_chat(
            model,
            prompt,
            make_session(mode, aurora_messages),
            on_chunk,
            stop_event,
            request_handle=handle,
            raw_line_observer=observe_raw_line,
            thinking_mode=think_mode,
        )
        status = "cancelled" if result == "stopped" else result
    except KeyboardInterrupt:
        handle.cancel()
        status = "cancelled"
    except Exception as exception:
        status = "failed"
        error = str(exception)
    return concise_report(
        mode,
        run_index,
        think_mode,
        diagnostics,
        status,
        visible_chars,
        error,
    )


def main():
    args = parse_args()
    if not args.model:
        raise SystemExit("No Ollama model selected; pass --model MODEL.")
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")

    try:
        aurora_messages = load_aurora_messages(args.aurora_session_json)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Unable to load Aurora session JSON: {error}") from error

    if not args.skip_ollama_ps:
        print(json.dumps(ollama_ps_snapshot("before"), ensure_ascii=False, indent=2))

    modes = ("minimal", "aurora") if args.mode == "both" else (args.mode,)
    reports = []
    with patch("modules.memory.MemoryStore.queue_candidates", return_value=[]):
        for mode in modes:
            for run_index in range(1, args.runs + 1):
                report = run_once(
                    args.model,
                    args.prompt,
                    mode,
                    run_index,
                    aurora_messages,
                    args.think,
                )
                reports.append(report)
                print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)

    if not args.skip_ollama_ps:
        print(json.dumps(ollama_ps_snapshot("after"), ensure_ascii=False, indent=2))
    if any(report["status"] != "completed" for report in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

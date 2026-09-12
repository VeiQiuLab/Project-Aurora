"""Real Ollama streaming cancellation smoke for Project Aurora."""

import argparse
import json
import sys
import threading
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.chat import ChatSession, StreamingRequestHandle, stream_chat
from modules.settings import settings


LONG_PROMPT = (
    "请用中文详细解释本地大语言模型从收到请求到逐 token 输出的完整过程，"
    "包括预填充、解码、KV cache、采样和流式网络传输，至少分成八个自然段。"
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=str(
            settings.get("resolved_chat_model", "")
            or settings.get("chat_model", "")
            or ""
        ).strip(),
        help="Installed Ollama chat model (defaults to Aurora's selected model).",
    )
    parser.add_argument(
        "--cancel-delay",
        type=float,
        default=0.25,
        help="Seconds to wait after the first chunk before cancelling.",
    )
    parser.add_argument(
        "--join-timeout",
        type=float,
        default=5.0,
        help="Maximum seconds to wait for the cancelled worker to exit.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.model:
        raise SystemExit("No Ollama chat model selected; pass --model MODEL.")

    session = ChatSession()
    cancel_event = threading.Event()
    first_chunk = threading.Event()
    diagnostics = {}
    handle = StreamingRequestHandle(cancel_event, diagnostics)
    chunks = []
    outcome = {"status": "running", "error": ""}

    def on_chunk(chunk):
        chunks.append(chunk)
        first_chunk.set()

    def run_first_request():
        try:
            result = stream_chat(
                args.model,
                LONG_PROMPT,
                session,
                on_chunk,
                cancel_event,
                request_handle=handle,
            )
            outcome["status"] = "cancelled" if result == "stopped" else result
        except Exception as error:
            outcome["status"] = "failed"
            outcome["error"] = str(error)

    with patch("modules.memory.MemoryStore.queue_candidates", return_value=[]):
        worker = threading.Thread(target=run_first_request, name="ollama-cancel-smoke")
        worker.start()
        if not first_chunk.wait(120):
            handle.cancel()
            worker.join(args.join_timeout)
            raise SystemExit("Timed out waiting for the first Ollama chunk.")

        sleep(max(0.0, args.cancel_delay))
        chunk_count_at_cancel = len(chunks)
        cancel_requested = monotonic()
        handle.cancel()
        worker.join(max(0.1, args.join_timeout))
        stream_exit = diagnostics.get("stream_exit_monotonic")

        report = {
            "cancel_request_monotonic": cancel_requested,
            "stream_exit_monotonic": stream_exit,
            "cancel_transport_latency_ms": diagnostics.get("cancel_transport_latency_ms"),
            "chunk_count_before_cancel": chunk_count_at_cancel,
            "chunk_count_after_cancel": len(chunks) - chunk_count_at_cancel,
            "final_status": outcome["status"],
            "active_response_cleared": diagnostics.get("active_response") is False,
            "worker_alive": worker.is_alive(),
            "error": outcome["error"],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if worker.is_alive() or outcome["status"] != "cancelled":
            raise SystemExit(1)

        recovery_chunks = []
        recovery = stream_chat(
            args.model,
            "只回复：恢复成功",
            session,
            recovery_chunks.append,
            threading.Event(),
        )
    recovery_report = {
        "status": recovery,
        "response": "".join(recovery_chunks).strip(),
    }
    print(json.dumps({"recovery_request": recovery_report}, ensure_ascii=False, indent=2))
    if recovery != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""Opt-in real Ollama context smoke for the V4-4A headless path.

The smoke uses the real user settings and read-only context sources, but an
isolated temporary conversation directory.  It reports only safe counts and
timings; prompts, responses, and source contents never leave the process.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

SIDECAR = Path(__file__).resolve().parent
ROOT = SIDECAR.parents[2]
sys.path[:0] = [str(SIDECAR), str(ROOT)]

from production_sidecar.composition import ProductionComposition
from production_sidecar.server import ProductionSidecar


def source_fingerprint(root):
    """Hash source inventory plus contents/mtime, without retaining source text."""
    paths = [root / "config" / "settings.json"]
    for name in ("memory", "persona", "knowledge"):
        paths.extend((root / name).rglob("*"))
    return {str(path.relative_to(root)): (_hash(path), path.stat().st_mtime_ns)
            for path in paths if path.is_file()}


def _hash(path: Path):
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_resource_snapshot(host: str):
    try:
        import urllib.request

        request = urllib.request.Request(host.rstrip("/") + "/api/ps", method="GET")
        with urllib.request.urlopen(request, timeout=3) as response:
            data = json.loads(response.read(1_048_576).decode("utf-8"))
        models = data.get("models", []) if isinstance(data, dict) else []
        return [{"name": item.get("name"), "size_vram": item.get("size_vram")}
                for item in models if isinstance(item, dict)]
    except Exception:
        return None


async def _run_once(sidecar, conversation_id, *, cancel_after_first_delta=False):
    events = []
    first_delta_at = None
    loop = asyncio.get_running_loop()

    async def send(connection, event):
        nonlocal first_delta_at
        if event.get("type") == "chat.delta" and first_delta_at is None:
            first_delta_at = loop.time()
        if event.get("type") == "chat.completed":
            events.append(event)

    sidecar.send = send
    request_id = f"context-smoke-{time.time_ns()}"
    message = {
        "protocol": "aurora-ipc", "version": 1, "type": "chat.request",
        "request_id": request_id, "session_id": request_id,
        "generation_id": request_id,
        "payload": {"conversation_id": conversation_id, "input": (
            "请写一篇两千字的科普文章，介绍太阳系，不要省略内容。" if cancel_after_first_delta else "请只回答：收到。")},
    }
    await sidecar.chat.start(object(), message)
    run = sidecar.chat.active
    if cancel_after_first_delta:
        async with asyncio.timeout(120):
            while first_delta_at is None and not run.task.done():
                await asyncio.sleep(0.005)
        cancellation = {
            "protocol": "aurora-ipc", "version": 1, "type": "chat.cancel.request",
            "request_id": request_id + "-cancel", "session_id": request_id,
            "generation_id": request_id,
            "payload": {"target_request_id": request_id},
        }
        await sidecar.chat.cancel(run.connection, cancellation)
    await asyncio.wait_for(run.task, 180)
    terminal = events[-1]["payload"] if events else {}
    diagnostics = terminal.get("diagnostics", {}) if isinstance(terminal, dict) else {}
    return {
        "status": terminal.get("terminal_state"),
        "output_chars": terminal.get("output_chars", 0),
        "context_total_ms": diagnostics.get("context_total_ms"),
        "memory_ms": diagnostics.get("memory_ms"),
        "persona_ms": diagnostics.get("persona_ms"),
        "knowledge_ms": diagnostics.get("knowledge_ms"),
        "rag_ms": diagnostics.get("rag_ms"),
        "prompt_assembly_ms": diagnostics.get("prompt_assembly_ms"),
        "history_message_count": diagnostics.get("history_message_count"),
        "memory_item_count": diagnostics.get("memory_item_count"),
        "knowledge_item_count": diagnostics.get("knowledge_item_count"),
        "rag_result_count": diagnostics.get("rag_result_count"),
        "persona_enabled": diagnostics.get("persona_enabled"),
        "knowledge_enabled": diagnostics.get("knowledge_enabled"),
        "rag_enabled": diagnostics.get("rag_enabled"),
        "first_sidecar_delta_ms": (
            round((first_delta_at - run.received_at) * 1000, 3)
            if first_delta_at is not None else None
        ),
        "ollama_load_duration_ms": diagnostics.get("load_duration_ms"),
        "ollama_first_content_ms": diagnostics.get("request_to_first_content_ms"),
        "ollama_first_model_output_ms": diagnostics.get("request_to_first_model_output_ms"),
        "reasoning_chars": diagnostics.get("reasoning_chars"),
        "worker_exited": diagnostics.get("worker_exited"),
        "active_response": diagnostics.get("active_response"),
    }


async def main_async(args):
    from modules import app_paths

    data_root = Path(args.data_root).expanduser() if args.data_root else app_paths.USER_DATA_DIR
    config = data_root / "config" / "settings.json"
    before = source_fingerprint(data_root)
    with tempfile.TemporaryDirectory(prefix="aurora-v4-context-smoke-") as isolated:
        isolated_root = Path(isolated)
        composition = ProductionComposition(
            ROOT, config_file=config,
            conversation_root=isolated_root / "conversations",
            context_root=data_root,
        )
        sidecar = ProductionSidecar("context-smoke", composition)
        # This pre-LLM-only smoke reads real context; post-turn writes belong
        # exclusively to smoke_post_turn's isolated roots.
        composition.post_turn.close()
        health = await composition.refresh()
        report = {
            "health_state": composition.state,
            "ollama_reachable": health.get("ollama", {}).get("reachable"),
            "model_available": health.get("ollama", {}).get("model_available"),
            "runs": [],
            "resource_before": _safe_resource_snapshot(health.get("ollama", {}).get("host", "")),
        }
        if not health.get("ollama", {}).get("reachable") or not health.get("ollama", {}).get("model_available"):
            composition.close()
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        created = await asyncio.to_thread(composition.conversations.create)
        conversation_id = created["conversation_id"]
        try:
            for _ in range(max(1, args.runs)):
                report["runs"].append(await _run_once(sidecar, conversation_id))
                assert report["runs"][-1]["status"] == "completed"
            saved = composition.conversations.get(conversation_id)
            report["persisted_user_turns"] = sum(m["role"] == "user" for m in saved["messages"])
            if args.cancel:
                created = await asyncio.to_thread(composition.conversations.create)
                report["cancel_run"] = await _run_once(
                    sidecar, created["conversation_id"], cancel_after_first_delta=True
                )
                assert report["cancel_run"]["status"] == "cancelled"
                report["cancelled_turn_not_saved"] = not (isolated_root / "conversations" / f"{created['conversation_id']}.json").exists()
            report["resource_after"] = _safe_resource_snapshot(health["ollama"]["host"])
        finally:
            await sidecar.chat.close()
            composition.close()
    after = source_fingerprint(data_root)
    report["context_sources_unchanged"] = before == after
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["context_sources_unchanged"]:
        raise SystemExit("context source changed during read-only smoke")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, help="explicit Aurora user-data root")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cancel", action="store_true", help="cancel one run after its first sidecar delta")
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()

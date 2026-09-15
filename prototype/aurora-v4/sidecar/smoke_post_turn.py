"""Opt-in real Ollama V4-4B contention smoke. ALL writes use a temporary root.

No GUI acceptance claim: first_sidecar_delta is not first_frontend_delta.
Does not print prompts, replies, candidates, titles, or reasoning bodies.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import uuid

SIDECAR = Path(__file__).resolve().parent
ROOT = SIDECAR.parents[2]
sys.path[:0] = [str(SIDECAR), str(ROOT)]
from modules import app_paths
from production_sidecar.composition import ProductionComposition
from production_sidecar.server import ProductionSidecar
from smoke_production_context import source_fingerprint, _safe_resource_snapshot


def resources(host):
    result = {"models": _safe_resource_snapshot(host)}
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "total_physical", "available_physical", "total_page", "available_page",
                    "total_virtual", "available_virtual", "extended")]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            result.update(ram_used_bytes=status.total_physical-status.available_physical,
                          ram_total_bytes=status.total_physical)
    return result


async def until(predicate, timeout=35):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("smoke condition not reached")
        await asyncio.sleep(.005)


async def run(args):
    source = app_paths.USER_DATA_DIR
    before = source_fingerprint(source)
    conversations_before = {p.name: p.read_bytes() for p in (source / "conversations").glob("*.json")}
    report = {"manual_gui": "NOT YET VERIFIED", "first_frontend_delta_ms": None,
              "timing_source": "Python IPC send boundary, not frontend", "runs": []}
    with tempfile.TemporaryDirectory(prefix="aurora-v44b-smoke-") as temporary:
        root = Path(temporary)
        # Read production policy, copy only Persona into isolated context.
        if (source / "persona").exists():
            shutil.copytree(source / "persona", root / "persona")
        composition = ProductionComposition(ROOT, config_file=source / "config/settings.json",
            conversation_root=root / "conversations", context_root=root)
        sidecar = ProductionSidecar("isolated-post-turn-smoke", composition)
        coordinator = composition.post_turn
        events = []
        async def send(connection, event):
            from mock_sidecar.server import validate_message
            validate_message(event)
            events.append((time.monotonic(), event))
        sidecar.send = send
        connection = object()
        health = await composition.refresh()
        probe = health["ollama"]
        assert probe["reachable"] and probe["model_available"], "Ollama unavailable"
        report["resources_before"] = resources(probe["host"])
        report["policy"] = composition.settings.policy.diagnostics()
        model = probe["configured_model"]
        destructive_calls = []
        def forbidden_mutation(*args, **kwargs):
            destructive_calls.append(True)
            raise AssertionError("Unconfirmed Memory mutation attempted")
        for method in ("delete", "archive", "merge", "update", "approve_candidate", "save_candidates"):
            setattr(composition.context.memory, method, forbidden_mutation)

        async def turn(cid, label, *, cancel=False):
            identity = uuid.uuid4().hex
            message = {"protocol": "aurora-ipc", "version": 1, "type": "chat.request",
                "request_id": identity, "session_id": identity, "generation_id": identity,
                "payload": {"conversation_id": cid, "input": (
                    "请详细介绍太阳系，写两千字。" if cancel else "我喜欢简洁的黑白界面。请只回答收到。")}}
            started = time.monotonic()
            await sidecar.start_chat(connection, message)
            execution = sidecar.chat.active
            if cancel:
                await until(lambda: any(e.get("generation_id") == identity and e["type"] == "chat.delta"
                                        for _, e in events), timeout=90)
                await sidecar.cancel_chat(connection, {"protocol": "aurora-ipc", "version": 1,
                    "type": "chat.cancel.request", "request_id": identity+"cancel", "session_id": identity,
                    "generation_id": identity, "payload": {"target_request_id": identity}})
            await asyncio.wait_for(execution.task, 120)
            terminal = next(e["payload"] for _, e in events if e["type"] == "chat.completed" and e.get("generation_id") == identity)
            first = next((t for t, e in events if e["type"] == "chat.delta" and e.get("generation_id") == identity), None)
            diagnostics = terminal["diagnostics"]
            summary = {"label": label, "status": terminal["terminal_state"],
                "first_sidecar_delta_ms": (first-started)*1000 if first else None,
                **{key: diagnostics.get(key) for key in ("context_total_ms", "load_duration_ms",
                    "prompt_eval_duration_ms", "request_to_first_model_output_ms", "request_to_first_content_ms",
                    "reasoning_chars", "worker_exited", "active_response")}}
            report["runs"].append(summary)
            print(json.dumps({"progress": summary}), flush=True)
            assert summary["status"] == ("cancelled" if cancel else "completed")
            if not cancel:
                assert not coordinator.schedule(cid, identity, execution.session_messages, model)
            return summary

        def count(event):
            return sum(e["event"] == event for e in coordinator.events)

        try:
            cid = composition.conversations.create()["conversation_id"]
            await turn(cid, "A-turn1")
            await asyncio.sleep(1)
            await turn(cid, "A-turn2-within-debounce")
            assert count("title_started") == 0
            assert count("deferred_foreground") >= 1
            await until(lambda: not coordinator.pending)
            await asyncio.sleep(.05)
            report["A_deferred"] = True
            report["B_idle_title_count"] = count("title_started")
            assert report["B_idle_title_count"] == 1
            assert any(e["type"] == "conversation.changed" for _, e in events)
            report["B_metadata_event_count"] = sum(e["type"] == "conversation.changed" for _, e in events)
            assert composition.conversations.get(cid)["title"] not in {"New Conversation", "新对话"}
            for n in range(3):
                await turn(cid, f"warm-{n+1}")
            await until(lambda: not coordinator.pending)

            # C: submit at the actual background call boundary, not merely near
            # an estimated timer. Original call remains the production function.
            entered = threading.Event()
            real_call = coordinator.chat_api["chat_with_messages"]
            def observe_call(*a, **kw):
                entered.set()
                return real_call(*a, **kw)
            coordinator.chat_api = {**coordinator.chat_api, "chat_with_messages": observe_call}
            cid2 = composition.conversations.create()["conversation_id"]
            await turn(cid2, "C-seed")
            await until(entered.is_set)
            report["resources_during_background"] = resources(probe["host"])
            await turn(cid2, "C-near-title-start")
            await until(lambda: not coordinator.pending)
            prior = (count("title_started"), count("memory_completed"))
            await asyncio.sleep(5.2)
            report["D_no_duplicate"] = prior == (count("title_started"), count("memory_completed"))
            assert report["D_no_duplicate"]
            candidates = composition.context.memory.list_candidates()
            report["E_memory"] = {"pending_candidates": len(candidates), "confirmed_memories": len(composition.context.memory.list_memories()),
                "all_pending": all(c["status"] == "pending" for c in candidates), "destructive_calls": len(destructive_calls)}
            assert candidates and report["E_memory"]["all_pending"]
            assert report["E_memory"]["confirmed_memories"] == 0
            assert not destructive_calls
            snapshot = composition.context.prepare("界面偏好", [], threading.Event())
            report["E_next_context_memory_items"] = snapshot.diagnostics["memory_item_count"]
            assert report["E_next_context_memory_items"] == 0  # no silent approval
            cid3 = composition.conversations.create()["conversation_id"]
            before_seen = len(coordinator.seen)
            await turn(cid3, "cancel-no-post-turn", cancel=True)
            assert len(coordinator.seen) == before_seen
            assert not coordinator.schedule(cid3, "failed-fixture", [], model, status="failed")
            assert not (root / "conversations" / f"{cid3}.json").exists()
            report["post_turn_events"] = list(coordinator.events)
            report["resources_after"] = resources(probe["host"])
            title_calls = [e for e in coordinator.events if e["event"] == "title_request_finished"]
            assert title_calls and all(e.get("reasoning_chars") == 0 for e in title_calls)
            # No hard SLA: flag unexpected warm stalls for investigation before closure.
            report["warm_stall_review_required"] = any((r["first_sidecar_delta_ms"] or 0) > 5000
                for r in report["runs"][1:] if r["status"] == "completed")
        finally:
            await sidecar.chat.close()
            composition.close()
            report["post_turn_worker_exited"] = coordinator.worker is None or not coordinator.worker.is_alive()
    report["real_sources_unchanged"] = before == source_fingerprint(source)
    report["real_conversations_unchanged"] = conversations_before == {p.name: p.read_bytes() for p in (source / "conversations").glob("*.json")}
    assert report["real_sources_unchanged"] and report["real_conversations_unchanged"]
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert not report["warm_stall_review_required"], "Warm stall: investigate before closure"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="Safe diagnostics report path; no conversation content")
    asyncio.run(run(parser.parse_args()))

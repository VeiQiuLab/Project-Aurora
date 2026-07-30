"""Standalone Ollama lifecycle verification for Project Aurora."""

from pathlib import Path
import json
import sys
import threading
import time

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.service_manager import ServiceManager  # noqa: E402


def print_snapshot(title, snapshot):
    print(title)
    summary = ServiceManager.process_summary(snapshot)
    if not summary:
        print("  none")
        return
    for item in summary:
        print(
            "  pid={pid}, name={name}, ppid={ppid}, session={session_id}, "
            "alive={alive}, owned={owned_candidate}, reason={ownership_reason}, "
            "exe={exe}, cmdline={cmdline}, create_time={create_time}".format(**item)
        )


def main():
    manager = ServiceManager()
    before = manager.ollama_process_snapshot()
    print_snapshot("[OLLAMA SNAPSHOT BEFORE START]", before)
    if before:
        manager.ollama_lifecycle_debug["started_by_app"] = False
        manager.ollama_lifecycle_debug["before_snapshot"] = ServiceManager.process_summary(before)
        manager.ollama_lifecycle_debug["after_shutdown_snapshot"] = ServiceManager.process_summary(before)
        manager.ollama_lifecycle_debug["errors"] = [
            "SKIP: Ollama was already running before lifecycle test; user process was not stopped."
        ]
        manager.write_ollama_lifecycle_debug()
        print("SKIP: Ollama is already running. Please close Ollama manually before scenario A.")
        return 2

    completed = threading.Event()
    events = []

    def callback(event):
        events.append(event)
        if isinstance(event, dict):
            if event.get("event") == "ollama_snapshot_before_start":
                print("[OLLAMA SNAPSHOT BEFORE START]", json.dumps(event.get("processes"), ensure_ascii=False))
            elif event.get("event") == "ollama_root_started":
                print(
                    "Ollama root started:",
                    json.dumps({
                        "pid": event.get("pid"),
                        "executable": event.get("executable"),
                        "args": event.get("args")
                    }, ensure_ascii=False)
                )
            elif event.get("event") == "ollama_snapshot_after_start":
                print("[OLLAMA SNAPSHOT AFTER START]", json.dumps(event.get("processes"), ensure_ascii=False))
            elif event.get("event") == "ollama_owned_processes":
                print("[OLLAMA OWNERSHIP RESULT]", json.dumps(event.get("processes"), ensure_ascii=False))
        else:
            print("event:", event)
            if event in {"started", "failed", "command_not_found", "online"}:
                completed.set()

    manager.start_ollama("ollama serve", "http://127.0.0.1:11434", callback=callback, timeout=30)
    completed.wait(timeout=40)

    if "started" not in events:
        print("FAIL: Ollama did not start under Aurora ownership.")
        return 1

    time.sleep(1)
    after_start = manager._annotate_ollama_ownership(manager.ollama_process_snapshot())
    print_snapshot("[OLLAMA SNAPSHOT AFTER START]", after_start)

    print("[OLLAMA SHUTDOWN BEGIN]")
    result = manager.stop_ollama_owned_processes(allow_image_fallback=True)
    print("[OLLAMA TERMINATE RESULT]", json.dumps(result.get("terminated"), ensure_ascii=False))
    print("[OLLAMA SNAPSHOT AFTER SHUTDOWN]", json.dumps(result.get("remaining"), ensure_ascii=False))

    debug_path = PROJECT_ROOT / "logs" / "ollama_lifecycle_debug.json"
    print("debug_file:", debug_path)
    if result.get("ok"):
        print("PASS: No Aurora-owned Ollama residual processes.")
        return 0
    print("FAIL: Aurora-owned Ollama residual processes remain.")
    print(json.dumps(result.get("remaining_owned_candidates"), ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

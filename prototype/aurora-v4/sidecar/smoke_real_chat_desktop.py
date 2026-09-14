"""Opt-in real desktop observer. Operate Send/Stop/Crash/Restart/Close in Aurora.

Starts the built desktop with production settings and loopback-only WebView
debugging for this launch. CDP is READ ONLY: records text-free performance marks.
It never sends a chat itself, changes settings, starts/stops Ollama or unloads a model.
Close the desktop to finish the report. Requires existing websockets and psutil.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import psutil
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from smoke_production_sidecar import ProductionComposition, hash_file, read_api


def get_json(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=2) as response:
        return json.loads(response.read(1048576))


def resources(pid):
    result = dict(rust_desktop_mib=0.0, webview2_mib=0.0, python_mib=0.0, ollama_mib=0.0)
    python_pids = []
    try:
        parent = psutil.Process(pid)
        result["rust_desktop_mib"] = parent.memory_info().rss / 1048576
        for p in parent.children(recursive=True):
            try:
                name = p.name().lower()
                key = "webview2_mib" if "webview2" in name else "python_mib" if "python" in name else None
                if key:
                    result[key] += p.memory_info().rss / 1048576
                if key == "python_mib":
                    python_pids.append(p.pid)
            except psutil.Error:
                pass
    except psutil.Error:
        pass
    runtime = {}
    for root in psutil.process_iter(["name"]):
        if "ollama" in (root.info["name"] or "").lower():
            try:
                runtime.update({p.pid: p for p in [root, *root.children(recursive=True)]})
            except psutil.Error:
                pass
    for p in runtime.values():
        try:
            result["ollama_mib"] += p.memory_info().rss / 1048576
        except psutil.Error:
            pass
    return {**{k: round(v, 2) for k, v in result.items()}, "python_pids": python_pids}


async def observe(args):
    composition = ProductionComposition()
    before_hash = hash_file(composition.settings.config_file)
    health = await composition.refresh()
    host = health["ollama"]["host"]
    report = {"kind": "DIRECT CHAT real desktop observer", "health": health,
              "models_before": read_api(host, "/api/ps"), "runs": [], "events": [],
              "stderr": [], "desktop_exit_code": None}
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="aurora-v4-webview-smoke-") as webview_data:
        env = {**os.environ, "AURORA_V4_BACKEND": "production",
               "WEBVIEW2_USER_DATA_FOLDER": webview_data,
               "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS":
                   f"--remote-debugging-port={port} --remote-debugging-address=127.0.0.1"}
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 1  # user-operated, explicitly interactive acceptance window
        process = subprocess.Popen([str(args.desktop_exe.resolve())], env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, startupinfo=startup)
        def drain():
            for raw in process.stderr:
                report["stderr"].append(raw.decode("utf-8", errors="replace").strip())
                report["stderr"] = report["stderr"][-200:]
        reader = threading.Thread(target=drain, name="desktop-smoke-stderr", daemon=True)
        reader.start()
        seen, python_ids = set(), set()
        started = time.monotonic()
        def save():
            temporary = args.report.with_name(args.report.name + ".tmp")
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(args.report)
        try:
            target = None
            while time.monotonic() - started < 25 and process.poll() is None:
                try:
                    pages = await asyncio.to_thread(get_json, f"http://127.0.0.1:{port}/json/list")
                    target = next((p for p in pages if p.get("type") == "page" and
                                   ("tauri.localhost" in p.get("url", "") or p.get("url", "").startswith("tauri://"))), None)
                    if target:
                        break
                except (OSError, ValueError):
                    pass
                await asyncio.sleep(.1)
            if not target:
                raise RuntimeError("Built WebView CDP target unavailable")
            report["desktop_pid"] = process.pid
            print(json.dumps({"observer": "ready", "desktop_pid": process.pid, "report": str(args.report)}), flush=True)
            async with connect(target["webSocketDebuggerUrl"], proxy=None) as ws:
                message_id = 0
                while process.poll() is None and time.monotonic() - started < args.duration:
                    message_id += 1
                    await ws.send(json.dumps({"id": message_id, "method": "Runtime.evaluate", "params": {
                        "expression": "performance.getEntriesByType('mark').filter(e => e.name.startsWith('aurora-')).map(e => ({name:e.name,startTime:e.startTime,detail:e.detail}))",
                        "returnByValue": True}}))
                    while True:
                        reply = json.loads(await ws.recv())
                        if reply.get("id") == message_id:
                            break
                    entries = reply.get("result", {}).get("result", {}).get("value", [])
                    current = resources(process.pid)
                    python_ids.update(current["python_pids"])
                    for item in entries:
                        key = (item["name"], item["startTime"])
                        if key in seen:
                            continue
                        seen.add(key)
                        report["events"].append(item)
                        if item["name"] == "aurora-terminal":
                            run = {**item["detail"], "resources": current, "models": read_api(host, "/api/ps")}
                            report["runs"].append(run)
                            print(json.dumps({"run": len(report["runs"]), **run}, ensure_ascii=False), flush=True)
                    report["latest_resources"] = current
                    report["models_latest"] = read_api(host, "/api/ps")
                    save()
                    await asyncio.sleep(.1)
        except ConnectionClosed as error:
            # WebView closes CDP before Tauri finishes its normal sidecar teardown.
            # Observe that grace period, rather than turning normal close into kill.
            try:
                await asyncio.to_thread(process.wait, timeout=8)
            except subprocess.TimeoutExpired:
                report["observer_error"] = type(error).__name__ + ": desktop still alive after CDP close"
                raise
        except Exception as error:
            if process.poll() is None:
                report["observer_error"] = type(error).__name__ + ": " + str(error)
                raise
        finally:
            if process.poll() is None:
                # Only this smoke's desktop; its existing Job Object reaps its sidecar.
                process.kill()
                report["forced_cleanup"] = True
            process.wait(timeout=10)
            reader.join(3)
            process.stderr.close()
            remaining = [psutil.Process(pid) for pid in python_ids if psutil.pid_exists(pid)]
            _, alive = psutil.wait_procs(remaining, timeout=5)
            report["orphan_python_pids"] = [p.pid for p in alive]
            report["desktop_exit_code"] = process.returncode
            report["models_after"] = read_api(host, "/api/ps")
            report["settings_unchanged"] = before_hash == hash_file(composition.settings.config_file)
            composition.close()
            save()
            print(json.dumps({"observer": "finished", "orphan_python_pids": report["orphan_python_pids"],
                              "settings_unchanged": report["settings_unchanged"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop-exe", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=1800, help="maximum observation seconds")
    args = parser.parse_args()
    asyncio.run(observe(args))


if __name__ == "__main__":
    main()

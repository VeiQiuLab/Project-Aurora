"""Opt-in local V4-3A acceptance. GET only; never starts Ollama or a model.

Runs Rust's real gateway smoke; optional built desktop lifecycle/RAM checks.
No settings writes. Process IDs are local CLI evidence, never frontend DTOs.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

SIDECAR = Path(__file__).resolve().parent
ROOT = SIDECAR.parents[2]
sys.path[:0] = [str(SIDECAR), str(ROOT)]
from production_sidecar.composition import ProductionComposition, NoRedirect


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def read_api(host, endpoint):
    assert endpoint in {"/api/ps", "/api/version"}
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(host + endpoint, timeout=2) as response:
            data = response.read(1_048_577)
        if len(data) > 1_048_576:
            raise ValueError("oversized response")
        result = json.loads(data)
        if endpoint == "/api/ps":
            return [{"name": m.get("name"), "size_vram": m.get("size_vram")}
                    for m in result["models"]]
        return {"version": result.get("version")}
    except Exception as error:
        return {"unavailable": type(error).__name__}


def request_window_close(pid):
    """WM_CLOSE to only this smoke's desktop window (normal application exit)."""
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    found = []

    @callback_type
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, len(title))
            if title.value == "Aurora":
                user32.PostMessageW(hwnd, 0x0010, 0, 0)
                found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    if not found:
        raise RuntimeError("desktop window not found")


def desktop_probe(executable, *, forced, cwd):
    import psutil
    env = {**os.environ, "AURORA_V4_BACKEND": "production"}
    started = time.monotonic()
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    process = subprocess.Popen([str(executable)], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startup)
    lines = []
    ready = threading.Event()

    def drain():
        for raw in process.stderr:
            line = raw.decode("utf-8", errors="replace").strip()
            lines.append((time.monotonic(), line))
            if "event=sidecar_ready" in line:
                ready.set()

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    children = []
    try:
        if not ready.wait(20):
            raise RuntimeError("desktop production bootstrap failed; " + "\n".join(line for _, line in lines[-8:]))
        parent = psutil.Process(process.pid)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            children = parent.children(recursive=True)
            if any("webview2" in p.name().lower() for p in children):
                break
            time.sleep(0.05)
        ram = {"rust_desktop_mib": parent.memory_info().rss / 1048576,
               "webview2_mib": 0.0, "python_mib": 0.0}
        python_ids = []
        for p in children:
            try:
                name = p.name().lower()
                if "webview2" in name:
                    ram["webview2_mib"] += p.memory_info().rss / 1048576
                elif "python" in name:
                    ram["python_mib"] += p.memory_info().rss / 1048576
                    python_ids.append(p.pid)
            except psutil.NoSuchProcess:
                pass
        if not python_ids:
            raise AssertionError("production Python child absent")
        metrics = [json.loads(line.split(" json=", 1)[1]) for _, line in lines if "event=backend_metrics json=" in line]
        report = {"exit_kind": "forced" if forced else "normal", "python_pids": python_ids,
                  "desktop_to_sidecar_ready_ms": round((next(t for t, line in lines if "event=sidecar_ready" in line) - started) * 1000, 2),
                  "ram": {k: round(v, 2) for k, v in ram.items()}, "backend_metrics": metrics}
        if forced:
            process.kill()
        else:
            request_window_close(process.pid)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired as error:
            report["stderr_tail"] = [line for _, line in lines[-12:]]
            raise RuntimeError("Desktop exit timed out: " + json.dumps(report)) from error
        _, alive = psutil.wait_procs(children, timeout=5)
        remaining_python = [p.pid for p in alive if p.pid in python_ids]
        report["orphan_python_pids"] = remaining_python
        if remaining_python:
            raise AssertionError(f"orphan Python: {remaining_python}")
        return report
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        reader.join(timeout=3)
        process.stdout.close()
        process.stderr.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop-exe", type=Path, help="also verify normal/forced built Windows desktop exit and RAM")
    parser.add_argument("--report", type=Path, help="write the read-only smoke report to this explicit artifact path")
    args = parser.parse_args()
    composition = ProductionComposition()
    settings_hash = hash_file(composition.settings.config_file)
    health = asyncio.run(composition.refresh())
    host = health["ollama"]["host"]
    before = read_api(host, "/api/ps")
    report = {"health": health, "ollama_version": read_api(host, "/api/version"),
              "models_before": before, "generation_requests": 0}
    try:
        result = subprocess.run(["cargo", "test", "production_real_read_only_smoke", "--", "--ignored", "--nocapture"],
                                cwd=ROOT / "prototype/aurora-v4/desktop/src-tauri", capture_output=True,
                                timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        report["rust_gateway_passed"] = result.returncode == 0
        for line in text.splitlines():
            for label in ("PRODUCTION_INITIAL", "PRODUCTION_RESTART", "PRODUCTION_PID"):
                if line.startswith(label + "="):
                    report[label.lower()] = json.loads(line.split("=", 1)[1])
        if result.returncode:
            raise RuntimeError(text)
        if args.desktop_exe:
            with tempfile.TemporaryDirectory(prefix="aurora-v4-foreign-cwd-") as directory:
                report["desktop"] = []
                for forced in (False, True):
                    report["desktop"].append(desktop_probe(args.desktop_exe.resolve(), forced=forced, cwd=directory))
    finally:
        report["models_after"] = read_api(host, "/api/ps")
        report["model_inventory_unchanged"] = (report["models_after"] == before
            if isinstance(before, list) and isinstance(report["models_after"], list) else None)
        report["settings_unchanged"] = hash_file(composition.settings.config_file) == settings_hash
        composition.close()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.report:
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["settings_unchanged"]:
        raise AssertionError("settings changed during read-only smoke")


if __name__ == "__main__":
    main()

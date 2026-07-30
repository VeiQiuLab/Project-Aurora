"""Background service lifecycle helpers for local Aurora services."""

import socket
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import shutil
import shlex
import json

try:
    import psutil
except ImportError:
    psutil = None


DEFAULT_DOCKER_DESKTOP_PATH = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
OLLAMA_PROCESS_NAMES = {"ollama.exe", "ollama app.exe"}


class ServiceManager:
    """Start and probe configured services without blocking the GUI."""

    def __init__(self):
        self.processes = {}
        self.process_metadata = {}
        self.ollama_pre_start_snapshot = {}
        self.ollama_after_start_snapshot = {}
        self.ollama_owned_processes = {}
        self.ollama_start_time = None
        self.ollama_executable_path = ""
        self.ollama_root_pid = 0
        self.ollama_lifecycle_debug = {
            "started_by_app": False,
            "resolved_executable": "",
            "root_pid": 0,
            "started_at": "",
            "before_snapshot": [],
            "after_start_snapshot": [],
            "owned_pids": [],
            "shutdown_actions": [],
            "after_shutdown_snapshot": [],
            "errors": []
        }
        self._lock = threading.Lock()

    @staticmethod
    def _hidden_window_flags():
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    @staticmethod
    def endpoint(url, default_host="localhost", default_port=8080):
        parsed = urllib.parse.urlparse(str(url or ""))
        return parsed.hostname or default_host, parsed.port or default_port

    @staticmethod
    def is_online(host="localhost", port=8080, timeout=1.0):
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True
        except (OSError, ValueError, TypeError):
            return False

    @staticmethod
    def command_executable_path(command):
        try:
            parts = shlex.split(str(command or ""), posix=False)
        except ValueError:
            parts = []
        executable = str(parts[0] if parts else "").strip().strip('"')
        return shutil.which(executable) or executable

    @staticmethod
    def same_install_dir(path_a, path_b):
        if not path_a or not path_b:
            return False
        try:
            return os.path.dirname(os.path.abspath(path_a)).casefold() == os.path.dirname(os.path.abspath(path_b)).casefold()
        except (OSError, ValueError):
            return False

    @staticmethod
    def process_summary(snapshot):
        return [
            {
                "pid": pid,
                "name": item.get("name", ""),
                "exe": item.get("exe", ""),
                "cmdline": item.get("cmdline", ""),
                "ppid": item.get("ppid"),
                "create_time": item.get("create_time"),
                "session_id": item.get("session_id"),
                "alive": item.get("alive", True),
                "owned_candidate": item.get("owned_candidate", False),
                "ownership_reason": item.get("ownership_reason", "")
            }
            for pid, item in sorted((snapshot or {}).items())
        ]

    @staticmethod
    def log_process_snapshot(logger, marker, snapshot):
        lines = [marker]
        for item in ServiceManager.process_summary(snapshot):
            lines.append(
                "pid={pid}, name={name}, ppid={ppid}, session={session_id}, "
                "alive={alive}, owned_candidate={owned_candidate}, reason={ownership_reason}, "
                "exe={exe}, cmdline={cmdline}, create_time={create_time}".format(**item)
            )
        if len(lines) == 1:
            lines.append("none")
        message = "\n".join(lines)
        if logger is not None:
            try:
                logger.info(message)
                return
            except Exception:
                pass
        print(message)

    @staticmethod
    def _parse_powershell_create_time(value):
        text = str(value or "").strip()
        if not text:
            return 0.0
        if text.startswith("/Date("):
            try:
                milliseconds = int(text.split("(", 1)[1].split(")", 1)[0])
                return milliseconds / 1000.0
            except (ValueError, IndexError):
                return 0.0
        try:
            return time.mktime(time.strptime(text[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError):
            pass
        try:
            # CIM datetime format: 20260730123045.123456+480
            parsed = time.strptime(text[:14], "%Y%m%d%H%M%S")
            return time.mktime(parsed)
        except (ValueError, TypeError):
            return 0.0

    @classmethod
    def ollama_process_snapshot(cls):
        if psutil is not None:
            snapshot = {}
            for process in psutil.process_iter(["pid", "name", "exe", "create_time", "ppid", "cmdline"]):
                try:
                    info = process.info
                    name = str(info.get("name") or "").casefold()
                    if name not in OLLAMA_PROCESS_NAMES:
                        continue
                    pid = int(info.get("pid"))
                    snapshot[pid] = {
                        "pid": pid,
                        "name": str(info.get("name") or ""),
                        "exe": str(info.get("exe") or ""),
                        "cmdline": " ".join(str(part) for part in (info.get("cmdline") or [])),
                        "ppid": info.get("ppid"),
                        "create_time": float(info.get("create_time") or 0.0),
                        "session_id": "",
                        "alive": process.is_running()
                    }
                except (psutil.Error, OSError, ValueError, TypeError):
                    continue
            return snapshot

        if os.name != "nt":
            return {}
        script = (
            "$names = @('ollama.exe','ollama app.exe'); "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $names -contains $_.Name.ToLower() } | "
            "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine,CreationDate,SessionId | "
            "ConvertTo-Json -Compress"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=cls._hidden_window_flags()
            )
        except (OSError, subprocess.TimeoutExpired):
            return {}
        text = result.stdout.strip()
        if text:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = []
            if isinstance(payload, dict):
                items = [payload]
            elif isinstance(payload, list):
                items = payload
            else:
                items = []
        else:
            items = []
        snapshot = {}
        for item in items:
            try:
                pid = int(item.get("ProcessId"))
            except (TypeError, ValueError, AttributeError):
                continue
            name = str(item.get("Name") or "")
            if name.casefold() not in OLLAMA_PROCESS_NAMES:
                continue
            snapshot[pid] = {
                "pid": pid,
                "name": name,
                "exe": str(item.get("ExecutablePath") or ""),
                "cmdline": str(item.get("CommandLine") or ""),
                "ppid": item.get("ParentProcessId"),
                "create_time": cls._parse_powershell_create_time(item.get("CreationDate")),
                "session_id": item.get("SessionId"),
                "alive": True
            }
        if snapshot:
            return snapshot

        fallback_script = (
            "$names = @('ollama','ollama app'); "
            "Get-Process | "
            "Where-Object { $names -contains $_.ProcessName.ToLower() } | "
            "Select-Object Id,ProcessName,Path,StartTime,SessionId | "
            "ConvertTo-Json -Compress"
        )
        try:
            fallback = subprocess.run(
                ["powershell", "-NoProfile", "-Command", fallback_script],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=cls._hidden_window_flags()
            )
        except (OSError, subprocess.TimeoutExpired):
            return {}
        text = fallback.stdout.strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(payload, dict):
            items = [payload]
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        snapshot = {}
        for item in items:
            try:
                pid = int(item.get("Id"))
            except (TypeError, ValueError, AttributeError):
                continue
            process_name = str(item.get("ProcessName") or "")
            name = process_name if process_name.casefold().endswith(".exe") else f"{process_name}.exe"
            if name.casefold() not in OLLAMA_PROCESS_NAMES:
                continue
            snapshot[pid] = {
                "pid": pid,
                "name": name,
                "exe": str(item.get("Path") or ""),
                "cmdline": "",
                "ppid": "",
                "create_time": cls._parse_powershell_create_time(item.get("StartTime")),
                "session_id": item.get("SessionId"),
                "alive": True,
                "ownership_reason": "Process snapshot used Get-Process fallback; command line and parent PID unavailable."
            }
        return snapshot

    def record_ollama_start_snapshot(self, command):
        executable_path = self.command_executable_path(command)
        snapshot = self.ollama_process_snapshot()
        started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self.ollama_pre_start_snapshot = snapshot
            self.ollama_after_start_snapshot = {}
            self.ollama_owned_processes = {}
            self.ollama_start_time = time.time()
            self.ollama_executable_path = executable_path
            self.ollama_root_pid = 0
            self.ollama_lifecycle_debug = {
                "started_by_app": False,
                "resolved_executable": executable_path,
                "root_pid": 0,
                "started_at": started_at,
                "before_snapshot": self.process_summary(snapshot),
                "after_start_snapshot": [],
                "owned_pids": [],
                "shutdown_actions": [],
                "after_shutdown_snapshot": [],
                "errors": []
            }
        self.write_ollama_lifecycle_debug()
        return snapshot

    def write_ollama_lifecycle_debug(self, path="logs/ollama_lifecycle_debug.json"):
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(path, "w", encoding="utf-8") as file:
                json.dump(self.ollama_lifecycle_debug, file, indent=2, ensure_ascii=False)
        except OSError as error:
            with self._lock:
                self.ollama_lifecycle_debug.setdefault("errors", []).append(str(error))

    def _annotate_ollama_ownership(self, snapshot):
        with self._lock:
            before = dict(self.ollama_pre_start_snapshot)
            start_time = float(self.ollama_start_time or 0.0)
            executable_path = self.ollama_executable_path
        annotated = {}
        for pid, item in (snapshot or {}).items():
            record = dict(item)
            reasons = []
            owned = True
            if pid in before:
                owned = False
                reasons.append("preexisting before Aurora start")
            create_time = float(item.get("create_time") or 0.0)
            if start_time and create_time and create_time + 1 < start_time:
                owned = False
                reasons.append("created before Aurora start time")
            exe = str(item.get("exe") or "")
            if executable_path and exe and not (
                os.path.abspath(exe).casefold() == os.path.abspath(executable_path).casefold()
                or self.same_install_dir(exe, executable_path)
            ):
                owned = False
                reasons.append("executable path does not match Aurora Ollama path")
            if owned:
                reasons.append("new process after Aurora start with matching path")
            record["owned_candidate"] = owned
            record["ownership_reason"] = "; ".join(reasons)
            annotated[pid] = record
        return annotated

    def record_ollama_owned_processes(self):
        after = self._annotate_ollama_ownership(self.ollama_process_snapshot())
        owned = {}
        for pid, item in after.items():
            if item.get("owned_candidate"):
                owned[pid] = item
        root_metadata = self.service_process_metadata("ollama")
        root_pid = root_metadata.get("pid")
        if root_pid:
            owned.setdefault(int(root_pid), {
                "pid": int(root_pid),
                "name": "ollama-root",
                "exe": str(root_metadata.get("executable_path") or ""),
                "cmdline": str(root_metadata.get("command") or ""),
                "ppid": "",
                "create_time": float(self.ollama_start_time or 0.0),
                "session_id": "",
                "alive": self.process_exists(int(root_pid)),
                "owned_candidate": True,
                "ownership_reason": "Aurora root Popen PID"
            })
        with self._lock:
            self.ollama_after_start_snapshot = after
            self.ollama_owned_processes = owned
            self.ollama_lifecycle_debug["started_by_app"] = bool(owned)
            self.ollama_lifecycle_debug["root_pid"] = int(root_pid or 0)
            self.ollama_lifecycle_debug["after_start_snapshot"] = self.process_summary(after)
            self.ollama_lifecycle_debug["owned_pids"] = self.process_summary(owned)
        self.write_ollama_lifecycle_debug()
        return owned

    @staticmethod
    def process_exists(pid):
        if not pid:
            return False
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
                creationflags=ServiceManager._hidden_window_flags()
            )
            return str(int(pid)) in result.stdout
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return False

    def record_process_children(self, service_name, pid):
        children = self.descendant_pids(pid)
        with self._lock:
            metadata = self.process_metadata.setdefault(service_name, {})
            known = list(metadata.get("child_pids", []))
            for child_pid in children:
                if child_pid not in known:
                    known.append(child_pid)
            metadata["child_pids"] = known
        return children

    @staticmethod
    def descendant_pids(pid):
        if os.name != "nt" or not pid:
            return []
        script = (
            "$root = " + str(int(pid)) + "; "
            "$all = Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId; "
            "$queue = @($root); $children = @(); "
            "while ($queue.Count -gt 0) { "
            "$parent = $queue[0]; "
            "if ($queue.Count -gt 1) { $queue = $queue[1..($queue.Count - 1)] } else { $queue = @() }; "
            "$found = $all | Where-Object { $_.ParentProcessId -eq $parent }; "
            "foreach ($item in $found) { $children += $item.ProcessId; $queue += $item.ProcessId } "
            "}; "
            "$children"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=ServiceManager._hidden_window_flags()
            )
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return []
        pids = []
        for line in result.stdout.splitlines():
            try:
                value = int(line.strip())
            except ValueError:
                continue
            if value and value != int(pid):
                pids.append(value)
        return pids

    @staticmethod
    def kill_pid_tree(pid, timeout=8):
        if not pid:
            return False
        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout,
                    check=False,
                    creationflags=ServiceManager._hidden_window_flags()
                )
                return result.returncode == 0
            except (OSError, subprocess.TimeoutExpired, ValueError):
                return False
        return False

    def start_service(self, service_name, command, url, callback=None, timeout=30):
        host, port = self.endpoint(url)

        def notify(event):
            if callback:
                callback(event)

        def run():
            if self.is_online(host, port):
                notify("online")
                return
            notify("starting")
            try:
                executable_path = self.command_executable_path(command)
                if executable_path and not os.path.exists(executable_path) and shutil.which(executable_path) is None:
                    notify("command_not_found")
                    return
                process = subprocess.Popen(
                    str(command),
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=ServiceManager._hidden_window_flags()
                )
                with self._lock:
                    self.processes[service_name] = process
                    self.process_metadata[service_name] = {
                        "pid": process.pid,
                        "command": str(command),
                        "executable_path": executable_path,
                        "started_at": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
            except (OSError, ValueError):
                notify("failed")
                return

            deadline = time.monotonic() + max(1, float(timeout))
            while time.monotonic() < deadline:
                self.record_process_children(service_name, process.pid)
                if self.is_online(host, port):
                    notify("started")
                    return
                if process.poll() is not None:
                    notify("failed")
                    return
                time.sleep(1)
            notify("failed")

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    def start_open_webui(self, command, url, callback=None, timeout=30):
        return self.start_service("openwebui", command, url, callback, timeout)

    def start_ollama(self, command, url, callback=None, timeout=30):
        host, port = self.endpoint(url, "127.0.0.1", 11434)
        before = self.record_ollama_start_snapshot(command)

        def notify(event):
            if callback:
                callback(event)

        notify({
            "event": "ollama_snapshot_before_start",
            "processes": self.process_summary(before)
        })

        def run():
            if self.is_online(host, port):
                notify("online")
                return
            notify("starting")
            try:
                parts = shlex.split(str(command or "ollama serve"), posix=False)
            except ValueError:
                parts = ["ollama", "serve"]
            if not parts:
                parts = ["ollama", "serve"]
            executable = shutil.which(str(parts[0]).strip('"'))
            if not executable:
                notify("command_not_found")
                return
            args = [executable] + [str(part).strip('"') for part in parts[1:]]
            if len(args) == 1:
                args.append("serve")
            try:
                process = subprocess.Popen(
                    args,
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=ServiceManager._hidden_window_flags()
                )
                with self._lock:
                    self.processes["ollama"] = process
                    self.ollama_root_pid = process.pid
                    self.ollama_executable_path = executable
                    self.process_metadata["ollama"] = {
                        "pid": process.pid,
                        "command": " ".join(args),
                        "args": args,
                        "executable_path": executable,
                        "started_at": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                    self.ollama_lifecycle_debug["resolved_executable"] = executable
                    self.ollama_lifecycle_debug["root_pid"] = process.pid
            except (OSError, ValueError) as error:
                with self._lock:
                    self.ollama_lifecycle_debug.setdefault("errors", []).append(str(error))
                notify("failed")
                return

            notify({
                "event": "ollama_root_started",
                "pid": process.pid,
                "executable": executable,
                "args": args
            })
            deadline = time.monotonic() + max(1, float(timeout))
            while time.monotonic() < deadline:
                self.record_process_children("ollama", process.pid)
                if self.is_online(host, port):
                    after = self._annotate_ollama_ownership(self.ollama_process_snapshot())
                    with self._lock:
                        self.ollama_after_start_snapshot = after
                        self.ollama_lifecycle_debug["after_start_snapshot"] = self.process_summary(after)
                    notify({
                        "event": "ollama_snapshot_after_start",
                        "processes": self.process_summary(after)
                    })
                    owned = self.record_ollama_owned_processes()
                    notify({
                        "event": "ollama_owned_processes",
                        "processes": self.process_summary(owned)
                    })
                    notify("started")
                    return
                if process.poll() is not None:
                    notify("failed")
                    return
                time.sleep(1)
            notify("failed")

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    def service_process_metadata(self, service_name):
        with self._lock:
            return dict(self.process_metadata.get(service_name, {}))

    def stop_tracked_process_tree(self, service_name, terminate_timeout=3, kill_timeout=8):
        with self._lock:
            process = self.processes.get(service_name)
            metadata = dict(self.process_metadata.get(service_name, {}))
        if process is None:
            return {
                "ok": True,
                "service": service_name,
                "pid": metadata.get("pid"),
                "state": "not_tracked",
                "children": []
            }

        pid = process.pid
        children = list(metadata.get("child_pids", []))
        for child_pid in self.descendant_pids(pid):
            if child_pid not in children:
                children.append(child_pid)
        for child_pid in list(children):
            for nested_pid in self.descendant_pids(child_pid):
                if nested_pid not in children:
                    children.append(nested_pid)
        result = {
            "ok": True,
            "service": service_name,
            "pid": pid,
            "children": children,
            "state": "stopped",
            "terminated": False,
            "killed": []
        }

        if process.poll() is None:
            try:
                process.terminate()
                result["terminated"] = True
                process.wait(timeout=terminate_timeout)
            except subprocess.TimeoutExpired:
                result["state"] = "terminate_timeout"
            except OSError:
                result["state"] = "terminate_failed"

        remaining = []
        if process.poll() is None and self.process_exists(pid):
            remaining.append(pid)
        remaining.extend(child for child in children if self.process_exists(child))

        for target_pid in dict.fromkeys(remaining):
            if self.kill_pid_tree(target_pid, timeout=kill_timeout):
                result["killed"].append(target_pid)

        still_running = []
        if self.process_exists(pid):
            still_running.append(pid)
        still_running.extend(child for child in children if self.process_exists(child))
        result["still_running"] = list(dict.fromkeys(still_running))
        result["ok"] = not result["still_running"]
        if result["still_running"]:
            result["state"] = "residual_process"
        return result

    def _terminate_pid(self, pid, timeout=3):
        outcome = {"pid": int(pid), "terminated": False, "killed": False, "taskkill": False, "error": ""}
        if psutil is not None:
            try:
                process = psutil.Process(int(pid))
                process.terminate()
                outcome["terminated"] = True
                try:
                    process.wait(timeout=timeout)
                    return outcome
                except psutil.TimeoutExpired:
                    process.kill()
                    outcome["killed"] = True
                    try:
                        process.wait(timeout=timeout)
                    except psutil.Error:
                        pass
                    return outcome
            except psutil.NoSuchProcess:
                outcome["terminated"] = True
                return outcome
            except (psutil.Error, OSError) as error:
                outcome["error"] = str(error)
        if self.kill_pid_tree(pid):
            outcome["taskkill"] = True
            outcome["killed"] = True
        return outcome

    def _ollama_residual_candidates(self, snapshot):
        candidates = {}
        for pid, item in self._annotate_ollama_ownership(snapshot).items():
            if item.get("owned_candidate"):
                candidates[pid] = item
        return candidates

    def _taskkill_image(self, image_name, timeout=5):
        try:
            result = subprocess.run(
                ["taskkill", "/IM", image_name, "/F"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                creationflags=self._hidden_window_flags()
            )
            return {
                "image": image_name,
                "returncode": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip()
            }
        except (OSError, subprocess.TimeoutExpired) as error:
            return {
                "image": image_name,
                "returncode": -1,
                "stdout": "",
                "stderr": str(error)
            }

    def stop_ollama_owned_processes(self, allow_image_fallback=False):
        with self._lock:
            before = dict(self.ollama_pre_start_snapshot)
            owned = dict(self.ollama_owned_processes)
        shutdown_begin = self._annotate_ollama_ownership(self.ollama_process_snapshot())
        result = {
            "before": self.process_summary(before),
            "shutdown_begin": self.process_summary(shutdown_begin),
            "owned": self.process_summary(owned),
            "terminated": [],
            "root_tree": {},
            "residual_candidates": [],
            "image_fallback": [],
            "remaining": [],
            "image_fallback_allowed": False
        }

        for pid in list(owned):
            result["terminated"].append(self._terminate_pid(pid))

        result["root_tree"] = self.stop_tracked_process_tree("ollama")

        after_pid_cleanup = self.ollama_process_snapshot()
        candidates = self._ollama_residual_candidates(after_pid_cleanup)
        result["residual_candidates"] = self.process_summary(candidates)
        for pid in list(candidates):
            result["terminated"].append(self._terminate_pid(pid))

        remaining = self.ollama_process_snapshot()
        remaining_candidates = self._ollama_residual_candidates(remaining)
        fallback_allowed = bool(
            allow_image_fallback
            and not before
            and owned
            and remaining_candidates
            and len(remaining_candidates) == len(remaining)
        )
        result["image_fallback_allowed"] = fallback_allowed
        if fallback_allowed:
            names = {
                str(item.get("name") or "").casefold()
                for item in remaining_candidates.values()
                if str(item.get("name") or "").casefold() in OLLAMA_PROCESS_NAMES
            }
            for image_name in sorted(names):
                result["image_fallback"].append(self._taskkill_image(image_name))

        final_snapshot = self.ollama_process_snapshot()
        final_candidates = self._ollama_residual_candidates(final_snapshot)
        result["remaining"] = self.process_summary(final_snapshot)
        result["remaining_owned_candidates"] = self.process_summary(final_candidates)
        result["ok"] = not final_candidates
        with self._lock:
            self.ollama_lifecycle_debug["shutdown_actions"] = (
                result["terminated"]
                + [{"root_tree": result["root_tree"]}]
                + [{"image_fallback": item} for item in result["image_fallback"]]
            )
            self.ollama_lifecycle_debug["after_shutdown_snapshot"] = result["remaining"]
            if not result["ok"]:
                self.ollama_lifecycle_debug.setdefault("errors", []).append(
                    f"Ollama shutdown incomplete: {result['remaining_owned_candidates']}"
                )
        self.write_ollama_lifecycle_debug()
        return result

    @staticmethod
    def docker_available(timeout=5):
        if shutil.which("docker") is None:
            return False
        try:
            result = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
                creationflags=ServiceManager._hidden_window_flags()
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def docker_engine_ready(timeout=5):
        """Return whether the Docker Engine responds to ``docker info``."""
        return ServiceManager.docker_available(timeout)

    @staticmethod
    def docker_desktop_running(timeout=3):
        """Check Docker Desktop process state without showing a console window."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Docker Desktop.exe"],
                capture_output=True, text=True, timeout=timeout, check=False,
                creationflags=ServiceManager._hidden_window_flags()
            )
            return "docker desktop.exe" in result.stdout.casefold()
        except (OSError, subprocess.TimeoutExpired):
            return False

    def start_docker_desktop(self, command="docker desktop start", callback=None,
                             timeout=60, path=None):
        """Start Docker Desktop from configured path, then wait for Engine readiness."""
        def notify(event):
            if callback:
                callback(event)

        def run():
            if self.docker_engine_ready():
                notify("engine_ready")
                return
            notify("starting_docker")
            try:
                launch_path = str(path or "").strip()
                if launch_path:
                    if not os.path.exists(launch_path):
                        notify("path_not_found")
                        return
                    subprocess.Popen(
                        [launch_path], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=ServiceManager._hidden_window_flags()
                    )
                else:
                    executable = str(command).strip().split()[0] if str(command).strip() else ""
                    if executable and shutil.which(executable) is None:
                        notify("command_not_found")
                        return
                    result = subprocess.run(
                        str(command), shell=True, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=30, check=False,
                        creationflags=ServiceManager._hidden_window_flags()
                    )
                    if result.returncode != 0:
                        notify("docker_start_failed")
                        return
            except (OSError, subprocess.TimeoutExpired):
                notify("docker_start_failed")
                return
            notify("waiting_engine")
            deadline = time.monotonic() + max(1, float(timeout))
            while time.monotonic() < deadline:
                if self.docker_engine_ready():
                    notify("desktop_started")
                    notify("engine_ready")
                    return
                time.sleep(1)
            notify("engine_timeout")

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    @staticmethod
    def docker_container_status(container_name, timeout=5):
        if not container_name or not ServiceManager.docker_available(timeout):
            return "docker_unavailable"
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Status}}", container_name],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                creationflags=ServiceManager._hidden_window_flags()
            )
        except (OSError, subprocess.TimeoutExpired):
            return "docker_unavailable"
        if result.returncode != 0:
            return "not_found"
        status = result.stdout.strip().casefold()
        return "running" if status == "running" else "stopped"

    @staticmethod
    def _http_probe(url, path="", timeout=3):
        target = str(url).rstrip("/") + str(path)
        try:
            with urllib.request.urlopen(target, timeout=timeout) as response:
                return True, int(getattr(response, "status", 200)), ""
        except urllib.error.HTTPError as error:
            return False, int(error.code), f"HTTP {error.code}"
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as error:
            return False, 0, str(error.reason if isinstance(error, urllib.error.URLError) else error)

    @classmethod
    def diagnose_ollama(cls, url="http://127.0.0.1:11434", timeout=3):
        """Validate both Ollama's port and its tags API."""
        host, port = cls.endpoint(url, "127.0.0.1", 11434)
        if not cls.is_online(host, port, timeout=timeout):
            return {"status": "Offline", "available": False, "reason": "Port unavailable"}
        ok, code, reason = cls._http_probe(url, "/api/tags", timeout)
        if ok:
            return {"status": "Online", "available": True, "reason": "API available", "http_status": code}
        return {"status": "Error", "available": False, "reason": reason or "API unavailable", "http_status": code}

    @classmethod
    def diagnose_docker(cls, timeout=3):
        running = cls.docker_desktop_running(timeout)
        ready = cls.docker_engine_ready(timeout)
        if ready:
            status = "Running"
        elif running:
            status = "Engine Not Ready"
        else:
            status = "Not Running"
        return {"status": status, "desktop_running": running, "engine_ready": ready}

    @classmethod
    def diagnose_openwebui(cls, container_name="open-webui", url="http://localhost:8080", timeout=3):
        container = cls.docker_container_status(container_name, timeout)
        http_ok, code, reason = cls._http_probe(url, "", timeout)
        basic_ok, basic_code, basic_reason = cls._http_probe(url, "/api/config", timeout)
        basic_ok = basic_ok or basic_code == 401
        if container == "running" and http_ok and basic_ok:
            return {"status": "Running", "available": True, "container": container, "http": True, "reason": "HTTP and API available", "http_status": code}
        if container == "running" and not http_ok and cls.is_online(*cls.endpoint(url), timeout=timeout):
            return {"status": "Error", "available": False, "container": container, "http": False, "reason": reason or "Open WebUI connection failed", "http_status": code}
        if container == "running" and http_ok and not basic_ok:
            return {"status": "Error", "available": False, "container": container, "http": True, "reason": basic_reason or f"API HTTP {basic_code}", "http_status": basic_code}
        if container == "stopped":
            return {"status": "Offline", "available": False, "container": container, "http": http_ok, "reason": "Container stopped"}
        if container == "docker_unavailable":
            return {"status": "Offline", "available": False, "container": container, "http": http_ok, "reason": "Docker Engine unavailable"}
        if container == "not_found":
            return {"status": "Offline", "available": False, "container": container, "http": http_ok, "reason": "Container not found"}
        return {"status": "Starting", "available": False, "container": container, "http": http_ok, "reason": reason or "Waiting for Open WebUI"}

    @classmethod
    def diagnose_all(cls, ollama_url, openwebui_url, container_name="open-webui", timeout=3):
        """Run all diagnostics synchronously; callers should invoke from a worker thread."""
        return {
            "ollama": cls.diagnose_ollama(ollama_url, timeout),
            "docker": cls.diagnose_docker(timeout),
            "openwebui": cls.diagnose_openwebui(container_name, openwebui_url, timeout)
        }

    def start_open_webui_docker(self, container_name, url, callback=None, timeout=30):
        host, port = self.endpoint(url)

        def notify(event):
            if callback:
                callback(event)

        def run():
            status = self.docker_container_status(container_name)
            if status == "docker_unavailable":
                notify("docker_unavailable")
                return
            if status == "not_found":
                notify("container_not_found")
                return
            if status == "stopped":
                notify("starting_container")
                try:
                    result = subprocess.run(
                        ["docker", "start", container_name],
                        capture_output=True,
                        text=True,
                        timeout=15,
                        check=False,
                        creationflags=ServiceManager._hidden_window_flags()
                    )
                except (OSError, subprocess.TimeoutExpired):
                    notify("container_start_failed")
                    return
                if result.returncode != 0:
                    notify("container_start_failed")
                    return
                notify("container_started")

            deadline = time.monotonic() + max(1, float(timeout))
            while time.monotonic() < deadline:
                if self.is_online(host, port):
                    notify("started")
                    return
                time.sleep(1)
            notify("timeout")

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    def start_open_webui_docker_with_engine(self, container_name, url,
                                            docker_command="docker desktop start",
                                            callback=None, timeout=30,
                                            docker_path=None, engine_timeout=60):
        """Ensure Docker Engine is ready, then start the configured container."""
        def notify(event):
            if callback:
                callback(event)

        def after_engine(event):
            notify(event)
            if event == "engine_ready":
                self.start_open_webui_docker(container_name, url, callback=notify, timeout=timeout)

        if self.docker_engine_ready():
            return self.start_open_webui_docker(container_name, url, callback=notify, timeout=timeout)
        return self.start_docker_desktop(
            docker_command, callback=after_engine, timeout=engine_timeout,
            path=docker_path
        )

    def stop_open_webui_docker(self, container_name, callback=None, timeout=15):
        """Stop the Open WebUI container without blocking the GUI."""
        def notify(event):
            if callback:
                callback(event)

        def run():
            status = self.docker_container_status(container_name, timeout=timeout)
            if status in {"docker_unavailable", "not_found", "stopped"}:
                notify("stopped" if status == "stopped" else status)
                return
            notify("stopping_container")
            try:
                result = subprocess.run(
                    ["docker", "stop", container_name], stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=timeout, check=False,
                    creationflags=ServiceManager._hidden_window_flags()
                )
                notify("stopped" if result.returncode == 0 else "stop_failed")
            except (OSError, subprocess.TimeoutExpired):
                notify("stop_failed")

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    def stop_docker_desktop(self, command="docker desktop stop", callback=None, timeout=30):
        """Optionally stop Docker Desktop through a configured command."""
        def run():
            try:
                result = subprocess.run(
                    str(command), shell=True, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=timeout, check=False,
                    creationflags=ServiceManager._hidden_window_flags()
                )
                if callback:
                    callback("stopped" if result.returncode == 0 else "stop_failed")
            except (OSError, subprocess.TimeoutExpired):
                if callback:
                    callback("stop_failed")
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

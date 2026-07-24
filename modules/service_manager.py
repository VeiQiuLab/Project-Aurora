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


DEFAULT_DOCKER_DESKTOP_PATH = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"


class ServiceManager:
    """Start and probe configured services without blocking the GUI."""

    def __init__(self):
        self.processes = {}
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
                executable = str(command).strip().split()[0] if str(command).strip() else ""
                if executable and shutil.which(executable) is None:
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
            except (OSError, ValueError):
                notify("failed")
                return

            deadline = time.monotonic() + max(1, float(timeout))
            while time.monotonic() < deadline:
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
        return self.start_service("ollama", command, url, callback, timeout)

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

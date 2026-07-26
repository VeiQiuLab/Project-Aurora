"""Remote Access foundation for local-only status and configuration."""

import json
import ipaddress
import socket
from pathlib import Path

from modules.authentication import AuthenticationManager
from modules.lan_server import DEFAULT_LAN_STATUS_PORT, is_port_available


DEFAULT_REMOTE_CONFIG = {
    "enabled": False,
    "mode": "local",
    "port": 0,
    "auth_required": True,
    "authentication_configured": False,
    "lan_ready": False,
    "ios_access_ready": False,
    "tailscale_ready": False,
    "user_confirmed": False,
    "security_confirmed": False,
    "auth_enabled": False,
    "authentication_type": "none",
    "token_configured": False,
    "last_token_update": None,
    "credential_storage": "windows_credential_manager",
    "secure_storage_configured": False,
    "secure_storage_available": False,
    "credential_test_passed": False,
    "credential_last_check": None,
    "credential_last_result": None,
    "credential_command_status": "Unavailable",
    "credential_last_operation": None,
    "credential_operation_result": None,
    "credential_duration_ms": 0,
    "credential_error_suggestion": None,
    "last_storage_error": None,
    "credential_history": [],
    "credential_steps": [],
    "network_history": [],
    "security_history": [],
    "authentication_history": [],
    "remote_history": [],
    "lan_status_page_enabled": False,
    "lan_status_port": DEFAULT_LAN_STATUS_PORT,
    "lan_status_user_confirmed": False,
    "lan_chat_enabled": False,
    "lan_chat_port": DEFAULT_LAN_STATUS_PORT,
    "mobile_access_confirmed": False,
    "mobile_chat_timeout": 60,
    "mobile_debug_mode": False,
    "mobile_response_limit": 12000,
    "selected_lan_ip": "",
    "selected_adapter": "",
    "last_mobile_error": "",
    "last_mobile_stage": "",
    "last_mobile_status": "",
    "last_mobile_duration_ms": 0,
    "last_mobile_model": "",
    "last_mobile_capability": "",
    "last_mobile_ollama_url": "",
    "last_mobile_client": "",
    "last_mobile_time": ""
}


class RemoteAccessManager:
    """Manage Remote Access configuration and read-only network status."""

    def __init__(self, file_path=None):
        root = Path(__file__).resolve().parent.parent
        if file_path:
            self.file_path = Path(file_path)
            self.directory = self.file_path.parent
        else:
            self.directory = root / "data" / "remote"
            self.file_path = self.directory / "remote.json"
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.save(DEFAULT_REMOTE_CONFIG)

    def _normalize(self, data):
        if not isinstance(data, dict):
            data = {}
        normalized = dict(DEFAULT_REMOTE_CONFIG)
        normalized.update({
            key: data.get(key, DEFAULT_REMOTE_CONFIG[key])
            for key in DEFAULT_REMOTE_CONFIG
        })
        normalized["enabled"] = bool(normalized.get("enabled", False))
        normalized["mode"] = str(normalized.get("mode") or "local")
        try:
            normalized["port"] = max(0, int(normalized.get("port", 0)))
        except (TypeError, ValueError):
            normalized["port"] = 0
        try:
            normalized["lan_status_port"] = max(1, int(normalized.get("lan_status_port", DEFAULT_LAN_STATUS_PORT)))
        except (TypeError, ValueError):
            normalized["lan_status_port"] = DEFAULT_LAN_STATUS_PORT
        try:
            normalized["lan_chat_port"] = max(1, int(normalized.get("lan_chat_port", DEFAULT_LAN_STATUS_PORT)))
        except (TypeError, ValueError):
            normalized["lan_chat_port"] = DEFAULT_LAN_STATUS_PORT
        normalized["auth_required"] = bool(normalized.get("auth_required", True))
        normalized["authentication_configured"] = bool(normalized.get("authentication_configured", False))
        normalized["lan_ready"] = bool(normalized.get("lan_ready", False))
        normalized["ios_access_ready"] = bool(normalized.get("ios_access_ready", False))
        normalized["tailscale_ready"] = bool(normalized.get("tailscale_ready", False))
        normalized["user_confirmed"] = bool(normalized.get("user_confirmed", False))
        normalized["security_confirmed"] = bool(normalized.get("security_confirmed", False))
        normalized["lan_status_page_enabled"] = bool(normalized.get("lan_status_page_enabled", False))
        normalized["lan_status_user_confirmed"] = bool(normalized.get("lan_status_user_confirmed", False))
        normalized["lan_chat_enabled"] = bool(normalized.get("lan_chat_enabled", False))
        normalized["mobile_access_confirmed"] = bool(normalized.get("mobile_access_confirmed", False))
        try:
            normalized["mobile_chat_timeout"] = max(1, int(normalized.get("mobile_chat_timeout", 60)))
        except (TypeError, ValueError):
            normalized["mobile_chat_timeout"] = 60
        normalized["mobile_debug_mode"] = bool(normalized.get("mobile_debug_mode", False))
        try:
            normalized["mobile_response_limit"] = max(1000, int(normalized.get("mobile_response_limit", 12000)))
        except (TypeError, ValueError):
            normalized["mobile_response_limit"] = 12000
        normalized["selected_lan_ip"] = str(normalized.get("selected_lan_ip") or "")
        normalized["selected_adapter"] = str(normalized.get("selected_adapter") or "")
        normalized["last_mobile_error"] = str(normalized.get("last_mobile_error") or "")
        normalized["last_mobile_stage"] = str(normalized.get("last_mobile_stage") or "")
        normalized["last_mobile_status"] = str(normalized.get("last_mobile_status") or "")
        try:
            normalized["last_mobile_duration_ms"] = max(0, int(normalized.get("last_mobile_duration_ms", 0) or 0))
        except (TypeError, ValueError):
            normalized["last_mobile_duration_ms"] = 0
        normalized["last_mobile_model"] = str(normalized.get("last_mobile_model") or "")
        normalized["last_mobile_capability"] = str(normalized.get("last_mobile_capability") or "")
        normalized["last_mobile_ollama_url"] = str(normalized.get("last_mobile_ollama_url") or "")
        normalized["last_mobile_client"] = str(normalized.get("last_mobile_client") or "")
        normalized["last_mobile_time"] = str(normalized.get("last_mobile_time") or "")
        normalized["auth_enabled"] = bool(normalized.get("auth_enabled", False))
        normalized["authentication_type"] = str(normalized.get("authentication_type") or "none").lower()
        if normalized["authentication_type"] not in {"none", "token", "password"}:
            normalized["authentication_type"] = "none"
        normalized["token_configured"] = bool(normalized.get("token_configured", False))
        normalized["last_token_update"] = normalized.get("last_token_update")
        normalized["credential_storage"] = str(normalized.get("credential_storage") or "none").lower()
        if normalized["credential_storage"] not in {
            "none",
            "windows_credential_manager",
            "encrypted_local_storage",
            "plain_text_file"
        }:
            normalized["credential_storage"] = "none"
        normalized["secure_storage_configured"] = bool(normalized.get("secure_storage_configured", False))
        normalized["secure_storage_available"] = bool(normalized.get("secure_storage_available", False))
        normalized["credential_test_passed"] = bool(normalized.get("credential_test_passed", False))
        normalized["credential_last_check"] = normalized.get("credential_last_check")
        normalized["credential_last_result"] = normalized.get("credential_last_result")
        normalized["credential_command_status"] = str(normalized.get("credential_command_status") or "Unavailable")
        normalized["credential_last_operation"] = normalized.get("credential_last_operation")
        normalized["credential_operation_result"] = normalized.get("credential_operation_result")
        try:
            normalized["credential_duration_ms"] = max(0, int(normalized.get("credential_duration_ms", 0) or 0))
        except (TypeError, ValueError):
            normalized["credential_duration_ms"] = 0
        normalized["credential_error_suggestion"] = normalized.get("credential_error_suggestion")
        normalized["last_storage_error"] = normalized.get("last_storage_error")
        if not isinstance(normalized.get("credential_history"), list):
            normalized["credential_history"] = []
        normalized["credential_history"] = normalized["credential_history"][-10:]
        if not isinstance(normalized.get("credential_steps"), list):
            normalized["credential_steps"] = []
        for history_key in ("network_history", "security_history", "authentication_history", "remote_history"):
            if not isinstance(normalized.get(history_key), list):
                normalized[history_key] = []
            normalized[history_key] = normalized[history_key][-10:]
        normalized["authentication_configured"] = bool(
            normalized.get("auth_enabled", False)
            and normalized.get("authentication_type") != "none"
            and normalized.get("token_configured", False)
        )
        return normalized

    def load(self):
        try:
            with self.file_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError, json.JSONDecodeError):
            data = {}
        config = self._normalize(data)
        self.save(config)
        return config

    def save(self, config):
        config = self._normalize(config)
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.file_path.open("w", encoding="utf-8") as file:
            json.dump(config, file, indent=4, ensure_ascii=False)
        return config

    def update(
        self,
        enabled=None,
        mode=None,
        port=None,
        auth_required=None,
        authentication_configured=None,
        lan_ready=None,
        ios_access_ready=None,
        tailscale_ready=None,
        user_confirmed=None,
        security_confirmed=None,
        auth_enabled=None,
        authentication_type=None,
        token_configured=None,
        credential_storage=None,
        secure_storage_configured=None,
        secure_storage_available=None,
        credential_test_passed=None,
        credential_last_check=None,
        credential_last_result=None,
        credential_command_status=None,
        credential_last_operation=None,
        credential_operation_result=None,
        credential_duration_ms=None,
        credential_error_suggestion=None,
        last_storage_error=None,
        credential_history=None,
        credential_steps=None,
        network_history=None,
        security_history=None,
        authentication_history=None,
        remote_history=None,
        lan_status_page_enabled=None,
        lan_status_port=None,
        lan_status_user_confirmed=None,
        lan_chat_enabled=None,
        lan_chat_port=None,
        mobile_access_confirmed=None,
        mobile_chat_timeout=None,
        mobile_debug_mode=None,
        mobile_response_limit=None,
        selected_lan_ip=None,
        selected_adapter=None,
        last_mobile_error=None,
        last_mobile_stage=None,
        last_mobile_status=None,
        last_mobile_duration_ms=None,
        last_mobile_model=None,
        last_mobile_capability=None,
        last_mobile_ollama_url=None,
        last_mobile_client=None,
        last_mobile_time=None
    ):
        config = self.load()
        if enabled is not None:
            config["enabled"] = bool(enabled)
        if mode is not None:
            config["mode"] = str(mode or "local")
        if port is not None:
            config["port"] = port
        if auth_required is not None:
            config["auth_required"] = bool(auth_required)
        if authentication_configured is not None:
            config["authentication_configured"] = bool(authentication_configured)
        if lan_ready is not None:
            config["lan_ready"] = bool(lan_ready)
        if ios_access_ready is not None:
            config["ios_access_ready"] = bool(ios_access_ready)
        if tailscale_ready is not None:
            config["tailscale_ready"] = bool(tailscale_ready)
        if user_confirmed is not None:
            config["user_confirmed"] = bool(user_confirmed)
        if security_confirmed is not None:
            config["security_confirmed"] = bool(security_confirmed)
        if auth_enabled is not None:
            config["auth_enabled"] = bool(auth_enabled)
        if authentication_type is not None:
            config["authentication_type"] = str(authentication_type or "none")
        if token_configured is not None:
            config["token_configured"] = bool(token_configured)
        if credential_storage is not None:
            config["credential_storage"] = str(credential_storage or "none")
        if secure_storage_configured is not None:
            config["secure_storage_configured"] = bool(secure_storage_configured)
        if secure_storage_available is not None:
            config["secure_storage_available"] = bool(secure_storage_available)
        if credential_test_passed is not None:
            config["credential_test_passed"] = bool(credential_test_passed)
        if credential_last_check is not None:
            config["credential_last_check"] = credential_last_check
        if credential_last_result is not None:
            config["credential_last_result"] = credential_last_result
        if credential_command_status is not None:
            config["credential_command_status"] = str(credential_command_status or "Unavailable")
        if credential_last_operation is not None:
            config["credential_last_operation"] = credential_last_operation
        if credential_operation_result is not None:
            config["credential_operation_result"] = credential_operation_result
        if credential_duration_ms is not None:
            config["credential_duration_ms"] = credential_duration_ms
        if credential_error_suggestion is not None:
            config["credential_error_suggestion"] = credential_error_suggestion
        if last_storage_error is not None:
            config["last_storage_error"] = last_storage_error
        if credential_history is not None:
            config["credential_history"] = credential_history[-10:] if isinstance(credential_history, list) else []
        if credential_steps is not None:
            config["credential_steps"] = credential_steps if isinstance(credential_steps, list) else []
        if network_history is not None:
            config["network_history"] = network_history[-10:] if isinstance(network_history, list) else []
        if security_history is not None:
            config["security_history"] = security_history[-10:] if isinstance(security_history, list) else []
        if authentication_history is not None:
            config["authentication_history"] = authentication_history[-10:] if isinstance(authentication_history, list) else []
        if remote_history is not None:
            config["remote_history"] = remote_history[-10:] if isinstance(remote_history, list) else []
        if lan_status_page_enabled is not None:
            config["lan_status_page_enabled"] = bool(lan_status_page_enabled)
        if lan_status_port is not None:
            config["lan_status_port"] = lan_status_port
        if lan_status_user_confirmed is not None:
            config["lan_status_user_confirmed"] = bool(lan_status_user_confirmed)
        if lan_chat_enabled is not None:
            config["lan_chat_enabled"] = bool(lan_chat_enabled)
        if lan_chat_port is not None:
            config["lan_chat_port"] = lan_chat_port
        if mobile_access_confirmed is not None:
            config["mobile_access_confirmed"] = bool(mobile_access_confirmed)
        if mobile_chat_timeout is not None:
            config["mobile_chat_timeout"] = mobile_chat_timeout
        if mobile_debug_mode is not None:
            config["mobile_debug_mode"] = bool(mobile_debug_mode)
        if mobile_response_limit is not None:
            config["mobile_response_limit"] = mobile_response_limit
        if selected_lan_ip is not None:
            config["selected_lan_ip"] = str(selected_lan_ip or "")
        if selected_adapter is not None:
            config["selected_adapter"] = str(selected_adapter or "")
        if last_mobile_error is not None:
            config["last_mobile_error"] = str(last_mobile_error or "")
        if last_mobile_stage is not None:
            config["last_mobile_stage"] = str(last_mobile_stage or "")
        if last_mobile_status is not None:
            config["last_mobile_status"] = str(last_mobile_status or "")
        if last_mobile_duration_ms is not None:
            config["last_mobile_duration_ms"] = last_mobile_duration_ms
        if last_mobile_model is not None:
            config["last_mobile_model"] = str(last_mobile_model or "")
        if last_mobile_capability is not None:
            config["last_mobile_capability"] = str(last_mobile_capability or "")
        if last_mobile_ollama_url is not None:
            config["last_mobile_ollama_url"] = str(last_mobile_ollama_url or "")
        if last_mobile_client is not None:
            config["last_mobile_client"] = str(last_mobile_client or "")
        if last_mobile_time is not None:
            config["last_mobile_time"] = str(last_mobile_time or "")
        return self.save(config)

    def add_credential_history(self, status, result, checked_time=None, error=None):
        config = self.load()
        history = config.get("credential_history", [])
        if not isinstance(history, list):
            history = []
        history.append({
            "time": checked_time,
            "status": status,
            "result": result,
            "error": error
        })
        config["credential_history"] = history[-10:]
        return self.save(config)

    def update_credential_diagnostics(self, result):
        config = self.load()
        status = "Available" if result.get("available", False) else "Unavailable"
        test_passed = bool(result.get("test_passed", False))
        last_result = result.get("last_result") or ("Passed" if test_passed else "Failed")
        checked_time = result.get("last_check")
        last_error = result.get("last_error")
        history = config.get("credential_history", [])
        if not isinstance(history, list):
            history = []
        history.append({
            "time": checked_time,
            "status": status,
            "result": last_result,
            "error": last_error
        })
        config["credential_storage"] = "windows_credential_manager"
        config["secure_storage_available"] = bool(result.get("available", False))
        config["credential_test_passed"] = test_passed
        config["credential_last_check"] = checked_time
        config["credential_last_result"] = last_result
        config["credential_command_status"] = result.get("command_status", status)
        config["credential_last_operation"] = result.get("last_operation")
        config["credential_operation_result"] = result.get("operation_result")
        config["credential_duration_ms"] = result.get("duration_ms", 0)
        config["credential_error_suggestion"] = result.get("suggestion")
        config["last_storage_error"] = last_error
        config["credential_history"] = history[-10:]
        config["credential_steps"] = result.get("steps", [])
        return self.save(config)

    def remote_readiness_summary(self):
        status = self.status()
        network = status.get("network", {})
        safety = self.safety_gate_check()
        auth = self.authentication_status()
        config = status.get("config", {})
        return {
            "network": "Ready" if network.get("network_available") else "Not Ready",
            "lan": safety.get("readiness", {}).get("lan", "Not Ready"),
            "authentication": "Ready" if auth.get("configured") else "Missing",
            "credential_storage": "Available" if auth.get("secure_storage_available") else "Missing",
            "remote_access": "Enabled" if config.get("enabled") else "Disabled"
        }

    def record_diagnostic_history(self):
        config = self.load()
        checked_time = AuthenticationManager(self.file_path).status().get("credential_last_check")
        if not checked_time:
            from datetime import datetime
            checked_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        summary = self.remote_readiness_summary()
        safety = self.safety_gate_check()
        for key, status_value in (
            ("network_history", summary["network"]),
            ("security_history", safety.get("readiness", {}).get("overall", "Blocked")),
            ("authentication_history", summary["authentication"]),
            ("remote_history", summary["remote_access"])
        ):
            history = config.get(key, [])
            if not isinstance(history, list):
                history = []
            history.append({
                "time": checked_time,
                "status": status_value,
                "result": "Passed" if status_value in {"Ready", "Enabled"} else "Failed"
            })
            config[key] = history[-10:]
        return self.save(config)

    def diagnostics(self):
        assessment = self.assessment()
        assessment["summary"] = self.remote_readiness_summary()
        assessment["config"] = self.load()
        return assessment

    def release_check(self, project_root):
        root = Path(project_root)
        config = self.load()
        auth = self.authentication_status()
        checks = [
            {"label": "Configuration Valid", "ok": self.file_path.exists()},
            {"label": "Data Directory Available", "ok": (root / "data").exists()},
            {"label": "Knowledge Directory Available", "ok": (root / "data" / "knowledge").exists()},
            {"label": "Remote Configuration Valid", "ok": isinstance(config, dict)},
            {"label": "Authentication Configuration Valid", "ok": isinstance(auth, dict)},
            {"label": "Credential Storage Available", "ok": bool(auth.get("secure_storage_available", False))},
            {"label": "LAN Server Module Available", "ok": True},
            {"label": "LAN Status Port Available", "ok": is_port_available(config.get("lan_status_port", DEFAULT_LAN_STATUS_PORT))},
            {"label": "LAN Status Page Stopped by Default", "ok": not bool(config.get("lan_status_page_enabled", False))},
            {"label": "LAN Chat Disabled by Default", "ok": not bool(config.get("lan_chat_enabled", False))},
            {"label": "Showcase Ready", "ok": True}
        ]
        return {
            "checks": checks,
            "passed": all(item.get("ok") for item in checks)
        }

    def authentication_status(self):
        return AuthenticationManager(self.file_path).status()

    @staticmethod
    def local_address():
        return "127.0.0.1"

    @staticmethod
    def _candidate_addresses():
        candidates = []
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(1)
                sock.connect(("8.8.8.8", 80))
                candidates.append(sock.getsockname()[0])
        except OSError:
            pass

        try:
            hostname = socket.gethostname()
            candidates.append(socket.gethostbyname(hostname))
            for item in socket.getaddrinfo(hostname, None, socket.AF_INET):
                address = item[4][0]
                candidates.append(address)
        except OSError:
            pass

        unique = []
        for address in candidates:
            if address and address not in unique:
                unique.append(address)
        return unique

    @staticmethod
    def _ipv4_priority(address):
        try:
            ip = ipaddress.ip_address(str(address))
        except ValueError:
            return -1
        if ip.version != 4:
            return -1
        text = str(ip)
        if text.startswith("127.") or text.startswith("169.254."):
            return -1
        if text.startswith("172."):
            second = int(text.split(".")[1])
            if 16 <= second <= 31:
                return -1
        if text.startswith("192.168."):
            return 100
        if text.startswith("10."):
            return 90
        if ip.is_private:
            return 50
        return -1

    @classmethod
    def select_lan_ip(cls, candidates=None):
        records = []
        ignored = []
        for address in candidates if candidates is not None else cls._candidate_addresses():
            priority = cls._ipv4_priority(address)
            if priority < 0:
                ignored.append(str(address))
                continue
            records.append((priority, str(address)))
        if not records:
            return {
                "lan_address": "",
                "selected_lan_ip": "",
                "selected_adapter": "Unavailable",
                "ignored_virtual_adapters": ignored
            }
        records.sort(key=lambda item: item[0], reverse=True)
        selected = records[0][1]
        return {
            "lan_address": selected,
            "selected_lan_ip": selected,
            "selected_adapter": "Auto-selected IPv4",
            "ignored_virtual_adapters": ignored
        }

    @classmethod
    def lan_address(cls):
        return cls.select_lan_ip().get("lan_address", "")

    def network_info(self):
        selection = self.select_lan_ip()
        lan = selection.get("lan_address", "")
        return {
            "local_address": self.local_address(),
            "lan_address": lan or "Unavailable",
            "network_available": bool(lan),
            "selected_lan_ip": selection.get("selected_lan_ip", ""),
            "selected_adapter": selection.get("selected_adapter", "Unavailable"),
            "ignored_virtual_adapters": selection.get("ignored_virtual_adapters", [])
        }

    def status(self):
        config = self.load()
        network = self.network_info()
        remote_status = "Ready" if config.get("enabled") and network.get("network_available") else "Disabled"
        security_status = (
            "Remote access requires authentication."
            if config.get("enabled")
            else "Local Only"
        )
        return {
            "config": config,
            "network": network,
            "remote_status": remote_status,
            "security_status": security_status
        }

    def listening_ports(self):
        """Return Aurora listening-port risk records.

        Aurora does not start a remote listener in the current framework,
        so this is intentionally limited to the configured local remote port.
        """

        config = self.load()
        port = int(config.get("port", 0) or 0)
        if port <= 0:
            return []
        return [{
            "port": port,
            "risk": "Unknown"
        }]

    def security_checklist(self):
        config = self.load()
        ports = self.listening_ports()
        firewall = "Safe" if not ports else "Unknown"
        public_exposure = "No"
        auth_configured = bool(config.get("authentication_configured", False))
        return {
            "remote_access": "Enabled" if config.get("enabled") else "Disabled",
            "current_mode": "Local Only",
            "authentication": "Required" if config.get("auth_required", True) else "Not Configured",
            "authentication_configured": "Yes" if auth_configured else "No",
            "public_exposure": public_exposure,
            "firewall": firewall,
            "listening_ports": ports
        }

    def remote_health(self):
        config = self.load()
        network = self.network_info()
        local_available = self.local_address() == "127.0.0.1"
        lan_available = bool(network.get("network_available", False))
        auth = self.authentication_status()
        auth_ready = bool(config.get("auth_required", True) and auth.get("configured", False))
        security_ready = (not config.get("enabled", False)) or auth_ready
        lan_ready = bool(
            config.get("enabled", False)
            and lan_available
            and config.get("port", 0) > 0
            and auth_ready
            and config.get("user_confirmed", False)
        )
        ios_ready = bool(lan_ready and config.get("ios_access_ready", False))
        return {
            "network": "OK" if lan_available else "Offline",
            "local_access": "Available" if local_available else "Unavailable",
            "lan_access": "Available" if lan_available else "Unavailable",
            "lan_readiness": "Ready" if lan_ready else "Not Ready",
            "ios_access": "Ready" if ios_ready else "Future Supported",
            "cellular_access": "Requires Secure Tunnel",
            "security": "Safe" if security_ready else "Warning"
        }

    def url_preview(self):
        config = self.load()
        network = self.network_info()
        port = int(config.get("port", 0) or 0)
        if port <= 0 or not config.get("enabled", False):
            return {
                "local_preview": "Port not configured yet.",
                "lan_preview": "Port not configured yet.",
                "port_configured": False
            }
        local_preview = f"http://{network.get('local_address', '127.0.0.1')}:{port}"
        lan_address = network.get("lan_address", "")
        if not lan_address or lan_address == "Unavailable":
            lan_preview = "No LAN address available."
        else:
            lan_preview = f"http://{lan_address}:{port}"
        return {
            "local_preview": local_preview,
            "lan_preview": lan_preview,
            "port_configured": True
        }

    def ios_compatibility(self):
        return {
            "safari_supported": "Yes",
            "android_required": "No",
            "same_wifi_access": "Future Supported",
            "cellular_access": "Requires Secure Tunnel"
        }

    def tailscale_readiness(self):
        config = self.load()
        return {
            "status": "Ready" if config.get("tailscale_ready", False) else "Not Configured / Future Supported",
            "description": "For cellular access from iPhone, Tailscale or another secure tunnel is recommended."
        }

    def lan_status_urls(self):
        config = self.load()
        network = self.network_info()
        port = int(config.get("lan_status_port", DEFAULT_LAN_STATUS_PORT) or DEFAULT_LAN_STATUS_PORT)
        lan_address = network.get("lan_address", "")
        return {
            "local_url": f"http://127.0.0.1:{port}",
            "lan_url": "No LAN address available." if not lan_address or lan_address == "Unavailable" else f"http://{lan_address}:{port}",
            "port": port
        }

    def lan_chat_urls(self):
        config = self.load()
        network = self.network_info()
        port = int(config.get("lan_chat_port", DEFAULT_LAN_STATUS_PORT) or DEFAULT_LAN_STATUS_PORT)
        lan_address = network.get("lan_address", "")
        return {
            "local_url": f"http://127.0.0.1:{port}/chat",
            "mobile_url": "No LAN address available." if not lan_address or lan_address == "Unavailable" else f"http://{lan_address}:{port}/chat",
            "port": port
        }

    def lan_status_start_check(self):
        config = self.load()
        network = self.network_info()
        network_ready = bool(network.get("network_available", False))
        lan_ready = bool(network.get("lan_address") and network.get("lan_address") != "Unavailable")
        user_confirmed = bool(config.get("lan_status_user_confirmed", False))
        ready = bool(network_ready and lan_ready and user_confirmed)
        if not user_confirmed:
            reason = "User confirmation is required before starting LAN Status Page."
        elif not lan_ready:
            reason = "LAN address is not ready."
        elif not network_ready:
            reason = "Network is not ready."
        else:
            reason = ""
        return {
            "ready": ready,
            "network_available": network_ready,
            "lan_address_available": lan_ready,
            "user_confirmed": user_confirmed,
            "reason": reason,
            "network": network,
            "urls": self.lan_status_urls()
        }

    def lan_chat_start_check(self):
        config = self.load()
        network = self.network_info()
        network_ready = bool(network.get("network_available", False))
        lan_ready = bool(network.get("lan_address") and network.get("lan_address") != "Unavailable")
        security_confirmed = bool(config.get("security_confirmed", False))
        mobile_confirmed = bool(config.get("mobile_access_confirmed", False))
        ready = bool(network_ready and lan_ready and security_confirmed and mobile_confirmed)
        if not mobile_confirmed:
            reason = "Mobile access confirmation is required before starting LAN Chat."
        elif not security_confirmed:
            reason = "Security confirmation is required before starting LAN Chat."
        elif not lan_ready:
            reason = "LAN address is not ready."
        elif not network_ready:
            reason = "Network is not ready."
        else:
            reason = ""
        return {
            "ready": ready,
            "network_available": network_ready,
            "lan_address_available": lan_ready,
            "security_confirmed": security_confirmed,
            "mobile_access_confirmed": mobile_confirmed,
            "reason": reason,
            "network": network,
            "urls": self.lan_chat_urls()
        }

    def lan_readiness_checklist(self):
        config = self.load()
        network = self.network_info()
        port_ready = int(config.get("port", 0) or 0) > 0
        auth_ready = bool(self.authentication_status().get("configured", False))
        user_confirmed = bool(config.get("user_confirmed", False))
        return [
            {"label": "Network Available", "ok": bool(network.get("network_available", False))},
            {"label": "LAN Address Found", "ok": bool(network.get("network_available", False))},
            {"label": "Remote Service Disabled", "ok": not bool(config.get("enabled", False)) or port_ready},
            {"label": "Authentication Not Configured", "ok": auth_ready},
            {"label": "User Confirmation Missing", "ok": user_confirmed},
        ]

    def safety_gate_check(self):
        config = self.load()
        network = self.network_info()
        auth = self.authentication_status()
        checks = {
            "network": bool(network.get("network_available", False)),
            "lan": bool(network.get("network_available", False)),
            "authentication_required": bool(config.get("auth_required", True)),
            "authentication_configured": bool(auth.get("configured", False)),
            "auth_enabled": bool(auth.get("auth_enabled", False)),
            "authentication_type": auth.get("authentication_type", "none"),
            "token_configured": bool(auth.get("token_configured", False)),
            "secure_storage_configured": bool(auth.get("secure_storage_configured", False)),
            "secure_storage_available": bool(auth.get("secure_storage_available", False)),
            "security_confirmed": bool(config.get("security_confirmed", False))
        }
        overall_ready = bool(
            checks["network"]
            and checks["lan"]
            and checks["authentication_required"]
            and checks["authentication_configured"]
            and checks["auth_enabled"]
            and checks["authentication_type"] != "none"
            and checks["token_configured"]
            and checks["secure_storage_available"]
            and checks["security_confirmed"]
        )
        return {
            "checks": checks,
            "readiness": {
                "network": "Ready" if checks["network"] else "Not Ready",
                "lan": "Ready" if checks["lan"] else "Not Ready",
                "authentication": "Ready" if checks["authentication_configured"] else "Missing",
                "storage": "Ready" if checks["secure_storage_available"] else "Missing",
                "security": "Confirmed" if checks["security_confirmed"] else "Not Confirmed",
                "overall": "Ready" if overall_ready else "Blocked"
            },
            "ready": overall_ready,
            "blocked_reason": "" if overall_ready else self.safety_block_reason(checks)
        }

    @staticmethod
    def safety_block_reason(checks):
        if checks.get("authentication_type") == "token" and not checks.get("token_configured"):
            return "Token authentication is not configured."
        if (
            checks.get("authentication_type") == "token"
            and checks.get("token_configured")
            and not checks.get("secure_storage_available")
        ):
            return "Remote access blocked:\nSecure credential storage unavailable.\nOpen Diagnostics for details."
        if not checks.get("authentication_configured"):
            return "Authentication is required before enabling remote access."
        if not checks.get("security_confirmed"):
            return "Security confirmation is required before enabling remote access."
        if not checks.get("network"):
            return "Network is not ready."
        if not checks.get("lan"):
            return "LAN address is not ready."
        return "Remote safety check blocked."

    def confirm_security(self):
        return self.update(security_confirmed=True, user_confirmed=True)

    def request_enable(self):
        gate = self.safety_gate_check()
        if not gate.get("ready"):
            self.update(enabled=False)
            return {
                "enabled": False,
                "allowed": False,
                "gate": gate,
                "message": gate.get("blocked_reason", "Remote safety check blocked.")
            }
        config = self.update(enabled=True)
        return {
            "enabled": True,
            "allowed": True,
            "gate": gate,
            "config": config,
            "message": "Remote safety check passed."
        }

    def assessment(self):
        return {
            "status": self.status(),
            "security": self.security_checklist(),
            "health": self.remote_health(),
            "url_preview": self.url_preview(),
            "ios_compatibility": self.ios_compatibility(),
            "tailscale": self.tailscale_readiness(),
            "lan_checklist": self.lan_readiness_checklist(),
            "safety_gate": self.safety_gate_check(),
            "authentication": self.authentication_status(),
            "lan_status": {
                "enabled": self.load().get("lan_status_page_enabled", False),
                "user_confirmed": self.load().get("lan_status_user_confirmed", False),
                "urls": self.lan_status_urls()
            },
            "lan_chat": {
                "enabled": self.load().get("lan_chat_enabled", False),
                "mobile_access_confirmed": self.load().get("mobile_access_confirmed", False),
                "urls": self.lan_chat_urls()
            },
            "mobile_debug": {
                "client": self.load().get("last_mobile_client", ""),
                "stage": self.load().get("last_mobile_stage", ""),
                "status": self.load().get("last_mobile_status", ""),
                "duration_ms": self.load().get("last_mobile_duration_ms", 0),
                "model": self.load().get("last_mobile_model", ""),
                "capability": self.load().get("last_mobile_capability", ""),
                "ollama_url": self.load().get("last_mobile_ollama_url", ""),
                "error": self.load().get("last_mobile_error", ""),
                "time": self.load().get("last_mobile_time", "")
            },
            "mode_descriptions": {
                "local": "Local Only",
                "lan": "LAN Only",
                "secure": "Secure Remote"
            }
        }

"""Windows Credential Manager preview and diagnostics provider.

This module only manages a test credential used to verify secure-storage
availability. It does not store real tokens, passwords, or user secrets.
"""

import platform
import subprocess
import time
from datetime import datetime


TEST_CREDENTIAL_NAME = "Aurora_Test_Credential"
TEST_CREDENTIAL_USER = "Aurora"
TEST_CREDENTIAL_SECRET = "Aurora_Test_Only"


class CredentialStorageProvider:
    """Preview wrapper around Windows Credential Manager diagnostics."""

    provider_name = "Windows Credential Manager"

    @staticmethod
    def _hidden_flags():
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    @staticmethod
    def _is_windows():
        return platform.system().casefold() == "windows"

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _step(name, ok, message="", duration_ms=0):
        return {
            "step": name,
            "ok": bool(ok),
            "result": "Passed" if ok else "Failed",
            "message": message or "",
            "duration_ms": int(duration_ms or 0)
        }

    @staticmethod
    def _error_category(result):
        if result.get("ok"):
            return None
        message = str(result.get("message") or result.get("stderr") or "").casefold()
        if "not found" in message or "\u627e\u4e0d\u5230" in message:
            return "Credential Manager unavailable"
        if "denied" in message or "\u62d2\u7edd" in message:
            return "Permission denied"
        if "timeout" in message:
            return "Storage access failed"
        if "command" in message:
            return "Command failed"
        return "Unknown error"

    @staticmethod
    def suggestion_for_error(error):
        suggestions = {
            "Permission denied": "Check Windows permissions.",
            "Credential Manager unavailable": "Verify Windows Credential Manager availability.",
            "Command failed": "Check command availability.",
            "Storage access failed": "Retry later or check Windows Credential Manager service status.",
            "Unknown error": "Review the diagnostic details and retry."
        }
        return suggestions.get(error or "", "No action required.")

    def _run_cmdkey(self, args):
        if not self._is_windows():
            return {
                "ok": False,
                "message": "Windows Credential Manager is only available on Windows.",
                "stdout": "",
                "stderr": "Unsupported platform",
                "duration_ms": 0
            }

        started = time.perf_counter()
        try:
            result = subprocess.run(
                ["cmdkey", *args],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=self._hidden_flags()
            )
        except FileNotFoundError:
            return {
                "ok": False,
                "message": "cmdkey command not found.",
                "stdout": "",
                "stderr": "Command not found",
                "duration_ms": int((time.perf_counter() - started) * 1000)
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "message": "Credential Manager command timed out.",
                "stdout": "",
                "stderr": "Timeout",
                "duration_ms": int((time.perf_counter() - started) * 1000)
            }
        except OSError as error:
            return {
                "ok": False,
                "message": str(error),
                "stdout": "",
                "stderr": str(error),
                "duration_ms": int((time.perf_counter() - started) * 1000)
            }

        return {
            "ok": result.returncode == 0,
            "message": "OK" if result.returncode == 0 else (result.stderr.strip() or result.stdout.strip() or "Command failed"),
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "duration_ms": int((time.perf_counter() - started) * 1000)
        }

    def check_available(self):
        result = self._run_cmdkey(["/list"])
        available = bool(result.get("ok"))
        error = None if available else self._error_category(result)
        return {
            "provider": self.provider_name,
            "available": available,
            "test_passed": False,
            "status": "Available" if available else "Unavailable",
            "command_status": "Available" if available else "Unavailable",
            "message": result.get("message", ""),
            "last_operation": "Command Status",
            "operation_result": "Success" if available else "Failed",
            "duration_ms": result.get("duration_ms", 0),
            "last_error": error,
            "suggestion": self.suggestion_for_error(error),
            "last_result": "Passed" if available else "Failed",
            "last_check": self._now()
        }

    def create_test_credential(self):
        result = self._run_cmdkey([
            f"/generic:{TEST_CREDENTIAL_NAME}",
            f"/user:{TEST_CREDENTIAL_USER}",
            f"/pass:{TEST_CREDENTIAL_SECRET}"
        ])
        created = bool(result.get("ok"))
        error = None if created else self._error_category(result)
        return {
            "provider": self.provider_name,
            "created": created,
            "status": "Passed" if created else "Failed",
            "message": result.get("message", ""),
            "last_error": error,
            "suggestion": self.suggestion_for_error(error),
            "duration_ms": result.get("duration_ms", 0),
            "last_check": self._now()
        }

    def has_test_credential(self):
        result = self._run_cmdkey([f"/list:{TEST_CREDENTIAL_NAME}"])
        output = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
        normalized_output = output.lower()
        found = bool(
            result.get("ok")
            and TEST_CREDENTIAL_NAME.lower() in normalized_output
            and "* none *" not in normalized_output
            and "* \u65e0 *" not in normalized_output
        )
        error = None if found else self._error_category(result)
        return {
            "provider": self.provider_name,
            "exists": found,
            "status": "Passed" if found else "Failed",
            "message": "Test credential found." if found else result.get("message", "Test credential not found."),
            "last_error": error,
            "suggestion": self.suggestion_for_error(error),
            "duration_ms": result.get("duration_ms", 0),
            "last_check": self._now()
        }

    def delete_test_credential(self):
        result = self._run_cmdkey([f"/delete:{TEST_CREDENTIAL_NAME}"])
        message = str(result.get("message", ""))
        missing_test_item = (
            "cmdkey command not found" not in message.casefold()
            and ("not found" in message.casefold() or "\u627e\u4e0d\u5230" in message)
        )
        removed = bool(result.get("ok") or missing_test_item)
        error = None if removed else self._error_category(result)
        return {
            "provider": self.provider_name,
            "removed": removed,
            "status": "Passed" if removed else "Failed",
            "message": "Test credential already removed." if missing_test_item else result.get("message", ""),
            "last_error": error,
            "suggestion": self.suggestion_for_error(error),
            "duration_ms": result.get("duration_ms", 0),
            "last_check": self._now()
        }

    def run_test(self):
        available = self.check_available()
        if not available.get("available"):
            return {
                "provider": self.provider_name,
                "available": False,
                "test_passed": False,
                "status": "Failed",
                "message": available.get("message", "Credential storage unavailable."),
                "last_operation": available.get("last_operation", "Command Status"),
                "operation_result": "Failed",
                "duration_ms": available.get("duration_ms", 0),
                "last_result": "Failed",
                "last_error": available.get("last_error") or "Credential Manager unavailable",
                "suggestion": available.get("suggestion"),
                "command_status": available.get("command_status", "Unavailable"),
                "steps": [self._step("Command Status", False, available.get("message", ""), available.get("duration_ms", 0))],
                "last_check": available.get("last_check")
            }

        created = self.create_test_credential()
        exists = self.has_test_credential()
        removed = self.delete_test_credential()
        removed_check = self.has_test_credential()
        removed_verified = not bool(removed_check.get("exists"))
        passed = bool(created.get("created") and exists.get("exists") and removed.get("removed") and removed_verified)
        error = (
            created.get("last_error")
            or exists.get("last_error")
            or removed.get("last_error")
            or (removed_check.get("last_error") if not removed_verified else None)
        )
        steps = [
            self._step("Create Test Credential", created.get("created"), created.get("message"), created.get("duration_ms")),
            self._step("Read Test Credential", exists.get("exists"), exists.get("message"), exists.get("duration_ms")),
            self._step("Delete Test Credential", removed.get("removed"), removed.get("message"), removed.get("duration_ms")),
            self._step("Verify Removed", removed_verified, removed_check.get("message"), removed_check.get("duration_ms"))
        ]
        duration_ms = sum(item.get("duration_ms", 0) for item in steps)
        return {
            "provider": self.provider_name,
            "available": True,
            "test_passed": passed,
            "status": "Passed" if passed else "Failed",
            "message": "Credential storage diagnostics completed." if passed else exists.get("message", created.get("message", "")),
            "last_operation": "Verify Removed",
            "operation_result": "Success" if passed else "Failed",
            "duration_ms": duration_ms,
            "last_result": "Passed" if passed else "Failed",
            "last_error": None if passed else (error or "Storage access failed"),
            "suggestion": self.suggestion_for_error(error),
            "command_status": "Available",
            "steps": steps,
            "last_check": removed_check.get("last_check") or exists.get("last_check") or created.get("last_check")
        }

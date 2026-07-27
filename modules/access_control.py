"""Secure LAN access control foundation.

This module defines reusable access decisions and audit entries for future
LAN/Remote protection. It does not enforce API checks or write runtime logs.
"""

from modules.auth_middleware import authenticate_request, check_permission
from modules.device_identity import DEVICE_ACTIVE, format_time, utc_now
from modules.device_pairing import PAIRING_VERIFIED


ACCESS_ALLOWED = "Allowed"
ACCESS_DENIED = "Denied"
ACCESS_PENDING = "Pending"


def access_decision(result=ACCESS_PENDING, reason="", device_id="", api_name="", mode=""):
    return {
        "result": str(result or ACCESS_PENDING),
        "allowed": result == ACCESS_ALLOWED,
        "denied": result == ACCESS_DENIED,
        "pending": result == ACCESS_PENDING,
        "reason": str(reason or ""),
        "device_id": str(device_id or ""),
        "api_name": str(api_name or ""),
        "mode": str(mode or ""),
    }


def audit_entry(device_id="", api_name="", result=ACCESS_PENDING, reason="", timestamp=None):
    return {
        "timestamp": format_time(timestamp or utc_now()),
        "device_id": str(device_id or ""),
        "api_name": str(api_name or ""),
        "result": str(result or ACCESS_PENDING),
        "reason": str(reason or ""),
    }


class AccessAuditLog:
    """In-memory audit log model for future persistence integration."""

    def __init__(self, entries=None):
        self.entries = list(entries or [])

    def record(self, device_id="", api_name="", result=ACCESS_PENDING, reason="", timestamp=None):
        entry = audit_entry(
            device_id=device_id,
            api_name=api_name,
            result=result,
            reason=reason,
            timestamp=timestamp,
        )
        self.entries.append(entry)
        return dict(entry)

    def list_entries(self, limit=100):
        size = max(1, int(limit or 100))
        return [dict(item) for item in self.entries[-size:]]


def evaluate_device_permission(device_id="", device_status="", pairing_status="", api_name=""):
    identifier = str(device_id or "")
    status = str(device_status or "")
    paired = str(pairing_status or "")

    if not identifier:
        return access_decision(
            ACCESS_PENDING,
            "Device identity is missing.",
            device_id=identifier,
            api_name=api_name,
        )
    if status != DEVICE_ACTIVE:
        return access_decision(
            ACCESS_DENIED,
            "Device is not active.",
            device_id=identifier,
            api_name=api_name,
        )
    if paired != PAIRING_VERIFIED:
        return access_decision(
            ACCESS_PENDING,
            "Device pairing is not verified.",
            device_id=identifier,
            api_name=api_name,
        )
    return access_decision(
        ACCESS_ALLOWED,
        "Device is active and pairing is verified.",
        device_id=identifier,
        api_name=api_name,
    )


def evaluate_request_access(
    request=None,
    headers=None,
    path="",
    method="",
    device_id="",
    device_status="",
    pairing_status="",
    api_name="",
    remote_manager=None,
    authentication_manager=None,
    enforce=False,
):
    """Combine auth middleware and device permission into one access decision.

    `enforce=False` preserves existing LAN behavior; denied auth decisions are
    reported as pending compatibility decisions instead of blocking requests.
    """

    auth_decision = authenticate_request(
        request=request,
        headers=headers,
        path=path,
        method=method,
        remote_manager=remote_manager,
        authentication_manager=authentication_manager,
        enforce=enforce,
    )
    permission = check_permission(auth_decision, permission=api_name or auth_decision.get("scope", ""))
    if permission.get("denied"):
        return access_decision(
            ACCESS_DENIED if enforce else ACCESS_PENDING,
            permission.get("reason", "Authentication denied."),
            device_id=device_id,
            api_name=api_name or permission.get("scope", ""),
            mode=permission.get("mode", ""),
        )

    device_decision = evaluate_device_permission(
        device_id=device_id,
        device_status=device_status,
        pairing_status=pairing_status,
        api_name=api_name or permission.get("scope", ""),
    )
    device_decision["mode"] = permission.get("mode", "")
    device_decision["auth"] = dict(permission)
    return device_decision

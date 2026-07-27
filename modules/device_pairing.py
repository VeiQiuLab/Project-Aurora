"""Device pairing flow foundation for Secure Remote.

This module keeps pairing sessions in memory only. It does not persist
runtime device data, create long-term tokens, or enable Remote access.
"""

import secrets
from datetime import timedelta

from modules.device_identity import (
    DeviceRegistry,
    format_time,
    generate_pairing_code,
    utc_now,
)


PAIRING_CREATED = "Created"
PAIRING_VERIFIED = "Verified"
PAIRING_EXPIRED = "Expired"
PAIRING_CANCELLED = "Cancelled"


def generate_session_id():
    return "aurora-pairing-" + secrets.token_hex(8)


class PairingSession:
    """Short-lived one-time pairing session."""

    def __init__(
        self,
        session_id=None,
        pairing_code=None,
        ttl_seconds=300,
        created_time=None,
        status=PAIRING_CREATED,
        device_name="",
    ):
        self.session_id = str(session_id or generate_session_id())
        self.pairing_code = str(pairing_code or generate_pairing_code())
        self.created_time = created_time or utc_now()
        self.expire_time = self.created_time + timedelta(seconds=max(30, int(ttl_seconds or 300)))
        self.status = str(status or PAIRING_CREATED)
        self.device_name = str(device_name or "")
        self.device_id = ""
        self.verified_time = ""
        self.paired_device = None

    def is_expired(self, now=None):
        if self.status in {PAIRING_VERIFIED, PAIRING_CANCELLED}:
            return False
        return (now or utc_now()) >= self.expire_time

    def current_status(self, now=None):
        if self.status == PAIRING_CREATED and self.is_expired(now):
            return PAIRING_EXPIRED
        return self.status

    def cancel(self):
        if self.status == PAIRING_CREATED:
            self.status = PAIRING_CANCELLED
        return self.to_dict(include_code=False)

    def verify_pairing_code(self, pairing_code, device_name="", registry=None, now=None):
        """Verify a one-time code and register a paired device in memory."""
        status = self.current_status(now)
        if status == PAIRING_VERIFIED:
            return self._result(False, "Pairing session already verified.")
        if status == PAIRING_CANCELLED:
            return self._result(False, "Pairing session cancelled.")
        if status == PAIRING_EXPIRED:
            self.status = PAIRING_EXPIRED
            return self._result(False, "Pairing session expired.")
        if str(pairing_code or "") != self.pairing_code:
            return self._result(False, "Pairing code mismatch.")

        device_registry = registry or DeviceRegistry()
        name = str(device_name or self.device_name or "Paired Device")
        device = device_registry.register_device(name)

        self.status = PAIRING_VERIFIED
        self.device_name = device.get("device_name", name)
        self.device_id = device.get("device_id", "")
        self.verified_time = format_time(now or utc_now())
        self.paired_device = dict(device)
        return self._result(True, "Pairing verified.", device=device)

    def _result(self, ok, reason, device=None):
        result = {
            "ok": bool(ok),
            "status": self.current_status(),
            "reason": reason,
            "session": self.to_dict(include_code=False),
        }
        if device:
            result["device"] = dict(device)
        return result

    def to_dict(self, include_code=True):
        data = {
            "session_id": self.session_id,
            "created_time": format_time(self.created_time),
            "expire_time": format_time(self.expire_time),
            "status": self.current_status(),
            "device_name": self.device_name,
            "device_id": self.device_id,
            "verified_time": self.verified_time,
        }
        if include_code:
            data["pairing_code"] = self.pairing_code
        return data


def verify_pairing_code(session, pairing_code, device_name="", registry=None, now=None):
    if not isinstance(session, PairingSession):
        return {"ok": False, "status": "", "reason": "Invalid pairing session."}
    return session.verify_pairing_code(pairing_code, device_name=device_name, registry=registry, now=now)


class PairingSessionManager:
    """In-memory pairing session manager for future Remote API integration."""

    def __init__(self, registry=None, ttl_seconds=300):
        self.registry = registry or DeviceRegistry()
        self.ttl_seconds = max(30, int(ttl_seconds or 300))
        self.sessions = {}

    def create_session(self, device_name=""):
        session = PairingSession(ttl_seconds=self.ttl_seconds, device_name=device_name)
        self.sessions[session.session_id] = session
        return session.to_dict()

    def get_session(self, session_id):
        session = self.sessions.get(str(session_id or ""))
        if not session:
            return None
        return session.to_dict(include_code=False)

    def cancel_session(self, session_id):
        session = self.sessions.get(str(session_id or ""))
        if not session:
            return {"ok": False, "status": "", "reason": "Pairing session not found."}
        return {"ok": True, "status": PAIRING_CANCELLED, "session": session.cancel()}

    def verify_session(self, session_id, pairing_code, device_name=""):
        session = self.sessions.get(str(session_id or ""))
        if not session:
            return {"ok": False, "status": "", "reason": "Pairing session not found."}
        return session.verify_pairing_code(pairing_code, device_name=device_name, registry=self.registry)

    def expire_sessions(self, now=None):
        expired = []
        for session in self.sessions.values():
            if session.current_status(now) == PAIRING_EXPIRED:
                session.status = PAIRING_EXPIRED
                expired.append(session.session_id)
        return expired

    def list_sessions(self):
        return [session.to_dict(include_code=False) for session in self.sessions.values()]

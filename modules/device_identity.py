"""Device identity foundation for Secure Remote.

This module defines registry, pairing, and token lifecycle models. It does
not create real tokens, write runtime device data, or enable Remote access.
"""

import secrets
import string
from datetime import datetime, timedelta

from modules.credential_storage import CredentialStorageProvider


TOKEN_CREATED = "Created"
TOKEN_ACTIVE = "Active"
TOKEN_EXPIRED = "Expired"
TOKEN_REVOKED = "Revoked"

DEVICE_ACTIVE = "Active"
DEVICE_DISABLED = "Disabled"
DEVICE_REVOKED = "Revoked"

PAIRING_PENDING = "Pending"
PAIRING_USED = "Used"
PAIRING_EXPIRED = "Expired"


def utc_now():
    return datetime.utcnow().replace(microsecond=0)


def format_time(value):
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    return str(value or "")


def generate_device_id():
    return "aurora-device-" + secrets.token_hex(8)


def generate_pairing_code(length=6):
    alphabet = string.digits
    size = max(4, int(length or 6))
    return "".join(secrets.choice(alphabet) for _ in range(size))


def credential_target_for_device(device_id):
    return f"ProjectAurora:RemoteDevice:{device_id}"


class DeviceRegistry:
    """In-memory registry model for future persisted paired devices."""

    def __init__(self, devices=None, credential_provider=None):
        self.devices = list(devices or [])
        self.credential_provider = credential_provider or CredentialStorageProvider()

    @staticmethod
    def new_device(device_name, device_id=None, created_time=None, status=DEVICE_ACTIVE):
        timestamp = format_time(created_time or utc_now())
        identifier = str(device_id or generate_device_id())
        return {
            "device_id": identifier,
            "device_name": str(device_name or "Unnamed Device"),
            "created_time": timestamp,
            "last_seen": "",
            "status": status,
            "credential_target": credential_target_for_device(identifier)
        }

    def list_devices(self):
        return [dict(item) for item in self.devices]

    def find_device(self, device_id):
        identifier = str(device_id or "")
        for item in self.devices:
            if item.get("device_id") == identifier:
                return item
        return None

    def register_device(self, device_name, device_id=None):
        device = self.new_device(device_name, device_id=device_id)
        self.devices.append(device)
        return dict(device)

    def update_last_seen(self, device_id, seen_time=None):
        device = self.find_device(device_id)
        if not device:
            return None
        device["last_seen"] = format_time(seen_time or utc_now())
        return dict(device)

    def set_status(self, device_id, status):
        device = self.find_device(device_id)
        if not device:
            return None
        device["status"] = str(status or DEVICE_DISABLED)
        return dict(device)

    def revoke_device(self, device_id):
        return self.set_status(device_id, DEVICE_REVOKED)

    def credential_storage_status(self):
        return self.credential_provider.check_available()


class PairingCode:
    """Short-lived one-time pairing code model."""

    def __init__(self, code=None, ttl_seconds=300, created_time=None):
        self.code = str(code or generate_pairing_code())
        self.created_time = created_time or utc_now()
        self.expire_time = self.created_time + timedelta(seconds=max(30, int(ttl_seconds or 300)))
        self.used = False

    def is_expired(self, now=None):
        return (now or utc_now()) >= self.expire_time

    def status(self, now=None):
        if self.used:
            return PAIRING_USED
        if self.is_expired(now):
            return PAIRING_EXPIRED
        return PAIRING_PENDING

    def verify(self, code, now=None):
        if self.used:
            return {"ok": False, "status": PAIRING_USED, "reason": "Pairing code already used."}
        if self.is_expired(now):
            return {"ok": False, "status": PAIRING_EXPIRED, "reason": "Pairing code expired."}
        if str(code or "") != self.code:
            return {"ok": False, "status": PAIRING_PENDING, "reason": "Pairing code mismatch."}
        self.used = True
        return {"ok": True, "status": PAIRING_USED, "reason": "Pairing code accepted."}

    def to_dict(self):
        return {
            "code": self.code,
            "created_time": format_time(self.created_time),
            "expire_time": format_time(self.expire_time),
            "one_time_use": True,
            "status": self.status()
        }


class TokenLifecycle:
    """Token status model without creating or storing real token secrets."""

    def __init__(self, status=TOKEN_CREATED, created_time=None, expire_time=None, revoked_time=""):
        self.status = str(status or TOKEN_CREATED)
        self.created_time = created_time or utc_now()
        self.expire_time = expire_time
        self.revoked_time = revoked_time

    def is_expired(self, now=None):
        return bool(self.expire_time and (now or utc_now()) >= self.expire_time)

    def current_status(self, now=None):
        if self.status == TOKEN_REVOKED:
            return TOKEN_REVOKED
        if self.is_expired(now):
            return TOKEN_EXPIRED
        return self.status

    def activate(self):
        if self.current_status() in {TOKEN_CREATED, TOKEN_ACTIVE}:
            self.status = TOKEN_ACTIVE
        return self.to_dict()

    def revoke(self, revoked_time=None):
        self.status = TOKEN_REVOKED
        self.revoked_time = format_time(revoked_time or utc_now())
        return self.to_dict()

    def to_dict(self):
        return {
            "status": self.current_status(),
            "created_time": format_time(self.created_time),
            "expire_time": format_time(self.expire_time),
            "revoked_time": self.revoked_time
        }

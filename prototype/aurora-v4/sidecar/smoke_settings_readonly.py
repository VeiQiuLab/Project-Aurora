"""Real app_paths settings read-only smoke. Never prints config or credentials."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from modules import app_paths


def fingerprint(path):
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def main():
    path = app_paths.CONFIG_FILE
    before = fingerprint(path)
    from modules.settings import settings
    from modules.settings_service import SettingsService
    owner = SettingsService()
    dto = owner.describe()
    snapshot = owner.snapshot()
    owner.close()
    after = fingerprint(path)
    assert before == after
    assert settings._instance is None
    print(json.dumps({"status":dto["status"],"descriptor_count":len(dto["descriptors"]),
        "revision":dto["revision"],"hash_unchanged":before == after,"mtime_unchanged":before == after,
        "legacy_singleton_initialized":False,"thinking_mode":snapshot.policy.thinking_mode,
        "keep_alive":snapshot.policy.keep_alive,"network_requests":0,"writes":0}))


if __name__ == "__main__":
    main()

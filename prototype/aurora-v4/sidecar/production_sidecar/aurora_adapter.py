"""Compatibility name for read-only callers; uses the real headless API."""
from modules.settings_service import SettingsService


class ReadOnlySettings:
    def __init__(self, root, config_file=None):
        service = SettingsService(config_file)
        self._snapshot = service.snapshot()
        self.config_file = service.config_file
        self.status = self._snapshot.status
        self.policy = self._snapshot.policy

    def get(self, key, default=None):
        return self._snapshot.get(key, default)

    def snapshot(self):
        return self._snapshot

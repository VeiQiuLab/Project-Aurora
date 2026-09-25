"""Character preferences use the existing authority, never renderer files."""
import json
import pytest
from modules.settings_service import SettingsService, SettingsError


def test_character_defaults_patch_persistence_and_conflict(tmp_path):
    path = tmp_path / "settings.json"
    service = SettingsService(path)
    descriptors = {d["key"]: d for d in service.describe()["descriptors"]}
    assert descriptors["live2d.enabled"]["value"] is False
    assert descriptors["live2d.visible"]["value"] is True
    changes = {"live2d.enabled": True, "live2d.visible": False, "live2d.x": -100, "live2d.y": 300}
    service.apply_patch(changes, service.revision)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["live2d"] == {"enabled": True, "visible": False, "x": -100, "y": 300}
    assert {d["key"]: d["value"] for d in SettingsService(path).describe()["descriptors"] if d["key"].startswith("live2d.")} == changes
    with pytest.raises(SettingsError, match="Settings operation"):
        service.apply_patch({"live2d.visible": True}, 0)
    assert json.loads(path.read_text(encoding="utf-8")) == saved


@pytest.mark.parametrize("patch", [
    {"live2d.enabled": 1}, {"live2d.visible": "true"}, {"live2d.x": 32768},
    {"live2d.y": -32769}, {"live2d.x": 1.2}, {"live2d.model": "private"},
])
def test_character_invalid_patch_is_atomic(tmp_path, patch):
    path = tmp_path / "settings.json"
    service = SettingsService(path)
    with pytest.raises(SettingsError):
        service.apply_patch(patch, service.revision)
    assert not path.exists()

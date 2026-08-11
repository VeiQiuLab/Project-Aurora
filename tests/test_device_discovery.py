from modules.experience.audio.device_discovery import (
    enumerate_dshow_audio_devices,
    resolve_voice_input_device,
)
from modules.experience.subprocess_utils import with_hidden_console


DSHOW_OUTPUT = '''
[dshow @ 000001] "耳机式麦克风 (2- INZONE H9 / INZONE H7)" (audio)
[dshow @ 000001]   Alternative name "@device_cm_{33D9A762-90C8-11D0-BD43-00A0C911CE86}\\wave_{C50E681C-D780-458E-ADCE-5F46F249D8D0}"
'''


def fake_run(*_args, **_kwargs):
    return type("Result", (), {"stdout": "", "stderr": DSHOW_OUTPUT, "returncode": 1})()


def test_enumerate_dshow_audio_devices_parses_guid():
    devices = enumerate_dshow_audio_devices(run=fake_run)

    assert len(devices) == 1
    assert "INZONE H9" in devices[0].name
    assert devices[0].device_name.endswith("D8D0}")


def test_enumerate_dshow_audio_devices_hides_windows_console():
    captured = {}

    def capturing_run(*_args, **kwargs):
        captured.update(kwargs)
        return type("Result", (), {"stdout": "", "stderr": DSHOW_OUTPUT, "returncode": 1})()

    enumerate_dshow_audio_devices(run=capturing_run)

    for key, value in with_hidden_console().items():
        assert captured[key] == value


def test_resolve_prefers_keyword_and_caches_guid():
    settings = {
        "voice": {
            "recorder": {
                "preferred_device_keyword": "INZONE H9",
                "device_name": "stale-guid",
            }
        }
    }

    resolved = resolve_voice_input_device(settings, run=fake_run)

    assert resolved.endswith("D8D0}")
    assert settings["voice"]["recorder"]["last_successful_device_guid"] == resolved


def test_resolve_uses_valid_cached_guid_before_keyword():
    settings = {
        "voice": {
            "recorder": {
                "preferred_device_keyword": "does-not-match",
                "last_successful_device_guid": "@device_cm_{33D9A762-90C8-11D0-BD43-00A0C911CE86}\\wave_{C50E681C-D780-458E-ADCE-5F46F249D8D0}",
            }
        }
    }

    assert resolve_voice_input_device(settings, run=fake_run).endswith("D8D0}")

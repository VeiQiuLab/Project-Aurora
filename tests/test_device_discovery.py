from modules.experience.audio.device_discovery import (
    DiscoveredAudioDevice,
    WINDOWS_DEFAULT_INPUT_ID,
    device_choice_map,
    enumerate_dshow_audio_devices,
    resolve_voice_input_device,
    select_voice_input_device,
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
    assert "INZONE H9" in devices[0].display_name
    assert devices[0].device_name.endswith("D8D0}")
    assert devices[0].stable_id.endswith("D8D0}")


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


def test_windows_default_device_is_resolved_at_runtime(monkeypatch):
    output = '''
[dshow] "MAONO PD200X" (audio)
[dshow] Alternative name "@device_maono"
[dshow] "麦克风阵列 (Realtek Audio)" (audio)
[dshow] Alternative name "@device_realtek"
'''
    run = lambda *_args, **_kwargs: type("Result", (), {"stdout": "", "stderr": output, "returncode": 1})()
    settings = {"voice": {"recorder": {"device_id": WINDOWS_DEFAULT_INPUT_ID}}}
    monkeypatch.setattr(
        "modules.experience.audio.device_discovery._windows_default_input_name",
        lambda: "Realtek Audio",
    )

    assert resolve_voice_input_device(settings, run=run) == "@device_realtek"
    assert settings["voice"]["recorder"].get("last_successful_device_guid", "") == ""


def test_missing_saved_device_falls_back_to_windows_default(monkeypatch):
    settings = {"voice": {"recorder": {"device_id": "@device_disconnected"}}}
    monkeypatch.setattr(
        "modules.experience.audio.device_discovery._windows_default_input_name",
        lambda: "INZONE H9",
    )

    assert resolve_voice_input_device(settings, run=fake_run).endswith("D8D0}")
    assert settings["voice"]["recorder"]["device_id"] == "@device_disconnected"


def test_same_friendly_name_keeps_distinct_stable_ids():
    devices = [
        DiscoveredAudioDevice("USB Microphone", "@device_one"),
        DiscoveredAudioDevice("USB Microphone", "@device_two"),
    ]

    choices = device_choice_map(devices, default_label="Windows default")

    assert choices["USB Microphone · 1"] == "@device_one"
    assert choices["USB Microphone · 2"] == "@device_two"
    assert all("@device_" not in label for label in choices)


def test_selecting_windows_default_does_not_pin_old_guid():
    settings = {"voice": {"recorder": {"last_successful_device_guid": "@device_old"}}}

    selected = select_voice_input_device(settings, WINDOWS_DEFAULT_INPUT_ID)

    assert selected == WINDOWS_DEFAULT_INPUT_ID
    assert settings["voice"]["recorder"]["device_name"] == ""
    assert settings["voice"]["recorder"]["last_successful_device_guid"] == ""


def test_usb_device_disconnect_falls_back_and_reconnect_restores_saved_id(monkeypatch):
    saved = '''
[dshow] "USB Podcast Microphone" (audio)
[dshow] Alternative name "@device_saved"
'''
    backup = '''
[dshow] "Microphone Array (Realtek Audio)" (audio)
[dshow] Alternative name "@device_backup"
'''
    both = saved + backup

    def runner(output):
        return lambda *_args, **_kwargs: type(
            "Result", (), {"stdout": "", "stderr": output, "returncode": 1}
        )()

    settings = {"voice": {"recorder": {"device_id": "@device_saved"}}}
    monkeypatch.setattr(
        "modules.experience.audio.device_discovery._windows_default_input_name",
        lambda: "Realtek Audio",
    )

    assert resolve_voice_input_device(settings, run=runner(saved)) == "@device_saved"
    assert resolve_voice_input_device(settings, run=runner(backup)) == "@device_backup"
    assert resolve_voice_input_device(settings, run=runner(both)) == "@device_saved"


def test_windows_default_change_is_honored_without_changing_settings(monkeypatch):
    output = '''
[dshow] "Microphone One" (audio)
[dshow] Alternative name "@device_one"
[dshow] "Microphone Two" (audio)
[dshow] Alternative name "@device_two"
'''
    run = lambda *_args, **_kwargs: type("Result", (), {"stdout": "", "stderr": output, "returncode": 1})()
    current = {"name": "Microphone One"}
    monkeypatch.setattr(
        "modules.experience.audio.device_discovery._windows_default_input_name",
        lambda: current["name"],
    )
    settings = {"voice": {"recorder": {"device_id": WINDOWS_DEFAULT_INPUT_ID}}}

    assert resolve_voice_input_device(settings, run=run) == "@device_one"
    current["name"] = "Microphone Two"
    assert resolve_voice_input_device(settings, run=run) == "@device_two"
    assert settings["voice"]["recorder"]["device_id"] == WINDOWS_DEFAULT_INPUT_ID

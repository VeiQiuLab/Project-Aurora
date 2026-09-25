"""Allowlisted Voice control/status only. No audio, endpoint or provider text."""

SNAPSHOT_KEYS = {"revision", "state", "enabled", "provider", "generation_id", "error_code"}
STATES = {"idle", "preparing", "speaking", "stopping", "error"}
ERRORS = {"", "VOICE_UNAVAILABLE", "SYNTHESIS_FAILED", "PLAYBACK_FAILED",
          "VOICE_TIMEOUT", "INVALID_VOICE_SETTINGS"}


def validate_voice(kind, payload):
    def require(ok):
        if not ok:
            raise ValueError("Invalid Voice payload")

    def identifier(value):
        return isinstance(value, str) and 0 < len(value) <= 128

    if kind == "voice.get.request":
        require(payload == {})
    elif kind == "voice.stop.request":
        require(set(payload) == {"target_generation_id"} and identifier(payload["target_generation_id"]))
    else:
        require(set(payload) == SNAPSHOT_KEYS)
        require(type(payload["revision"]) is int and 0 <= payload["revision"] <= 9007199254740991)
        require(payload["state"] in STATES and type(payload["enabled"]) is bool)
        require(payload["provider"] in {"", "edge_tts", "remote_cosyvoice", "fake"})
        require(payload["generation_id"] is None or identifier(payload["generation_id"]))
        require(payload["error_code"] in ERRORS)
        require((payload["state"] == "error") == bool(payload["error_code"]))

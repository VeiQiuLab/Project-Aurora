"""Only disposable config roots. No production configuration writes."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from modules.settings_service import SettingsService, SettingsError, RULES, valid_host


def test_legacy_proxy_field_assignment_and_method_override(tmp_path, monkeypatch):
    from modules import settings as api
    path = tmp_path / "legacy.json"
    proxy = api._LazySettings()
    monkeypatch.setattr(api, "CONFIG_FILE", path)
    monkeypatch.setattr(api, "CONFIG_DIR", tmp_path)
    original_get = proxy.get
    monkeypatch.setattr(proxy, "get", lambda key, default=None: "override" if key == "fixture" else original_get(key, default))
    assert proxy.get("ollama.thinking_mode") == "off"
    proxy.data = {"fixture":"saved"}
    proxy.save()
    assert json.loads(path.read_text()) == {"fixture":"saved"}
    assert proxy.get("fixture") == "override"


@pytest.fixture
def service(tmp_path):
    path = tmp_path / "config" / "settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"ollama": {"thinking_mode": "off", "keep_alive": "30m"},
                               "qq": {"access_token": "fixture-secret"}, "unknown": {"retained": True}}))
    return SettingsService(path)


def rejected(service, values, code, revision=None):
    before, snap = service.config_file.read_bytes(), service.snapshot()
    with pytest.raises(SettingsError) as error:
        service.apply_patch(values, service.revision if revision is None else revision)
    assert error.value.code == code
    assert "fixture-secret" not in str(error.value)
    assert service.config_file.read_bytes() == before
    assert service.snapshot() is snap


def test_read_allowlist_secrets_defaults_no_write(service):
    before = service.config_file.stat().st_mtime_ns, service.config_file.read_bytes()
    dto = service.describe()
    assert {d["key"] for d in dto["descriptors"]} == set(RULES)
    assert "fixture-secret" not in json.dumps(dto)
    assert "qq.access_token" not in json.dumps(dto)
    assert service.policy.thinking_mode == "off" and service.policy.keep_alive == "30m"
    service.load()
    assert (service.config_file.stat().st_mtime_ns, service.config_file.read_bytes()) == before


@pytest.mark.parametrize("values,code", [
    ({"unknown":1}, "INVALID_SETTING"), ({"qq.access_token":"new"}, "INVALID_SETTING"),
    ({"resolved_chat_model":"new"}, "READ_ONLY"), ({"ollama.thinking_mode":"bad"}, "INVALID_VALUE"),
    ({"embedding_model_mode":"auto"}, "READ_ONLY"),
    ({"ollama.thinking_mode":False}, "INVALID_VALUE"), ({"rag.pipeline_enabled":1}, "INVALID_VALUE"),
    ({"memory.max_injection":True}, "INVALID_VALUE"), ({"memory.max_injection":0}, "INVALID_VALUE"),
    ({"memory.retrieval_threshold":1.1}, "INVALID_VALUE"), ({"memory.min_importance":float("nan")}, "INVALID_VALUE"),
    ({"ollama.keep_alive":-1}, "INVALID_VALUE"), ({"ollama.keep_alive":"forever"}, "INVALID_VALUE"),
    ({"chat_model":"bad model"}, "INVALID_VALUE"), ({"chat_model":"nomic-embed-text"}, "INVALID_VALUE"),
    ({"embedding_model":"qwen3.5:9b"}, "INVALID_VALUE"),
    ({"ollama.thinking_mode":"on","memory.max_injection":0}, "INVALID_VALUE"),
])
def test_invalid_all_or_nothing(service, values, code):
    rejected(service, values, code)


@pytest.mark.parametrize("host", ["http://127.0.0.1:11434", "https://localhost", "http://[::1]:11434", "https://node.example/"])
def test_host_allowed(host):
    assert valid_host(host)


@pytest.mark.parametrize("host", ["file:///secret", "http://user:pass@host", "http://host/api/chat",
    "http://host?token=secret", "http://host#secret", "http://host:0", "http://host:65536",
    "http://host:", "http://ho st", "http://host\\path", "http://host?", "http://host#", "http://"])
def test_host_rejected(service, host):
    rejected(service, {"ollama.host":host}, "INVALID_VALUE")


def test_noop_and_atomic_roundtrip(service):
    before = service.config_file.stat().st_mtime_ns, service.config_file.read_bytes()
    with patch.object(service, "_persist", side_effect=AssertionError("no IO")):
        assert service.apply_patch({"ollama.thinking_mode":"off"}, 0) == {
            "revision":0,"changed_keys":[],"restart_required_keys":[]}
    assert before == (service.config_file.stat().st_mtime_ns, service.config_file.read_bytes())
    old = service.snapshot()
    result = service.apply_patch({"ollama.thinking_mode":"on","ollama.keep_alive":"5m","rag.pipeline_enabled":False},0)
    assert result["revision"] == 1
    assert old.policy.thinking_mode == "off"
    assert service.policy.thinking_mode == "on" and service.policy.keep_alive == "5m"
    assert old.get("rag.pipeline_enabled") is True and service.get("rag.pipeline_enabled") is False
    reloaded = SettingsService(service.config_file)
    assert reloaded.policy == service.policy
    stored = json.loads(service.config_file.read_text())
    assert stored["qq"]["access_token"] == "fixture-secret" and stored["unknown"]["retained"] is True
    assert "voice" not in stored  # no mass migration/default insertion
    assert not list(service.config_file.parent.glob(".settings-*.tmp"))


@pytest.mark.parametrize("target", ["modules.settings_service.os.fsync", "modules.settings_service.os.replace",
                                    "modules.settings_service.tempfile.NamedTemporaryFile"])
def test_persistence_failure_preserves_file(service, target):
    with patch(target, side_effect=OSError("private path")):
        rejected(service, {"ollama.thinking_mode":"on"}, "PERSISTENCE_ERROR")
    assert not list(service.config_file.parent.glob(".settings-*.tmp"))


def test_invalid_serialization_before_write(service):
    service._raw["unsupported"] = object()
    rejected(service, {"ollama.thinking_mode":"on"}, "PERSISTENCE_ERROR")


def test_mid_temp_write_failure_preserves_original(service):
    import tempfile
    original = tempfile.NamedTemporaryFile
    class FailedWriter:
        def __init__(self, **kwargs):
            self.file = original(**kwargs)
            self.name = self.file.name
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.file.close()
        def write(self, data):
            self.file.write(data[:10])
            raise OSError("fixture partial write")
    with patch("modules.settings_service.tempfile.NamedTemporaryFile", FailedWriter):
        rejected(service, {"ollama.thinking_mode":"on"}, "PERSISTENCE_ERROR")
    assert not list(service.config_file.parent.glob(".settings-*.tmp"))


def test_stale_and_external_change(service):
    service.apply_patch({"ollama.thinking_mode":"on"},0)
    rejected(service, {"ollama.keep_alive":"5m"}, "CONFLICT", revision=0)
    raw = json.loads(service.config_file.read_text())
    raw["ollama"]["keep_alive"] = "2m"
    service.config_file.write_text(json.dumps(raw))
    rejected(service, {"ollama.keep_alive":"5m"}, "CONFLICT")
    service.load()
    assert service.policy.keep_alive == "2m" and service.revision == 2
    assert service.apply_patch({"ollama.keep_alive":"5m"},2)["revision"] == 3


def test_two_rapid_updates_one_revision_winner(service):
    def update(mode):
        try:
            return service.apply_patch({"ollama.thinking_mode":mode},0)["revision"]
        except SettingsError as e:
            return e.code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(update, ["on","default"]), key=str) == [1,"CONFLICT"]


def test_shutdown_waits_transaction_then_rejects_updates(service):
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    original = service._persist
    def persist(data):
        entered.set()
        assert release.wait(3)
        return original(data)
    with patch.object(service, "_persist", side_effect=persist), ThreadPoolExecutor(2) as pool:
        future = pool.submit(service.apply_patch, {"ollama.thinking_mode":"on"}, 0)
        assert entered.wait(2)
        close = pool.submit(lambda: (service.close(),closed.set()))
        assert not closed.wait(.03)
        release.set()
        assert future.result(timeout=3)["revision"] == 1
        close.result(timeout=3)
    rejected(service, {"ollama.keep_alive":"5m"}, "READ_ONLY")
    assert SettingsService(service.config_file).policy.thinking_mode == "on"


def test_invalid_and_missing_not_written(tmp_path):
    p = tmp_path / "missing" / "settings.json"
    s = SettingsService(p)
    assert not p.parent.exists()
    s.apply_patch({"ollama.thinking_mode":"on"},0)
    assert SettingsService(p).policy.thinking_mode == "on"
    p.write_text("{invalid")
    s = SettingsService(p)
    rejected(s, {"ollama.thinking_mode":"on"}, "PERSISTENCE_ERROR")


def test_public_descriptor_redacts_invalid_existing_host(service):
    raw = json.loads(service.config_file.read_text())
    raw["ollama"]["host"] = "http://user:fixture-secret@host"
    service.config_file.write_text(json.dumps(raw))
    service.load()
    assert "fixture-secret" not in json.dumps(service.describe())


def test_clear_model_does_not_resurrect_legacy_alias_on_reload(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"model":"old-model","mobile":{"model":"older-model","preserved":True},
                            "qq":{"access_token":"fixture-secret"}}))
    s = SettingsService(p)
    assert s.get("chat_model") == "old-model"
    s.apply_patch({"chat_model":""},0)
    assert s.get("chat_model") == ""
    assert SettingsService(p).get("chat_model") == ""
    raw = json.loads(p.read_text())
    assert raw["mobile"] == {"preserved":True}
    assert raw["qq"]["access_token"] == "fixture-secret"

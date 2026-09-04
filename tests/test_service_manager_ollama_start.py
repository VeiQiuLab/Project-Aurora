from modules.service_manager import ServiceManager


class _ImmediateThread:
    def __init__(self, target, daemon=True):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()


class _DeferredThread:
    created = []

    def __init__(self, target, daemon=True):
        self.target = target
        self.daemon = daemon
        self.__class__.created.append(self)

    def start(self):
        return None


def test_ready_api_never_starts_another_ollama(monkeypatch):
    manager = ServiceManager()
    events = []
    monkeypatch.setattr("modules.service_manager.threading.Thread", _ImmediateThread)
    monkeypatch.setattr(manager, "record_ollama_start_snapshot", lambda command: {})
    monkeypatch.setattr(manager, "diagnose_ollama", lambda url, timeout=1: {"available": True})
    monkeypatch.setattr(manager, "ollama_process_snapshot", lambda: {})
    monkeypatch.setattr("modules.service_manager.subprocess.Popen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not start")))

    manager.start_ollama("ollama serve", "http://127.0.0.1:11434", callback=events.append)

    assert "online" in events


def test_existing_offline_ollama_process_is_not_duplicated(monkeypatch):
    manager = ServiceManager()
    events = []
    existing = {42: {"pid": 42, "name": "ollama.exe"}}
    monkeypatch.setattr("modules.service_manager.threading.Thread", _ImmediateThread)
    monkeypatch.setattr(manager, "record_ollama_start_snapshot", lambda command: existing)
    monkeypatch.setattr(manager, "diagnose_ollama", lambda url, timeout=1: {"available": False})
    monkeypatch.setattr(manager, "ollama_process_snapshot", lambda: existing)
    monkeypatch.setattr("modules.service_manager.subprocess.Popen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not start")))

    manager.start_ollama("ollama serve", "http://127.0.0.1:11434", callback=events.append)

    assert "existing_process_offline" in events
    assert any(isinstance(event, dict) and event.get("event") == "ollama_existing_process_offline" for event in events)


def test_concurrent_start_requests_create_only_one_worker(monkeypatch):
    manager = ServiceManager()
    events = []
    _DeferredThread.created = []
    monkeypatch.setattr("modules.service_manager.threading.Thread", _DeferredThread)

    first = manager.start_ollama("ollama serve", "http://127.0.0.1:11434", callback=events.append)
    second = manager.start_ollama("ollama serve", "http://127.0.0.1:11434", callback=events.append)

    assert first is _DeferredThread.created[0]
    assert second is None
    assert len(_DeferredThread.created) == 1
    assert "starting" in events

import ast
import threading
import time
from pathlib import Path

import pytest

from modules.single_instance import (
    ACTIVATION_EVENT_NAME,
    WAIT_OBJECT_0,
    MutexResult,
    SingleInstanceGuard,
    enforce_single_instance,
)


class _FakeKernel:
    def __init__(self):
        self.mutex_owned = False
        self.activation_event = None
        self.activation_requests = 0

    def crash_primary(self):
        self.mutex_owned = False
        self.activation_event = None


class _FakeBackend:
    def __init__(self, kernel):
        self.kernel = kernel

    def create_mutex(self, _name):
        if self.kernel.mutex_owned:
            return MutexResult(("duplicate_mutex", object()), True)
        self.kernel.mutex_owned = True
        return MutexResult(("primary_mutex", object()), False)

    def create_event(self, name):
        assert name == ACTIVATION_EVENT_NAME
        event = threading.Event()
        self.kernel.activation_event = event
        return ("primary_event", event)

    def open_event(self, name):
        assert name == ACTIVATION_EVENT_NAME
        event = self.kernel.activation_event
        return ("opened_event", event) if event is not None else None

    def set_event(self, handle):
        if not handle:
            return False
        self.kernel.activation_requests += 1
        handle[1].set()
        return True

    def wait_event(self, handle, _timeout_ms=0xFFFFFFFF):
        handle[1].wait(timeout=1.0)
        handle[1].clear()
        return WAIT_OBJECT_0

    def close_handle(self, handle):
        if not handle:
            return
        if handle[0] == "primary_mutex":
            self.kernel.mutex_owned = False
        elif handle[0] == "primary_event":
            self.kernel.activation_event = None

    def activate_window(self, _hwnd):
        return True


def _guard(kernel):
    return SingleInstanceGuard(_FakeBackend(kernel))


def test_first_instance_starts_normally():
    kernel = _FakeKernel()
    guard = _guard(kernel)

    assert guard.claim_or_activate() is True
    assert guard.is_primary is True
    assert kernel.mutex_owned is True
    guard.close()


def test_second_instance_is_rejected_and_requests_activation():
    kernel = _FakeKernel()
    first = _guard(kernel)
    second = _guard(kernel)
    assert first.claim_or_activate() is True

    assert second.claim_or_activate() is False
    assert second.activation_requested is True
    assert kernel.activation_requests == 1
    first.close()


def test_second_instance_exits_before_service_initialization():
    kernel = _FakeKernel()
    primary = enforce_single_instance(_guard(kernel))
    initialized = []

    with pytest.raises(SystemExit) as exit_info:
        enforce_single_instance(_guard(kernel))
        initialized.append("services")

    assert exit_info.value.code == 0
    assert initialized == []
    primary.close()


def test_normal_close_allows_next_launch():
    kernel = _FakeKernel()
    first = enforce_single_instance(_guard(kernel))
    first.close()

    next_launch = enforce_single_instance(_guard(kernel))
    assert next_launch.is_primary is True
    next_launch.close()


def test_simulated_crash_does_not_leave_permanent_stale_lock():
    kernel = _FakeKernel()
    crashed = enforce_single_instance(_guard(kernel))
    assert crashed.is_primary is True
    kernel.crash_primary()

    recovered = enforce_single_instance(_guard(kernel))
    assert recovered.is_primary is True
    recovered.close()


def test_activation_listener_receives_request_from_second_instance():
    kernel = _FakeKernel()
    first = enforce_single_instance(_guard(kernel))
    activated = threading.Event()
    first.start_activation_listener(activated.set)

    with pytest.raises(SystemExit):
        enforce_single_instance(_guard(kernel))

    assert activated.wait(timeout=1.0)
    first.close()


def test_single_instance_gate_precedes_application_imports_and_services():
    source = Path("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    gate_line = next(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "enforce_single_instance"
    )
    customtkinter_line = next(
        node.lineno
        for node in tree.body
        if isinstance(node, ast.Import)
        and any(alias.name == "customtkinter" for alias in node.names)
    )
    store_line = source.index("memory_store = MemoryStore()")

    assert gate_line < customtkinter_line
    assert source.index("single_instance_guard = enforce_single_instance()") < store_line

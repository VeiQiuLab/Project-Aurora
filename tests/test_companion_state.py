import pytest

from modules.experience.state import (
    CompanionState,
    CompanionStateStore,
)


def test_initial_state_is_idle():
    store = CompanionStateStore()

    assert store.current_state is CompanionState.IDLE


def test_valid_transitions_follow_the_declared_flow():
    store = CompanionStateStore()

    for state in (
        CompanionState.LISTENING,
        CompanionState.TRANSCRIBING,
        CompanionState.THINKING,
        CompanionState.SPEAKING,
        CompanionState.IDLE,
    ):
        result = store.transition(state, source="test")
        assert result.success is True
        assert result.state is state


def test_invalid_transition_returns_failure_and_diagnostics():
    store = CompanionStateStore()

    result = store.transition(CompanionState.SPEAKING)

    assert result.success is False
    assert result.state is CompanionState.IDLE
    assert result.event is None
    assert result.diagnostics["success"] is False
    assert result.diagnostics["reason"] == "invalid_transition"
    assert store.last_diagnostics["reason"] == "invalid_transition"


@pytest.mark.parametrize(
    "state",
    (
        CompanionState.IDLE,
        CompanionState.LISTENING,
        CompanionState.TRANSCRIBING,
        CompanionState.THINKING,
        CompanionState.SPEAKING,
        CompanionState.FOCUSING,
        CompanionState.RESTING,
    ),
)
def test_any_non_error_state_can_enter_error(state):
    store = CompanionStateStore(initial_state=state)

    result = store.transition(CompanionState.ERROR, source="test")

    assert result.success is True
    assert store.current_state is CompanionState.ERROR


def test_subscribers_receive_events_and_can_unsubscribe():
    store = CompanionStateStore()
    received = []

    handle = store.subscribe(received.append)
    store.transition(CompanionState.THINKING, reason="chat_started", source="test")

    assert len(received) == 1
    assert received[0].previous_state is CompanionState.IDLE
    assert received[0].current_state is CompanionState.THINKING
    assert received[0].reason == "chat_started"
    assert store.unsubscribe(handle) is True
    assert store.unsubscribe(handle) is False
    store.transition(CompanionState.SPEAKING)
    assert len(received) == 1


def test_subscriber_exception_isolated_and_recorded():
    store = CompanionStateStore()
    received = []

    def broken_subscriber(_event):
        raise RuntimeError("renderer unavailable")

    store.subscribe(broken_subscriber)
    store.subscribe(received.append)

    result = store.transition(CompanionState.THINKING)

    assert result.success is True
    assert received
    assert result.diagnostics["warnings"]
    assert "renderer unavailable" in result.diagnostics["warnings"][0]


@pytest.mark.parametrize(
    "state",
    (
        CompanionState.LISTENING,
        CompanionState.TRANSCRIBING,
        CompanionState.THINKING,
        CompanionState.SPEAKING,
        CompanionState.ERROR,
        CompanionState.FOCUSING,
        CompanionState.RESTING,
    ),
)
def test_force_idle_recovers_from_any_non_idle_state(state):
    store = CompanionStateStore(initial_state=state)

    result = store.force_idle(reason="cleanup", source="test")

    assert result.success is True
    assert store.current_state is CompanionState.IDLE

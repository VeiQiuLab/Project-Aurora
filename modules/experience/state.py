"""Small, testable state coordinator for Aurora's Experience Layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from time import time
from typing import Callable, Mapping

from modules.diagnostics import create_diagnostics


class CompanionState(str, Enum):
    """States shared by optional companion experiences."""

    IDLE = "IDLE"
    VOICE_READY = "VOICE_READY"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"
    FOCUSING = "FOCUSING"
    RESTING = "RESTING"


@dataclass(frozen=True)
class CompanionStateEvent:
    """Immutable notification emitted after a valid state transition."""

    previous_state: CompanionState
    current_state: CompanionState
    reason: str = ""
    source: str = ""
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    timestamp: float = field(default_factory=time)


@dataclass(frozen=True)
class CompanionStateTransitionResult:
    """Result object for both accepted and rejected transitions."""

    success: bool
    state: CompanionState
    event: CompanionStateEvent | None = None
    diagnostics: Mapping[str, object] = field(default_factory=dict)


Subscriber = Callable[[CompanionStateEvent], None]


class CompanionStateStore:
    """Own the current state and notify subscribers without owning any UI."""

    _ALLOWED_TRANSITIONS = {
        CompanionState.IDLE: frozenset(
            {CompanionState.VOICE_READY, CompanionState.LISTENING, CompanionState.THINKING, CompanionState.ERROR}
        ),
        CompanionState.VOICE_READY: frozenset(
            {CompanionState.LISTENING, CompanionState.IDLE, CompanionState.ERROR}
        ),
        CompanionState.LISTENING: frozenset(
            {CompanionState.TRANSCRIBING, CompanionState.ERROR}
        ),
        CompanionState.TRANSCRIBING: frozenset(
            {CompanionState.THINKING, CompanionState.ERROR}
        ),
        CompanionState.THINKING: frozenset(
            {CompanionState.SPEAKING, CompanionState.ERROR}
        ),
        CompanionState.SPEAKING: frozenset(
            {CompanionState.IDLE, CompanionState.ERROR}
        ),
        CompanionState.ERROR: frozenset({CompanionState.IDLE}),
        CompanionState.FOCUSING: frozenset({CompanionState.ERROR}),
        CompanionState.RESTING: frozenset({CompanionState.ERROR}),
    }

    def __init__(self, initial_state: CompanionState = CompanionState.IDLE):
        self._lock = RLock()
        self._state = self._coerce_state(initial_state)
        self._subscribers: list[Subscriber] = []
        self._last_diagnostics = create_diagnostics(
            stage="experience.companion_state",
            success=True,
            reason="initialized",
            metrics={"state": self._state.value},
        )

    @property
    def current_state(self) -> CompanionState:
        with self._lock:
            return self._state

    @property
    def last_diagnostics(self) -> Mapping[str, object]:
        with self._lock:
            return dict(self._last_diagnostics)

    def subscribe(self, callback: Subscriber) -> Subscriber:
        """Register a callback and return it as the unsubscribe handle."""

        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)
        return callback

    def unsubscribe(self, callback: Subscriber) -> bool:
        """Remove a callback; return whether it was registered."""

        with self._lock:
            if callback not in self._subscribers:
                return False
            self._subscribers.remove(callback)
            return True

    def transition(
        self,
        next_state: CompanionState,
        *,
        reason: str = "",
        source: str = "",
    ) -> CompanionStateTransitionResult:
        """Attempt a validated transition without raising for invalid input."""

        try:
            target = self._coerce_state(next_state)
        except (TypeError, ValueError) as exc:
            diagnostics = self._set_diagnostics(
                success=False,
                reason="invalid_state",
                warnings=[str(exc)],
            )
            return CompanionStateTransitionResult(
                success=False,
                state=self.current_state,
                diagnostics=diagnostics,
            )

        with self._lock:
            current = self._state
            if target not in self._ALLOWED_TRANSITIONS[current]:
                diagnostics = self._set_diagnostics_locked(
                    success=False,
                    reason="invalid_transition",
                    warnings=[f"{current.value} -> {target.value} is not allowed"],
                )
                return CompanionStateTransitionResult(
                    success=False,
                    state=current,
                    diagnostics=diagnostics,
                )
            self._state = target
            event = CompanionStateEvent(
                previous_state=current,
                current_state=target,
                reason=reason,
                source=source,
                diagnostics=create_diagnostics(
                    stage="experience.companion_state",
                    success=True,
                    reason="transitioned",
                    metrics={"from": current.value, "to": target.value},
                ),
            )
            subscribers = tuple(self._subscribers)

        subscriber_errors = []
        for callback in subscribers:
            try:
                callback(event)
            except Exception as exc:  # subscriber isolation is part of the contract
                subscriber_errors.append(f"{type(exc).__name__}: {exc}")

        diagnostics = self._set_diagnostics(
            success=True,
            reason="transitioned",
            warnings=subscriber_errors,
            metrics={"from": event.previous_state.value, "to": event.current_state.value},
        )
        return CompanionStateTransitionResult(
            success=True,
            state=target,
            event=event,
            diagnostics=diagnostics,
        )

    def force_idle(self, *, reason: str = "", source: str = "") -> CompanionStateTransitionResult:
        """Return safely to IDLE after an error or cancelled experience action."""

        with self._lock:
            current = self._state
            if current is CompanionState.IDLE:
                diagnostics = self._set_diagnostics_locked(
                    success=True,
                    reason="already_idle",
                    metrics={"state": CompanionState.IDLE.value},
                )
                return CompanionStateTransitionResult(
                    success=True,
                    state=CompanionState.IDLE,
                    diagnostics=diagnostics,
                )
            self._state = CompanionState.IDLE
            event = CompanionStateEvent(
                previous_state=current,
                current_state=CompanionState.IDLE,
                reason=reason or "forced_idle",
                source=source,
                diagnostics=create_diagnostics(
                    stage="experience.companion_state",
                    success=True,
                    reason="forced_idle",
                    metrics={"from": current.value, "to": CompanionState.IDLE.value},
                ),
            )
            subscribers = tuple(self._subscribers)

        subscriber_errors = []
        for callback in subscribers:
            try:
                callback(event)
            except Exception as exc:  # subscriber isolation is part of the contract
                subscriber_errors.append(f"{type(exc).__name__}: {exc}")

        diagnostics = self._set_diagnostics(
            success=True,
            reason="forced_idle",
            warnings=subscriber_errors,
            metrics={"from": event.previous_state.value, "to": event.current_state.value},
        )
        return CompanionStateTransitionResult(
            success=True,
            state=CompanionState.IDLE,
            event=event,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _coerce_state(state: CompanionState) -> CompanionState:
        if isinstance(state, CompanionState):
            return state
        return CompanionState(state)

    def _set_diagnostics(
        self,
        *,
        success: bool,
        reason: str,
        warnings: list[str] | None = None,
        metrics: dict[str, object] | None = None,
    ) -> Mapping[str, object]:
        with self._lock:
            return self._set_diagnostics_locked(
                success=success,
                reason=reason,
                warnings=warnings,
                metrics=metrics,
            )

    def _set_diagnostics_locked(
        self,
        *,
        success: bool,
        reason: str,
        warnings: list[str] | None = None,
        metrics: dict[str, object] | None = None,
    ) -> Mapping[str, object]:
        self._last_diagnostics = create_diagnostics(
            stage="experience.companion_state",
            success=success,
            reason=reason,
            warnings=warnings,
            metrics=metrics,
        )
        return dict(self._last_diagnostics)

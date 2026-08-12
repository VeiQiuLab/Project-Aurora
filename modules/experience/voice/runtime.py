"""Application entry point for running the optional voice pipeline."""

from __future__ import annotations

from threading import Event, RLock, Thread
from time import sleep
from typing import Callable
from uuid import uuid4

from modules.experience.state import CompanionStateEvent
from modules.logger import logger

from .orchestrator import VoiceOrchestrationResult, VoiceOrchestrator


StateCallback = Callable[[CompanionStateEvent], None]


class RuntimeService:
    """Own voice session lifecycle while delegating workflow to the orchestrator."""

    def __init__(
        self,
        orchestrator: VoiceOrchestrator,
        *,
        state_callback: StateCallback | None = None,
        session_manager=None,
        orchestrator_factory: Callable[[], VoiceOrchestrator] | None = None,
    ):
        self.orchestrator = orchestrator
        self.session_manager = session_manager
        self.orchestrator_factory = orchestrator_factory
        self._lock = RLock()
        self._session_running = False
        self._thread: Thread | None = None
        self._finished = Event()
        self._last_result: VoiceOrchestrationResult | None = None
        self._run_token: str | None = None
        self._state_callbacks: list[StateCallback] = []
        self.orchestrator.state_store.subscribe(self._forward_state_event)
        if state_callback is not None:
            self.subscribe_state(state_callback)

    @property
    def session_running(self) -> bool:
        """Return whether a voice session is currently executing."""

        with self._lock:
            return self._session_running

    @property
    def last_result(self) -> VoiceOrchestrationResult | None:
        with self._lock:
            return self._last_result

    def start_voice_session(self) -> bool:
        """Start one background voice session; return False if one is active."""

        with self._lock:
            if self._session_running:
                return False
            token = uuid4().hex
            orchestrator = (
                self.orchestrator_factory()
                if self.orchestrator_factory is not None
                else self.orchestrator
            )
            set_generation_context = getattr(orchestrator, "set_generation_context", None)
            if callable(set_generation_context) and self.session_manager is None:
                set_generation_context(token, getattr(orchestrator, "generation_id", token))
            self.orchestrator = orchestrator
            self._session_running = True
            self._run_token = token
            self._last_result = None
            self._finished.clear()
            self._thread = Thread(
                target=self._run_session,
                args=(token, orchestrator),
                name="aurora-voice-runtime",
                daemon=True,
            )
            thread = self._thread
        try:
            thread.start()
        except Exception:
            with self._lock:
                self._session_running = False
                self._thread = None
                self._run_token = None
                self._finished.set()
            raise
        return True

    def cancel_voice_session(self) -> bool:
        """Request cancellation for the active session."""

        with self._lock:
            if not self._session_running:
                return False
            token = self._run_token
            self._session_running = False
        logger.info(f"[VOICE] event=interrupt runtime_token={token}")
        if self.session_manager is not None:
            self.session_manager.cancel_session()
        else:
            self.orchestrator.cancel()
        return True

    def subscribe_state(self, callback: StateCallback) -> StateCallback:
        """Subscribe to state events forwarded from the shared state store."""

        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._lock:
            if callback not in self._state_callbacks:
                self._state_callbacks.append(callback)
        return callback

    def unsubscribe_state(self, callback: StateCallback) -> bool:
        """Remove a runtime state callback."""

        with self._lock:
            if callback not in self._state_callbacks:
                return False
            self._state_callbacks.remove(callback)
            return True

    def wait_for_session(self, timeout_seconds: float | None = None) -> VoiceOrchestrationResult | None:
        """Wait for the current session and return its orchestration result."""

        self._finished.wait(timeout_seconds)
        return self.last_result

    def _run_session(self, token: str, orchestrator: VoiceOrchestrator) -> None:
        try:
            if self.session_manager is None:
                result = orchestrator.run()
            else:
                if not self.session_manager.start_session():
                    result = VoiceOrchestrationResult(
                        success=False,
                        stage="session_start_failed",
                    )
                else:
                    session_id = self.session_manager.session_id
                    while (
                        self.session_manager.session_running
                        and self.session_manager.session_id == session_id
                    ):
                        sleep(0.05)
                    session_result = (
                        self.session_manager.last_result
                        if self.session_manager.session_id == session_id
                        else None
                    )
                    if session_result is None:
                        result = VoiceOrchestrationResult(
                            success=False,
                            stage="session_result_missing",
                        )
                    else:
                        result = VoiceOrchestrationResult(
                            success=session_result.completed,
                            cancelled=session_result.cancelled,
                            stage=session_result.reason,
                            diagnostics=session_result.diagnostics,
                        )
            with self._lock:
                if token == self._run_token:
                    self._last_result = result
        except Exception as error:
            with self._lock:
                if token == self._run_token:
                    self._last_result = VoiceOrchestrationResult(
                        success=False,
                        stage="runtime_error",
                        diagnostics={"error": str(error)},
                    )
        finally:
            with self._lock:
                if token == self._run_token:
                    self._session_running = False
                    self._run_token = None
                    self._finished.set()

    def _forward_state_event(self, event: CompanionStateEvent) -> None:
        with self._lock:
            callbacks = tuple(self._state_callbacks)
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                # State observers are optional and must not stop the runtime thread.
                continue

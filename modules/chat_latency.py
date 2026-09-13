"""Request-local, content-free latency diagnostics for Aurora chat turns."""

from __future__ import annotations

import inspect
import json
import threading
from contextlib import contextmanager
from time import monotonic


_STAGES = (
    "session_snapshot",
    "memory_context",
    "knowledge_context",
    "persona_context",
    "rag_context",
    "context_builder",
)

_DERIVED_DURATIONS = {
    "turn_to_stream_chat_ms": (
        "turn_start_monotonic",
        "stream_chat_enter_monotonic",
    ),
    "turn_to_ollama_request_ms": (
        "turn_start_monotonic",
        "urlopen_start_monotonic",
    ),
    "context_ready_to_stream_chat_ms": (
        "final_messages_ready_monotonic",
        "stream_chat_enter_monotonic",
    ),
}

_STAGE_DURATION_NAMES = {
    "session_snapshot": "session_snapshot_ms",
    "memory_context": "memory_ms",
    "knowledge_context": "knowledge_ms",
    "persona_context": "persona_ms",
    "rag_context": "rag_ms",
    "context_builder": "context_builder_total_ms",
}


def callback_accepts_keyword(callback, keyword):
    """Return whether *callback* explicitly or generically accepts a keyword."""

    try:
        parameters = inspect.signature(callback).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        or (
            parameter.name == keyword
            and parameter.kind
            in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
        )
        for parameter in parameters
    )


class PreLLMLatencyDiagnostics:
    """Own timing state for exactly one ChatPage text or voice turn."""

    def __init__(self, *, source, clock=monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self.data = {
            "latency_schema": "pre_llm_v1",
            "turn_source": str(source or "chat"),
            "turn_id": None,
            "turn_status": "pending",
            "turn_start_monotonic": self._clock(),
            "final_messages_ready_monotonic": None,
            "stream_chat_enter_monotonic": None,
            "ollama_request_start_monotonic": None,
            "turn_end_monotonic": None,
            "turn_to_stream_chat_ms": None,
            "turn_to_ollama_request_ms": None,
            "context_ready_to_stream_chat_ms": None,
            "error_stage": None,
            "error_type": None,
        }
        for stage in _STAGES:
            self.data.update({
                f"{stage}_enabled": None,
                f"{stage}_status": "not_run",
                f"{stage}_start_monotonic": None,
                f"{stage}_end_monotonic": None,
                _STAGE_DURATION_NAMES[stage]: None,
            })

    def set_turn_id(self, turn_id):
        self.update(turn_id=int(turn_id))

    def mark(self, name):
        now = self._clock()
        with self._lock:
            if self.data.get(name) is None:
                self.data[name] = now
                return now
            return self.data[name]

    def update(self, **values):
        with self._lock:
            self.data.update(values)

    def start_stage(self, stage, *, enabled=True):
        self._validate_stage(stage)
        if not enabled:
            self.skip_stage(stage)
            return False
        now = self._clock()
        with self._lock:
            self.data[f"{stage}_enabled"] = True
            self.data[f"{stage}_status"] = "running"
            self.data[f"{stage}_start_monotonic"] = now
            self.data[f"{stage}_end_monotonic"] = None
            self.data[_STAGE_DURATION_NAMES[stage]] = None
        return True

    def finish_stage(self, stage, *, status="completed"):
        self._validate_stage(stage)
        now = self._clock()
        with self._lock:
            started = self.data.get(f"{stage}_start_monotonic")
            if started is None:
                return None
            self.data[f"{stage}_end_monotonic"] = now
            self.data[f"{stage}_status"] = str(status)
            duration = max(0.0, (now - started) * 1000.0)
            self.data[_STAGE_DURATION_NAMES[stage]] = duration
        return duration

    def skip_stage(self, stage):
        self._validate_stage(stage)
        with self._lock:
            self.data[f"{stage}_enabled"] = False
            self.data[f"{stage}_status"] = "not_run"
            self.data[f"{stage}_start_monotonic"] = None
            self.data[f"{stage}_end_monotonic"] = None
            self.data[_STAGE_DURATION_NAMES[stage]] = None

    def fail_stage(self, stage, error):
        self.finish_stage(stage, status="failed")
        with self._lock:
            if self.data.get("error_stage") is None:
                self.data["error_stage"] = stage
                self.data["error_type"] = type(error).__name__

    @contextmanager
    def stage(self, stage, *, enabled=True):
        running = self.start_stage(stage, enabled=enabled)
        try:
            yield running
        except Exception as error:
            if running:
                self.fail_stage(stage, error)
            raise
        else:
            if running:
                self.finish_stage(stage)

    def finish_turn(self, status):
        now = self._clock()
        with self._lock:
            self.data["turn_end_monotonic"] = now
            self.data["turn_status"] = str(status)
            self.data["ollama_request_start_monotonic"] = self.data.get(
                "urlopen_start_monotonic"
            )
            for output_name, (start_name, end_name) in _DERIVED_DURATIONS.items():
                start = self.data.get(start_name)
                end = self.data.get(end_name)
                self.data[output_name] = (
                    max(0.0, (end - start) * 1000.0)
                    if isinstance(start, (int, float)) and isinstance(end, (int, float))
                    else None
                )
        return self.report()

    def report(self):
        """Return only scalar timing, status, count, and size diagnostics."""

        with self._lock:
            values = dict(self.data)
        report = {}
        for key, value in values.items():
            allowed = (
                key in {
                    "latency_schema",
                    "turn_source",
                    "turn_id",
                    "turn_status",
                    "error_stage",
                    "error_type",
                    "active_response",
                    "status",
                    "ollama_think_mode",
                    "think_payload_value",
                    "ollama_keep_alive",
                }
                or key.endswith("_monotonic")
                or key.endswith("_ms")
                or key.endswith("_count")
                or key.endswith("_chars")
                or key.endswith("_tokens")
                or key.endswith("_enabled")
                or key.endswith("_status")
            )
            if allowed and isinstance(value, (str, int, float, bool, type(None))):
                report[key] = value
        return report

    def to_log_line(self):
        return "chat_latency_diagnostics " + json.dumps(
            self.report(),
            ensure_ascii=True,
            sort_keys=True,
        )

    @staticmethod
    def _validate_stage(stage):
        if stage not in _STAGES:
            raise ValueError(f"Unsupported latency stage: {stage}")

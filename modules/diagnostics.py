"""Serializable diagnostics contract for future Aurora pipeline stages."""

from copy import deepcopy


class Diagnostics:
    """Small value object for creating independent diagnostics dictionaries."""

    def __init__(
        self,
        stage="",
        success=True,
        reason="",
        warnings=None,
        metrics=None,
        trace=None,
    ):
        self.stage = str(stage or "")
        self.success = bool(success)
        self.reason = str(reason or "")
        self.warnings = deepcopy(warnings) if isinstance(warnings, list) else []
        self.metrics = deepcopy(metrics) if isinstance(metrics, dict) else {}
        self.trace = deepcopy(trace) if isinstance(trace, dict) else {}

    def to_dict(self):
        """Return a detached, serializable diagnostics dictionary."""

        return {
            "stage": self.stage,
            "success": self.success,
            "reason": self.reason,
            "warnings": deepcopy(self.warnings),
            "metrics": deepcopy(self.metrics),
            "trace": deepcopy(self.trace),
        }

    as_dict = to_dict

    @classmethod
    def create(cls, **kwargs):
        return cls(**kwargs).to_dict()


def create_diagnostics(
    stage="",
    success=True,
    reason="",
    warnings=None,
    metrics=None,
    trace=None,
):
    """Create a detached diagnostics dictionary with the stable C6 schema."""

    return Diagnostics(
        stage=stage,
        success=success,
        reason=reason,
        warnings=warnings,
        metrics=metrics,
        trace=trace,
    ).to_dict()

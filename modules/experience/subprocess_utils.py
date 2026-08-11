"""Subprocess helpers for optional Experience Layer background tools."""

from __future__ import annotations

import os
import subprocess
from typing import Any


def with_hidden_console(kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Hide background subprocess consoles on Windows when supported."""

    options = dict(kwargs or {})
    if os.name == "nt":
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if create_no_window:
            options["creationflags"] = int(options.get("creationflags", 0)) | create_no_window
    return options

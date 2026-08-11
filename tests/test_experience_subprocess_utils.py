import os
import subprocess

from modules.experience.subprocess_utils import with_hidden_console


def test_with_hidden_console_preserves_existing_kwargs():
    options = with_hidden_console({"text": True})

    assert options["text"] is True


def test_with_hidden_console_sets_create_no_window_on_windows():
    options = with_hidden_console()

    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        assert options["creationflags"] & subprocess.CREATE_NO_WINDOW
    else:
        assert "creationflags" not in options

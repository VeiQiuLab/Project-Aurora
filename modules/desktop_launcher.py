"""Launch only v4 Desktop; never build, download or fall back to legacy UI."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
RELEASE = Path("prototype/aurora-v4/desktop/src-tauri/target/release/aurora-v4-desktop.exe")


def resolve_executable(root: Path = ROOT) -> Path:
    configured = os.environ.get("AURORA_DESKTOP_EXE")
    path = Path(configured) if configured else root / RELEASE
    if not path.is_absolute() or not path.is_file() or path.suffix.lower() != ".exe":
        raise ValueError("Aurora v4 Desktop is unavailable. Run build_exe.ps1 or set AURORA_DESKTOP_EXE to its absolute EXE path. No legacy fallback.")
    return path.resolve()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Launch Aurora v4 / Tauri Desktop (no Tk fallback).")
    parser.add_argument("--check", action="store_true", help="Validate the Desktop path without starting any process.")
    args = parser.parse_args(argv)
    try:
        executable = resolve_executable()
        if args.check:
            print(executable)
            return 0
        if sys.platform != "win32":
            raise ValueError("Aurora Desktop currently requires Windows.")
        subprocess.Popen([str(executable)], cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)
        return 0
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2

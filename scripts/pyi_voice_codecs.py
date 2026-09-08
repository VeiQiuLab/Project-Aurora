"""PyInstaller runtime hook: load only Aurora's packaged LGPL codec DLLs."""
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    # Retain the handle for the lifetime of the process. Never add a developer
    # environment or PATH directory to the frozen application's DLL search.
    sys._aurora_codec_directory = os.add_dll_directory(str(Path(sys._MEIPASS) / "voice_codecs"))

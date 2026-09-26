"""Select a separate legacy data namespace before any shared module is loaded."""
import os
from pathlib import Path
import sys


def activate_legacy_data() -> Path:
    if "modules.app_paths" in sys.modules:
        raise RuntimeError("Legacy data isolation must precede shared runtime imports")
    appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    destination = (appdata / "Aurora-Legacy").resolve()
    protected = [(appdata / "Aurora").resolve()]
    if os.environ.get("AURORA_USER_DATA_DIR"):
        protected.append(Path(os.environ["AURORA_USER_DATA_DIR"]).expanduser().resolve())
    for path in protected:
        if destination == path or destination.is_relative_to(path) or path.is_relative_to(destination):
            raise RuntimeError("Legacy and production data directories overlap")
    os.environ["AURORA_USER_DATA_DIR"] = str(destination)
    return destination

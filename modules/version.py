"""
Project Aurora
Version Information
"""

APP_NAME = "Project Aurora"

VERSION = "3.8.0-alpha"

# Windows PE resources require a numeric four-part version. Keep this derived
# from the display version so VERSION remains the release source of truth.
_VERSION_CORE = VERSION.split("-", 1)[0]
WINDOWS_VERSION = f"{_VERSION_CORE}.0"
WINDOWS_VERSION_TUPLE = tuple(int(part) for part in WINDOWS_VERSION.split("."))

BUILD_DATE = "2026-08-12"

BUILD = BUILD_DATE

RELEASE = f"v{VERSION}"

AUTHOR = "Xu"

COPYRIGHT = "Copyright \u00a9 2026 Project Aurora"

WELCOME = "Your Local AI Control Center"

WINDOW_TITLE = f"{APP_NAME} {VERSION}"

USER_AGENT = f"ProjectAurora/{VERSION}"

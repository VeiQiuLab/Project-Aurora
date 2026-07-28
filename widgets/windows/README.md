# Project Aurora Window Modules

This directory is reserved for the v2.6 window-module layout.

Current window modules remain in `widgets/` for compatibility:

- `chat_window.py`
- `settings_window.py`
- `knowledge_window.py`
- `memory_window.py`
- `persona_window.py`
- `remote_window.py`
- `conversation_browser.py`

Do not move these files until imports, PyInstaller packaging, and legacy entry
points are migrated in a dedicated phase.

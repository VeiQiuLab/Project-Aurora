# Project Aurora Window Modules

The production user entry point is:

```text
AppShell
  -> Chat
  -> Settings
```

The `widgets/windows/` directory remains reserved for a possible organized
window-module layout. Existing window classes are still located directly under
`widgets/` and have mixed status.

## Active Compatibility / Utility

- `settings_window.py`: opened from the current Settings page for existing
  detailed settings editors.

## Legacy / Needs Review

- `chat_window.py`
- `conversation_browser.py`
- `health_window.py`
- `models_window.py`
- `knowledge_window.py`
- `memory_window.py`
- `persona_window.py`

Some classes remain imported or referenced by legacy callbacks in `main.py`;
others may remain useful as focused editors or diagnostics. They are not current
primary navigation and must not be declared dead or deleted without a dedicated
reachability, packaging, and callback review.

Do not move or remove these modules casually. Any cleanup must preserve active
Settings callbacks, PyInstaller imports, and user data operations.

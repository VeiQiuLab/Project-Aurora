# Retired Tk Desktop — explicit compatibility only

Aurora v4/Tauri is the official product. This directory retains the former
entrypoint without deleting shared AI logic or historical behavioral tests.
`widgets/` and Tk-only theme code remain in place to preserve those imports;
their location does not make them v4 dependencies.

For deliberate legacy development, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r legacy/requirements.txt
.\.venv\Scripts\python.exe -m legacy.tk_desktop
```

Legacy requires Tcl/Tk and optional historical Voice dependencies. It always
selects `%APPDATA%/Aurora-Legacy` **before** importing settings, logging or stores.
It does not honor production `AURORA_USER_DATA_DIR` as a write destination, copy
production data or migrate the old production directory. Resolved overlap with
the production directory (including junctions) is rejected. Only its own
isolated data is owned by its old settings/conversation/voice controllers.
Do not use a junction to deliberately join these namespaces after launch.

Retained package recipes require explicit `-Legacy` on build_exe.ps1,
build_portable.ps1 and installer/build_installer.ps1. The PyInstaller spec also
requires `AURORA_LEGACY_BUILD=1`; the Inno recipe requires AuroraLegacyBuild.
They are historical compatibility tools, not production release targets, and
have not been rebuilt as part of retirement. Full Voice distribution licensing
and integrity checks remain intact. Legacy installer shortcuts are labeled Legacy.
Portable/installer entrypoints require a fresh `legacy-build.json` marker and
matching EXE hash from the updated legacy builder. This prevents accidentally
repackaging a pre-retirement EXE that still writes production data; it is a local
build consistency check, not a signature or a trust guarantee for outside files.

The main project requirements no longer include CustomTkinter, PyInstaller,
pygame, Faster-Whisper, sounddevice or websocket-client. They remain here for
legacy tests/tools. No installed dependency or Python Tcl/Tk component is
uninstalled by this change. The full historical regression suite still needs
these extras; v4-only tests must not.

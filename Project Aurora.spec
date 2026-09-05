from pathlib import Path
import os
import unicodedata

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

from modules.version import (
    APP_NAME,
    BUILD_DATE,
    COPYRIGHT,
    VERSION,
    WINDOWS_VERSION,
    WINDOWS_VERSION_TUPLE,
)


project_root = Path(SPECPATH)
icon_path = project_root / "assets" / "app.ico"
assets_dir = project_root / "assets"
unicodedata_binary = Path(unicodedata.__file__)
if not unicodedata_binary.is_file():
    raise RuntimeError(f"unicodedata extension not found: {unicodedata_binary}")
if not assets_dir.is_dir():
    raise RuntimeError(f"release assets directory not found: {assets_dir}")

datas = [
    (str(project_root / "locales"), "locales"),
    (str(project_root / "config" / "default_settings.json"), "config"),
    (str(project_root / "config" / "voice_runtime_build.json"), "config"),
    (str(assets_dir), "assets"),
    *collect_data_files("customtkinter"),
]

# Keep the portable test package Core-only.  In particular, faster-whisper's
# PyAV dependency redistributes FFmpeg codec libraries.  Aurora must not ship
# those optional binaries until their release/licensing obligations are handled
# explicitly.  Runtime diagnostics report these components as optional/missing.
full_voice_build = os.environ.get("AURORA_FULL_VOICE_BUILD") == "1"
if full_voice_build and os.environ.get("AURORA_VOICE_CODEC_LICENSE_REVIEW") != "approved":
    raise RuntimeError(
        "Full Voice Build is gated until FFmpeg/PyAV codec licensing is explicitly reviewed."
    )

optional_voice_excludes = [] if full_voice_build else [
    "av",
    "ctranslate2",
    "edge_tts",
    "faster_whisper",
    "pygame",
    "sounddevice",
]
voice_hiddenimports = []
if full_voice_build:
    for package in ("faster_whisper", "ctranslate2", "edge_tts", "pygame", "sounddevice", "av"):
        voice_hiddenimports.extend(collect_submodules(package))

version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=WINDOWS_VERSION_TUPLE,
        prodvers=WINDOWS_VERSION_TUPLE,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringTable("040904B0", [
                StringStruct("CompanyName", APP_NAME),
                StringStruct("FileDescription", APP_NAME),
                StringStruct("FileVersion", WINDOWS_VERSION),
                StringStruct("InternalName", "Aurora"),
                StringStruct("LegalCopyright", COPYRIGHT),
                StringStruct("OriginalFilename", "Aurora.exe"),
                StringStruct("ProductName", APP_NAME),
                StringStruct("ProductVersion", VERSION),
                StringStruct("BuildDate", BUILD_DATE),
            ])
        ]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)


a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[(str(unicodedata_binary), ".")],
    datas=datas,
    hiddenimports=[
        "customtkinter",
        *collect_submodules("customtkinter"),
        *voice_hiddenimports,
        "unicodedata",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=optional_voice_excludes,
    noarchive=False
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="Aurora",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(icon_path) if icon_path.exists() else None,
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="Aurora"
)

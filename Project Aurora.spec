from pathlib import Path
import unicodedata

from PyInstaller.utils.hooks import collect_submodules
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
tools_dir = project_root / "tools"
ffmpeg_path = tools_dir / "ffmpeg.exe"
unicodedata_binary = Path(unicodedata.__file__)
if not unicodedata_binary.is_file():
    raise RuntimeError(f"unicodedata extension not found: {unicodedata_binary}")
if not assets_dir.is_dir():
    raise RuntimeError(f"release assets directory not found: {assets_dir}")
if not ffmpeg_path.is_file():
    raise RuntimeError(f"bundled ffmpeg not found: {ffmpeg_path}")

datas = [
    (str(project_root / "locales"), "locales"),
    (str(project_root / "config" / "default_settings.json"), "config"),
    (str(assets_dir), "assets"),
    (str(tools_dir), "tools"),
]

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


def optional_submodules(package_name):
    try:
        return collect_submodules(package_name)
    except Exception:
        return []

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[(str(unicodedata_binary), ".")],
    datas=datas,
    hiddenimports=[
        "customtkinter",
        *collect_submodules("customtkinter"),
        *optional_submodules("edge_tts"),
        *optional_submodules("faster_whisper"),
        *optional_submodules("ctranslate2"),
        *optional_submodules("sounddevice"),
        *optional_submodules("pygame"),
        "unicodedata",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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

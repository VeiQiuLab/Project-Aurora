from pathlib import Path
import unicodedata

from PyInstaller.utils.hooks import collect_submodules


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
    icon=str(icon_path) if icon_path.exists() else None
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

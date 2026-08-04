from pathlib import Path
import unicodedata

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPECPATH)
icon_path = project_root / "assets" / "app.ico"
unicodedata_binary = Path(unicodedata.__file__)
if not unicodedata_binary.is_file():
    raise RuntimeError(f"unicodedata extension not found: {unicodedata_binary}")

datas = [
    (str(project_root / "config"), "config"),
    (str(project_root / "data"), "data"),
    (str(project_root / "locales"), "locales"),
    (str(project_root / "logs"), "logs")
]

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[(str(unicodedata_binary), ".")],
    datas=datas,
    hiddenimports=[
        "customtkinter",
        *collect_submodules("customtkinter"),
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
    name="Project Aurora",
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
    name="Project Aurora"
)

from pathlib import Path
import os
import sys
import json
import hashlib
import unicodedata

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs, copy_metadata
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

# Core excludes Voice. Full uses a locked, hash-verified LGPL PyAV overlay;
# an unrestricted PyPI codec wheel must not leak into the distribution.
full_voice_build = os.environ.get("AURORA_FULL_VOICE_BUILD") == "1"
voice_binaries = []
voice_paths = []
voice_runtime_hooks = []
if full_voice_build:
    overlay = Path(os.environ.get("AURORA_VOICE_CODEC_OVERLAY", ""))
    integrity = json.loads((overlay / "overlay-integrity.json").read_text(encoding="utf-8"))
    actual_files = {
        path.relative_to(overlay).as_posix()
        for path in overlay.rglob("*")
        if path.is_file() and path != overlay / "overlay-integrity.json"
        and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    if not integrity.get("files") or set(integrity["files"]) != actual_files:
        raise RuntimeError("Codec overlay file inventory differs from its integrity manifest")
    for relative, expected in integrity["files"].items():
        path = (overlay / relative).resolve()
        if not path.is_relative_to(overlay.resolve()):
            raise RuntimeError("Invalid codec overlay path")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise RuntimeError(f"Codec overlay integrity mismatch: {relative}")
    expected_lock = json.loads((project_root / "config/voice_codec_lock.json").read_text(encoding="utf-8"))
    actual_lock = json.loads((overlay / "third_party/voice-codecs/codec-lock.json").read_text(encoding="utf-8"))
    if actual_lock != expected_lock:
        raise RuntimeError("Codec overlay is not the reviewed locked build")
    expected_dlls = {Path(name).name.casefold() for package in expected_lock["packages"] for name in package["files"]}
    actual_dlls = {path.name.casefold() for path in (overlay / "voice_codecs").iterdir() if path.is_file()}
    if not expected_dlls or actual_dlls != expected_dlls:
        raise RuntimeError("Codec overlay DLL inventory differs from the reviewed lock")
    if not (overlay / "third_party/playback/sources-lock.json").is_file():
        raise RuntimeError("Playback notices and corresponding source are required")
    if json.loads((overlay / "third_party/playback/sources-lock.json").read_text(encoding="utf-8")) != json.loads((project_root / "config/voice_playback_sources_lock.json").read_text(encoding="utf-8")):
        raise RuntimeError("Playback source lock mismatch")
    voice_paths = [str(overlay / "python")]
    sys.path.insert(0, voice_paths[0])
    codec_dll_handle = os.add_dll_directory(str(overlay / "voice_codecs"))
    voice_binaries = [(str(path), "voice_codecs") for path in (overlay / "voice_codecs").glob("*.dll")]
    datas.append((str(overlay / "third_party"), "third_party"))
    voice_runtime_hooks = [str(project_root / "scripts/pyi_voice_codecs.py")]
    # Cython imports do not appear in Python bytecode. Enumerate every PyAV
    # extension from the reviewed overlay (not from an installed PyPI wheel).
    for extension in (overlay / "python/av").rglob("*.pyd"):
        destination = extension.parent.relative_to(overlay / "python").as_posix()
        voice_binaries.append((str(extension), destination))

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
        voice_hiddenimports.extend(collect_submodules(package, filter=lambda name: ".tests" not in name and ".examples" not in name))
        datas.extend(collect_data_files(package, excludes=["tests/**", "examples/**"]))
        voice_binaries.extend(collect_dynamic_libs(package))
    for distribution in ("faster-whisper", "ctranslate2", "edge-tts", "pygame", "sounddevice", "av"):
        datas.extend(copy_metadata(distribution, recursive=True))

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
    pathex=[*voice_paths, str(project_root)],
    binaries=[(str(unicodedata_binary), "."), *voice_binaries],
    datas=datas,
    hiddenimports=[
        "customtkinter",
        *collect_submodules("customtkinter"),
        *voice_hiddenimports,
        "unicodedata",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=voice_runtime_hooks,
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
    name="Aurora-Full" if full_voice_build else "Aurora-Core"
)

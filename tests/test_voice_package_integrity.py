"""Release gates reject stale or incomplete inputs without running a build."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_script("validate_portable_package")
preparer = load_script("prepare_voice_codec_overlay")


def write(path, data=b"test"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_json(path, data):
    write(path, json.dumps(data).encode())


def codec_lock():
    return {"packages": [{"files": ["Library/bin/avcodec-63.dll"]}]}


def full_package(root):
    for name in ("Aurora.exe", "_internal/python312.dll", "_internal/faster_whisper/assets/silero_vad_v6.onnx", "_internal/voice_codecs/avcodec-63.dll"):
        write(root / name)
    write_json(root / "_internal/third_party/voice-codecs/codec-lock.json", codec_lock())
    entries = [
        {"path": p.relative_to(root).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest().upper(), "size": p.stat().st_size}
        for p in root.rglob("*") if p.is_file()
    ]
    write_json(root / "voice-runtime-integrity.json", {"files": entries})
    return entries


def test_full_package_requires_exact_manifest_inventory(tmp_path):
    full_package(tmp_path)
    assert validator.validate_package(tmp_path, full_voice=True) == []
    write(tmp_path / "_internal/unlisted.dll")
    assert any("inventory differs" in error for error in validator.validate_package(tmp_path, full_voice=True))


def test_full_package_rejects_missing_manifest_file(tmp_path):
    full_package(tmp_path)
    (tmp_path / "Aurora.exe").unlink()
    assert validator.validate_package(tmp_path, full_voice=True)


@pytest.mark.parametrize("mutation", ["empty", "duplicate", "duplicate_alias"])
def test_full_package_rejects_empty_or_duplicate_manifest(tmp_path, mutation):
    entries = full_package(tmp_path)
    if mutation == "empty":
        entries = []
    else:
        duplicate = dict(entries[0])
        if mutation == "duplicate_alias":
            duplicate["path"] = "./" + duplicate["path"]
        entries.append(duplicate)
    write_json(tmp_path / "voice-runtime-integrity.json", {"files": entries})
    errors = validator.validate_package(tmp_path, full_voice=True)
    assert any("Empty" in error or "Duplicate" in error for error in errors)


def test_full_package_rejects_extra_codec_even_when_manifest_lists_it(tmp_path):
    entries = full_package(tmp_path)
    path = tmp_path / "_internal/voice_codecs/stale.dll"
    write(path)
    entries.append({"path": path.relative_to(tmp_path).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(), "size": path.stat().st_size})
    write_json(tmp_path / "voice-runtime-integrity.json", {"files": entries})
    assert "Voice codec file inventory differs from its lock" in validator.validate_package(tmp_path, full_voice=True)


def test_prepare_rejects_stale_codec_without_deleting_it(tmp_path):
    write(tmp_path / "voice_codecs/avcodec-63.dll")
    preparer.reject_stale_codec_files(tmp_path, {"avcodec-63.dll"})
    write(tmp_path / "voice_codecs/stale.dll")
    with pytest.raises(RuntimeError, match="Unreviewed codec"):
        preparer.reject_stale_codec_files(tmp_path, {"avcodec-63.dll"})
    assert (tmp_path / "voice_codecs/stale.dll").is_file()


def test_prepare_rejects_stale_pyav_extension(tmp_path):
    source = tmp_path / "prefix/av"
    output = tmp_path / "overlay"
    write(source / "_core.pyd")
    write(output / "python/av/_core.pyd")
    preparer.reject_stale_codec_files(output, {"avcodec-63.dll"}, source)
    write(output / "python/av/stale.pyd")
    with pytest.raises(RuntimeError, match="stale.pyd"):
        preparer.reject_stale_codec_files(output, {"avcodec-63.dll"}, source)


def run_spec_integrity_gate(project, overlay):
    # Execute the actual spec's input gates only: no PyInstaller imports,
    # native loading, collection, or generated build output.
    tree = ast.parse((ROOT / "Project Aurora.spec").read_text(encoding="utf-8"))
    gate = next(node for node in tree.body if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "full_voice_build")
    statements = []
    for node in gate.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "voice_paths" for target in node.targets):
            break
        statements.append(node)
    code = compile(ast.Module(body=statements, type_ignores=[]), "Project Aurora.spec", "exec")
    exec(code, {"Path": Path, "json": json, "hashlib": hashlib, "project_root": project, "os": SimpleNamespace(environ={"AURORA_VOICE_CODEC_OVERLAY": str(overlay)})})


def overlay_input(tmp_path):
    overlay = tmp_path / "overlay"
    project = tmp_path / "project"
    write(overlay / "voice_codecs/avcodec-63.dll")
    write(overlay / "python/av/_core.pyd")
    write_json(project / "config/voice_codec_lock.json", codec_lock())
    write_json(overlay / "third_party/voice-codecs/codec-lock.json", codec_lock())
    write_json(project / "config/voice_playback_sources_lock.json", ["locked"])
    write_json(overlay / "third_party/playback/sources-lock.json", ["locked"])
    files = {p.relative_to(overlay).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in overlay.rglob("*") if p.is_file()}
    write_json(overlay / "overlay-integrity.json", {"files": files})
    return project, overlay, files


def test_spec_accepts_verified_overlay_and_ignores_import_cache(tmp_path):
    project, overlay, _files = overlay_input(tmp_path)
    write(overlay / "python/av/__pycache__/__init__.cpython-312.pyc")
    run_spec_integrity_gate(project, overlay)


@pytest.mark.parametrize("mutation", ["unlisted", "missing", "empty", "listed_extra_codec"])
def test_spec_rejects_incomplete_or_unreviewed_overlay(tmp_path, mutation):
    project, overlay, files = overlay_input(tmp_path)
    if mutation in {"unlisted", "listed_extra_codec"}:
        write(overlay / "voice_codecs/stale.dll")
        if mutation == "listed_extra_codec":
            files["voice_codecs/stale.dll"] = hashlib.sha256(b"test").hexdigest()
    elif mutation == "missing":
        (overlay / "voice_codecs/avcodec-63.dll").unlink()
    else:
        files = {}
    write_json(overlay / "overlay-integrity.json", {"files": files})
    with pytest.raises(RuntimeError, match="inventory"):
        run_spec_integrity_gate(project, overlay)

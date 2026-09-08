"""Reject private, developer-specific, or optional binary data in a portable build."""

from __future__ import annotations

import argparse
import os
import json
import hashlib
from pathlib import Path
from typing import Iterable


FORBIDDEN_DIRECTORY_NAMES = {
    ".codex",
    ".git",
    ".ollama",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "caches",
    "tests",
    "venv",
}
FORBIDDEN_OPTIONAL_RUNTIME_DIRECTORY_PREFIXES = (
    "_sounddevice",
    "av-",
    "av.",
    "ctranslate2",
    "edge_tts",
    "faster_whisper",
    "pygame",
    "sounddevice",
)
FORBIDDEN_OPTIONAL_RUNTIME_DIRECTORY_NAMES = {"av"}
FORBIDDEN_ROOT_DIRECTORY_NAMES = {
    "conversations",
    "data",
    "knowledge",
    "logs",
    "memory",
    "persona",
}
FORBIDDEN_FILE_NAMES = {
    ".env",
    "ffmpeg.exe",
    "settings.json",
}
FORBIDDEN_FILE_SUFFIXES = {
    ".bak",
    ".backup",
    ".log",
}
FORBIDDEN_FFMPEG_LIBRARY_PREFIXES = (
    "avcodec",
    "avdevice",
    "avfilter",
    "avformat",
    "avutil",
    "libx264",
    "libx265",
    "postproc",
    "swresample",
    "swscale",
)
READ_CHUNK_SIZE = 1024 * 1024


def validate_package(root: Path, forbidden_text: Iterable[str] = (), *, full_voice: bool = False) -> list[str]:
    """Return human-readable violations found below an extracted package root."""

    root = Path(root).resolve()
    if not root.is_dir():
        return [f"package root is missing or not a directory: {root}"]

    text_values = _normalized_forbidden_text(forbidden_text)
    violations: list[str] = []
    allowed_codecs = set()
    if full_voice:
        try:
            lock = json.loads((root / "_internal/third_party/voice-codecs/codec-lock.json").read_text(encoding="utf-8"))
            allowed_codecs = {Path(name).name.casefold() for package in lock["packages"] for name in package["files"]}
            if not allowed_codecs:
                raise ValueError("Empty codec file lock")
            codec_root = root / "_internal/voice_codecs"
            actual_codecs = {path.name.casefold() for path in codec_root.iterdir() if path.is_file()}
            if actual_codecs != allowed_codecs:
                violations.append("Voice codec file inventory differs from its lock")
            manifest = json.loads((root / "voice-runtime-integrity.json").read_text(encoding="utf-8"))
            if not isinstance(manifest.get("files"), list) or not manifest["files"]:
                raise ValueError("Empty or invalid Voice integrity manifest")
            manifest_paths = set()
            for entry in manifest["files"]:
                path = (root / entry["path"]).resolve()
                if not path.is_relative_to(root) or path == root / "voice-runtime-integrity.json":
                    raise ValueError("Invalid integrity path")
                relative = path.relative_to(root).as_posix().casefold()
                if relative in manifest_paths:
                    raise ValueError(f"Duplicate integrity path: {entry['path']}")
                manifest_paths.add(relative)
                with path.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest().upper() != entry["sha256"]:
                        violations.append(f"Voice integrity mismatch: {entry['path']}")
            actual_paths = {
                path.relative_to(root).as_posix().casefold()
                for path in root.rglob("*")
                if path.is_file() and path != root / "voice-runtime-integrity.json"
            }
            if actual_paths != manifest_paths:
                violations.append("Voice file inventory differs from its integrity manifest")
            for required in ("python312.dll", "faster_whisper/assets/silero_vad_v6.onnx", "voice_codecs/avcodec-63.dll"):
                if not (root / "_internal" / required).is_file():
                    violations.append(f"Full Voice runtime file missing: {required}")
        except (OSError, ValueError, KeyError, TypeError) as error:
            violations.append(f"Full Voice distribution metadata invalid: {error}")
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        parts = tuple(part.casefold() for part in relative.parts)
        if path.is_symlink():
            violations.append(f"symbolic link is not allowed: {relative}")
            continue
        if path.is_dir():
            if any(part in FORBIDDEN_DIRECTORY_NAMES for part in parts):
                violations.append(f"forbidden directory: {relative}")
            elif not full_voice and (any(part in FORBIDDEN_OPTIONAL_RUNTIME_DIRECTORY_NAMES for part in parts) or any(
                part.startswith(prefix)
                for part in parts
                for prefix in FORBIDDEN_OPTIONAL_RUNTIME_DIRECTORY_PREFIXES
            )):
                violations.append(f"forbidden optional runtime directory: {relative}")
            elif len(parts) == 1 and parts[0] in FORBIDDEN_ROOT_DIRECTORY_NAMES:
                violations.append(f"forbidden user-data directory: {relative}")
            continue
        if not path.is_file():
            continue

        name = path.name.casefold()
        if name in FORBIDDEN_FILE_NAMES:
            violations.append(f"forbidden file: {relative}")
        elif name.endswith(".dll") and name.startswith(FORBIDDEN_FFMPEG_LIBRARY_PREFIXES) and (
            not full_voice or name not in allowed_codecs or name.startswith(("libx264", "libx265"))
        ):
            violations.append(f"forbidden FFmpeg codec library: {relative}")
        elif path.suffix.casefold() in FORBIDDEN_FILE_SUFFIXES:
            violations.append(f"forbidden file type: {relative}")

        matched = _find_forbidden_bytes(path, text_values)
        for value in matched:
            violations.append(f"developer-specific text {value!r}: {relative}")
    return sorted(set(violations))


def _normalized_forbidden_text(values: Iterable[str]) -> tuple[str, ...]:
    normalized = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return tuple(normalized)


def _find_forbidden_bytes(path: Path, values: Iterable[str]) -> list[str]:
    needles: list[tuple[str, bytes]] = []
    for value in values:
        variants = {
            value.encode("utf-8", errors="ignore"),
            value.encode("utf-16-le", errors="ignore"),
        }
        for variant in variants:
            if variant:
                needles.append((value, variant))
    if not needles:
        return []

    max_needle = max(len(needle) for _value, needle in needles)
    overlap = b""
    found: set[str] = set()
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(READ_CHUNK_SIZE)
                if not chunk:
                    break
                data = overlap + chunk
                for value, needle in needles:
                    if value not in found and needle in data:
                        found.add(value)
                if len(found) == len({value for value, _needle in needles}):
                    break
                overlap = data[-(max_needle - 1) :] if max_needle > 1 else b""
    except OSError as error:
        return [f"<unreadable: {error}>"]
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_root", type=Path)
    parser.add_argument("--full-voice", action="store_true")
    parser.add_argument(
        "--forbidden-text",
        action="append",
        default=[],
        help="Text that must not appear in any packaged file (repeatable).",
    )
    args = parser.parse_args(argv)
    violations = validate_package(args.package_root, args.forbidden_text, full_voice=args.full_voice)
    if violations:
        print("Portable package validation failed:")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print(f"Portable package validation passed: {args.package_root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

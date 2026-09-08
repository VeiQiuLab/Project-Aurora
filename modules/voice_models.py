"""Shared local Whisper model locations for setup, diagnostics and inference."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from functools import lru_cache
from threading import RLock
from uuid import uuid4

from modules.app_paths import USER_DATA_DIR


_INTEGRITY_FILE = "aurora-model-integrity.json"
_MODEL_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt", "vocabulary.json", "preprocessor_config.json")
_VALIDATION_LOCK = RLock()


def managed_model_path(model: str) -> Path:
    if model not in {"tiny", "small", "medium"}:
        raise ValueError("Unsupported managed Whisper model")
    return USER_DATA_DIR / "models" / "whisper" / model


def model_download_directory(path: Path) -> str:
    """Keep Hub's long temporary filenames usable on Windows without a
    machine-wide long-path policy change. This prefix is not persisted in UI.
    """
    value = str(path.resolve())
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def valid_model_directory(path: Path) -> bool:
    """Validate content, caching by file identity rather than directory existence.

    Hub metadata gives an expected content hash. Older local models without it
    must load successfully once on CPU. Checks do not write into legacy caches.
    """

    try:
        path = Path(path).resolve()
        with _VALIDATION_LOCK:
            return _validated_hashes(str(path), _fingerprint(path)) is not None
    except (OSError, ValueError, TypeError):
        return False


def _fingerprint(path):
    names = (*_MODEL_FILES, _INTEGRITY_FILE, *(f".cache/huggingface/download/{name}.metadata" for name in _MODEL_FILES))
    result = []
    for name in names:
        try:
            stat = (path / name).stat()
            result.append((name, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        except FileNotFoundError:
            result.append((name, None))
    return tuple(result)


def _digest_file(path, *, git_blob=False):
    digest = hashlib.sha1() if git_blob else hashlib.sha256()
    if git_blob:
        digest.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hub_etag(path, name):
    metadata = path / ".cache/huggingface/download" / (name + ".metadata")
    try:
        etag = metadata.read_text(encoding="utf-8").splitlines()[1].strip()
    except (OSError, IndexError):
        # Older Hub snapshots may link directly to content-addressed blobs.
        etag = (path / name).resolve().name
    if len(etag) in {40, 64} and all(c in "0123456789abcdef" for c in etag):
        return etag
    return None


def _load_legacy_model(path):
    from faster_whisper import WhisperModel

    # Required local tokenizer/model files are checked before this call, so
    # the upstream tokenizer fallback cannot silently fetch missing assets.
    model = WhisperModel(str(path), device="cpu", compute_type="int8", local_files_only=True)
    del model


@lru_cache(maxsize=32)
def _validated_hashes(path_string, fingerprint):
    path = Path(path_string)
    try:
        if (path / "model.bin").stat().st_size < 1024:
            return None
        for name in ("config.json", "tokenizer.json"):
            if not isinstance(json.loads((path / name).read_text(encoding="utf-8")), dict):
                return None
        if not any((path / name).is_file() for name in ("vocabulary.txt", "vocabulary.json")):
            return None
        files = [name for name in _MODEL_FILES if (path / name).is_file()]
        hashes = {name: _digest_file(path / name) for name in files}
        marker = path / _INTEGRITY_FILE
        if marker.exists():
            expected = json.loads(marker.read_text(encoding="utf-8"))
            if expected.get("schema_version") != 1 or expected.get("files") != hashes:
                return None
        else:
            all_hub_verified = True
            for name in files:
                etag = _hub_etag(path, name)
                if etag is None:
                    all_hub_verified = False
                elif (hashes[name] if len(etag) == 64 else _digest_file(path / name, git_blob=True)) != etag:
                    return None
            if not all_hub_verified:
                _load_legacy_model(path)
        # Do not cache a successful validation if a writer changed any input
        # while hashing/loading it.
        return hashes if _fingerprint(path) == fingerprint else None
    except Exception:
        return None


def publish_model_integrity(path: Path) -> None:
    """Seal a verified download before its directory is made active."""
    path = Path(path).resolve()
    with _VALIDATION_LOCK:
        hashes = _validated_hashes(str(path), _fingerprint(path))
        if hashes is None:
            raise ValueError("Downloaded Whisper model failed integrity validation")
        temporary = path / (".aurora-model-integrity-" + uuid4().hex + ".tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump({"schema_version": 1, "files": hashes}, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path / _INTEGRITY_FILE)
        finally:
            temporary.unlink(missing_ok=True)


def local_model_path(model: str) -> Path | None:
    configured = Path(model).expanduser()
    if configured.is_dir():
        return configured if valid_model_directory(configured) else None
    if model in {"tiny", "small", "medium"}:
        managed = managed_model_path(model)
        if valid_model_directory(managed):
            return managed
    cache = os.environ.get("HF_HUB_CACHE")
    if cache:
        hub = Path(cache)
    else:
        hf_home = os.environ.get("HF_HOME")
        hub = Path(hf_home) / "hub" if hf_home else Path.home() / ".cache" / "huggingface" / "hub"
    snapshots = hub / f"models--Systran--faster-whisper-{model}" / "snapshots"
    try:
        return next((path for path in sorted(snapshots.iterdir()) if valid_model_directory(path)), None)
    except OSError:
        return None

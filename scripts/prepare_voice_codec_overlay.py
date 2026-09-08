"""Build-only PyAV overlay from pinned conda-forge LGPL binaries.

Never called by Aurora. Copies only the PE dependency closure, licenses,
build recipes and hash-verified corresponding sources, not a conda environment.
The generated lock is an input to later builds, not a license-approval switch.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reject_stale_codec_files(output, expected_names, av_source=None):
    """Do not bless old or extra native inputs with a newly generated manifest."""
    codec_root = output / "voice_codecs"
    expected_names = {name.casefold() for name in expected_names}
    unexpected = [
        path.relative_to(codec_root).as_posix()
        for path in codec_root.rglob("*")
        if path.is_file() and (path.parent != codec_root or path.name.casefold() not in expected_names)
    ]
    if av_source is not None:
        for path in (output / "python/av").rglob("*.pyd"):
            relative = path.relative_to(output / "python/av")
            if not (av_source / relative).is_file():
                unexpected.append("python/av/" + relative.as_posix())
    if unexpected:
        raise RuntimeError(f"Unreviewed codec files remain in the overlay: {', '.join(sorted(unexpected))}")


def closure(prefix):
    import pefile

    libraries = {p.name.lower(): p for p in (prefix / "Library/bin").glob("*.dll")}
    queue = list((prefix / "Lib/site-packages/av").rglob("*.pyd"))
    found = {}
    while queue:
        path = queue.pop()
        with pefile.PE(str(path), fast_load=True) as pe:
            pe.parse_data_directories(directories=[1, 13])
            for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) + getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []):
                name = entry.dll.decode().lower()
                # Windows 10 supplies API sets; do not redistribute SDK stubs.
                if name.startswith(("api-ms-", "ext-ms-")):
                    continue
                if name in libraries and name not in found:
                    found[name] = libraries[name]
                    queue.append(libraries[name])
                elif name not in libraries and not (Path(os.environ["SystemRoot"]) / "System32" / name).exists() and name != "python312.dll":
                    raise RuntimeError(f"Unresolved native dependency: {path.name}: {name}")
    return found


def prepare(prefix, output, lock_path, *, create_lock=False):
    import yaml

    found = closure(prefix)
    if any("x264" in n or "x265" in n for n in found):
        raise RuntimeError("GPL codec dependency is forbidden")
    with os.add_dll_directory(str(prefix / "Library/bin")):
        codec = ctypes.CDLL(str(prefix / "Library/bin/avcodec-63.dll"))
        codec.avcodec_configuration.restype = ctypes.c_char_p
        configuration = codec.avcodec_configuration().decode()
        codec.avcodec_license.restype = ctypes.c_char_p
        license_text = codec.avcodec_license().decode()
    if "LGPL" not in license_text or "--enable-gpl" in configuration or "--enable-nonfree" in configuration:
        raise RuntimeError("Non-LGPL FFmpeg configuration refused")

    packages = []
    metadata = []
    for path in sorted((prefix / "conda-meta").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        selected = [p.relative_to(prefix).as_posix() for p in found.values() if p.relative_to(prefix).as_posix() in record["files"]]
        if not selected and record["name"] not in {"av", "freetype"}:
            continue
        if record["name"] == "ffmpeg" and (record["version"], record["build"]) != ("9.0.1", "lgpl_h098eaf0_0"):
            raise RuntimeError("Unreviewed FFmpeg build")
        if record["name"] == "av" and (record["version"], record["build"]) != ("18.1.0", "py312hb2f1342_0"):
            raise RuntimeError("Unreviewed PyAV build")
        archive = Path(record["extracted_package_dir"]).parent / record["url"].rsplit("/", 1)[-1]
        if digest(archive) != record["sha256"]:
            raise RuntimeError(f"Package integrity mismatch: {record['name']}")
        info = Path(record["extracted_package_dir"]) / "info"
        recipe_path = info / "recipe/meta.yaml"
        if recipe_path.exists():
            recipe = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
        else:
            recipe = yaml.safe_load((info / "recipe/rendered_recipe.yaml").read_text(encoding="utf-8"))["recipe"]
        sources = recipe.get("source", [])
        sources = sources if isinstance(sources, list) else [sources]
        for cache in recipe.get("staging_caches", []):
            inherited = cache.get("source", [])
            sources.extend(inherited if isinstance(inherited, list) else [inherited])
        packages.append({key: record[key] for key in ("name", "version", "build", "url", "sha256", "license")})
        packages[-1]["files"] = sorted(selected)
        metadata.append((record, info, sources))
    lock = {"schema_version": 1, "ffmpeg_license": license_text, "ffmpeg_configuration": configuration, "packages": packages}
    if create_lock:
        lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    elif json.loads(lock_path.read_text(encoding="utf-8")) != lock:
        raise RuntimeError("Codec input differs from the checked-in lock")

    reject_stale_codec_files(output, found, prefix / "Lib/site-packages/av")
    output.mkdir(parents=True, exist_ok=True)
    python_root = output / "python"
    python_root.mkdir(exist_ok=True)
    for name in ("av", "av-18.1.0.dist-info"):
        shutil.copytree(prefix / "Lib/site-packages" / name, python_root / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"))
    codec_root = output / "voice_codecs"
    codec_root.mkdir(exist_ok=True)
    for path in found.values():
        shutil.copy2(path, codec_root / path.name)

    notices = output / "third_party/voice-codecs"
    for record, info, sources in metadata:
        dest = notices / record["name"]
        dest.mkdir(parents=True, exist_ok=True)
        for folder in ("licenses", "recipe"):
            if (info / folder).is_dir():
                shutil.copytree(info / folder, dest / folder, dirs_exist_ok=True)
        if record["name"] == "libfreetype6" and not (dest / "licenses").is_dir():
            donor = next(info for package, info, _sources in metadata if package["name"] == "freetype" and package["version"] == record["version"])
            shutil.copytree(donor / "licenses", dest / "licenses", dirs_exist_ok=True)
        if not (dest / "licenses").is_dir():
            raise RuntimeError(f"Missing license files: {record['name']}")
        # Provide corresponding source + the exact packaging patches for all
        # LGPL libraries. The other permissive components retain full notices.
        if "LGPL" in record["license"]:
            if not sources:
                raise RuntimeError(f"Missing corresponding source: {record['name']}")
            for number, source in enumerate(sources):
                urls = source.get("url", [])
                urls = urls if isinstance(urls, list) else [urls]
                sha = source.get("sha256")
                if not urls or not sha:
                    raise RuntimeError(f"Unpinned corresponding source: {record['name']}")
                url = urls[0]
                if url.startswith("http://"):
                    url = "https://" + url[len("http://"):]
                target = dest / (f"source-{number}-" + url.rsplit("/", 1)[-1])
                if not target.exists() or digest(target) != sha:
                    if not url.startswith("https://"):
                        raise RuntimeError("Source downloads require HTTPS")
                    print(f"Source: {record['name']}: {url}", flush=True)
                    with urllib.request.urlopen(url, timeout=60) as response, target.with_suffix(target.suffix + ".part").open("wb") as stream:
                        shutil.copyfileobj(response, stream)
                    temporary = target.with_suffix(target.suffix + ".part")
                    if digest(temporary) != sha:
                        raise RuntimeError(f"Source hash mismatch: {record['name']}")
                    os.replace(temporary, target)
    shutil.copy2(lock_path, notices / "codec-lock.json")
    (notices / "NOTICE.txt").write_text(
        "Aurora Voice Runtime uses unmodified conda-forge PyAV and dynamically linked LGPL FFmpeg libraries.\n"
        "No FFmpeg executable, x264, x265, GPL-enabled or nonfree-enabled FFmpeg is included.\n"
        "Corresponding LGPL sources, conda-forge build recipes and patches accompany this directory.\n"
        "Libraries in _internal/voice_codecs may be replaced by ABI-compatible modified versions.\n"
        "Aurora imposes no restriction on reverse engineering for debugging modifications to these libraries.\n"
        "FreeType is redistributed under the FTL alternative. See each component's license and copyright notices.\n"
        "Upstream: https://ffmpeg.org/ ; https://pyav.org/ ; https://conda-forge.org/\n",
        encoding="utf-8",
    )
    files = {
        p.relative_to(output).as_posix(): digest(p)
        for p in sorted(output.rglob("*"))
        if p.is_file() and p != output / "overlay-integrity.json"
        and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    (output / "overlay-integrity.json").write_text(json.dumps({"files": files}, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(found)} native libraries and {len(packages)} component notices")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--create-lock", action="store_true")
    args = parser.parse_args()
    prepare(args.prefix.resolve(), args.output.resolve(), args.lock.resolve(), create_lock=args.create_lock)

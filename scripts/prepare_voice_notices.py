"""Build-time notices and corresponding pygame source; never used at runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request
import zipfile


# URLs and original SHA-1 values are from pygame 2.6.1's versioned sdist
# buildconfig/download_win_prebuilt.py. The checked-in lock also fixes SHA-256.
INPUTS = [
    ("https://files.pythonhosted.org/packages/49/cc/08bba60f00541f62aaa252ce0cfbd60aebd04616c0b9574f755b583e45ae/pygame-2.6.1.tar.gz", "sha256", "56fb02ead529cee00d415c3e007f75e0780c655909aaa8e8bf616ee09c9feb1f"),
    ("https://www.libsdl.org/release/SDL2-devel-2.28.4-VC.zip", "sha1", "25ef9d201ce3fd5f976c37dddedac36bd173975c"),
    ("https://www.libsdl.org/projects/SDL_image/release/SDL2_image-devel-2.0.5-VC.zip", "sha1", "137f86474691f4e12e76e07d58d5920c8d844d5b"),
    ("https://github.com/libsdl-org/SDL_ttf/releases/download/release-2.20.1/SDL2_ttf-devel-2.20.1-VC.zip", "sha1", "371606aceba450384428fd2852f73d2f6290b136"),
    ("https://github.com/libsdl-org/SDL_mixer/releases/download/release-2.6.2/SDL2_mixer-devel-2.6.2-VC.zip", "sha1", "000e3ea8a50261d46dbd200fb450b93c59ed4482"),
    ("https://github.com/pygame/pygame/releases/download/2.1.3.dev4/prebuilt-x64-pygame-2.1.4-20220319.zip", "sha1", "16b46596744ce9ef80e7e40fa72ddbafef1cf586"),
]


def prepare(cache, output, lock_path, create_lock):
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for url, algorithm, expected in INPUTS:
        path = cache / url.rsplit("/", 1)[-1]
        if not path.exists():
            print(f"Notices source: {path.name}", flush=True)
            with urllib.request.urlopen(url, timeout=60) as response, path.open("wb") as stream:
                shutil.copyfileobj(response, stream)
        data = path.read_bytes()
        if hashlib.new(algorithm, data).hexdigest() != expected:
            raise RuntimeError(f"Upstream integrity mismatch: {path.name}")
        records.append({"url": url, "sha256": hashlib.sha256(data).hexdigest()})
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                members = [(i.filename, lambda i=i: archive.read(i)) for i in archive.infolist() if not i.is_dir()]
                for name, read in members:
                    # Only human-readable notices; no unreviewed binaries from
                    # upstream SDK/prebuilt archives are redistributed here.
                    if any(word in Path(name).name.lower() for word in ("license", "copying", "copyright", "readme")) and Path(name).suffix.lower() not in {".dll", ".exe", ".lib"}:
                        target = (output / path.stem / name).resolve()
                        if not target.is_relative_to(output.resolve()):
                            raise ValueError("Invalid archive path")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(read())
        else:
            shutil.copy2(path, output / path.name)
            with tarfile.open(path) as archive:
                for name in ("pygame-2.6.1/docs/LGPL.txt", "pygame-2.6.1/README.rst"):
                    (output / Path(name).name).write_bytes(archive.extractfile(name).read())
    if create_lock:
        lock_path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    elif json.loads(lock_path.read_text(encoding="utf-8")) != records:
        raise RuntimeError("Notices inputs do not match SHA-256 lock")
    shutil.copy2(lock_path, output / "sources-lock.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--create-lock", action="store_true")
    args = parser.parse_args()
    prepare(args.cache, args.output, args.lock, args.create_lock)

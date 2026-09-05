"""Validate pinned Full Build inputs and write a SHA-256 release manifest."""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path


def load_policy(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_environment(policy: dict) -> list[str]:
    errors = []
    for distribution, expected in policy.get("components", {}).items():
        try:
            actual = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            errors.append(f"{distribution} is not installed (expected {expected})")
            continue
        if actual != expected:
            errors.append(f"{distribution} is {actual} (expected {expected})")
    return errors


def write_integrity_manifest(root: Path, output: Path, policy: dict) -> None:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item != output):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": digest.hexdigest().upper(),
                "size": path.stat().st_size,
            }
        )
    payload = {
        "schema_version": 1,
        "distribution": policy.get("distribution"),
        "components": policy.get("components", {}),
        "files": files,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--validate-environment", action="store_true")
    parser.add_argument("--build-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    policy = load_policy(args.policy)
    if args.validate_environment:
        errors = validate_environment(policy)
        if errors:
            print("\n".join(errors))
            return 1
    if args.build_root or args.output:
        if not args.build_root or not args.output:
            parser.error("--build-root and --output must be used together")
        write_integrity_manifest(args.build_root.resolve(), args.output.resolve(), policy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Check Aurora locale coverage.

This script is read-only. It scans source files for translation key usage and
reports missing and unused keys across zh_CN and en_US locale files.
"""

import argparse
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCALE_FILES = {
    "zh_CN": PROJECT_ROOT / "locales" / "zh_CN.json",
    "en_US": PROJECT_ROOT / "locales" / "en_US.json",
}
SCAN_DIRS = [
    PROJECT_ROOT / "main.py",
    PROJECT_ROOT / "modules",
    PROJECT_ROOT / "widgets",
]
PATTERNS = [
    re.compile(r'\bt\(\s*["\']([A-Za-z0-9_.-]+)["\']'),
    re.compile(r'\bi18n\.get\(\s*["\']([A-Za-z0-9_.-]+)["\']'),
    re.compile(r'\bTEXT\.get\(\s*["\']([A-Za-z0-9_.-]+)["\']'),
]


def iter_python_files(paths):
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            yield path
        elif path.is_dir():
            yield from sorted(path.rglob("*.py"))


def load_locale(path):
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Locale parse failed: {path} ({error})")
    if not isinstance(data, dict):
        raise SystemExit(f"Locale root must be an object: {path}")
    return data


def scan_used_keys():
    used = set()
    locations = {}
    for path in iter_python_files(SCAN_DIRS):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern in PATTERNS:
                for match in pattern.finditer(line):
                    key = match.group(1)
                    used.add(key)
                    locations.setdefault(key, []).append(f"{path.relative_to(PROJECT_ROOT)}:{line_number}")
    return used, locations


def print_list(title, values):
    print(f"{title}:")
    if not values:
        print("- none")
        return
    for value in sorted(values):
        print(f"- {value}")


def main():
    parser = argparse.ArgumentParser(description="Check Project Aurora i18n locale coverage.")
    parser.add_argument("--fail-on-unused", action="store_true", help="Return non-zero when unused keys exist.")
    args = parser.parse_args()

    locales = {name: load_locale(path) for name, path in LOCALE_FILES.items()}
    used_keys, _locations = scan_used_keys()
    all_locale_keys = set().union(*(set(data.keys()) for data in locales.values()))

    missing_by_locale = {
        name: used_keys - set(data.keys())
        for name, data in locales.items()
    }
    unused_keys = all_locale_keys - used_keys

    print("Project Aurora i18n Check")
    print(f"Used Keys: {len(used_keys)}")
    for name, data in locales.items():
        print(f"{name} Keys: {len(data)}")
    print("")

    has_missing = False
    for name in sorted(missing_by_locale):
        missing = missing_by_locale[name]
        has_missing = has_missing or bool(missing)
        print_list(f"Missing Keys ({name})", missing)
        print("")

    print_list("Unused Keys", unused_keys)

    if has_missing or (args.fail_on_unused and unused_keys):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

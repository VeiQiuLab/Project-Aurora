"""Read-only PE/source inventory for the V4-7B.3A experiment."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def inspect_pe(path, dumpbin):
    records = {}
    for mode in ("imports", "exports", "dependents"):
        run = subprocess.run([str(dumpbin), "/" + mode, str(path)], capture_output=True,
                             encoding="utf-8", errors="replace", check=True)
        records[mode] = run.stdout
    content = path.read_bytes()
    strings = [x.decode("ascii") for x in re.findall(rb"[\x20-\x7e]{4,}", content)]
    strings += [x.decode("utf-16-le") for x in re.findall(rb"(?:[\x20-\x7e]\x00){4,}", content)]
    records.update(file=str(path), bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                   dependencies=re.findall(r"^\s+([\w.-]+\.dll)\s*$", records["dependents"], re.M | re.I),
                   suspicious_strings=[x for x in strings if re.search(r"espeak|piper|phonemize|\bGPL\b", x, re.I)])
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("build", "reference", "repo", "dumpbin", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False)
    clean_dir = args.build / "clean-bin" / "Release"
    # Recurse through non-system runtime dependencies. Windows OS/VC CRT/API
    # sets are explicit leaf dependencies, not silently counted as bundled DLLs.
    remaining = list(clean_dir.glob("*.dll")) + list(clean_dir.glob("*.exe"))
    visited, clean = set(), []
    while remaining:
        path = remaining.pop()
        if path.name.lower() in visited:
            continue
        visited.add(path.name.lower())
        row = inspect_pe(path, args.dumpbin)
        for dep in row["dependencies"]:
            local = clean_dir / dep
            if local.exists():
                remaining.append(local)
        clean.append(row)
    reference = [inspect_pe(path, args.dumpbin) for path in (args.reference / "lib").glob("*.dll")]
    files = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=args.repo,
                                   encoding="utf-8").splitlines()
    inventory = [dict(path=name, sha256=hashlib.sha256((args.repo / name).read_bytes()).hexdigest(),
                      bytes=(args.repo / name).stat().st_size) for name in files]
    source_projects = {}
    for project in args.build.glob("*.vcxproj"):
        text = project.read_text(encoding="utf-8-sig")
        sources = re.findall(r'<ClCompile Include="([^"]+)"', text)
        if project.stem in ("clean_melo", "normalizer", "fst", "benchmark_sherpa_melo"):
            assert not any(re.search(r"espeak|piper|asr|vad|diarization", x, re.I) for x in sources)
            source_projects[project.name] = sources
    for project in args.build.rglob("fst.vcxproj"):
        source_projects[project.name] = re.findall(r'<ClCompile Include="([^"]+)"', project.read_text(encoding="utf-8-sig"))
    report = dict(clean=clean, reference=reference, untracked_inventory=inventory,
                  compiled_sources=source_projects, system_dependencies=sorted({dep for row in clean for dep in row["dependencies"] if not (clean_dir / dep).exists()}))
    for row in clean:
        assert not re.search(r"espeak_|espeak_ng_|phonemize_eSpeak", row["exports"] + row["imports"], re.I)
        assert not any(re.search(r"espeak|piper", d, re.I) for d in row["dependencies"])
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(clean_binaries=len(clean), untracked=len(inventory), suspicious={Path(x["file"]).name:x["suspicious_strings"] for x in clean}), ensure_ascii=False))


if __name__ == "__main__":
    main()

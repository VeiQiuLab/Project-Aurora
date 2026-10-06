"""Read-only recursive PE audit of the production native voice directory."""
import argparse
import importlib.util
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--dumpbin", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("pe_audit", Path(__file__).with_name("audit_clean_melo.py"))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    pending = [args.runtime / "aurora-local-voice-host.exe"]
    visited, records = set(), []
    forbidden = re.compile(r"espeak|piper[-_]phonemize|phonemize_eSpeak|\bGPL\b", re.I)
    while pending:
        path = pending.pop()
        if path.name.lower() in visited: continue
        visited.add(path.name.lower())
        record = module.inspect_pe(path, args.dumpbin)
        assert not forbidden.search(record["imports"] + record["exports"])
        assert not any(forbidden.search(value) for value in record["suspicious_strings"])
        for dependency in record["dependencies"]:
            assert not forbidden.search(dependency)
            candidate = args.runtime / dependency
            if candidate.is_file(): pending.append(candidate)
        records.append(record)
    # providers_shared is shipped alongside ORT; scan even without a static import.
    shared = args.runtime / "onnxruntime_providers_shared.dll"
    if shared.name.lower() not in visited:
        record = module.inspect_pe(shared, args.dumpbin)
        assert not forbidden.search(record["imports"] + record["exports"])
        assert not any(forbidden.search(value) for value in record["suspicious_strings"])
        records.append(record)
    assert len(records) == 4, "Unexpected native runtime dependency set"
    leaves = sorted({dependency for record in records for dependency in record["dependencies"]
                     if not (args.runtime / dependency).is_file()})
    windows_leaf = re.compile(r"^(api-ms-win-.*|kernel32|advapi32|msvcp140(?:_1)?|vcruntime140(?:_1)?|dbghelp|setupapi|dxgi)\.dll$", re.I)
    assert all(windows_leaf.fullmatch(name) for name in leaves), leaves
    report = dict(status="passed", records=records, system_dependencies=leaves,
                  excluded_runtime_symbols=0, legal_review="LEGAL REVIEW RECOMMENDED",
                  ort_mpl="Retain exact-version notices and covered-source availability in future distribution")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": "passed", "binaries": len(records), "excluded_runtime_symbols": 0}))


if __name__ == "__main__": main()

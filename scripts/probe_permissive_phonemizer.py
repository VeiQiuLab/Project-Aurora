"""Evaluate an external pypinyin wheel without installing it into Aurora."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True, help="External unpacked wheel directory")
    parser.add_argument("--tokens", type=Path, required=True)
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    sys.path.insert(0, str(args.package.resolve(strict=True)))
    from pypinyin import Style, lazy_pinyin, __version__
    symbols = {line.rsplit(" ", 1)[0] for line in args.tokens.read_text(encoding="utf-8").splitlines()}
    old = json.loads(args.golden.read_text(encoding="utf-8"))["captures"]["reference"]["rows"]
    rows = []
    for row in old:
        pinyin = lazy_pinyin(row["text"], style=Style.TONE3, neutral_tone_with_five=True)
        oov = [part for part in pinyin if part not in symbols]
        rows.append(dict(text=row["text"], pinyin=pinyin, model_symbol_oov=oov,
            direct_token_contract="INVALID" if oov else "NOT PROVEN",
            reason="Pinyin syllables are not Melo phoneme IDs; no aligned tones/blank or English G2P"))
    report = dict(candidate="pypinyin", version=__version__, license="MIT", wheel_sha256=hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
        selected=False, installed_into_project=False, rows=rows,
        conclusion="Chinese pinyin component only; needs exporter-compatible map + full English lexicon/G2P. Not a drop-in phonemizer or direct-token API.")
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(version=__version__, cases=len(rows), direct_token_invalid=sum(x["direct_token_contract"] == "INVALID" for x in rows))))


if __name__ == "__main__":
    main()

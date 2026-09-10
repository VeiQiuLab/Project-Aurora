"""Read-only health plus one blocking WAV smoke request for a configured Voice Node."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise argparse.ArgumentTypeError("URL must be an HTTP(S) base URL")
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test an Aurora Voice Node")
    parser.add_argument("--url", type=base_url, required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with urlopen(args.url + "/health", timeout=min(args.timeout, 10.0)) as response:
        health = json.loads(response.read().decode("utf-8"))
    if health.get("runtime", {}).get("available") is not True:
        raise SystemExit(f"Voice Node runtime is unavailable: {health}")

    request = Request(
        args.url + "/tts",
        data=json.dumps({"text": args.text, "speed": args.speed}, ensure_ascii=False).encode("utf-8"),
        headers={"Accept": "audio/wav", "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(request, timeout=args.timeout) as response:
        audio = response.read()
    if audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise SystemExit("Voice Node returned an invalid WAV response")
    if args.output:
        args.output.write_bytes(audio)
    print(f"Voice Node ready; received {len(audio)} WAV bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

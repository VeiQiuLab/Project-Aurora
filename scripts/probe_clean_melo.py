"""V4-7B.3A isolated oracle/token/audio comparison, never production."""
from __future__ import annotations
from array import array
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import wave

CORPUS = ["你好，今天过得怎么样？", "他说：你好！可以吗？当然可以；我们继续，保持安静。",
          "一共123个人，温度是25.5度。", "现在是2026年10月6日。",
          "Aurora 今天运行正常。", "请打开 Project Aurora。", "hello world",
          "你好，hello world，这是一个test。", "价格是￥25，折扣50%，请联系A+B。"]


def compare_inputs(reference, clean):
    if reference == clean and reference:
        return "IDENTICAL"
    return "INVALID"  # Do not infer phonetic equivalence from WAV existence.


def pcm_stats(path):
    data = path.read_bytes()
    with wave.open(str(path), "rb") as audio:
        assert audio.getcomptype() == "NONE" and audio.getsampwidth() == 2
        frames = audio.readframes(audio.getnframes())
        assert len(frames) == audio.getnframes() * audio.getnchannels() * 2
        duration = audio.getnframes() / audio.getframerate()
        rate, channels = audio.getframerate(), audio.getnchannels()
    samples = array("h", frames)
    if sys.byteorder != "little":
        samples.byteswap()
    rms = math.sqrt(sum((x / 32768) ** 2 for x in samples) / len(samples))
    assert rms > 1e-5
    return dict(duration_seconds=duration, sample_rate=rate, channels=channels,
                rms=rms, peak=max(abs(x) for x in samples) / 32768,
                samples=len(samples), sha256=hashlib.sha256(data).hexdigest())


def capture(host, model, output):
    output.mkdir(exist_ok=False)
    trace = output / "onnx-inputs.jsonl"
    env = dict(os.environ, AURORA_ORACLE_TRACE=str(trace))
    rows = []
    with (output / "frontend.log").open("w", encoding="utf-8") as errors:
        child = subprocess.Popen([str(host), str(model), str(output / "audio"), "4"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
            text=True, encoding="utf-8", env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            ready_line = child.stdout.readline()
            if not ready_line.startswith("READY "):
                raise RuntimeError("Oracle initialization failed; inspect frontend.log")
            ready = json.loads(ready_line[6:])
            offset = 0
            for i, text in enumerate(CORPUS):
                child.stdin.write(f"golden_{i}\t{text.encode('utf-8').hex()}\n")
                child.stdin.flush()
                line = child.stdout.readline()
                if not line.startswith("{"):
                    raise RuntimeError("Oracle generation failed: " + line)
                row = json.loads(line)
                trace_rows = [json.loads(x) for x in trace.read_text().splitlines()]
                row.update(text=text, onnx_inputs=trace_rows[offset:],
                           wav=pcm_stats(output / "audio" / f"speech-{i}.wav"))
                assert row["onnx_inputs"], "No actual ONNX Run captured"
                offset = len(trace_rows)
                rows.append(row)
                print(json.dumps(dict(host=host.name, case=i, captured_runs=len(row["onnx_inputs"])), ensure_ascii=False), flush=True)
            child.stdin.write("quit\n")
            child.stdin.flush()
            tail = child.communicate(timeout=15)[0]
            assert child.returncode == 0 and "CLOSED" in tail
        finally:
            if child.poll() is None:
                child.kill()  # Exceptional test cleanup, not normal cancel.
                child.communicate(timeout=10)
    assert "ORACLE_CAPTURE_FAILED" not in (output / "frontend.log").read_text(encoding="utf-8")
    return dict(ready=ready, rows=rows, exit_code=child.returncode, cleared=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False)
    captures = {}
    for kind in ("reference", "clean"):
        captures[kind] = capture(args.build / f"{kind}-oracle" / "Release" / f"{kind}_oracle.exe",
                                 args.model, args.output / kind)
    comparisons = []
    for old, new in zip(captures["reference"]["rows"], captures["clean"]["rows"]):
        comparisons.append(dict(text=old["text"], classification=compare_inputs(old["onnx_inputs"], new["onnx_inputs"]),
            reference_wav=old["wav"], clean_wav=new["wav"],
            duration_delta_seconds=new["wav"]["duration_seconds"] - old["wav"]["duration_seconds"]))
    report = dict(captures=captures, comparisons=comparisons, deterministic_seed="NOT EXPOSED",
                  manual_listening="NOT MANUALLY VERIFIED")
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(output=str(args.output), identical=sum(x["classification"] == "IDENTICAL" for x in comparisons), total=len(comparisons))))


if __name__ == "__main__":
    main()

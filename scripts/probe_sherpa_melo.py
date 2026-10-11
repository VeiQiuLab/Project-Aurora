"""Offline V4-7B.2 native C API benchmark controller, never a production provider.

Only the experiment uses Python; synthesis is the official CPU native library.
All generated evidence stays in a fresh caller-selected benchmark directory.
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import wave

TEXTS = ["你好，这是本机中文语音合成测试。",
         "你好，这是本机中文语音合成测试。",
         "今天我们在本机验证中文语音，模型保持常驻，不依赖远端电脑，也不使用网络语音服务。接下来检查播放是否完整。",
         "今天我们在本机验证完整的中文语音生成流程。文字首先进入本地语音模型，生成的音频随后交给播放层。整个过程不依赖远端电脑，也不调用网络语音服务。我们还需要检查模型常驻、停止后的恢复，以及与本地聊天模型共同运行时的资源占用。"]

COVERAGE = ["今天的温度是23.5度，一共123个人。",
            "今天是2026年10月6日，下次在2026-10-08见。",
            "你好，hello world，这是一个test。",
            "他说：你好！可以吗？当然可以；我们继续，保持安静。",
            "这里有一个词AuroraNonexistentWordXYZ，随后继续中文。"]


def inspect_pcm(path):
    """Fully read PCM16; format/header alone is not an audio-quality pass."""
    data = path.read_bytes()
    if (data[:4] != b"RIFF" or data[8:12] != b"WAVE"
            or int.from_bytes(data[4:8], "little") != len(data) - 8):
        raise ValueError("Invalid RIFF size/signature")
    with wave.open(str(path), "rb") as wav:
        if (wav.getcomptype() != "NONE" or wav.getsampwidth() != 2
                or wav.getnchannels() != 1 or wav.getnframes() <= 0):
            raise ValueError("Expected nonempty mono PCM16")
        frames = wav.readframes(wav.getnframes())
        if len(frames) != wav.getnframes() * 2:
            raise ValueError("Truncated PCM data")
        sr, duration = wav.getframerate(), wav.getnframes() / wav.getframerate()
    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    rms = math.sqrt(sum((v / 32768)**2 for v in samples) / len(samples))
    if rms < 1e-5:
        raise ValueError("All-silent PCM")
    return dict(sample_rate=sr, channels=1, audio_seconds=duration,
                pcm_rms=rms, sha256=hashlib.sha256(data).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, choices=(1, 4, 8, 16), default=1)
    parser.add_argument("--commands", action="store_true")
    parser.add_argument("--deadline", type=float, default=600)
    args = parser.parse_args()
    host, runtime, model = [p.resolve(strict=True) for p in (args.host, args.runtime, args.model)]
    for dll in ("sherpa-onnx-c-api.dll", "onnxruntime.dll", "onnxruntime_providers_shared.dll"):
        # PATH alone can lose to a different system ONNX Runtime on Windows.
        # Own a private test bin directory; never alter system DLLs.
        expected, actual = runtime / "lib" / dll, host.parent / dll
        if not actual.is_file() or actual.read_bytes() != expected.read_bytes():
            parser.error("Official runtime DLLs must be co-located with the test host: " + dll)
    output = args.output.resolve()
    if any(output.is_relative_to(p) for p in [runtime, model]):
        parser.error("Evidence must not overwrite runtime/model assets")
    output.mkdir(parents=True, exist_ok=False)
    native_output = output / "audio"
    report = dict(status="starting", native_host=str(host), runtime=str(runtime),
                  model=str(model), num_threads=args.threads, measurements=[])
    started = time.perf_counter()
    child = None
    def save():
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    def expire():
        report.update(status="timeout")
        save()
        if child is not None and child.poll() is None:
            child.kill()
        os._exit(124)
    timer = threading.Timer(args.deadline, expire)
    timer.daemon = True
    timer.start()
    try:
        env = dict(os.environ, PATH=str(runtime / "lib") + os.pathsep + os.environ.get("PATH", ""))
        # Native engine has no HTTP/GUI/server startup. No Torch or CosyVoice imports.
        with (output / "native.log").open("w", encoding="utf-8") as errors:
            process_start = time.perf_counter()
            child = subprocess.Popen([str(host), str(model), str(native_output), str(args.threads)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                                     text=True, encoding="utf-8", env=env,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            line = child.stdout.readline()
            if not line.startswith("READY "):
                raise RuntimeError("Native initialization failed; inspect native.log")
            ready = json.loads(line[6:])
            report.update(status="ready", ready=ready,
                          native_start_to_ready_seconds=time.perf_counter()-process_start,
                          controller_start_to_ready_seconds=time.perf_counter()-started)
            save()
            print("READY " + json.dumps(report), flush=True)
            def synthesize(command):
                text = command.get("text", TEXTS[int(command.get("text_index", 0))])
                label = command.get("label", "legacy")
                if not isinstance(text, str) or not text.strip() or len(text) > 1000:
                    raise ValueError("Expected 1..1000 text characters")
                if not isinstance(label, str) or not label or len(label) > 80 or any(
                        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-." for c in label):
                    raise ValueError("Invalid benchmark label")
                t0 = time.perf_counter()
                child.stdin.write(label + "\t" + text.encode("utf-8").hex() + "\n")
                child.stdin.flush()
                line = child.stdout.readline()
                if not line.startswith("{"):
                    raise RuntimeError("Native request failed; inspect native.log")
                result = json.loads(line)
                result["request_to_audio_ready_seconds"] = time.perf_counter()-t0
                path = native_output / f"speech-{result['index']}.wav"
                metadata = inspect_pcm(path)
                if abs(metadata["audio_seconds"]-result["audio_seconds"]) > .0001:
                    raise ValueError("Decoded duration mismatch")
                result.update(metadata, wav=str(path))
                report["measurements"].append(result)
                save()
                print(json.dumps(result), flush=True)
            if args.commands:
                for line in sys.stdin:
                    command = json.loads(line)
                    if command.get("quit"):
                        break
                    synthesize(command)
            else:
                synthesize(dict(label="first", text_index=0))
                for text_index in [0, 2, 3]:
                    for i in range(5):
                        synthesize(dict(label=f"warm_{text_index}_{i}", text_index=text_index))
                for i, text in enumerate(COVERAGE):
                    synthesize(dict(label=f"coverage_{i}", text=text))
                for i in range(20):
                    synthesize(dict(label=f"soak_{i}", text_index=0))
            child.stdin.write("quit\n")
            child.stdin.flush()
            if child.stdout.readline().strip() != "CLOSED" or child.wait(timeout=10) != 0:
                raise RuntimeError("Native shutdown failed")
            report.update(status="passed", native_exited=True)
    except BaseException as error:
        report.update(status="failed", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        timer.cancel()
        if child is not None:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
            report["native_exited"] = child.poll() is not None
        report["elapsed_seconds"] = time.perf_counter()-started
        save()


if __name__ == "__main__":
    main()

"""Opt-in offline feasibility probe; external runtime/model files stay read-only.

Run with the already installed CosyVoice interpreter. Not an Aurora provider or
supervisor. Reports full local paths only to the explicitly chosen local report.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from collections import Counter
from functools import wraps

TEXTS = ["你好，这是本机中文语音合成测试。",
         "你好，这是本机中文语音合成测试。",
         "今天我们在本机验证中文语音，模型保持常驻，不依赖远端电脑，也不使用网络语音服务。接下来检查播放是否完整。",
         "今天我们在本机验证完整的中文语音生成流程。文字首先进入本地语音模型，生成的音频随后交给播放层。整个过程不依赖远端电脑，也不调用网络语音服务。我们还需要检查模型常驻、停止后的恢复，以及与本地聊天模型共同运行时的资源占用。"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=("rocm", "cpu"), default="rocm")
    parser.add_argument("--deadline", type=float, default=300)
    parser.add_argument("--threads", type=int, help="Explicit PyTorch CPU thread count for feasibility comparison")
    parser.add_argument("--samples", type=int, choices=(1, 2, 3, 4), default=4)
    parser.add_argument("--controlled", action="store_true", help="Wait for stdin before each synthesis (feasibility harness only)")
    parser.add_argument("--commands", action="store_true", help="Persistent JSON stdin benchmark commands; not an HTTP runtime")
    parser.add_argument("--profile-stages", action="store_true")
    parser.add_argument("--count-host-sync", action="store_true", help="Count explicit Tensor host reads/copies; diagnostic run only")
    parser.add_argument("--weight-half", action="store_true", help="In-memory LLM/flow half storage; leave HiFT/F0 precision unchanged")
    parser.add_argument("--f0-cpu", action="store_true", help="In-memory F0-only CPU offload experiment")
    parser.add_argument("--fp32", action="store_true", help="Disable upstream fp16 autocast for a baseline comparison")
    args = parser.parse_args()
    if args.threads is not None and args.threads < 1:
        parser.error("--threads must be positive")
    source = args.source.resolve(strict=True)
    model_dir = args.model.resolve(strict=True)
    prompt = args.prompt.resolve(strict=True)
    output = args.output.resolve()
    if output.is_relative_to(source) or output.is_relative_to(model_dir):
        parser.error("Evidence must not be written into external source/model directories")
    output.mkdir(parents=True, exist_ok=False)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      MODELSCOPE_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1")
    if args.threads is not None:
        for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            os.environ[name] = str(args.threads)
    sys.dont_write_bytecode = True
    if args.backend == "cpu":
        os.environ["HIP_VISIBLE_DEVICES"] = "-1"
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    # Fail closed on accidental package/model downloads, even if an upstream
    # library does not honor the offline flags. This process needs no network.
    def no_network(*_args, **_kwargs):
        raise RuntimeError("Offline feasibility probe forbids network access")
    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    started = time.perf_counter()
    report = dict(status="starting", backend_requested=args.backend,
                  source=str(source), model=str(model_dir), measurements=[])
    def save():
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    def expired():
        report.update(status="timeout", elapsed_seconds=time.perf_counter()-started)
        save()
        os._exit(124)
    timer = threading.Timer(args.deadline, expired)
    timer.daemon = True
    timer.start()
    try:
        sys.path[:0] = [str(source), str(source / "third_party/Matcha-TTS")]
        import torch
        import torchaudio
        import soundfile as sf
        import onnxruntime as ort
        from cosyvoice.cli.cosyvoice import AutoModel
        import cosyvoice.cli.frontend as frontend
        if args.threads is not None:
            torch.set_num_threads(args.threads)
            torch.set_num_interop_threads(1)

        # Existing installed torchaudio now uses optional TorchCodec for load.
        # Use installed libsndfile for the trusted prompt, without editing upstream.
        def load_wav(path, target_sr, min_sr=16000):
            data, sr = sf.read(path, dtype="float32", always_2d=True)
            if sr < min_sr:
                raise ValueError("Prompt sample rate too low")
            speech = torch.from_numpy(data.T).mean(dim=0, keepdim=True)
            if sr != target_sr:
                speech = torchaudio.transforms.Resample(sr, target_sr)(speech)
            return speech
        frontend.load_wav = load_wav
        gpu = torch.cuda.is_available()
        if args.backend == "rocm" and (not gpu or not torch.version.hip):
            raise RuntimeError("Requested ROCm backend is not actually available")
        if args.backend == "cpu" and gpu:
            raise RuntimeError("CPU isolation failed")
        report.update(torch=torch.__version__, hip=torch.version.hip,
                      device=torch.cuda.get_device_name(0) if gpu else "cpu",
                      onnx_providers=ort.get_available_providers(), threads=torch.get_num_threads(),
                      interop_threads=torch.get_num_interop_threads(),
                      thread_environment={name: os.environ.get(name) for name in
                          ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
        report.update(pid=os.getpid(), import_seconds=time.perf_counter()-started,
                      autocast_fp16=gpu and not args.fp32, weight_half=args.weight_half,
                      f0_cpu=args.f0_cpu, profile_stages=args.profile_stages,
                      torch_configuration=torch.__config__.show())
        save()
        print(json.dumps(report), flush=True)
        load_start = time.perf_counter()
        model = AutoModel(model_dir=str(model_dir), load_trt=False, load_vllm=False, fp16=gpu and not args.fp32)
        if args.weight_half:
            if not gpu or args.fp32:
                raise ValueError("Half storage comparison requires GPU fp16 autocast")
            model.model.llm.half()
            model.model.flow.half()
        if gpu:
            torch.cuda.synchronize()
        report["cold_model_load_seconds"] = time.perf_counter()-load_start
        prompt_start = time.perf_counter()
        model.add_zero_shot_spk("You are a helpful assistant.<|endofprompt|>希望你以后能够做的比我还好呦。",
                               str(prompt), "aurora_probe")
        if gpu:
            torch.cuda.synchronize()
        report["prompt_cache_seconds"] = time.perf_counter()-prompt_start
        if args.f0_cpu:
            f0 = model.model.hift.f0_predictor.cpu()
            original_forward = f0.forward
            def offloaded_f0(value, *a, **kw):
                result = original_forward(value.cpu(), *a, **kw)
                return result.to(value.device)
            f0.forward = offloaded_f0
        def placement():
            result = {}
            for name in ("llm", "flow", "hift"):
                counts = Counter()
                for p in getattr(model.model, name).parameters():
                    counts[str(p.device)+"/"+str(p.dtype)] += p.numel()*p.element_size()
                result[name] = dict(counts)
            return result
        report["parameter_bytes_by_device_dtype"] = placement()
        report["text_frontend"] = model.frontend.text_frontend
        report["attention_implementation"] = model.model.llm.llm.model.config._attn_implementation
        report["flash_sdp_enabled"] = torch.backends.cuda.flash_sdp_enabled()
        report["trt_vllm_enabled"] = False
        report.update(status="ready", model_load_seconds=time.perf_counter()-load_start,
                      cold_ready_seconds=time.perf_counter()-started, sample_rate=model.sample_rate,
                      model_device=str(next(model.model.llm.parameters()).device),
                      tokenizer_providers=model.frontend.speech_tokenizer_session.get_providers())
        save()
        print("READY " + json.dumps(report), flush=True)
        stages = []
        transfers = Counter()
        if args.count_host_sync:
            def count_tensor_method(name):
                original = getattr(torch.Tensor, name)
                @wraps(original)
                def counted(value, *a, **kw):
                    result = original(value, *a, **kw)
                    if name in {"item", "tolist", "__bool__", "__int__"} and value.device.type != "cpu":
                        transfers["device_host_read_"+name] += 1
                    elif isinstance(result, torch.Tensor) and value.device != result.device:
                        transfers[str(value.device)+"->"+str(result.device)] += 1
                    return result
                setattr(torch.Tensor, name, counted)
            for method in ("item", "tolist", "__bool__", "__int__", "cpu", "to"):
                count_tensor_method(method)
        def timed(owner, attribute, name):
            original = getattr(owner, attribute)
            @wraps(original)
            def measured(*a, **kw):
                if gpu:
                    torch.cuda.synchronize()
                begin = time.perf_counter()
                try:
                    return original(*a, **kw)
                finally:
                    if gpu:
                        torch.cuda.synchronize()
                    stages.append(dict(stage=name, seconds=time.perf_counter()-begin,
                                       thread=threading.current_thread().name,
                                       torch_threads=torch.get_num_threads()))
            setattr(owner, attribute, measured)
        if args.profile_stages:
            for owner, attribute, name in (
                (model.frontend, "text_normalize", "text_preprocess"),
                (model.frontend, "_extract_text_token", "tokenization"),
                (model.model, "llm_job", "speech_token_generation"),
                (model.model.flow, "inference", "flow"),
                (model.model.hift, "inference", "vocoder"),
                (model.model.hift.f0_predictor, "forward", "f0_nested_in_vocoder")):
                timed(owner, attribute, name)
        def synthesize(command):
            index = len(report["measurements"])
            text = command.get("text", TEXTS[int(command.get("text_index", 0))])
            if not isinstance(text, str) or not text.strip() or len(text) > 1000:
                raise ValueError("Benchmark text must contain 1 to 1000 characters")
            stream = bool(command.get("stream", False))
            # Identical seed per matched case; varied seeds across repetitions.
            seed = int(command.get("seed", 1986))
            import random
            import numpy as np
            random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
            if gpu:
                torch.cuda.manual_seed_all(seed)
            stages.clear()
            transfers.clear()
            if gpu:
                torch.cuda.reset_peak_memory_stats()
            print("START " + json.dumps(dict(index=index, label=command.get("label", "legacy"), pid=os.getpid())), flush=True)
            t0 = time.perf_counter()
            chunks = []
            first_chunk_seconds = None
            for value in model.inference_zero_shot(
                    text, "", "", zero_shot_spk_id="aurora_probe", stream=stream, speed=1.0):
                chunks.append(value["tts_speech"].detach().cpu())
                if first_chunk_seconds is None:
                    first_chunk_seconds = time.perf_counter()-t0
            if gpu:
                torch.cuda.synchronize()
            elapsed = time.perf_counter()-t0
            audio = torch.cat(chunks, dim=-1).squeeze(0).numpy()
            if not len(audio) or not bool(torch.isfinite(torch.from_numpy(audio)).all()):
                raise RuntimeError("Invalid synthesized audio")
            write_start = time.perf_counter()
            path = output / f"speech-{index}.wav"
            sf.write(str(path), audio, model.sample_rate, subtype="PCM_16")
            write_seconds = time.perf_counter()-write_start
            duration = len(audio)/model.sample_rate
            measurement = dict(index=index, text_chars=len(text), synthesis_seconds=elapsed,
                               audio_seconds=duration, rtf=elapsed/duration,
                               peak_allocated_bytes=torch.cuda.max_memory_allocated() if gpu else 0,
                               reserved_bytes=torch.cuda.memory_reserved() if gpu else 0,
                               label=command.get("label", "legacy"), seed=seed, stream_internal=stream,
                               internal_chunks=len(chunks), first_internal_chunk_seconds=first_chunk_seconds,
                               wav=str(path), stages=list(stages), audio_write_seconds=write_seconds,
                               explicit_tensor_transfer_counts=dict(transfers),
                               parameter_bytes_by_device_dtype=placement(), pid=os.getpid())
            report["measurements"].append(measurement)
            save()
            print(json.dumps(measurement), flush=True)
        if args.commands:
            for line in sys.stdin:
                command = json.loads(line)
                if command.get("quit"):
                    break
                synthesize(command)
        else:
            for text_index in range(args.samples):
                if args.controlled and sys.stdin.readline().strip() != "go":
                    raise RuntimeError("Feasibility controller disconnected")
                synthesize(dict(text_index=text_index))
        report["status"] = "passed"
    except BaseException as exc:
        report.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        timer.cancel()
        report["elapsed_seconds"] = time.perf_counter()-started
        save()


if __name__ == "__main__":
    main()

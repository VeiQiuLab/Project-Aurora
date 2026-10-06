# V4-7B local voice feasibility audit

Audit date: 2026-10-06. Production baseline: `refactor/aurora-v4`,
`dd1ceb24b59d2ad26a934055c7d6554528828bbb`.

Gate 0 passed: local and remote agreed and the starting working tree was clean.
The WIP optics branch remained at `adeee5aa4949a47e62ba9f7a2cb708f50a361970`.
The retired remote laptop is not an available resource or a prerequisite.

## Evidence boundaries

This audit uses existing, read-only runtime/model assets. No packages or models
were installed or downloaded. Network connections are blocked inside the probe,
including attempted Modelscope text-normalizer resolution. The upstream frontend
falls back to its existing basic normalization when those resources are absent.
The installed torchaudio expects missing TorchCodec for prompt loading; the probe
uses already installed soundfile in memory instead. No external source file is
patched, and the speaker cache is kept in memory rather than saved to spk2info.

The Release coexist harness starts the existing 4B model and visible Live2D,
then separately starts an offline voice probe. Production Voice is disabled.
This is NOT proof of automatic LocalVoiceSupervisor startup, Local TTS routing,
Rust Audio playback, lip sync, request cancellation, crash recovery, or manual
listening. Its `status=passed` means the measured operations completed, not that
the V4-7B performance/production gates passed. Evidence lives under ignored
`tests/output/`; audio, logs, private paths and conversation data stay out of Git.

## Gate 1: existing assets

Hardware verified: Ryzen 9 7940HX (16 cores / 32 logical processors), 32 GB RAM,
AMD Radeon RX 7600 XT, driver 32.0.31041.1004. PyTorch reports 8,573,157,376
bytes of device memory. WMI AdapterRAM alone is not reliable for this card.

No real cosyvoice.cpp checkout, cosyvoice-cli/server executable or
CosyVoice3-2512_Q8_0.gguf was found in the searched local asset directories
(user profile/Downloads/Desktop/Documents, C:\AI, Projects, Apps, Data,
Installers, Exchange, and Program Files; this is not a claim about inaccessible
or unsearched system/recovery locations).
Repository test fixtures with those names are not real runtimes/models.

An alternative existing runtime and model WERE found:

| Item | Actual local asset |
| --- | --- |
| Runtime | Python CosyVoice, `C:\Users\X\CosyVoice` |
| Runtime revision | `main`, `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc` |
| Interpreter | `C:\Users\X\anaconda3\envs\cosyvoice-amd\python.exe`, Python 3.11.16 |
| Torch | 2.12.0+rocm10.0.0, HIP 7.15.26333; CUDA version is null |
| Device support verified | ROCm/HIP on the actual RX 7600 XT; CPU also runs |
| Other backend claims | No verified Vulkan or DirectML route in this Python runtime; no NVIDIA/CUDA execution |
| ONNX tokenizer | ONNXRuntime 1.18.0, actual CPUExecutionProvider |
| Model | Fun-CosyVoice3-0.5B-2512, `C:\Users\X\CosyVoice\pretrained_models\Fun-CosyVoice3-0.5B` |
| Format | PyTorch `.pt`, ONNX, Qwen tokenizer/safetensors; NOT GGUF |
| Directory size | 20 files, 9,747,515,976 bytes (includes unused alternate checkpoints/ONNX files) |
| Metadata | Modelscope `.mv`: revision `master`, CreatedAt 1769681956; not an immutable model commit |
| Reference prompt | `C:\Users\X\CosyVoice\asset\zero_shot_prompt.wav`, existing upstream sample |
| Audio | Actual synthesized RIFF/WAVE, PCM16, 24 kHz mono |

The external checkout already had five untracked test/requirements files. They
were inspected without execution or modification. Its tracked source was clean.
These machine-specific paths are audit evidence and explicit probe arguments,
not production defaults or frontend diagnostics.

SHA256 (actual existing files):

| File | Bytes | SHA256 |
| --- | ---: | --- |
| llm.pt | 2024669519 | 69f43bd545131c30e98947fb360ea8b4dc9916d8e83dded7757c7ea4f5a24970 |
| flow.pt | 1329116148 | a6fab32a7825e5b0bc855ddd948f8db9370b0a786fbc249caa4595e95b608e4b |
| hift.pt | 83202622 | b279d7641eb97ae55b3b540cfba4f953c26492a2df758328a89a4d007ab87a65 |
| campplus.onnx | 28303423 | a6ac6a63997761ae2997373e2ee1c47040854b4b759ea41ec48e4e42df0f4d73 |
| speech_tokenizer_v3.onnx | 969451503 | 23236a74175dbdda47afc66dbadd5bcb41303c467a57c261cb8539ad9db9208d |
| CosyVoice-BlankEN/model.safetensors | 988097824 | 130282af0dfa9fe5840737cc49a0d339d06075f83c5a315c3372c9a0740d0b96 |
| cosyvoice3.yaml | 6934 | f5a6b2c6f05139d0f18861a1fe506f751e787026b77c05f7e8fef9f8a4405965 |
| .msc | 1389 | 56a81af329f29e89b36b98e764ec5555246c90ee91c8cf948e16853981bcd6a0 |
| .mv | 36 | 172d690bf1c81cbf2d5872e46fdaeadeec05910679f17029c1698c9e4c6d2004 |
| asset/dingding.png | 122824 | 7f04815e2e676d31b089af6fa270135f3214f2193d5e0ad98b491d007d48f1c6 |
| configuration.json | 47 | c502b6328c67638b401df8dd05de89e9e8d1cff9cd0ada10dfbdbe13556c20de |
| CosyVoice-BlankEN/config.json | 659 | 168aa1bd401abc3bc262ba15ba4e499627a8b4e006e9d050b47c22de20660185 |
| CosyVoice-BlankEN/generation_config.json | 242 | e558847a8b4402616f1273797b015104dc266fe4b520056fca88823ba8f8ebe6 |
| CosyVoice-BlankEN/merges.txt | 1402109 | ac8ff86a72bee70828fbc1119bc4398c6f3a9a6e490d7b0dbe917be025478bd0 |
| CosyVoice-BlankEN/tokenizer_config.json | 1287 | 482bd979881423375ca5414e4e0d94cd7c5349dbb17fffd46b4d36d71e62a1bc |
| CosyVoice-BlankEN/vocab.json | 2776833 | ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910 |
| flow.decoder.estimator.fp32.onnx | 1326216933 | 9b51b9533a55937762b262bf2cf9c6220ce40760f76d6532cb16a6a6d84059a8 |
| llm.rl.pt | 2024682701 | 74d34b01a80c7154670ae75ac372d1b1712c78bceae9f467eb9f1f6f61ec764f |
| README.md | 11364 | 9ce4334fdd276864e60a072fe65cd8791c77239d0204ac7f6c8d04466e455c56 |
| speech_tokenizer_v3.batch.onnx | 969451579 | b156b8a7bbff436585e153f4637b9a368009005ac66efa108a6c8bfb34e5ee43 |
| zero_shot_prompt.wav (outside model directory) | 334138 | c7b31d6dbe7cc6a716dded00550db5b50940bf209e424e4ad207b12e657c8ff6 |

All 20 model files were hashed at closure. Primary llm/flow/hift/tokenizer and
prompt hashes matched the initial audit. The external Git revision/status stayed
unchanged, including the same five pre-existing untracked files.

Source LICENSE and the official [model card](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512/blob/main/README.md)
identify Apache-2.0. No redistribution is performed here. Model/runtime packaging,
third-party dependency notices and permission to use/redistribute a reference
voice require their own checks; this is not a blanket voice-rights approval.

## Gate 2: existing integration boundaries

`TTSRouter` performs explicit selection with no automatic fallback.
`local_cosyvoice` is a reserved name, not an implemented provider. Composition,
settings validation and strict Rust voice snapshots currently register only
Edge, Remote and Fake. `voice.ipc=true`, `voice.streaming_pcm=false`, and
`cosyvoice_local=false` remain accurate and unchanged.

`VoiceExecution` owns generation/revision cancellation and stale suppression;
the existing private file handoff sends complete MP3/WAV to Rust Audio. Rust
releases the decoder/device before its stopped acknowledgement. Existing
amplitude lip sync consumes that same playback chain. A local runtime should
produce complete PCM16 WAV through this boundary rather than create a second
audio or mouth-control pipeline.

`LocalModelSupervisor` already supplies epoch ownership, a random private token,
dynamic 127.0.0.1 port, authenticated model-list plus health readiness, child
exit detection, Job Object ownership, and bounded shutdown. Those small patterns
can be reused, with a distinct `LocalVoiceSupervisor`; lifecycle owners must not
be combined. Its existing restart behavior is not an unlimited automatic loop.

The upstream Python FastAPI example binds 0.0.0.0, has no authentication/health
gate, and streams unframed PCM with a naive int16 cast. It is unsuitable for
direct production adoption. A future small adapter would bind loopback, use a
fresh private token, initialize model/prompt once, publish truthful readiness,
limit request sizes/concurrency, validate samples, and return complete PCM16
WAV. Rust alone would spawn/own it; Python's provider would only request/cancel.

If a feasible runtime is selected, the minimal design would use background
EAGER startup only when Voice is enabled and Local is selected (measured cold
ready is about 19–21 s). Other providers/disabled Voice must not spawn it. States:
STOPPED -> STARTING -> LOADING_MODEL -> READY; failures -> DEGRADED/FAILED;
shutdown -> STOPPING -> STOPPED. Readiness must include loaded-model and cached
prompt state, not process presence. Private endpoint/token/path/PID stay in
Rust-to-sidecar handoff; frontend sees only safe state/model/backend labels.

Cancellation would retain current generation invalidation, close the client
request and discard late output. This Python runtime has no verified native
request-cancel hook; cancellation must not use a process kill loop. A supervisor
could retry at most twice with increasing cooldown, then FAILED, with explicit
manual retry. Exit invalidates the old epoch, closes the child and Job Object,
and waits boundedly. These are conditional design decisions, NOT implementation
or acceptance claims.

## Gate 3: measured feasibility

Reference transcript is the existing upstream sample. Four texts contain 16,
16, 52 and 109 characters. The same model/prompt remain loaded between requests.
No Edge or Remote requests occur; probe network access is disabled.

ROCm alone: `tests/output/local-voice-feasibility-20261006-rocm/report.json`.
Cold ready 21.180 s; model/prompt load 11.880 s.

| Request | Synthesis s | Audio s | RTF |
| --- | ---: | ---: | ---: |
| 16 chars, cold | 26.324 | 3.64 | 7.232 |
| 16 chars, warm | 5.613 | 3.96 | 1.417 |
| 52 chars | 12.470 | 10.40 | 1.199 |
| 109 chars | 26.589 | 22.56 | 1.179 |

ROCm + real Release 4B Vulkan + visible Live2D:
`tests/output/local-voice-coexist/run-RedBez/`.
Cold ready 18.821 s; model/prompt load 10.891 s.

| Request | Synthesis s | Audio s | RTF |
| --- | ---: | ---: | ---: |
| 16 chars, cold | 38.145 | 3.64 | 10.479 |
| 16 chars, warm | 26.452 | 3.96 | 6.680 |
| 52 chars | 33.202 | 10.40 | 3.193 |
| 109 chars | 121.790 | 22.56 | 5.398 |

| Chat sample group | First content ms | Eval tokens/s |
| --- | --- | --- |
| LLM only (3 requests) | 62 / 93 / 32 | 71.84 / 72.27 / 72.33 |
| Voice loaded idle (3) | 94 / 62 / 46 | 71.91 / 72.24 / 71.84 |
| Voice synthesis (4) | 47 / 313 / 281 / 360 | 70.29 / 7.20 / 9.12 / 7.36 |
| After voice process exited | 172 | 10.82 |

No hard OOM or driver crash was observed. However, warm short synthesis became
4.7x slower, later LLM evaluation about 8–10x slower, and the long synthesis
exceeded even the current 120 s maximum configured TTS timeout. Shared GPU
memory was seen in both runtime processes. Contention/paging is supported by
the measurements; its exact driver-level cause is not established.

CPU, 16 PyTorch threads, same Release/4B/visible Live2D:
`tests/output/local-voice-coexist/run-stfarW/`.
Cold ready 19.695 s; model/prompt load 10.689 s. First 16 chars: synthesis
112.830 s, audio 3.40 s, RTF 33.185. Warm 16 chars: synthesis 128.319 s,
audio 3.60 s, RTF 35.644. The total 360 s probe deadline ended the 52-char
request without a completed result; no 109-char request was attempted. Partial
or timed-out requests must not be assigned invented latency/audio/RTF values.
Concurrent LLM samples remained 68.55–70.99 tok/s, first content 141–203 ms.
All owned processes were removed after the deadline.

CPU with only `torch.set_num_threads(4)` in the main thread:
`tests/output/local-voice-coexist/run-L9Mzp7/`.
Cold ready 17.055 s. First 16 chars: 92.418 s / 3.40 s / RTF 27.182;
warm 16 chars: 98.406 s / 3.60 s / RTF 27.335. The probe was deliberately
stopped after these two completed short samples, during the next long request.
The harness therefore records failure rather than a completed four-case run.
All owned processes were removed.

This setting alone did NOT constrain the whole process: inference launches an
additional Python thread and native math libraries also have thread pools. A
correctly timed 5.047 s sample still measured 2576.0% of one core for the voice
probe (about 80.5% of 32 logical cores). A final two-short-sample comparison sets
OMP/MKL/OpenBLAS/NumExpr environment variables before imports, plus PyTorch
intra-op=4 and inter-op=1. This explicitly configures those APIs/environment
variables; it does not prove all native worker pools obey them.

Final CPU comparison: `tests/output/local-voice-coexist/run-0gL8r7/`.
Cold ready 17.162 s, model/prompt load 9.219 s. Both short requests completed and
all processes exited normally; no further long CPU trial was needed after these
latencies demonstrated the blocker.

| Request | Synthesis s | Audio s | RTF |
| --- | ---: | ---: | ---: |
| 16 chars, cold | 93.413 | 3.40 | 27.474 |
| 16 chars, warm | 113.230 | 3.60 | 31.453 |

Final CPU chat baseline: first content 63–94 ms, 70.80–72.04 tok/s; voice idle
47–79 ms, 71.91–72.54 tok/s; synthesis 47 / 110 ms, 70.51 / 64.40 tok/s;
after the probe exited 78 ms, 70.47 tok/s. Desktop send round-trip during
synthesis was 3.2–3.3 ms. A separate correctly timed 5.046 s probe-only sample
still showed 2561.0% one core (~80.0% of 32 logical cores), confirming that the
tested environment did not actually produce a four-core process-wide limit.

Resource samples sum Desktop's owned process tree and the independent probe:

| Backend / phase | Working set GiB | Dedicated GPU GiB | GPU engine percent sum |
| --- | ---: | ---: | ---: |
| ROCm / LLM only | 3.420 | 2.908 | 0.44 |
| ROCm / voice idle | 7.766 | 5.741 | 0.39 |
| ROCm / synth 0 | 8.215 | 5.832 | 143.19 |
| ROCm / synth 1 | 10.133 | 5.119 | 147.82 |
| ROCm / synth 2 | 10.126 | 5.183 | 144.70 |
| ROCm / synth 3 | 10.132 | 5.363 | 152.36 |
| CPU 16 / LLM only | 6.931 | 3.576 | 6.79 |
| CPU 16 / voice idle | 14.474 | 3.545 | 10.60 |
| CPU 16 / synth 0 | 14.553 | 3.545 | 10.52 |
| CPU 16 / synth 1 | 13.726 | 4.927 | 56.21 |
| CPU 16 / synth 2 (timed out) | 12.932 | 3.573 | 6.43 |

These are short Windows counter samples, not global peak memory or percentages
of the physical GPU/whole CPU. Multiple GPU engines/processes are summed and
can exceed 100. Desktop and probe samples occur in successive windows rather than one
instant. GPU memory residency changes between runs. They must not be converted
into invented hardware utilization guarantees. Desktop send command round-trip
stayed 2.5–4.9 ms during the ROCm samples and 2.9–5.2 ms during CPU synthesis;
this is an automated responsiveness sample, not sustained/manual UI acceptance.

The original resource helper's CPU value is excluded: it reads the lazy
Process.TotalProcessorTime property after GPU queries but divides by an earlier
elapsed interval. That inflates CPU values. The new feasibility harness captures
the ending CPU values before GPU queries in memory; the existing committed
helper and production code are not changed. Original raw JSON is retained for
traceability, not used as valid CPU utilization evidence.

Final CPU run resources use the corrected CPU timing capture:

| Phase | Working set GiB | Dedicated GPU GiB | CPU one-core percent sum | GPU engine percent sum |
| --- | ---: | ---: | ---: | ---: |
| LLM only | 3.512 | 2.907 | 8.67 | 0.447 |
| Voice idle | 11.317 | 2.937 | 6.23 | 0.457 |
| Synth 0 | 11.402 | 2.940 | 2685.70 | 0.451 |
| Synth 1 | 9.979 | 2.937 | 2648.82 | 0.448 |

14 generated WAV files passed independent Python stdlib validation for nonempty
PCM16 / 24 kHz / mono RIFF/WAVE. Finite samples were checked by the probe. This
does not substitute for a Rust decoder/playback or manual listening test.

## Stage disposition

**Stage V4-7B: NOT PASS — ASSET / COMPATIBILITY BLOCKER (resource/performance).**

The historic cpp/GGUF assets are absent. Existing Python CosyVoice does generate
real local audio on this AMD machine, but the tested GPU coexist route severely
regresses LLM throughput and the CPU route takes roughly 1.5–2 minutes for a
16-character sentence. Neither qualifies for production integration under the
current assets/configurations. This is not a claim that all possible AMD/CPU
implementations of CosyVoice are impossible; optimization or another runtime
would require a separate feasibility decision and fresh evidence.

Per the blocked-gate instruction, no LocalCosyVoiceProvider/LocalVoiceSupervisor
or production behavior is implemented. No downloads, default changes, fallback,
streaming PCM, commit or push are performed. Three new audit/probe files remain
untracked for review. No model, EXE, DLL, SDK, audio, logs, tokens or user data
are included in the candidate source files.

The next useful work is an explicitly scoped runtime/CPU-math or quantized
backend feasibility investigation, before any integration. No replacement model
or runtime package is selected in this audit, so there is no approved download
size or redistribution plan for new assets. A proposed replacement must first
document hardware/backend compatibility, RAM/VRAM budget, exact download size
and licenses. Existing Edge remains functional by baseline evidence; it is not
used to pass a local voice test. Manual voice quality: NOT MANUALLY VERIFIED.

Closure checks: compileall 279/279 (278 tracked Python files + the new probe),
probe CLI/help and Python syntax, Node syntax, and whitespace checks passed.
All four coexist runs show `remainingOwned=[]`; a final actual process inventory
found no Desktop/llama/Live2D/voice-probe residuals. Ollama and LM Studio remained
closed. Real origin HEAD was read again and matched local HEAD. WIP optics stayed
at its original revision. Full Python/Rust/frontend regression suites and a new
Release build were not run because the feasibility gate blocked implementation;
previous-stage passes are not presented as this stage's test results.

## Required report fields (1–81)

| # | Field | Actual disposition |
| ---: | --- | --- |
| 1 | Branch | refactor/aurora-v4 |
| 2 | Commit hash | dd1ceb24b59d2ad26a934055c7d6554528828bbb, unchanged |
| 3 | Commit message | feat(v4): add avatar behavior and lip sync; no new commit |
| 4 | Local / Remote | Final actual origin HEAD equals local dd1ceb24...; no push performed |
| 5 | Working tree | Three untracked audit/probe files; no tracked modifications |
| 6 | Modified/new count | 0 modified, 3 new |
| 7 | Local Voice Runtime | FOUND: existing Python CosyVoice; cpp runtime NOT FOUND |
| 8 | Exact runtime | Python CosyVoice AutoModel / CosyVoice3 |
| 9 | Version / commit | 074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc; dependency versions above |
| 10 | Runtime path strategy | Read-only explicit probe arguments; no production discovery implemented |
| 11 | Backend | Verified ROCm/HIP and CPU; no verified Vulkan/DirectML voice route |
| 12 | RX 7600 XT support | Actual PyTorch HIP device, not NVIDIA/CUDA; tokenizer actually CPU |
| 13 | Local Voice Model | FOUND; historical GGUF NOT FOUND |
| 14 | Exact model | Fun-CosyVoice3-0.5B-2512 |
| 15 | Format | PT + ONNX + safetensors/tokenizer, not GGUF |
| 16 | Size | 9,747,515,976 bytes / 20 files; includes unused duplicate representations |
| 17 | Hash | SHA256 manifest above; llm/flow/hift are separate files, no invented single checkpoint hash |
| 18 | License / redistribution | Apache-2.0 metadata/source; no redistribution, independent voice/dependency checks required |
| 19 | LocalVoiceSupervisor | Conditional separate Rust owner design above; NOT IMPLEMENTED |
| 20 | State machine | Proposed STOPPED/STARTING/LOADING_MODEL/READY/DEGRADED/FAILED/STOPPING; NOT IMPLEMENTED |
| 21 | EAGER / LAZY | Proposed conditional background EAGER because cold ready ~17–21 s; no policy enabled |
| 22 | Dynamic port | Existing LLM pattern audited; Voice implementation absent |
| 23 | Auth / isolation | Existing example has no auth and binds 0.0.0.0; conditional loopback adapter/private token design only |
| 24 | Readiness | Probe proves model+prompt loaded and subsequent synthesis; production HTTP readiness NOT IMPLEMENTED |
| 25 | Crash detection | Conditional Rust child/epoch design only |
| 26 | Restart policy | Proposed bounded retries/cooldown then FAILED; NOT IMPLEMENTED |
| 27 | Shutdown | Probe/harness own cleanup verified separately; production Local Voice owner absent |
| 28 | Job Object | Existing reusable Rust primitive audited; no new Local Voice Job owner |
| 29 | LocalCosyVoiceProvider | NOT IMPLEMENTED |
| 30 | TTSRouter | Existing Edge/Remote/Fake unchanged; Local remains reserved |
| 31 | Edge role | Existing selectable network provider; never used in local probes |
| 32 | Remote role | Compatibility provider retained; production selection unchanged |
| 33 | Remote Node dependency | Not used or required; retired laptop not contacted |
| 34 | Synthesis cancellation | New local provider request cancellation NOT IMPLEMENTED/NOT TESTED |
| 35 | Stale suppression | Existing ownership audited and unchanged; new Local path NOT TESTED |
| 36 | Rust Audio integration | Existing complete-file boundary audited; local production handoff NOT IMPLEMENTED |
| 37 | Lip sync integration | Existing Rust amplitude boundary retained; local voice mouth updates NOT TESTED |
| 38 | voice.ipc | true, unchanged |
| 39 | voice.streaming_pcm | false, unchanged |
| 40 | cosyvoice_local | false, unchanged and truthful |
| 41 | Cold runtime ready | ROCm alone 21.180 s; ROCm coexist 18.821 s; CPU 16 19.695 s; CPU comparison above |
| 42 | Cold synthesis | 16 chars: ROCm alone 26.324 s / coexist 38.145 s; CPU 16 112.830 s; CPU comparisons above |
| 43 | Warm synthesis | 16 chars: ROCm alone 5.613 s / coexist 26.452 s; CPU 16 128.319 s; CPU comparisons above |
| 44 | Text lengths | 16 / 16 / 52 / 109 chars; only completed samples count |
| 45 | Audio durations | ROCm 3.64 / 3.96 / 10.40 / 22.56 s; CPU short samples 3.40 / 3.60 s |
| 46 | RTF | Measured tables above, all observed examples >1; no timed-out result invented |
| 47 | RAM | ROCm coexist sampled working set 7.77–10.13 GiB; CPU 16 up to 14.55 GiB; definitions above |
| 48 | VRAM | ROCm coexist sampled dedicated 5.12–5.83 GiB plus observed shared residency; not peak-total proof |
| 49 | CPU | Old sampler values invalid/excluded; corrected final synth sum ~2649–2686% one core (32 logical cores); definitions above |
| 50 | GPU | Per-engine aggregate samples above; NOT percent of entire physical GPU |
| 51 | LLM first token baseline | ROCm coexist baseline first-content 32–93 ms, 3 warm samples |
| 52 | LLM first token with Voice | ROCm idle 46–94 ms; synth 47–360 ms; CPU values above |
| 53 | LLM tok/s baseline | ROCm run 71.84–72.33 |
| 54 | LLM tok/s with Voice | ROCm idle ~72, later synthesis 7.20–9.12; CPU short samples retain ~64–71 |
| 55 | OOM / contention | No hard OOM/driver crash observed; major GPU performance regression and shared-memory use observed |
| 56 | Local Voice disabled | Current Release with Voice disabled starts no Local Voice; probe is a separately launched test process |
| 57 | Runtime missing | Local supervisor path not implemented; local-specific missing-runtime isolation NOT TESTED |
| 58 | Model missing | Local-specific missing-model isolation NOT TESTED |
| 59 | Runtime crash | Local integration isolation NOT TESTED; feasibility timeout/cleanup is not its substitute |
| 60 | Restart recovery | Local integration NOT IMPLEMENTED/NOT TESTED |
| 61 | Stop Voice | Local production Stop Voice NOT TESTED |
| 62 | No Edge synthesis | Confirmed for actual local probes: socket access disabled, existing local model inference only |
| 63 | Rust actual playback | Local output NOT TESTED through Rust Audio |
| 64 | Actual mouth changes | Local synthesis mouth movement NOT TESTED; Live2D visibility/readiness alone verified |
| 65 | Python tests | Probe syntax/CLI checked; full Python suite NOT RUN for blocked integration |
| 66 | Rust tests | NOT RUN; Rust source unchanged |
| 67 | Frontend tests | NOT RUN; frontend source unchanged |
| 68 | Voice regression | No production Voice changes; regression suite NOT RUN in this blocked stage |
| 69 | Audio regression | No production Audio changes; NOT RUN |
| 70 | Live2D regression | Visible/ready in coexist smoke; full regression suite NOT RUN |
| 71 | Local Model regression | Actual existing 4B Release chats completed; GPU coexist performance Gate FAILED |
| 72 | Full source / Legacy | NOT RUN; no implementation gate falsely declared complete |
| 73 | compileall | 279/279 passed: 278 tracked Python files plus new probe |
| 74 | Release build | Existing baseline Release used; no new build, NOT RUN |
| 75 | Real Release smoke | Actual Chat+4B+visible Live2D coexist; full automatic Local Voice/Audio/Lip Sync smoke NOT RUN |
| 76 | Exit residue | All completed/aborted runs report remainingOwned=[]; final process inventory clean |
| 77 | Ollama | Not running during harness prechecks; never started |
| 78 | LM Studio | Not running during harness prechecks; never started |
| 79 | Known limitations | Historic assets absent; HIP coexist regression, slow CPU, no native request cancel, missing normalizer/TorchCodec compatibility |
| 80 | Manual verification | NOT MANUALLY VERIFIED: naturalness, timbre, prosody, volume and listening |
| 81 | Next step | Separate runtime/backend feasibility work before integration; no automatic advance/download |

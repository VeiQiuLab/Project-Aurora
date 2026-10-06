# V4-7B.1 Local Voice Runtime Performance Feasibility

Date: 2026-10-06. Baseline: `refactor/aurora-v4`,
`dd1ceb24b59d2ad26a934055c7d6554528828bbb`.

This is a performance experiment, NOT Local Voice Integration.
The previous `LOCAL_VOICE_RUNTIME_AUDIT.md` remains historical evidence;
its concurrent-inference numbers must not substitute for this stage's serial
resident measurements. No production provider, supervisor, routing, defaults,
audio, Live2D, model or UI source is changed.

## Method and evidence boundaries

The existing Release starts its own 4B Vulkan LLM and real visible Cubism host.
An explicitly launched, separately owned offline Python voice probe loads the
existing model once. Fresh disposable application settings/history are used.
Fixed texts contain 16, 52 and 109 characters. Seeds 1986/1987/1988 are matched
across comparisons; output duration can differ by seed/precision. Every warm
comparison has three samples, reported as min/median/max, not best-only.

Foreground-serial scheduling waits for the actual Chat terminal before
synthesis, keeps both models loaded, and measures the next Chat after TTS.
Production also schedules a background title request after a turn: foreground
terminal alone therefore does NOT prove absence of all LLM inference. Strict
isolation disables only PostTurnCoordinator.schedule in the opt-in benchmark
process, not in production. The production-playback comparison leaves it on.
Concurrent scheduling starts synthesis while Chat is actually in the thinking
state; timestamps prove overlap. Voice-only is a separate process without
Desktop/LLM. Hidden/visible comparisons keep the same model processes alive.

Stage timers synchronize HIP around stage boundaries. F0 timing is nested in
vocoder timing and must NOT be added twice. Internal model `stream=True` is only
an inference comparison: chunks are accumulated into a complete WAV; no Aurora
streaming transport or playback is implemented. Uninstrumented comparisons
must be identified independently. Explicit host-read counters count Python
Tensor entry points, not every driver copy or C++ internal synchronization.

The optional completed-WAV fixture exists only in an opt-in benchmark sidecar
entrypoint. Existing VoiceExecution test dependency injection waits for the
actual completed assistant text, and accepts a request-matched, SHA256-checked
CosyVoice WAV. Existing private IPC, Rust Audio/rodio and Cubism amplitude drive
real playback. It is NOT a production LocalCosyVoiceProvider or Supervisor.
The UI's `fake` provider label denotes this test fixture, not synthesized fake
audio or an approved production provider. Default production launch is untouched.

Working set / peak working set describe process RAM, not total host RAM peaks.
Windows dedicated/shared GPU counters are sampled process residency, not exact
peak physical VRAM. PyTorch peak allocation covers its allocator, not all driver
workspaces. GPU engine percentages are per-engine aggregates, not a single GPU
utilization percentage. CPU percent is one-core-relative (3200% equals all 32
logical processors); the benchmark repairs the old sampler's timing in memory
without modifying the existing helper. Driver stall/kernel serialization/PCIe
byte rates require a GPU trace and must not be claimed from these counters.

Evidence WAVs/logs/disposable conversations remain ignored under `tests/output`.
Manual listening: **NOT MANUALLY VERIFIED**. No assets/packages are downloaded.

## Candidate alternatives: evaluation only, no installation

If current CosyVoice fails, prioritize a CPU ONNX experiment before another
GPU-heavy voice model. These are candidate routes, not local measured passes.

| Item | sherpa-onnx + MeloTTS Chinese ONNX | sherpa-onnx + Kokoro Chinese |
| --- | --- | --- |
| Selected model | vits-melo-tts-zh_en, one speaker | Kokoro-82M / Chinese-English v1.1, preset speakers |
| Published size | ONNX 163 MB; dictionaries/lexicon/FSTs extra | Chinese v1.1 PT weights 327 MB; v1.0 ONNX 310 MB + 26 MB voices; v1.1 ONNX/int8 release sizes not confirmed |
| Windows / AMD | Native Windows CPU ONNX; avoids AMD GPU contention | Same CPU route; no AMD acceleration assumed |
| Performance evidence | Upstream claims CPU real-time; official Pi 4 ONNX RTF 2.518 at four threads, NOT Ryzen/Windows proof | Official v1.0 Pi 4 RTF 3.191 at four threads, NOT v1.1 or Ryzen/Windows proof |
| License metadata | Runtime Apache-2.0; Melo source/model MIT; verify shipped bundle notices | Runtime/model Apache-2.0; phonemizer/eSpeak assets require independent license review |
| Chinese positioning | Basic fixed-voice Chinese with lexicon-limited English; listening needed | Larger preset-voice selection; actual Chinese quality/listening needed |
| Clone / custom speaker | Selected model does not offer zero-shot cloning | Selected model offers presets, not general zero-shot cloning |
| Python required | No: C/C++ API and executable are available; Python binding optional | Same |
| Headless / output | CPU synthesis to PCM16 WAV, no window required | Same, 24 kHz output family |
| Local API | No ready Aurora-compatible health/TTS server verified; a small future adapter would be needed | Same |
| Rust ownership | Inference: spawnable host + loopback/dynamic port, explicit ready/health, exit/crash/Job ownership are straightforward design boundaries, NOT implemented/tested | Same |
| Offline / CUDA | Bundle all required files; CPU path does not require CUDA | Same; fully cache Chinese frontend/voice assets |
| Main risks | CPU cost/quality, lexicon and normalization coverage, exact distribution size, future cancellation contract | CPU cost, frontend/dependency licenses, quality/voice selection, exact release version/size |

Public sources checked this stage:

- [Melo model, native invocation, size and Pi benchmark](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/vits.html).
- [Melo upstream CPU claim and MIT license](https://github.com/myshell-ai/MeloTTS), [Chinese model card](https://huggingface.co/myshell-ai/MeloTTS-Chinese).
- [Kokoro ONNX models, voices and Pi benchmark](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/kokoro.html), [Chinese v1.1 model card](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh).
- [Native Windows build](https://k2-fsa.github.io/sherpa/onnx/install/windows.html), [C TTS API](https://k2-fsa.github.io/sherpa/onnx/c-api/html/tts.html), [runtime license](https://github.com/k2-fsa/sherpa-onnx/blob/master/LICENSE).

Piper huayan is NOT a preferred candidate: its individual model card explicitly
lists dataset license as Unknown despite repository-level MIT metadata.
[Individual model card](https://huggingface.co/rhasspy/piper-voices/blob/main/zh/zh_CN/huayan/medium/MODEL_CARD).
No asset or runtime was downloaded. GitHub release-size API was rate limited;
unverified archive sizes are deliberately not invented.

## Measurements and final decision

**Decision C: NOT FEASIBLE — CURRENT COSYVOICE, ALTERNATIVE REQUIRED.**

This rejects the current Python CosyVoice as Aurora's default local voice on
this machine, not every possible local TTS. Serial inference does preserve the
next LLM request and is materially better than simultaneous inference. However,
even strict serial inference, half weight storage, 16 threads, no stage timers
and no resource polling during synthesis fail the short-text gate in all three
repetitions. Do not implement the production Local provider/Supervisor now.

### Hardware and existing runtime audit

- Ryzen 9 7940HX: 16 cores / 32 logical processors; usable RAM 31.71 GiB.
- RX 7600 XT: this installed device reports 8,573,157,376 bytes; Windows driver
  32.0.31041.1004. Do not infer the capacity from the product name or WMI alone.
- Source: `C:\Users\X\CosyVoice`, `main`,
  `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`. Tracked source stays clean; the
  same five pre-existing untracked test/requirements files are untouched.
- Interpreter: `C:\Users\X\anaconda3\envs\cosyvoice-amd\python.exe`, 3.11.16;
  torch 2.12.0+rocm10.0.0, HIP 7.15.26333, torchaudio 2.11.0+rocm10.0.0,
  ONNX Runtime 1.18.0. Torch build: USE_ROCM=ON, USE_CUDA=OFF, MIOpen 3.6.0.
  `cuda:0` is PyTorch's HIP device namespace here, NOT NVIDIA CUDA execution.
- Model: `C:\Users\X\CosyVoice\pretrained_models\Fun-CosyVoice3-0.5B`,
  Fun-CosyVoice3-0.5B-2512. Twenty files total 9,747,515,976 bytes, including
  unused alternate PT and ONNX checkpoints. The complete manifest is in the
  previous audit; all 20 hashes plus the reference WAV were rechecked unchanged.
  Modelscope metadata is mutable `master`, not an immutable checkpoint commit.
- Entry: AutoModel → cached add_zero_shot_spk → inference_zero_shot. LLM,
  flow/diffusion and HiFT parameters are GPU-resident. Text preprocessing,
  text tokenization, Python sampling/control and ONNX prompt speech-tokenizer
  run on CPU. The actual tokenizer session uses CPUExecutionProvider; Azure is
  merely an available provider. Prompt features are cached once in RAM.
  This does not prove the placement of every individual kernel/operator.
- The ONNX flow checkpoint is not used by this PT inference path. TensorRT and
  vLLM are disabled. No voice Vulkan/DirectML route was verified.
- SDPA attention is selected; flash_sdp_enabled is true, but this is not proof
  of which fused kernel dispatches on each request. No explicit torch.compile,
  captured graph or new backend was enabled. Existing library/kernel warmup
  and caches explain part of the cold/warm difference; exact cache contents
  were not traced. Existing request cleanup empties the Torch allocator cache
  and synchronizes, without unloading model parameters or reloading files.
- Default fp16=True enables autocast, not half parameter storage. Baseline
  parameter bytes: LLM 2,024,593,920; flow 1,329,028,352; HiFT 83,119,548, FP32.
  The benchmark's in-memory standard PyTorch half conversion reduces LLM to
  1,012,296,960 and flow to 664,514,176 bytes; HiFT is left unchanged. After
  inference HiFT includes 69,858,744 FP32 and 26,521,608 FP64 parameter bytes.
  This is not a newly quantized checkpoint or an upstream CLI option.
- FP32 autocast-off and F0-only CPU offload are exposed as probe comparisons
  but were NOT run. F0 is only 7–35 ms nested in vocoder work; moving it to CPU
  would not address the measured multi-second bottleneck. BF16/int8/graph
  optimization was not invented without an already validated runtime option.
- Existing upstream FastAPI example is headless but does not supply a verified
  Aurora-ready health/cancel/lifecycle contract, binds 0.0.0.0 by default, and
  was not started. Source/model Apache-2.0 metadata is not blanket permission
  to redistribute every dependency, prompt or cloned voice.

### Texts and timing definitions

Fixed texts, including punctuation, are 16 / 52 / 109 characters:

```text
你好，这是本机中文语音合成测试。
今天我们在本机验证中文语音，模型保持常驻，不依赖远端电脑，也不使用网络语音服务。接下来检查播放是否完整。
今天我们在本机验证完整的中文语音生成流程。文字首先进入本地语音模型，生成的音频随后交给播放层。整个过程不依赖远端电脑，也不调用网络语音服务。我们还需要检查模型常驻、停止后的恢复，以及与本地聊天模型共同运行时的资源占用。
```

Synthesis wall time spans model iteration through completed CPU audio chunks;
file write is separately timed. RTF = synthesis seconds / decoded audio
seconds. All table triples are **min / median / max**, computed independently
per metric over seeds 1986/1987/1988. The RTF median is not obtained by dividing
the other two medians. First synthesis is excluded from warm samples.

The strict uninstrumented resident run (`run-Q6002G`) is the primary gate:

| Characters | Warm synthesis seconds | Decoded audio seconds | Warm RTF | Judgment |
| ---: | --- | --- | --- | --- |
| 16 | 6.013 / 6.054 / 6.143 | 3.680 / 3.720 / 3.920 | 1.544 / 1.616 / 1.669 | FAIL: every sample > 1.5 |
| 52 | 14.935 / 16.317 / 17.052 | 10.320 / 11.120 / 11.760 | 1.447 / 1.450 / 1.467 | MARGINAL, not real-time |
| 109 | 34.522 / 35.418 / 38.709 | 22.400 / 24.000 / 25.120 | 1.476 / 1.541 / 1.541 | Above recommended default threshold |

Cold costs in that run: imports/runtime startup 7.354 s; model construction
including the in-memory half conversion 9.099 s; cached prompt 0.459 s;
READY 16.918 s from probe startup. First 16-character synthesis then takes
17.113 s. These are separate costs, not one warm RTF. Across the three completed
half/16-thread resident runs, import time is 7.222 / 7.354 / 7.462 s, model load
8.849 / 8.932 / 9.099 s, READY 16.616 / 16.771 / 16.918 s. First synthesis is
17.113 / 17.928 / 18.081 s. Cold starts are separate process launches, not
per-sentence reloads. The voice-only baseline cold import/model/prompt/READY
costs are 6.795 / 8.378 / 0.492 / 15.672 s; first synthesis is 15.997 s.

### Scenario and optimization comparisons

Each warm text/group below has three repetitions. Resource/profile and title
behavior differ as labeled; do not turn these into an exact causal attribution.

| Scenario | 16-character warm RTF min / median / max | 52-character RTF | 109-character RTF | Evidence |
| --- | --- | --- | --- | --- |
| Voice alone, autocast + FP32 weights, profiled | 1.041 / 1.184 / 1.327 | 1.111 / 1.141 / 1.144 | 1.129 / 1.132 / 1.146 | `v47b1-voice-alone-profile` |
| Foreground serial, both resident, FP32 weights, title behavior retained, profiled/sampled | 5.358 / 5.820 / 6.118 | 6.319 / 6.481 / 6.547 | 4.773 / 5.475 / 6.295 | `run-hcSQjV`, nine main samples completed |
| Same foreground serial, half weights / 16 threads, profiled/sampled | 1.627 / 1.638 / 1.641 | 1.265 / 1.368 / 1.372 | 1.305 / 1.337 / 1.360 | `run-wMcMLX`, nine main samples completed |
| Foreground serial, half weights / 4 threads, no stage timers, sampled | 1.494 / 1.618 / 1.664 | 1.527 / 1.547 / 1.556 | 1.527 / 1.551 / 1.562 | `run-rWl0eS`, nine main samples completed |
| Strict no-background inference, half / 16, profiled/sampled | 1.606 / 1.610 / 1.763 | 1.488 / 1.489 / 1.547 | 1.510 / 1.537 / 1.589 | `run-emeYQ7`, completed |
| Strict no-background inference, half / 16, no timers or synthesis resource polling | 1.544 / 1.616 / 1.669 | 1.447 / 1.450 / 1.467 | 1.476 / 1.541 / 1.541 | `run-Q6002G`, completed; primary gate |
| Real simultaneous Chat + TTS, half / 16, explicit host-read counters only | 2.177 / 2.249 / 2.387 | Not repeated | Not repeated | `run-4Obnaa`, completed |

Voice-only synthesis triples are 3.540 / 4.308 / 4.563 s (16 chars),
12.039 / 12.868 / 13.071 s (52), 25.005 / 27.316 / 27.334 s (109).
The matching FP32 resident triples are 18.216 / 20.022 / 22.269 s,
66.472 / 73.101 / 76.991 s, and 105.387 / 130.533 / 152.343 s.
Half weight storage gives a large improvement over the FP32 resident baseline,
but it does not make the primary gate pass. Four threads do not improve the
result over 16. Disabling timers/synthesis polling also does not make it pass.

Visible/hidden comparison in the same warmed half process: hidden short RTF
1.266 / 1.321 / 1.335, followed by visible-again 1.239 / 1.317 / 1.338.
Times are 4.660 / 4.967 / 5.177 s versus 4.561 / 4.977 / 5.164 s. Both groups
have no synthesis resource polling; the earlier visible matrix was polled and
less warmed. Do not compare only the later hidden group to that earlier group
and attribute the improvement to hiding. The matched later visible-again group
is as fast as hidden. Hiding Live2D is not a demonstrated solution. LLM-only
visible/hidden samples likewise stay around 72 tok/s.

Upstream internal stream=True short RTF is 1.615 / 1.623 / 2.281.
First internal chunks arrive at 3.727, 6.331 and 6.036 s; chunk counts are
3, 1, 1. The upstream persistent token_hop_len grows from 25 toward 100, so the
next short requests no longer supply an early chunk. No reset was added to
cherry-pick a first-request latency. This neither meets the speed gate nor
provides an Aurora production streaming integration.

The earlier harnesses did not wholly pass: `run-hcSQjV` timed out on a settings
status matcher *after* its nine measurements; `run-wMcMLX` then reached a
benchmark handoff whose Windows extended path was not canonicalized, and
`run-rWl0eS` reported INVALID_VOICE_SETTINGS for the same benchmark path guard.
The nine completed measurements in each are usable, but they are not a full
playback pass. The benchmark-only settings matcher/path guard was repaired and
tested. The final three runs complete with no remaining owned children. No
production fix was required.

### Where the time goes

Stage medians, in seconds; F0 is nested and must not be added again:

| Scenario / characters | Preprocess | Tokenization | Speech-token generation | Flow | Vocoder | Nested F0 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Voice alone / 16 | .00011 | .00076 | 2.880 | .652 | .321 | .007 |
| Voice alone / 52 | .00012 | .00091 | 9.628 | 1.939 | 1.309 | .015 |
| Voice alone / 109 | .00014 | .00162 | 20.125 | 4.325 | 2.779 | .031 |
| FP32 resident / 16 | .00013 | .00095 | 14.629 | 4.844 | .545 | .010 |
| FP32 resident / 52 | .00014 | .00109 | 51.764 | 17.058 | 1.486 | .026 |
| FP32 resident / 109 | .00019 | .00172 | 100.418 | 27.302 | 3.022 | .035 |
| Strict half resident / 16 | .00013 | .00085 | 5.006 | .659 | .331 | .008 |
| Strict half resident / 52 | .00010 | .00096 | 14.923 | 1.817 | .438 | .015 |
| Strict half resident / 109 | .00019 | .00141 | 31.291 | 4.056 | .860 | .032 |

Audio write in the strict profiled run is .0019 / .0034 / .0063 s. These stage
medians need not sum exactly to a separately computed total median; model
iteration includes control/thread work, and profiling changes synchronization.
The separate uninstrumented gate above is therefore authoritative for speed.

The bottleneck is autoregressive speech-token generation, then flow, not text
normalization, WAV writes or the nested FP64 F0 predictor. Source sampling in
`cosyvoice/utils/common.py` uses GPU scalar conditionals/items and constructs
CPU sampling results that are copied back to GPU. Explicit short non-stream
counters measured 213–243 Tensor.item reads, 1514–1591 Tensor.__bool__ reads,
2 Tensor.__int__ reads, 378–414 explicit CPU→GPU Tensor transitions and one
GPU→CPU final chunk per request. This confirms frequent host-visible operations,
but not their exact elapsed time, byte volume, PCIe bandwidth, or every hidden
driver synchronization. No GPU timeline was collected; driver stall and kernel
serialization remain unproven explanations, not established root causes.

### LLM impact and recovery

Primary strict run, tok/s and first-content ms (min / median / max):

| State | LLM tok/s | First content ms |
| --- | --- | --- |
| LLM only | 71.879 / 71.998 / 72.010 | 31 / 47 / 62 |
| Both models READY, Voice idle | 70.572 / 71.926 / 72.067 | 31 / 46 / 46 |
| Next request after TTS, nine samples | 72.249 / 72.620 / 73.205 | 46 / 47 / 63 |

There is no LLM token-rate measurement *during* strict TTS: intentionally no
LLM generation is running. Calling this 0 tok/s or a slowdown would be wrong.
Both-resident idle and next-request throughput do not regress by 15%.

In the final concurrent comparison, LLM-only is 71.760 / 72.151 / 72.208 tok/s;
simultaneous Chat+TTS is 39.839 / 42.048 / 42.393 (median about 42% lower), with
first content 93 / 172 / 187 ms versus baseline 47 / 47 / 47 ms. Timestamp
overlaps are 8061 / 8862 / 8943 ms: these requests really overlap, not merely
coexist. Subsequent recovery (concurrent and internal-stream groups) is
72.170 / 72.605 / 73.548 tok/s, first content 78 / 78 / 109 ms. After exiting
Voice, the next Chat is 72.663 tok/s and 78 ms. The old 7–9 tok/s collapse is
not reproduced by these half-storage samples and must not be substituted for
them. Recovery passes; short voice speed still fails.

### Resources, stability and residency

Sampled strict half run (`run-emeYQ7`), nine warm synthesis observations:

| Metric | min / median / max |
| --- | --- |
| Voice working set | 4.376 / 4.380 / 4.392 GiB |
| Voice peak working set | 6.938 / 6.938 / 6.938 GiB |
| Voice Windows dedicated GPU residency | 3.180 / 3.333 / 3.385 GiB |
| Voice Windows shared GPU residency | .549 / .608 / .754 GiB |
| Voice CPU, one-core-relative | 124.696 / 129.356 / 134.786% |
| Voice sum of GPU-engine percentages | 110.739 / 125.071 / 129.998% |
| LLM working set | 2.928 / 3.227 / 3.426 GiB |
| LLM dedicated GPU residency | 2.809 / 2.809 / 2.809 GiB |
| Visible Cubism sampled FPS | 57.787 / 57.889 / 58.084 |

The CPU median is about 4.04% of 32 logical-processor capacity, not 129% of
the entire machine. GPU-engine sums above 100% are possible and are NOT the
whole-GPU busy percentage. No synthesis resource polling was enabled in the
primary uninstrumented timing run. Torch peak allocated memory falls from
about 3.65 GiB in the FP32 resident run to 2.099 GiB in the strict half run;
this does not account for all Windows driver allocations. Total-system RAM/
physical-VRAM peak and PCIe transfer rate were not precisely traced.

No OOM, device-loss/driver-reset exception, Desktop protocol failure or severe
Live2D frame collapse was observed. Same-day System log query returned no
Display 4101 reset events; that is not proof that no unlogged stall occurred.
UI remained responsive to settings/new conversation/snapshots and clean exit;
no human full-desktop performance acceptance is claimed.

Residency choices:

1. **LLM + Voice resident:** technically succeeds; next LLM stays fast, but
   current Voice misses the gate. Each matrix retains one Voice PID and loaded
   4B model, without per-sentence reloads.
2. **LLM resident + lazy Voice:** cold creation while the LLM stays READY works
   experimentally. Approximately 17 s READY plus 17–18 s first synthesis is
   unacceptable for quick first speech. This is startup timing, not proof of
   an implemented production lazy lifecycle. Keeping it warm later still fails.
3. **Strict serial:** removes background title inference in the benchmark and
   recovers LLM throughput, but cannot bring short warm RTF below 1.5.
4. **Pause/reduce other GPU work:** hiding Live2D does not provide a repeatable
   benefit; background title exclusion is not sufficient. The 4B is never
   unloaded per sentence. CPU-only repeats were deliberately skipped: the prior
   measured RTF 31.45 is a known negative control, not a new result this stage.

### Actual Chat terminal → TTS → existing Rust Audio

Final `run-4Obnaa`: three actual completed assistant replies are independently
matched to the handoff request; synthesized WAV SHA256 is checked before it is
fed to unchanged VoiceExecution/private IPC/Rust Audio. Foreground Chat has
ended before each synthesis; production background title behavior is retained.

| Repeat | Actual assistant characters | Synthesis s / decoded audio s / RTF | Observed Rust speaking interval s | Peak Cubism mouth / final mouth |
| ---: | ---: | --- | ---: | --- |
| 1 | 25 | 9.378 / 4.840 / 1.938 | 4.946 | .999 / 0 |
| 2 | 16 | 7.182 / 3.920 / 1.832 | 4.023 | .998 / 0 |
| 3 | 25 | 10.104 / 5.240 / 1.928 | 5.339 | .992 / 0 |

Observed playback start is 62–65 ms after synthesis/handoff completion;
speaking intervals agree with WAV duration within roughly 0.11 s polling
overhead. All three finish idle without playback errors. Voice PID **11272**
is unchanged for cold, concurrent, internal-stream and actual-playback requests.
Audio reaches the existing local output stream and drives amplitude lip sync.
This proves the requested production execution semantics with benchmark input
DI, not automatic Local provider startup/integration. No full delivery/underrun
instrumentation or manual listening was performed: acoustic dropout/quality
acceptance is **NOT MANUALLY VERIFIED**.

76 stage WAVs were reopened and fully read: nonempty RIFF/WAVE, format 1,
PCM16, 24 kHz, mono; frame payload and RIFF sizes match. Probe checks finite
float output before writing. The three playback WAV hashes match their receipts.
No audio/log/cache/disposable conversation enters Git.

### Supervisor feasibility (design assessment only)

This Python runtime can be spawned headlessly and kept warm, with one owned
process per runtime. A future wrapper would need model/prompt/warmup readiness,
explicit health, dynamic loopback-only binding, serialized inference and an
explicit shutdown protocol. Existing Windows child exit/Job ownership could
bound failures and restart; no such wrapper/Supervisor is implemented here.
The sample FastAPI server is not an approved drop-in. Cooperative cancellation
of an in-flight GPU inference has not been established; process termination
would be the last-resort boundary and reload is expensive. The installed
Windows HIP/Torch environment and frontend dependency compatibility add
maintenance risk. Performance failure is sufficient to stop current integration
without pretending these lifecycle requirements were already solved.

Native CPU sherpa-onnx candidates have simpler potential deployment/resource
boundaries, but still require a future validated loopback/ready/cancel contract,
dependency license inventory and real local speed/audio tests. Candidates are
not accepted routes until those gates pass.

### Reproduction without production changes

Use the existing Release and existing installed assets; do not build/download
models to reproduce this report. Example PowerShell from
`prototype/aurora-v4/desktop` (machine-specific paths are explicit experiment
configuration, never production defaults):

```powershell
$env:NODE_PATH = 'C:\Users\X\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
$env:AURORA_LIVE2D_CONFIG = (Resolve-Path '../runtime-local/live2d/config.json').Path
$env:AURORA_PROBE_PYTHON = 'C:\Users\X\anaconda3\envs\cosyvoice-amd\python.exe'
$env:AURORA_PROBE_SOURCE = 'C:\Users\X\CosyVoice'
$env:AURORA_PROBE_MODEL = 'C:\Users\X\CosyVoice\pretrained_models\Fun-CosyVoice3-0.5B'
$env:AURORA_PROBE_PROMPT = 'C:\Users\X\CosyVoice\asset\zero_shot_prompt.wav'
$env:AURORA_BENCH_VARIANT = 'half'
$env:AURORA_BENCH_SCHEDULE = 'serial'
$env:AURORA_BENCH_STRICT = 'true'
$env:AURORA_BENCH_PROFILE = 'false'
$env:AURORA_BENCH_SAMPLE = 'false'
# Use a fresh shell, or clear previous optional flags before comparing.
Remove-Item Env:AURORA_BENCH_PLAYBACK, Env:AURORA_BENCH_PLAYBACK_ONLY,
  Env:AURORA_BENCH_STREAM, Env:AURORA_BENCH_EXTRA_STREAM,
  Env:AURORA_BENCH_SHORT, Env:AURORA_BENCH_THREADS,
  Env:AURORA_BENCH_HOST_SYNC, Env:AURORA_BENCH_HIDDEN,
  Env:AURORA_BENCH_LLM_HIDDEN -ErrorAction SilentlyContinue
node tests/local_voice_performance.mjs
```

For the final concurrent/internal-stream/production-playback comparison, set
STRICT=false, SCHEDULE=concurrent, SHORT=true, HOST_SYNC=true, PLAYBACK=true,
EXTRA_STREAM=true, leaving PROFILE=false and SAMPLE=false. Strict and playback
cannot be combined: controlled isolation must not impersonate production.
Output is a new ignored run directory printed by the harness. Never execute
the external checkout's pre-existing scripts that overwrite their old outputs.
Run reports/logs are local machine evidence, not committed test fixtures.

### Closure and required 55-item report

| # | Required field | Final result |
| ---: | --- | --- |
| 1 | Branch | refactor/aurora-v4 |
| 2 | HEAD | dd1ceb24b59d2ad26a934055c7d6554528828bbb |
| 3 | Working tree | No tracked changes; 7 untracked text/source audit/probe files. Not globally clean. |
| 4 | Untracked handling | Retained original 3, expanded probe, added benchmark/fixture/tests/report; all remain unstaged/uncommitted. |
| 5 | Python CosyVoice path | C:\Users\X\CosyVoice; interpreter path in runtime audit above |
| 6 | Version | Source 074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc; Python 3.11.16, Torch 2.12.0+rocm10.0.0 |
| 7 | Model path | C:\Users\X\CosyVoice\pretrained_models\Fun-CosyVoice3-0.5B |
| 8 | Composition | PT LLM/flow/HiFT + ONNX tokenizer/speaker assets + Qwen tokenizer; 20 files / 9,747,515,976 bytes; NOT GGUF |
| 9 | Backend | Real AMD ROCm/HIP GPU, CPU ONNX frontend; no NVIDIA execution |
| 10 | Precision | Baseline FP32 weights + FP16 autocast; experiment half LLM/flow, unchanged HiFT FP32/FP64; no model-file change |
| 11 | ROCm / HIP state | Real synthesis verified on RX 7600 XT, HIP 7.15.26333; Torch CUDA version null |
| 12 | GPU / CPU placement | GPU LLM/flow/HiFT; CPU text/control/sampling and ONNX prompt tokenizer; full kernel fallback trace not collected |
| 13 | Stage costs | Tables above: speech-token generation dominates, flow second; preprocessing/writing/F0 not dominant |
| 14 | Cold runtime start | Strict primary imports 7.354 s; repeated half runs 7.222 / 7.354 / 7.462 s |
| 15 | Cold model load | Strict primary 9.099 s + .459 s prompt; READY 16.918 s total |
| 16 | First synthesis | Strict primary 17.113 s; three half starts 17.113 / 17.928 / 18.081 s |
| 17 | Warm synthesis | Strict primary 6.054 / 16.317 / 35.418 s medians for 16 / 52 / 109 characters |
| 18 | Short min / median / max | 6.013 / 6.054 / 6.143 s, RTF 1.544 / 1.616 / 1.669 |
| 19 | Medium min / median / max | 14.935 / 16.317 / 17.052 s, RTF 1.447 / 1.450 / 1.467 |
| 20 | Long min / median / max | 34.522 / 35.418 / 38.709 s, RTF 1.476 / 1.541 / 1.541 |
| 21 | Audio durations | Primary short 3.680–3.920 s, medium 10.320–11.760 s, long 22.400–25.120 s; all PCM16 24k mono |
| 22 | RTF gate | Short all >1.5: FAIL; medium marginal; no current real-time/default-local pass |
| 23 | LLM only tok/s | Primary 71.879 / 71.998 / 72.010 |
| 24 | Resident idle impact | Voice-idle LLM 70.572 / 71.926 / 72.067; no token generation during strict TTS, therefore N/A then |
| 25 | Concurrent tok/s | 39.839 / 42.048 / 42.393 vs matched 71.760 / 72.151 / 72.208 baseline |
| 26 | Next LLM after TTS | Primary nine recoveries 72.249 / 72.620 / 73.205; passes sustained 15% gate |
| 27 | First-token regression | Primary recovery 46 / 47 / 63 ms vs baseline 31 / 47 / 62; no sustained serious regression |
| 28 | RAM | Voice sampled WS 4.376–4.392 GiB, peak WS 6.938 GiB; LLM 2.928–3.426 GiB; not total-system RAM peak |
| 29 | VRAM | Voice sampled dedicated 3.180–3.385 GiB + shared .549–.754; LLM dedicated 2.809 GiB; Torch peak 2.099 GiB; not exact physical peak |
| 30 | CPU | Voice 124.696 / 129.356 / 134.786% of one core; median about 4.04% of logical CPU capacity |
| 31 | GPU | Engine-sum 110.739 / 125.071 / 129.998%; not single whole-GPU utilization; no driver timeline |
| 32 | Live2D FPS | Sampled visible strict run 57.787 / 57.889 / 58.084 |
| 33 | Audio stability | 76 WAV integrity passes; 3 Rust playback completions with mouth reset; audible dropout/listening NOT MANUALLY VERIFIED |
| 34 | OOM | None observed in tested runs |
| 35 | Driver reset | None observed; same-day Display 4101 query empty; unlogged stalls not ruled out |
| 36 | UI stalls | No observed protocol/UI freeze; snapshots/settings/chat/exit continue; not human full-desktop acceptance |
| 37 | Dual residency | Technically possible and recovery normal; current TTS performance unacceptable as default |
| 38 | Serial improvement | Yes vs real overlap; half storage also substantially improves FP32 baseline; strict serial still misses gate |
| 39 | Lazy Voice | Cold load with resident LLM works experimentally, but ~17 s READY plus first-synthesis latency unsuitable; no production lazy supervisor |
| 40 | Can current CosyVoice be rescued? | No acceptable route found through tested precision/thread/serial/visibility/internal-stream options; further deep kernel changes outside scope |
| 41 | cosyvoice.cpp local | NOT AVAILABLE LOCALLY in audited paths; repository fixtures are not binaries |
| 42 | CosyVoice GGUF local | NOT AVAILABLE LOCALLY in audited paths |
| 43 | Alternatives | Prioritize sherpa-onnx + MeloTTS Chinese CPU; Kokoro Chinese secondary; evaluation only, no local pass |
| 44 | Licenses | sherpa runtime Apache-2.0; Melo source/model MIT; Kokoro model Apache-2.0; dependency/bundle notices independently require review |
| 45 | AMD / CPU feasibility | Native Windows CPU ONNX avoids voice GPU contention, no CUDA required; Ryzen performance NOT TESTED |
| 46 | Candidate sizes | Melo ONNX 163 MB + frontend; Kokoro Chinese PT 327 MB, v1.0 ONNX 310 MB + 26 MB voices; v1.1 ONNX bundle size unconfirmed |
| 47 | Supervisor fitness | Headless ownership plausible; ready/health/dynamic loopback/serialized inference/shutdown/crash/Job/restart need future validation; not implemented |
| 48 | Continue LocalCosyVoiceProvider? | NO production implementation now; remains NOT IMPLEMENTED |
| 49 | Continue LocalVoiceSupervisor? | NO current-runtime integration now; remains NOT IMPLEMENTED |
| 50 | Manual listening | NOT MANUALLY VERIFIED |
| 51 | Production code modified? | NO; opt-in benchmark DI and strict scheduling patches exist only in experiment process memory |
| 52 | Commit? | NO, intentionally retain audit/probe work uncommitted |
| 53 | New commit hash | None; HEAD unchanged |
| 54 | Local / Remote | Both dd1ceb24b59d2ad26a934055c7d6554528828bbb; WIP Glass adeee5aa4949a47e62ba9f7a2cb708f50a361970 unchanged |
| 55 | Next recommendation | Separate, explicitly authorized native CPU candidate experiment with licensed/pinned assets and identical gates; keep Edge production meanwhile; do not begin now |

Closure validation this stage:

- New benchmark fixture unit tests plus Voice integration/runtime regression:
  **26 passed, 3 skipped**. The six new fixture cases pass, including extended
  Windows paths, request identity, digest/outside guards and cancellation/deadline.
- compileall: **281 Python files passed** (tracked plus untracked Python probes).
- Both benchmark modules pass `node --check`; probe `--help` passes.
- `git diff --check` and explicit whitespace checks of all seven untracked text
  files pass (ordinary git diff does not include untracked files).
- Final successful runs have remainingOwned=[]; final process inventory finds
  no Desktop, llama-server, Cubism host or benchmark probe/fixture process.
- All 20 model hashes and reference-prompt hash are unchanged; external source
  revision and pre-existing untracked inventory unchanged. No downloaded asset,
  SDK/model binary, audio, secret, runtime archive or user conversation enters Git.
- No full-project high-cost regression/build was rerun; production is unchanged.
  Earlier stage test totals are not presented as fresh results here.

Retained untracked files (7):

```text
prototype/aurora-v4/desktop/tests/local_voice_feasibility.mjs
prototype/aurora-v4/desktop/tests/local_voice_performance.mjs
prototype/aurora-v4/docs/LOCAL_VOICE_RUNTIME_AUDIT.md
prototype/aurora-v4/docs/LOCAL_VOICE_PERFORMANCE_FEASIBILITY.md
scripts/probe_local_cosyvoice.py
scripts/voice_feasibility_sidecar/production_sidecar/server.py
tests/test_voice_feasibility_fixture.py
```

Stage V4-7B.1 — Local Voice Runtime Performance Feasibility: **NOT FEASIBLE**.
Final choice: **C — NOT FEASIBLE — CURRENT COSYVOICE, ALTERNATIVE REQUIRED**.
Stage complete; stop. No Local Voice integration or next-stage work is authorized
by this conclusion. The retired Remote Voice Node is not used or required.

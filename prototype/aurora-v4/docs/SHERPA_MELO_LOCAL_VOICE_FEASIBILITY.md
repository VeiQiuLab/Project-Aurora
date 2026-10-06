# V4-7B.2 — sherpa-onnx + MeloTTS Local Voice Feasibility

Date: 2026-10-06. Production baseline: `refactor/aurora-v4`,
`dd1ceb24b59d2ad26a934055c7d6554528828bbb`.

**Stage result: PASS. Final classification: B — CANDIDATE WITH LIMITATIONS.**

The real Windows CPU route passes the performance and engineering gates with
the 4B Vulkan model resident and Cubism visible. It is suitable for considering
a future fixed-voice offline baseline, NOT a replacement for all CosyVoice
character-voice capabilities. No production integration is implemented here.
Manual listening/Chinese pronunciation quality: **NOT MANUALLY VERIFIED**.

## Scope and evidence boundaries

Production source, routing, defaults, Rust Audio, Cubism, 4B runtime and WIP
Glass are unchanged. The seven earlier untracked files are retained unchanged.
Five new source/audit/test files are untracked, unstaged and uncommitted.
Edge remains the production provider. LocalCosyVoiceProvider and
LocalVoiceSupervisor remain **NOT IMPLEMENTED**. The sold Remote Voice Node is
not contacted or required. Existing CosyVoice assets are neither used nor changed.

The experiment links a tiny native benchmark executable against the official
C API; a Python controller only drives tests, validates WAVs and records results.
No PyTorch/CosyVoice/ROCm/GPU TTS participates. The native executable itself
can generate repeatedly without Python. Its stdin test commands are NOT a
production service/API. No system Python/package installation is required or
performed; existing project Python is used for the experiment only.

The unchanged Release owns its actual 4B/Cubism processes. The prior opt-in
completed-WAV benchmark fixture supplies request-matched real Melo audio through
existing VoiceExecution constructor DI, private IPC, Rust/rodio output and
existing amplitude lip sync. The UI's `fake` provider name labels that fixture,
NOT fake audio or a new registered provider. Disposable settings/history live
under ignored tests/output, not user data.

The controlled coexist matrix suppresses post-turn title generation in that
benchmark process only, so LLM resident idle really means no background title
inference. The separate actual-playback run retains production title behavior.
Chat terminal is observed before synthesis. Poll-observed terminal/audio-ready
times have approximately 25 ms polling granularity, plus ordinary IPC/UI delay;
they are not sample-accurate backend timestamps. Physical listening, semantic
pronunciation/transcript accuracy and acoustic dropout were not manually checked.

## Official assets, version and provenance

External asset root:
`C:\Users\X\.cache\aurora-feasibility\v47b2-sherpa-melo-20261006`.

No asset is placed in the Git tree. Both archives downloaded once successfully
from official GitHub release URLs; no third-party mirror/wheel/install was used.
The GitHub metadata API was rate-limited, so the official release HTML was read
instead; no repeated binary download was needed.

| Asset | Exact bytes | SHA-256 |
| --- | ---: | --- |
| Runtime archive | 20,494,724 | `3e971a04b2e0ba4dfa53d381a006367ce8c9f5f09b4ae00043e9845c2baded22` |
| Model archive | 167,006,755 | `e58351ed7149f290a54534538badd4077cdbe6fddc964b24d0bee870415d1514` |
| model.onnx | 170,429,550 | `bf30582eb1b012250a35b1a4a80e7dfbcf8485e7bb9de0d95efbbeef0e4ad86d` |
| sherpa-onnx-c-api.dll | 4,197,376 | `f86ed1570de14b4750d29fb4f58cfaf5558f734040d73133da79dd6457ed77ff` |
| Built experiment host | 76,288 | `0bb601ab1c4e58838d6de9eda80e89d8da4ffba4eb51791d75a2c997422fb522` |

Sources:

- [Pinned v1.13.8 Release](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v1.13.8),
  [published runtime digest](https://github.com/k2-fsa/sherpa-onnx/releases/expanded_assets/v1.13.8).
- [Windows x64 shared CPU runtime archive](https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.8/sherpa-onnx-v1.13.8-win-x64-shared-MD-Release.tar.bz2).
- [Official converted zh_en model archive](https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2),
  [model documentation](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/vits.html).

The runtime archive hash equals its published SHA-256. The model archive hash
is our recorded local hash of the official download, not an independently
published publisher checksum. Both archives remain available in the external
experiment folder, unchanged. Actual library getters confirm sherpa **1.13.8**,
Git SHA **11afbd00**, build date Thu Sep 10 13:52:45 2026, ORT **1.28.2**.
This is CPU-only Windows x64 shared MD Release, not a GPU distribution.

Complete inventory, size and hashes for every runtime/model/private-bin file are
recorded locally in ignored `tests/output/v47b2-asset-manifest.json`.
Runtime unpacked: 32 files / 59,034,751 bytes. Model unpacked: 20 files /
191,246,256 bytes. The separate native test bin is 21,420,544 bytes, including
copies of the three official DLLs and the experiment executable; not an extra
download. Archives total 187,501,479 bytes; with the separately fetched pinned
runtime LICENSE (11,358 bytes), total downloaded bytes are **187,512,837**.
Object files/build leftovers/audio are separate experiment outputs, not assets
to commit or a measured future production package size.

Exact model file list (relative to vits-melo-tts-zh_en):

| File | Bytes |
| --- | ---: |
| model.onnx | 170429550 |
| model.int8.onnx | 133 |
| lexicon.txt | 6837671 |
| tokens.txt | 655 |
| date.fst | 59154 |
| number.fst | 64482 |
| phone.fst | 88630 |
| new_heteronym.fst | 21974 |
| LICENSE | 1053 |
| README.md | 257 |
| dict/hmm_model.utf8 | 519739 |
| dict/idf.utf8 | 5998717 |
| dict/jieba.dict.utf8 | 5071204 |
| dict/README.md | 683 |
| dict/stop_words.utf8 | 8974 |
| dict/user.dict.utf8 | 49 |
| dict/pos_dict/char_state_tab.utf8 | 327139 |
| dict/pos_dict/prob_emit.utf8 | 1687686 |
| dict/pos_dict/prob_start.utf8 | 4347 |
| dict/pos_dict/prob_trans.utf8 | 124159 |

The 133-byte int8 file is a Git LFS pointer, NOT usable int8 weights. Only the
real model.onnx is used; no quantization or alternate model is tested/downloaded.
Native configuration: provider=cpu, SID=0, speed/length_scale=1, noise_scale=.667,
noise_scale_w=.8, max_num_sentences=2, silence_scale=.2; date.fst then number.fst.
The deprecated vits dict_dir field is unused in this release, as CLI help states.

### Licenses and deployment caution

Runtime source is [Apache-2.0 at the pinned release](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/LICENSE).
The exact file is retained externally as LICENSE-sherpa-onnx-v1.13.8.txt.
Converted model includes an actual MIT LICENSE, copyright MyShell.ai 2024;
[original Chinese model metadata](https://huggingface.co/myshell-ai/MeloTTS-Chinese)
also says MIT. ONNX Runtime has a [MIT license](https://github.com/microsoft/onnxruntime/blob/v1.28.2/LICENSE).

These are component licenses, NOT a completed redistribution approval for all
compiled dependencies. Before shipping, inventory linked frontend/phonemizer/
dictionary/FST dependencies and notices. The upstream
[piper-phonemize build configuration](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/cmake/piper-phonemize.cmake)
can include third-party code in shared builds; unused frontend selection alone
does not prove such code is absent from a prebuilt DLL. This stage neither
packages nor redistributes a production binary, and does not claim blanket
Apache/MIT coverage. Keep this as an explicit future distribution gate.

### Resolved benchmark compatibility issue

An initial host placed outside the DLL directory failed: Windows loaded system
ORT **1.17.1**, which only exposes API versions through 17, while this release
requires API 28. Adding the official lib directory to PATH was not sufficient
because system DLL search precedes PATH. No system DLL was replaced.

The test executable now lives in a private native-bin directory with exact
official sherpa-onnx-c-api.dll, onnxruntime.dll and
onnxruntime_providers_shared.dll. The controller verifies these against the
official release copies before launch; library getters then report ORT 1.28.2.
Record this deployment requirement for any future native service. The initial
failed report is preserved as evidence; all subsequent synthesis matrices pass.
The native host also defines NOMINMAX for Windows headers; no upstream source
or inference library is patched.

## Measurements

Hardware is the prior verified Ryzen 9 7940HX (16 cores/32 logical processors),
RX 7600 XT reporting about 8 GiB, and 31.71 GiB usable RAM. The same fixed texts
are exactly 16 / 52 / 109 characters, including punctuation, and are asserted
against the previous stage in an automated test. Every warm matrix cell has
**five repetitions**, not a best-only sample. Native noise sampling is not
exposed as a seeded option here; decoded durations therefore vary slightly.

All triples below are independent **min / median / max**. RTF is native
synthesis wall time divided by decoded audio duration, not a ratio of medians.
WAV conversion/write and controller validation are separate from native
synthesis. File-ready timing includes the native response/write/Windows counters
but does not include manual listening. Five-sample main timing cells have no
concurrent WMI polling; one separate long request measures diagnostic resources.

### Cold vs warm

| Native process, threads | Spawn → READY | Model load | First synthesis |
| --- | ---: | ---: | ---: |
| Alone, default 1 | 2.352 s | 2.178 s | 1.432 s |
| Alone, low 4 | 2.178 s | 2.115 s | .468 s |
| Alone, physical-core-friendly 16 | 2.282 s | 2.225 s | .300 s |
| Visible coexist, 1 | 2.131 s | 2.062 s | 1.411 s |
| Visible coexist, 4 | 2.070 s | 2.001 s | .446 s |
| Visible coexist, 16 | 2.120 s | 2.054 s | .309 s |

Native process startup excluding model load is roughly .06–.17 s, computed from
spawn→READY minus model-load timing; this includes loader/pipe overhead and is
not a separately instrumented DLL timer. Python argument/DLL preflight is not
part of that native timer. These are fresh-process/model starts, not cleared
OS disk-cache trials. Model stays loaded for each matrix/soak, not per request.
The official standalone CLI also generated a valid WAV, reported first native
synthesis 1.461 s / 2.582 s audio / RTF .566 at its default one thread. Windows
console arguments were detected/converted from GB2312 by the CLI; the native
test pipe sends explicit UTF-8 bytes encoded as hex, avoiding codepage ambiguity.

### Standalone native model

| Threads | Chars | Synthesis seconds | RTF |
| ---: | ---: | --- | --- |
| 1 (official default) | 16 | 1.411 / 1.413 / 1.503 | .500 / .501 / .565 |
| 1 | 52 | 4.440 / 4.478 / 4.661 | .502 / .513 / .527 |
| 1 | 109 | 9.322 / 9.334 / 9.796 | .515 / .515 / .552 |
| 4 | 16 | .455 / .462 / .465 | .162 / .165 / .175 |
| 4 | 52 | 1.415 / 1.485 / 1.510 | .163 / .168 / .171 |
| 4 | 109 | 3.028 / 3.127 / 3.208 | .167 / .173 / .179 |
| 16 | 16 | .289 / .302 / .337 | .106 / .114 / .119 |
| 16 | 52 | 1.025 / 1.032 / 1.107 | .116 / .119 / .125 |
| 16 | 109 | 2.095 / 2.123 / 2.186 | .116 / .118 / .121 |

### 4B resident + visible Live2D + native TTS, strict serial

| Threads | Chars | Synthesis seconds | RTF | Request → complete WAV seconds |
| ---: | ---: | --- | --- | --- |
| 1 | 16 | 1.414 / 1.437 / 1.481 | .501 / .537 / .541 | 1.461 / 1.486 / 1.531 |
| 1 | 52 | 4.389 / 4.501 / 4.587 | .496 / .515 / .529 | 4.434 / 4.546 / 4.646 |
| 1 | 109 | 9.212 / 9.274 / 9.437 | .507 / .515 / .521 | 9.269 / 9.340 / 9.511 |
| 4 | 16 | .727 / .730 / .733 | .259 / .260 / .273 | .785 / .786 / .792 |
| 4 | 52 | 2.291 / 2.303 / 2.316 | .264 / .266 / .270 | 2.358 / 2.368 / 2.384 |
| 4 | 109 | 4.783 / 4.820 / 4.833 | .263 / .267 / .269 | 4.861 / 4.890 / 4.916 |
| 16 | 16 | .308 / .311 / .318 | .109 / .113 / .118 | .370 / .374 / .379 |
| 16 | 52 | .969 / .991 / 1.027 | .109 / .112 / .116 | 1.035 / 1.061 / 1.097 |
| 16 | 109 | 2.085 / 2.111 / 2.139 | .116 / .117 / .118 | 2.172 / 2.196 / 2.229 |

Recommended future default: **4 threads**, not unlimited/automatic scaling.
It already meets ideal short RTF and sub-second warm completion while using
roughly four cores. Sixteen is fastest but consumes roughly half the 32 logical
processor capacity. It showed no severe UI/LLM regression here and can be a
later opt-in latency mode; faster alone is not sufficient reason to default to
16. The release's actual default is 1, not a guessed automatic CPU-count value.
One thread is also feasible if minimizing CPU consumption matters.

At 4 threads, audio duration ranges are 2.660–2.821 s (short), 8.500–8.685 s
(medium), 17.943–18.297 s (long). These differ from CosyVoice's cadence; both
use speed=1 and the same text, not artificially slowed audio to improve RTF.

### 4B resident without Live2D Host

`run-Rc9Eor` disables Live2D through disposable settings and verifies zero
aurora-live2d-host processes; it is not merely an invisible renderer. At 4
threads, five repeats per text:

| Chars | Synthesis seconds | RTF |
| ---: | --- | --- |
| 16 | .446 / .716 / .735 | .158 / .254 / .260 |
| 52 | 2.301 / 2.318 / 2.397 | .262 / .266 / .277 |
| 109 | 4.842 / 4.866 / 4.883 | .265 / .270 / .272 |

A separate warmed hidden-host group in the visible matrix gives short RTF
about .252–.262, similar to visible. Neither hiding nor removing Cubism is
required for the candidate to pass. Short .44 versus .73 s variation exists
after some requests; power/CPU scheduling/cache attribution was not traced.
Do not claim a specific cause or use only its fastest sample.

### LLM recovery and resources

LLM tok/s and first-content milliseconds, min / median / max:

| State | tok/s | First content ms |
| --- | --- | --- |
| Visible LLM-only baseline, 5 | 73.001 / 73.334 / 73.596 | 47 / 47 / 79 |
| After 1-thread TTS, 15 | 71.746 / 73.242 / 74.512 | 46 / 47 / 110 |
| After 4-thread TTS, 15 | 72.996 / 73.490 / 74.161 | 47 / 47 / 78 |
| After 16-thread TTS, 15 | 72.374 / 73.439 / 73.889 | 32 / 47 / 78 |
| No-Live2D baseline, 5 | 72.897 / 73.267 / 73.859 | 32 / 47 / 63 |
| No-Live2D after TTS, 15 | 72.362 / 74.132 / 75.134 | 47 / 62 / 93 |

No sustained >15% token-rate regression or serious first-token regression.
Strict serial intentionally has no LLM token generation during TTS: N/A,
not zero throughput. Actual production title behavior is tested separately.

Visible 4-thread warm process working set is 417,144,832–488,505,344 bytes
(about 398–466 MiB); max peak working set 495,026,176 bytes (~472 MiB), max
private commit 563,462,144 bytes (~537 MiB). These are process counters, not
total-system memory peaks. Working set settles after larger texts/allocator
warmup, rather than being unloaded per sentence.

4-thread native CPU is 382.800 / 390.550 / 397.851% of one core across the
15 visible warm samples, median approximately 12.2% of 32 logical processors.
16-thread samples are about 1535–1605% (roughly 48–50% of logical capacity).
The diagnostic long request independently measures about 385.9% native CPU
while the resident LLM is at 0% CPU; no background title inference in that run.

Native process GPU memory/engine counters have no entries, and provider=cpu
with a CPU-only official ORT library is verified. Do not turn unavailable
per-PID counter fields into an exact whole-GPU utilization measurement. The
4B retains 3,020,083,200 bytes (~2.813 GiB) dedicated GPU residency; Cubism
33,501,184 bytes (~32 MiB). Voice adds no observed GPU allocation/engine
workload. Live2D sampled FPS during visible 4-thread warm requests is
**57.169 / 57.326 / 57.588**; 16-thread groups also remain around 57 FPS.
No OOM, native crash, observed UI freeze or severe frame collapse. Settings,
chat, snapshots, Stop Voice and shutdown remain responsive. Not a human
full-desktop smoothness or acoustic-dropout acceptance.

### Residency/soak and long-text stability

Each standalone thread setting completes 41 requests in one PID: first +
15 warm + 5 coverage + 20 consecutive short requests. All three native hosts
close normally. For four-thread standalone soak, handles stay 141, threads
stay 6, working set stays 518,795,264 bytes. Other settings show bounded
worker housekeeping changes, not monotonically increasing resource counts.
Sixteen-thread standalone soak fluctuates 19–21 threads and 153–154 handles;
20 requests do not prove leak freedom over days.

Visible coexist selected PID **19796** completes first, 15 warm, 20 short
soak, 5 consecutive long requests and one diagnostic request without reloading:

- Short soak: handles 143 throughout; threads 7→6, working set
  488,505,344→488,484,864 bytes, private commit 563,462,144→563,429,376 bytes.
- Long soak: 4.766 / 4.835 / 4.909 s, RTF .263 / .265 / .271. Working set
  488,484,864 and private commit 563,429,376 bytes, 6 threads/143 handles stable.
- No empty/corrupt WAV, crash or continuing memory growth in these runs.

## Rust Audio, existing lip sync and Stop Voice

`run-iyNu0A` uses actual completed assistant text. Five normal replies (16–25
characters) are generated by the real 4B, synthesized by native Melo and sent
to existing Rust Audio via the benchmark bridge. Terminal→complete-audio
latency: **776.760 / 835.287 / 1333.145 ms**. All are below the ideal 2 s;
16-character replies individually take about 817–835 ms. No TTS before the
observed assistant terminal. Foreground Chat/TTS are serial, background title
behavior is retained. No production streaming route is added.

All five normal playback requests complete idle, amplitude reaches Cubism and
mouth returns to 0. Peak mouth opening spans .481–.585; decoded durations agree
with speaking intervals within polling/command overhead. Native WAV is PCM16,
mono **44,100 Hz**; the existing Rust decoder/output chain handles it unchanged.
The native host itself does not open the audio device.

A sixth real 130-character response creates ~22 s audio. Stop Voice is clicked
after actual amplitude begins: idle plus mouth=0 is observed in **48.841 ms**,
far before the remainder could finish playing. The following short recovery
request plays normally and returns mouth=0. This is the existing playback stop
path, NOT implementation/proof of interrupting a native synthesis mid-graph.
All seven playback/stop/recovery requests use the same native engine PID.

228 real stage WAVs, including the official CLI output, pass full frame-read,
RIFF length, nonempty PCM16 mono, sample-rate/duration and non-silence checks.
Native code rejects NaN/Inf before conversion and saturates signed PCM16;
no output has clipping in the reported native samples. SHA receipts identify
exact audio consumed by the bridge. Structural/byte truncation is rejected;
semantic spoken-word coverage, natural ending and audible artifacts still need
manual listening. No audio/cache/log/disposable conversation enters Git.

## Chinese coverage and limitations

Five standalone coverage cases are repeated under each thread setting:

```text
今天的温度是23.5度，一共123个人。
今天是2026年10月6日，下次在2026-10-08见。
你好，hello world，这是一个test。
他说：你好！可以吗？当然可以；我们继续，保持安静。
这里有一个词AuroraNonexistentWordXYZ，随后继续中文。
```

All finish with nonempty finite audio and valid WAV; date/number FSTs are
explicitly enabled. Accurate numeric/date reading and pronunciation are not
manually verified. Logs explicitly warn that full-width **：** and **；** are
out-of-vocabulary and ignored; other tested common punctuation does not fail
generation. This can change pause/prosody, and is not silently declared perfect
punctuation support. No dictionary edits/normalization feature is added.

Official [model documentation](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/vits.html)
limits English coverage to lexicon entries. Successful mixed-input synthesis
does not prove every arbitrary English name is pronounced correctly. The
archive README says a single female speaker for zh_en: no zero-shot cloning,
reference prompt, arbitrary speaker embedding or distinct character voices in
this selected model. Engineering success does not settle perceived quality.

## Future runtime form and cancellation assessment — NOT IMPLEMENTED

Recommended runtime form **A: long-running native local service**, with the
official C API inside its own process and no system Python dependency. Keep
one model loaded and serialize synthesis. A future adapter would supply an
explicit readiness handshake after model load, bounded warmup, health,
dynamic loopback-only binding, request identity/stale discard and shutdown.
The benchmark proves native spawn, resident repeated generation, version/READY
response and clean destruction, not a production HTTP/health API or restart
Supervisor. Existing Rust Job/exit monitoring boundaries are appropriate future
ownership, not implemented/validated for a new LocalVoiceSupervisor here.

**B: Rust FFI in-process** is possible through the C ABI but a native crash
would threaten Desktop; avoid adopting it before isolation/resource contracts.
**C: per-request CLI** works independently, but reload adds about 2 s to each
short request, roughly 3–4 s at the tested settings; residency is preferable.

Cancellation is assessed from the pinned
[VITS implementation](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/sherpa-onnx/csrc/offline-tts-vits-impl.h)
and [C API](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/sherpa-onnx/c-api/c-api.h):

- Progress callbacks can stop between sentence batches. They are not an
  asynchronous cancellation of the active ONNX graph. In a single-batch call,
  the callback happens after Process and its return does not interrupt that work.
- Future cancel should first invalidate ownership/stop playback, then discard
  any late result. A callback flag may bound remaining multi-batch generation,
  but must not convert a cancelled partial waveform into normal successful speech.
- Do not kill a native worker thread. A bounded hung/crashed runtime may require
  terminating the owned process/Job and restarting; reload is about 2 s and the
  model cache is lost. Native ready/health/cancel/restart integration remains
  a future gate. No synthesis cancellation API was added/tested this stage.

## Direct comparison to the measured Python CosyVoice route

| Item | Current Python CosyVoice | Native sherpa-onnx + MeloTTS |
| --- | --- | --- |
| Model size on disk | 20 files, 9,747,515,976 bytes | 20 files, 191,246,256 bytes; main ONNX 170,429,550 |
| Runtime | Existing Python/Torch/HIP environment; full environment size not inventoried | Official native archive 20,494,724 bytes; unpacked 59,034,751, tested private DLL/host bin ~21.4 MB |
| Cold start/READY | ~16.9 s including imports/model/prompt | ~2.07 s native resident start; includes ~2.00 s model load |
| Model load | ~9.10 s plus cached prompt .459 s | ~2.00 s, no prompt embedding |
| 16 chars warm median | 6.054 s / RTF 1.616 | .730 s / RTF .260 (4 threads, visible coexist) |
| 52 chars warm median | 16.317 s / RTF 1.450 | 2.303 s / RTF .266 |
| 109 chars warm median | 35.418 s / RTF 1.541 | 4.820 s / RTF .267 |
| Process RAM | WS ~4.38 GiB, peak WS ~6.94 GiB | Warm WS ~398–466 MiB, peak ~472 MiB; private commit up to ~537 MiB |
| Voice VRAM | Sampled dedicated ~3.18–3.39 GiB plus shared memory | No observed per-PID GPU allocation; CPU-only engine |
| Voice CPU | Median about 129% of one core; GPU does heavy work | Median about 391% of one core at 4 threads, ~12.2% logical capacity |
| Voice GPU | HIP, GPU-engine aggregate around 125% across engines | No GPU EP/use required; counter fields have no native process entries |
| LLM interference | Serial recovery normal, concurrency expensive | Serial recovery normal; GPU residency retained, no severe CPU interference observed |
| Supervisor fitness | Headless possible, expensive load/special HIP environment, failed speed gate | Native headless/ready/cleanup proven experimentally; small future service/ownership contract still needed |
| Voice cloning | Existing prompt-conditioned capability | NO; selected model has one fixed speaker |
| Chinese quality | This stage does not retest its listening quality | Basic offline fixed voice candidate; perceived quality/pronunciation not manually verified |
| Deployment complexity | Python/Torch/HIP/ONNX/frontend compatibility | Native CPU DLLs + model/FST/lexicon; private DLL directory and license inventory mandatory |

These are same-machine/text comparisons, not an identical-voice quality
equivalence. CosyVoice numbers are explicitly prior V4-7B.1 evidence and were
not re-benchmarked or further optimized this stage.

## Reproduction and closure

Sources added this stage only:

```text
scripts/benchmark_sherpa_melo.cpp
scripts/probe_sherpa_melo.py
prototype/aurora-v4/desktop/tests/sherpa_melo_feasibility.mjs
tests/test_sherpa_melo_probe.py
prototype/aurora-v4/docs/SHERPA_MELO_LOCAL_VOICE_FEASIBILITY.md
```

Build the experiment with existing VS2022 x64 tools, `/std:c++17 /O2 /MD
/EHsc /utf-8`, official release include path and sherpa-onnx-c-api.lib/Psapi.lib.
Place the output EXE/OBJ outside Git; co-locate the three official DLLs and
verify their hashes. No upstream build or Aurora Release rebuild is needed.

Standalone from repository root, with explicit caller-selected paths:

```powershell
$taskAssets = 'C:\Users\X\.cache\aurora-feasibility\v47b2-sherpa-melo-20261006'
$taskOutput = 'tests/output/v47b2-repeat-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
& .\.venv\Scripts\python.exe -B scripts/probe_sherpa_melo.py `
  --host "$taskAssets/native-bin/benchmark_sherpa_melo.exe" `
  --runtime "$taskAssets/sherpa-onnx-v1.13.8-win-x64-shared-MD-Release" `
  --model "$taskAssets/vits-melo-tts-zh_en" --output $taskOutput --threads 4
```

For Desktop tests from prototype/aurora-v4/desktop, set AURORA_BENCH_PYTHON,
AURORA_SHERPA_HOST, AURORA_SHERPA_RUNTIME, AURORA_MELO_MODEL and
AURORA_LIVE2D_CONFIG to the explicit existing assets, and NODE_PATH to the
installed Playwright dependency directory. Run
`node tests/sherpa_melo_feasibility.mjs`, mode matrix/playback/resident-only via
AURORA_MELO_MODE. Playback defaults to four threads. Do not overlap these runs
or terminate existing user runtimes: the harness refuses if they are present.
All output paths are new ignored directories. No production default path is
hard-coded by these developer-specific audit examples.

Evidence directories:

- tests/output/v47b2-standalone-v2-threads-1, -4, -16: successful independent
  matrices/coverage/20-short soaks, 41 invocations per PID.
- tests/output/v47b2-coexist/run-BD5oiy: visible strict matrix/soak/hidden,
  80 requests, passed.
- tests/output/v47b2-coexist/run-iyNu0A: real terminal→native TTS→Rust Audio,
  stop/recovery, passed; 8 requests including warmup, 7 playback cases.
- tests/output/v47b2-coexist/run-Rc9Eor: 4B resident with no Live2D Host,
  16 requests, passed.
- tests/output/v47b2-standalone-threads-1: initial failed DLL-loader attempt,
  preserved, zero generated requests. Not counted as a success.
- tests/output/v47b2-asset-manifest.json: complete file/size/hash inventory.

Automated closure: **34 passed, 3 skipped**, including 8 new WAV/text tests and
6 existing fixture guards, plus Voice runtime/integration regression. Native
experiment MSVC compile passed; **compileall 283 Python files passed**; Node
syntax/probe help passed; 228 actual WAV integrity/non-silence validations pass.
No full 1000+ test/build suite rerun is claimed: production source was not changed.
All final reports have remainingOwned=[]; native engines report normal exit;
final process inventory has no benchmark host/controller, Desktop, llama-server
or Cubism leftovers. git diff --check plus all-untracked whitespace checks pass.

## Required final 68-item report

| # | Field | Result |
| ---: | --- | --- |
| 1 | Branch | refactor/aurora-v4 |
| 2 | HEAD | dd1ceb24b59d2ad26a934055c7d6554528828bbb |
| 3 | Working tree | No tracked/staged changes; 12 untracked source/audit/test files; not globally clean |
| 4 | Previous seven | Preserved unchanged; no deletion/commit |
| 5 | New files | Five listed above; only benchmark controller/native host/harness/tests/report |
| 6 | sherpa version | 1.13.8, library Git SHA 11afbd00, ORT 1.28.2 |
| 7 | Download source | Official k2-fsa/sherpa-onnx v1.13.8 Windows CPU shared MD Release |
| 8 | Runtime hash | Archive 3e971a04b2e0ba4dfa53d381a006367ce8c9f5f09b4ae00043e9845c2baded22, published digest matched |
| 9 | Runtime license | sherpa Apache-2.0; ORT MIT; full prebuilt dependency redistribution inventory still needed |
| 10 | Melo model | vits-melo-tts-zh_en, one Chinese/English female speaker |
| 11 | Model source | Official tts-models release archive URL above |
| 12 | model.onnx bytes | 170429550 |
| 13 | Model hash | bf30582eb1b012250a35b1a4a80e7dfbcf8485e7bb9de0d95efbbeef0e4ad86d |
| 14 | Model license | Actual included MIT LICENSE, MyShell.ai 2024 |
| 15 | Total assets | Downloaded 187512837 bytes including separate LICENSE; unpacked runtime 59034751 + model 191246256; test-bin duplicate DLL bytes separately inventoried |
| 16 | Windows CPU runtime | PASS; native C API, provider=cpu, private official DLL directory; no Python inference/GPU TTS |
| 17 | Cold native startup | Visible four-thread spawn→READY 2.070 s; loader/pipe portion roughly .069 s excluding model load, not a separately timed DLL-only result |
| 18 | Model load | Visible four-thread 2.001 s; fresh process, OS file cache not cleared |
| 19 | First synthesis | Visible four-thread .446 s; separate from loading and warm matrix |
| 20 | 16-char warm min/median/max | .727 / .730 / .733 s, five visible four-thread samples |
| 21 | 16-char RTF | .259 / .260 / .273, IDEAL |
| 22 | 52-char warm min/median/max | 2.291 / 2.303 / 2.316 s |
| 23 | 52-char RTF | .264 / .266 / .270 |
| 24 | 109-char warm min/median/max | 4.783 / 4.820 / 4.833 s |
| 25 | 109-char RTF | .263 / .267 / .269 |
| 26 | Terminal→audio ready | Actual five normal replies 776.760 / 835.287 / 1333.145 ms, 16–25 characters; observed/poll-based |
| 27 | Sample rate | 44100 Hz |
| 28 | Channels | Mono |
| 29 | WAV integrity | 228 actual outputs fully validated, PCM16/RIFF/payload/non-silence |
| 30 | Numbers | Successful nonempty audio with number.fst; exact spoken reading NOT MANUALLY VERIFIED |
| 31 | Dates | Successful Chinese/ISO date input with date.fst; exact spoken reading NOT MANUALLY VERIFIED |
| 32 | Chinese/English | Mixed case generates valid audio; English lexicon limitation remains, arbitrary-word correctness not proven |
| 33 | Punctuation | Tested generation succeeds; full-width colon/semicolon log OOV and are ignored; prosody limitation |
| 34 | RAM | Visible four-thread WS ~398–466 MiB, peak ~472 MiB, private commit max ~537 MiB |
| 35 | CPU | Four-thread warm median 390.550% of one core, about 12.2% of 32 logical processors |
| 36 | GPU | No GPU EP/use required; no native per-PID GPU-engine counter entry; not an exact total-system GPU busy measurement |
| 37 | VRAM | No observed native allocation; resident 4B ~2.813 GiB, Cubism ~32 MiB dedicated counters |
| 38 | Live2D FPS | Visible four-thread 57.169 / 57.326 / 57.588 sampled |
| 39 | LLM baseline tok/s | 73.001 / 73.334 / 73.596, five samples |
| 40 | LLM after TTS tok/s | Four-thread 72.996 / 73.490 / 74.161, fifteen samples |
| 41 | LLM first token | Baseline 47 / 47 / 79 ms; after four-thread 47 / 47 / 78 |
| 42 | LLM impact | No sustained >15% regression in strict serial; actual background title behavior retained in playback test |
| 43 | Threads | Recommend 4 for balanced future default; 1 default and 16 physical-core setting also pass |
| 44 | 20-short soak | PASS alone for each setting and visible selected-four-thread process |
| 45 | Thread growth | Selected coexist 7→6, no monotonic growth; 16-thread standalone bounded 19–21 variation |
| 46 | Handle growth | Selected coexist 143 stable; standalone 4-thread 141 stable |
| 47 | RAM growth | Selected coexist 488505344→488484864 WS, private commit also slightly decreases; five subsequent long requests stable; not long-term leak proof |
| 48 | Rust Audio playback | Five normal actual output-stream completions plus stop/recovery; benchmark DI only, production decoder unchanged |
| 49 | Lip sync change | Existing amplitude chain produces mouth peaks .481–.585 in normal cases |
| 50 | Stop Voice | Existing button stops active ~22-second WAV in ~48.841 ms to idle plus mouth=0 |
| 51 | Mouth reset | All natural completion, stop and following recovery reset to 0 |
| 52 | Supervisor suitability | Native spawn/READY/residency/destruction proven; future health/ownership/Job/restart contract required, NOT implemented |
| 53 | Runtime form | Recommend A: long-running native separate-process service using C API, not a Python-dependent production runtime |
| 54 | Cancellation feasibility | Callback between batches only; no current ONNX graph interrupt proven; future invalidate/stale discard + optional batch stop + owned-process watchdog; no implementation |
| 55 | Headless | PASS; native executable has no GUI/network/audio device; test controller launches hidden |
| 56 | Single speaker | YES, fixed female Chinese+English voice |
| 57 | Voice clone | NO for this selected model |
| 58 | CosyVoice comparison | Visible median short RTF 1.616→.260; medium 1.450→.266; long 1.541→.267; much less RAM/no voice VRAM, loses cloning |
| 59 | Production modified | NO; prior opt-in test DI is reused unchanged; isolated test settings only |
| 60 | Tests | 34 passed, 3 skipped; native repeated invocation/soak/playback/stop/cleanup pass; 228 valid WAVs |
| 61 | compileall | 283 Python files PASS; Node syntax/CLI help and native benchmark compile PASS |
| 62 | Cleanup | All reports remainingOwned=[]; native_exited true; final matching process inventory empty |
| 63 | Commit | NO; no asset/binary/WAV/log/cache committed |
| 64 | Local / Remote | Both dd1ceb24b59d2ad26a934055c7d6554528828bbb; WIP Glass adeee5aa4949a47e62ba9f7a2cb708f50a361970 unchanged |
| 65 | Manual listening | NOT MANUALLY VERIFIED |
| 66 | Final classification | B — CANDIDATE WITH LIMITATIONS |
| 67 | Consider next integration? | YES, as fixed-voice offline baseline after agreeing to limitations and required lifecycle/license gates; not full character/cloning replacement |
| 68 | Next step | Separately authorize native local service/Provider/Supervisor integration with immutable asset inventory, private DLL resolution, ownership/cancel/error isolation and existing Rust Audio; do not start now |

Stage V4-7B.2 — sherpa-onnx + MeloTTS Local Voice Feasibility: **PASS**.
Final classification: **B — CANDIDATE WITH LIMITATIONS**.
This stage is complete. Stop; no production integration or next-stage work.

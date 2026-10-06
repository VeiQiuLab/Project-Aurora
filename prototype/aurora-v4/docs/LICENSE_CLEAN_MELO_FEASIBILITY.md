# V4-7B.3A — License-Clean Sherpa/Melo Runtime Feasibility

2026-10-06. Engineering feasibility: **PASS — B, LICENSE-CLEAN + FUNCTIONAL
LIMITATIONS**. No production integration, commit, push, packaging, new model,
or default/provider/supervisor change. Manual listening: **NOT MANUALLY VERIFIED**.
This is a technical dependency/license inventory, not legal clearance.

The important correction is that **Melo zh_en already uses MeloTtsLexicon**.
Removing the generic eSpeak/Piper build dependencies does not require replacing
its phonemizer. A small, source-allowlisted native target preserves the actual
Melo frontend, inference and normalization. Nine real reference ONNX input
captures match the clean runtime exactly. This is not a 20-sentence fake lexicon.

## Gate 0 — untouched baseline and original inventory

Repository: `C:/Users/X/Documents/ChatGPT/本地AI再创/Project-Aurora-baseline-20260902-010344`.
Branch `refactor/aurora-v4`; HEAD and live origin head
`dd1ceb24b59d2ad26a934055c7d6554528828bbb`.
WIP Glass remains `adeee5aa4949a47e62ba9f7a2cb708f50a361970`, not checked out or merged.
Tracked/staged modifications: zero. Original 13 untracked files preserved.
Ten new experimental source/test/doc files make 23 untracked files in total.
Working tree is **not globally clean**, intentionally; nothing is staged.

| Original path | Purpose / continuing use | SHA-256, entry and exit unchanged |
| --- | --- | --- |
| prototype/aurora-v4/desktop/tests/local_voice_feasibility.mjs | Prior CosyVoice coexist evidence; preserve, not executed | f32b2525f86be719787678c6d5103829006bcc047ec95315dd7c4f6842ab4878 |
| prototype/aurora-v4/desktop/tests/local_voice_performance.mjs | Prior performance fixture; preserve, not executed | ed7509648870a34400198af0ade03432827ecce935fdfe97e91e06cb46710e8f |
| prototype/aurora-v4/desktop/tests/sherpa_melo_feasibility.mjs | Reused in memory for unchanged Release/Rust Audio/Live2D injection | 898b90e8d31b0c0f6628535c1353a948d0543640545bc63d2e68f2b1ceca228e |
| prototype/aurora-v4/docs/LOCAL_VOICE_LICENSE_CLOSURE.md | Prior GPL evidence, read-only | a7df95bc327206291ce0b7e4f5885dbbff0908182cf4443b85cb76ebc2a5e7d3 |
| prototype/aurora-v4/docs/LOCAL_VOICE_PERFORMANCE_FEASIBILITY.md | Prior audit; retained as historical evidence | b27261118ad926e25b558388a83e30337df808d1e6a92996de47c037b1d61e18 |
| prototype/aurora-v4/docs/LOCAL_VOICE_RUNTIME_AUDIT.md | Historical runtime boundary audit | f66956bf6e73aa61b01cec37131a123211d17a2386f8c78af633e59b34de712e |
| prototype/aurora-v4/docs/SHERPA_MELO_LOCAL_VOICE_FEASIBILITY.md | Prior native benchmark baseline and recipe | d324d61fc8a0075d25e24a1dc702c894da12390c189c41bd3e38633b1207d444 |
| scripts/benchmark_sherpa_melo.cpp | Native host main, compiled unchanged against clean subset ABI | de89f308b2d6ec9c17d6489c4d6237088bca26557ffdc46ce2fd3c632ec135a1 |
| scripts/probe_local_cosyvoice.py | Prior CosyVoice probe, not executed | 22be9e34c772c7594f71cf323d5ec325022354584e7c35cf9d7c025f4d1c3ee4 |
| scripts/probe_sherpa_melo.py | Reused unchanged CPU benchmark controller/WAV verifier | f7f6f56e2e1baa63cf8aedcd9347cd63345eb8b65ea2e1e16b6aa406b5280382 |
| scripts/voice_feasibility_sidecar/production_sidecar/server.py | Existing opt-in benchmark injection, never installed production | 15b42220f6ea9b55f9ca461db22c2b4ff3e7900247ad05f6986fc5e72f6c3009 |
| tests/test_sherpa_melo_probe.py | Existing probe regression, rerun unchanged | 5f51ec063ff70f2a309d84ffe3ce3b0aa180275819b2aac1233a79e5244fc856 |
| tests/test_voice_feasibility_fixture.py | Existing injection/isolation regression, rerun unchanged | ebe66f77f4c2cb5a586f6620f2862eef0d96f1719598157aebef6fdd1f9af22e |

New files only:

- scripts/sherpa_melo_clean/CMakeLists.txt — minimal external-source build recipe.
- scripts/sherpa_melo_clean/clean_c_api.cpp — experimental eight-function ABI subset.
- scripts/sherpa_melo_clean/cpu_session.cpp — CPU-only session options adapter.
- scripts/sherpa_melo_clean/oracle_trace.cpp — isolated-process real OrtApi::Run capture.
- scripts/probe_clean_melo.py — fixed corpus, actual tensor and WAV comparisons.
- scripts/audit_clean_melo.py — read-only imports/exports/strings/dependency/source inventory.
- scripts/probe_permissive_phonemizer.py — separately unpacked MIT pypinyin evaluation.
- prototype/aurora-v4/desktop/tests/clean_melo_feasibility.mjs — unchanged old fixture reused in memory, four threads, new output root.
- tests/test_clean_melo_feasibility.py — evidence tooling and scope regression.
- prototype/aurora-v4/docs/LICENSE_CLEAN_MELO_FEASIBILITY.md — this independent report.

## Old and clean dependency graphs

Old official v1.13.8 DLL (4,197,376 bytes,
`f86ed1570de14b4750d29fb4f58cfaf5558f734040d73133da79dd6457ed77ff`):

```text
TTS-on root CMake -> sherpa-onnx-core -> piper_phonemize (static)
                                        -> eSpeak NG (static) + ucd
                       -> sherpa-onnx-c-api.dll
Melo dispatch -> MeloTtsLexicon -> tokens + complete lexicon -> VITS ONNX
```

Actual DLL exports include espeak_Initialize / espeak_Cancel / espeak_Synth /
espeak_Terminate, espeak_ng_* and piper::phonemize_eSpeak. Imports/dependents
contain no separate eSpeak DLL. These are executable symbols plus corroborating
static CMake targets, not mere documentation strings. Pins: eSpeak
`ed530aa113046142eb5115cf2fc9157854d0ffe1`, piper
`f3ff95afc03640bc1399e113e83361192a2fafb4`. The reference is an **oracle only**.

Clean candidate:

```text
benchmark_sherpa_melo.exe -> eight-function experimental C ABI DLL
  -> untouched MeloTtsLexicon + PhraseMatcher + symbol/text/file utilities
  -> kaldifst TextNormalizer + OpenFst core (static, date then number rules)
  -> untouched OfflineTtsVitsModel -> onnxruntime.dll CPU EP -> existing model
  -> upstream per-batch ScaleSilence -> existing benchmark PCM16 writer
```

Never configure sherpa root or kaldi-decoder. No eSpeak/Piper sources, ASR,
VAD, diarization, KWS, LLM, sentencepiece, fbank, Torch, Python phonemizer or
audio device library in the candidate DLL. Header-only declarations of other
models do not instantiate their implementations. Generic metadata parsing has
one literal `piper` used to recognize model metadata; it remains in the unchanged
VITS model TU. This is **not piper-phonemize code**. No espeak_* / espeak_ng_* /
phonemize_eSpeak exports, imports, dependency DLLs or strings remain.

All four non-system PE artifacts are scanned recursively: host, minimal API,
ORT and providers-shared. Windows/VC CRT/API sets are explicitly listed as OS
leaf dependencies, not claimed as bundled permissive open-source libraries.
All raw imports/exports/strings and the vcxproj compile-source allowlist are in
`tests/output/v47b3a-binary-audit-final/report.json`.

## Sources, hashes and reproducible build

All sources, headers, third-party files, archives, object trees and binaries:
`C:/Users/X/.cache/aurora-feasibility/v47b3a-clean-sherpa-20261006`.
Existing model/reference assets are read-only under
`C:/Users/X/.cache/aurora-feasibility/v47b2-sherpa-melo-20261006`.

| Download | Version / official source | SHA-256 |
| --- | --- | --- |
| sherpa-v1.13.8.tar.gz, 11,642,707 bytes | [tag source](https://github.com/k2-fsa/sherpa-onnx/tree/v1.13.8), commit 11afbd009a7f8c08f4bcf2fc1b265d0df4670fbf | b0374cc56dbc186d442ae73d5de743bb092470b640c4c50ce7b029044c0c4fa8 |
| kaldifst-v1.8.0.tar.gz, 172,147 bytes | [official v1.8.0](https://github.com/k2-fsa/kaldifst/tree/v1.8.0) | 3f247b7e5a2409071202f5e2bc6200060f66728c0a3443c03923ad2723e040b3 |
| openfst-v1.8.5-2026-07-09.tar.gz, 1,501,685 bytes | [Windows-capable source used by upstream](https://github.com/csukuangfj/openfst/tree/v1.8.5-2026-07-09) | 2ff712a32952fcb01d351121a6bc8ccf4fdc6b2aa06ce8df2b3095dedd518c0e |
| kaldi-decoder-v0.3.0.tar.gz, 51,199 bytes | [official v0.3.0](https://github.com/k2-fsa/kaldi-decoder/tree/v0.3.0); inspected for dependency pin only, NOT compiled/linked | b9f34cfb4fd3b1344100eead79ef4d37aa15962274b9e3056de345021f76a1b0 |
| pypinyin wheel, 840 KB | [PyPI 0.55.0](https://pypi.org/project/pypinyin/0.55.0/), separately unpacked, not installed into project | d53b1e8ad2cdb815fb2cb604ed3123372f5a28c6f447571244aca36fc62a286f |
| ORT headers / LICENSE / ThirdPartyNotices | [ORT v1.28.2 source](https://github.com/microsoft/onnxruntime/tree/v1.28.2); notices hash at right | 0e07b95f3a8d6230037707c5c4a2b554d12c4cb67369669ac255635528ffcee2 |

The full sherpa archive contains unrelated Android/WASM/example symlinks that
Windows tar declined to create. Required real source/header/license files were
extracted and compiled; no fabricated replacement files or changes to upstream
inference were used. This is not a failed core build. ORT six required headers
come from the same v1.28.2 source. Existing official ORT DLL remains hash-identical:
`422d776ab0e3218260f7f628fcb84606aaa5c21116f720c8619a6da5e0b2e0f9`.

Build: MSVC 19.44.35228, Visual Studio 17 2022 x64 generator, CMake 4.4.3,
C++17, Release /MD, /utf-8, /Gy, /OPT:REF, /OPT:ICF. OpenFst static, no tools,
tests, scripting, extra FST extensions or Abseil. Kaldifst text-normalizer TU
uses its upstream Windows /Od /Ob0 workaround; inference remains optimized.

The eight ABI exports are CreateOfflineTts, DestroyOfflineTts,
DestroyOfflineTtsGeneratedAudio, GetGitSha1, GetOnnxruntimeVersionStr,
GetVersionStr, OfflineTtsGenerateWithConfig, OfflineTtsSampleRate (SherpaOnnx
prefix). Other C API functions are **not supported**. Version reports
`1.13.8-clean-melo-experiment`; it is not advertised as a replacement release.

```powershell
# Explicit external directories supplied by the developer; no production paths.
cmake -S scripts/sherpa_melo_clean -B $Build -G 'Visual Studio 17 2022' -A x64 `
  "-DSHERPA_SOURCE=$SherpaSource" "-DKALDIFST_SOURCE=$KaldifstSource" `
  "-DOPENFST_SOURCE=$OpenFstSource" "-DORT_HEADERS=$OrtHeaders" `
  "-DREFERENCE_RUNTIME=$ReferenceRuntime"
cmake --build $Build --config Release --target benchmark_sherpa_melo --parallel 4
# Separate oracle targets, never dependencies of the clean performance target.
cmake --build $Build --config Release --target reference_oracle clean_oracle --parallel 4
```

Build log: external `clean-build-final.log` is a from-clean successful build.
It contains only allowlisted compile units and no GPL source/target. Compiler
warnings (upstream conversions, allocator deprecation, existing NOMINMAX define)
are recorded; no errors. Final sizes: API DLL **878,592 bytes**, host **76,800**,
ORT **17,136,128**, providers-shared **10,752**. Co-located official ORT avoids
the known system ORT 1.17.1 DLL shadowing; no system file is replaced.

## Real model contract and Golden Corpus

Existing `vits-melo-tts-zh_en/model.onnx`, 170,429,550 bytes:
`bf30582eb1b012250a35b1a4a80e7dfbcf8485e7bb9de0d95efbbeef0e4ad86d`.
Metadata: melo-vits version 2, Chinese + English, add_blank=1, n_speakers=1,
sample_rate=44100, speaker_id=1, lang_id=3, tone_start=0, bert_dim=1024,
ja_bert_dim=768, MIT. Request sid=0 is mapped by the model runner to actual sid=1.

| Actual ONNX input | Type / shape | Meaning |
| --- | --- | --- |
| x | int64 [1,N] | model phoneme IDs with blank ID 0 |
| x_lengths | int64 [1] | N |
| tones | int64 [1,N] | aligned tone/stress IDs, blank tones 0 |
| sid | int64 [1] | actual model speaker 1 |
| noise_scale | float32 [1] | 0.667 |
| length_scale | float32 [1] | 1.0 at speed 1; reciprocal speed |
| noise_scale_w | float32 [1] | 0.8 |

Output y is mono Float32; host checks finite/nonzero samples and writes PCM16.
Language ID and zero BERT conditioning are folded into the exporter graph, not
extra HTTP/C API inputs. No explicit BOS/EOS or language token is injected here.
Each sentence gets leading/interspersed/trailing blanks, then two sentences may
be concatenated into one inference call, yielding adjacent zeros at the join.

tokens.txt has **112 symbols**, IDs 0..111. `_`=0 (also space/blank), punctuation
!=103, ?=104, ellipsis=105, comma=106, period=107, apostrophe=108, hyphen=109,
SP=110, UNK=111. Unsupported symbols may be ignored, not converted to UNK.
Lexicon has **195,828 entries**, including **20,888 single common Han characters**
and phrase/English entries. It was generated using full pypinyin dictionaries
and Melo's CMU-derived English dictionary by the pinned upstream exporter.
Chinese phrase matching handles polyphones within dictionary coverage; unknown
phrases fall back to characters; unknown English falls back to spelling letters.
Rare Han outside the dictionary and mathematical/currency operators are not an
open-vocabulary pronunciation guarantee. No new fake lexicon was created.

Golden corpus, actual final normalization and token category:

| # | Original text | Actual last normalization | Clean final ONNX inputs |
| --- | --- | --- | --- |
| 0 | 你好，今天过得怎么样？ | unchanged | IDENTICAL |
| 1 | 他说：你好！可以吗？当然可以；我们继续，保持安静。 | unchanged | IDENTICAL |
| 2 | 一共123个人，温度是25.5度。 | 一共一百二十三个人，温度是二十五点五度。 | IDENTICAL |
| 3 | 现在是2026年10月6日。 | 现在是二零二六年十月六日。 | IDENTICAL |
| 4 | Aurora 今天运行正常。 | unchanged | IDENTICAL |
| 5 | 请打开 Project Aurora。 | unchanged | IDENTICAL |
| 6 | hello world | unchanged | IDENTICAL |
| 7 | 你好，hello world，这是一个test。 | unchanged | IDENTICAL |
| 8 | 价格是￥25，折扣50%，请联系A+B。 | 价格是￥二十五，折扣五十%，请联系A+B。 | IDENTICAL |

Capture uses original reference DLL, with debug enabled only in a generated
oracle main outside the repo. A test-only in-process OrtApi::Run slot hook records
real names/dtypes/shapes/values **before forwarding the unchanged inference call**.
It is restored on process exit. No binary/source patch on disk, no other-process
injection, no hypothesized tokens. Frontend debug logs capture actual normalized
text and word phonemes/tones; actual ONNX arrays are in JSON. Instrumentation is
excluded from performance/clean-host binaries. Capture failure is explicit and
empty traces cannot pass. Total: **9 IDENTICAL / 0 EQUIVALENT / 0 DIFFERENT-VALID /
0 INVALID**, covering 12 ONNX calls per runtime.

Actual first reference phonemes, excluding blanks:
`n i h ao , j in t ian g uo d e z en m e y ang ?`.
The full x tensor (including per-sentence blanks) is:

```text
x = [0,62,0,40,0,37,0,16,0,106,0,0,55,0,49,0,78,0,44,0,35,0,91,0,23,0,26,0,100,0,30,0,60,0,26,0,99,0,15,0,104,0]
tones = [0,3,0,3,0,3,0,3,0,0,0,0,1,0,1,0,1,0,1,0,4,0,4,0,2,0,2,0,3,0,3,0,5,0,5,0,4,0,4,0,0,0]
x_lengths=[42], sid=[1], noise_scale=[0.666999996], length_scale=[1], noise_scale_w=[0.800000012]
```

Full captures and frontend logs: `tests/output/v47b3a-golden-v2/{reference,clean}`.
All nine WAVs per runtime are PCM16, 44.1 kHz, mono, non-silent, structurally read
in full. Durations equal for 7/9; differences are -0.975 ms and -171.451 ms for
the other two. Clean RMS 0.0271–0.0596, peak 0.1187–0.3237. Waveform hashes are
different for 9/9: stochastic noise is enabled and no seed is exposed in this
C API. No bit-equivalence, phonetic correctness or subjective naturalness claim.

## Upstream API and route B

The inspected current master is pinned to
`99ddefaa92129858b80a71a426903dd4215c83fa`; live ls-remote verified it again.
[GenerationConfig at that commit](https://github.com/k2-fsa/sherpa-onnx/blob/99ddefaa92129858b80a71a426903dd4215c83fa/sherpa-onnx/csrc/offline-tts.h)
does **not** expose a direct tokens member, nor does v1.13.8.
[Issue 3731](https://github.com/k2-fsa/sherpa-onnx/issues/3731) is a plan for 2.0,
not a released API. No commit implementing that proposed API was identified.
Chosen API is the existing VITS model's typed Run(x, tones, sid, speed) behind a
minimal experiment-only C subset, with the existing native lexicon frontend.

Route B was evaluated with external **pypinyin 0.55.0 (MIT)**, downloaded from
PyPI and unpacked outside Aurora without pip install or production dependencies.
Real outputs for all nine texts are retained in `tests/output/v47b3a-pypinyin.json`.
Pinyin syllables with tone digits are not Melo's phoneme symbols; all nine raw
candidate token streams contain model-symbol OOVs. It also leaves English chunks
unchanged and provides no English G2P, aligned Melo tones, blanks or sentence
batches. **NOT A DROP-IN COMPATIBLE PIPELINE**, not selected. It is a usable
Chinese component only after exporter-compatible pinyin-to-symbol mapping,
matching phrase behavior/normalization and an English dictionary/G2P; proving
that additional route is unnecessary because native route A matches the oracle.
The current master has no public direct-token transport to accept it anyway.

## License inventory and distribution evidence

This is **no-GPL-runtime** engineering, not a claim of entirely permissive-only
transitive code: ORT notices explicitly include Eigen **MPL-2.0**. This is a known
license, not silently reclassified MIT and not an unknown GPL phonemizer boundary.
No LGPL phonemizer is selected. Redistribution/installer compliance is a later
explicit gate. **LEGAL REVIEW RECOMMENDED**, especially MPL/VC redistributable
handling and model/dataset notices; this experiment distributes nothing.

| Component / version | License / official evidence | Runtime / obligations |
| --- | --- | --- |
| New benchmark/adapter/probe source | Aurora-owner-controlled first-party code; no third-party license inferred | experiment only, not publicly distributed |
| sherpa 1.13.8 selected sources | [Apache-2.0](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/LICENSE) | retain license/copyright/applicable notices; identify adapted/generated files |
| OpenFst 1.8.5 Windows fork tag | [Apache-2.0 COPYING](https://github.com/csukuangfj/openfst/blob/v1.8.5-2026-07-09/COPYING) | statically linked core; retain attribution/licenses |
| kaldifst 1.8.0 / Kaldi-derived IO | [Apache-2.0 LICENSE](https://github.com/k2-fsa/kaldifst/blob/v1.8.0/LICENSE), per-file copyright | normalization/IO only, no ASR decoder; retain attribution |
| ORT 1.28.2 CPU DLL + C/C++ headers | [MIT LICENSE](https://github.com/microsoft/onnxruntime/blob/v1.28.2/LICENSE), [full third-party notices](https://github.com/microsoft/onnxruntime/blob/v1.28.2/ThirdPartyNotices.txt) | redistribute license and complete applicable notices; do not erase transitive MPL |
| ORT-transitive Eigen | MPL-2.0 in same exact-version notices | provide covered-source availability information/notices if distributing; not general GPL whole-host source offer |
| Remaining ORT transitive components | Exact-version notices contain Apache/BSD/MIT/zlib/Boost/Intel/public-domain and component-specific terms | retain entire notice bundle; optional GPU/Python/mobile sections are not proof those runtimes are linked |
| Melo ONNX/tokens | [package MIT LICENSE, MyShell.ai 2024](https://huggingface.co/csukuangfj/vits-melo-tts-zh_en/blob/main/LICENSE), embedded model MIT metadata | model redistribution must retain model license/attribution; no new weights downloaded |
| Full Melo lexicon Chinese component | upstream exporter + [pypinyin MIT](https://github.com/mozillazg/python-pinyin/blob/master/LICENSE.txt), [pinyin-data MIT](https://github.com/mozillazg/pinyin-data/blob/master/LICENSE), [phrase data MIT](https://github.com/mozillazg/phrase-pinyin-data/blob/master/LICENSE) | generated data, not runtime Python; retain relevant authors/licenses; historical generator package version not recorded |
| Full lexicon English component | [Melo CMU dictionary notice](https://github.com/myshell-ai/MeloTTS/blob/main/melo/text/cmudict.rep): unrestricted research/commercial use, acknowledgement requested | retain CMU provenance plus Melo MIT; no eSpeak code |
| date.fst / number.fst | Origin repository [Apache-2.0 model card](https://huggingface.co/csukuangfj/icefall-tts-aishell3-vits-low-2024-04-06), pinned revision 57345c004e13ed640e408c4c29ab56187b18f065 | downloader origin corroborated by pinned export workflow; both exact original bytes match, retain Apache attribution; generator provenance not a new permissive inference |
| pypinyin 0.55.0 evaluation candidate | wheel LICENSE.txt MIT | external evaluation only; no candidate-runtime dependency |
| MSVC runtime / Windows SDK API sets | [Microsoft terms / redistributable restrictions](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170) | installed system dependencies; no CRT/SDK copies or installer made here |
| eSpeak/Piper/ucd | GPL-containing old oracle graph | excluded from candidate; never a production dependency or shipped candidate component |
| Model dict/cppjieba, int8 LFS stub, phone/new_heteronym rules | not opened by the selected frontend/config; not candidate dependencies | existing assets retained read-only, not packaged or claimed necessary |

FST provenance is not guessed from a generic WeTextProcessing license. The
official pinned Melo export workflow downloads these exact rules from the
Apache-declared origin above. Re-downloaded small rules have identical hashes:
date `eb8aa079ae3cb81d8f4404992f39d61a0cb990947512b5b8d1e54d1f6980e718`,
number `743f402181fcfebf76cc2f0546b71fa26476e626fbe4e460fb7b4c3a7a8bd5bd`.
The origin README was retained externally. Known-license components above:
UNKNOWN license count **0 at the technical declaration/inventory level**.
This is not an independent legal investigation of training-data title or a
guarantee that upstream declarations eliminate all third-party rights.

ORT notice coverage is retained verbatim externally, SHA-256 above. Its named
component sections (including optional build families) comprise:
Intel MKL (Intel Simplified); protobuf (BSD-3); zlib (zlib); pybind11 (BSD-3);
ONNX (Apache-2); Eigen (MPL-2); oneDNN (Apache-2); Microsoft GSL (MIT);
TensorFlow (Apache-2); CNTK (MIT); NumPy (BSD); PyTorch/Caffe2 (BSD);
Caffe (BSD); LLVM (NCSA/BSD); benchmark (Apache-2); HalideIR (MIT);
dmlc-core/DLPack (Apache-2); HowardHinnant/date (MIT); FreeBSD getopt (BSD);
GoogleTest (BSD-3); G3log (public-domain dedication); scikit-learn (BSD);
RE2 (BSD-3); ONNX-TensorRT (MIT); CUTLASS (BSD-3); Boost (BSL-1.0);
DNNLibrary (Apache-2); FlatBuffers (Apache-2); glog (BSD); Abseil (Apache-2);
WIL/JSON/SafeInt (MIT); Open MPI (BSD-3); Android snippets (Apache-2);
mpi4py (BSD); Transformers (Apache-2); msgpack (Apache-2); tensorboardX (MIT);
TensorBoard (Apache-2); Cerberus (ISC); MurmurHash3 (MIT); gtest-ios (BSD);
Emscripten (MIT/Expat); coremltools (BSD-3); React Native (MIT); cpuinfo (BSD-2);
SQLite (public domain); XNNPACK (BSD); SentencePiece (Apache-2);
dlfcn-win32 (MIT); PIL (HPND/PIL permission notice); OpenSSL (Apache-2);
RapidJSON (MIT plus its supplied component notices); libb64 (public-domain
dedication); pthreads4w (Apache-2); Triton (BSD); mimalloc (MIT);
TensorFlow.js/neural-compressor/neural-speed (Apache-2); FlashAttention (BSD-3);
Dawn (BSD-3); KleidiAI (Apache-2). This broad upstream notice list is **not an
assertion that GPU, mobile, Python or every optional component exists in this CPU
DLL**. Whole notice text remains authoritative for exact component terms.
The generic LGPL sentence in Microsoft's preamble does not establish a linked
LGPL component; no LGPL phonemizer/library is identified in this candidate graph.

## Performance, coexistence, Rust Audio and soak

Hardware: Ryzen 9 7940HX, 16 cores / 32 logical processors, Radeon RX 7600 XT.
Unchanged production Release; current verified 4B Vulkan model resident and
real native Live2D visible. Single CPU TTS worker, four ORT threads. Benchmarks
are strictly serial: chat terminal -> TTS -> next chat; post-turn background
inference suppressed only in the already-existing opt-in fixture. No Ollama,
LM Studio, Edge, Remote Voice Node or new model involved.

| Characters | Five warm synthesis seconds min / median / max | Median RTF | Prior median RTF |
| ---: | --- | ---: | ---: |
| 16 | 0.746 / 0.761 / 0.768 | 0.281 | 0.260 |
| 52 | 2.347 / 2.387 / 2.413 | 0.270 | 0.266 |
| 109 | 4.930 / 4.971 / 5.037 | 0.274 | 0.267 |

All medians below target 0.5 and requirement 1.0. Small variation vs the prior
run does not show a normalization bottleneck or justify changing the LLM/GPU.
API model initialization 2.51 s; this is separate from warm synthesis latency.
Five short production terminal-to-WAV-ready samples: 951, 1318, 880, 871, 847 ms;
median 880 ms, max 1318 ms. They include the existing benchmark handoff and one
actual 25-character reply. Recovery sample 912 ms. Not first PCM streaming latency.

LLM baseline five turns: median **72.761 tok/s**, first-content median 62 ms.
Fifteen pre-TTS turns median **73.421 tok/s**, post-TTS **72.723 tok/s**;
post-soak recovery **73.63 tok/s**. Post-TTS first-content median 63 ms,
max 141 ms (one pre-TTS outlier 219 ms). No sustained throughput regression.

Measured during synthesis: native CPU **393.7% one-core basis**, about 12.3% of
32 logical processors; native working set **490,717,184 bytes** (~468 MiB).
Steady idle native working set **489,005,056**, private bytes **564,408,320**.
CPU EP only; no native GPU process counter allocation observed. Missing GPU
counters are reported as null, not fabricated zero. 4B dedicated counter
**3,020,083,200 bytes** (~2.813 GiB); Live2D **33,501,184** (~32 MiB).
Visible Live2D **57.93 FPS** during TTS and **58.00 FPS** resident idle.

Soak: 20 consecutive short syntheses, same native PID **20828**, 20 successes,
zero failures. Working-set first/last **489,005,056 / 489,005,056**; private first/
last **564,408,320 / 564,408,320**; handles **141 / 141**; threads **6 / 6**.
Twenty expected WAV artifacts retained only as ignored evidence. First/last RTF
0.2878 / 0.2688; no monotonic deterioration. Native allocation caching after
longer requests is not mistaken for a leak. A separate final from-clean build
smoke repeats 41 requests (matrix, coverage, 20-short soak), CPU only.

Rust Audio injection uses actual complete clean WAVs and the unchanged existing
test bridge. Five normal completions, one stop and one recovery; actual lip-sync
mouth maxima **0.451–0.681** on completed playback; every final mouth **0**.
Stop after mouth became active resets idle/mouth in **49.15 ms** and discards
remaining playback; recovery succeeds without restarting the voice model.
This proves native playback/state plumbing, not human audition of output or
phoneme-aligned/viseme lip sync. Physical listening: NOT MANUALLY VERIFIED.
All benchmark-owned processes exit; `remainingOwned=[]` for matrix and playback.

## Runtime shape, cancel and future boundary

Recommend **independent C++ native host**, with one worker owning this narrow
native adapter and model. Rust Desktop should supervise an isolated process,
not load model/FFI failures into its UI process. A Rust native child host is also
feasible, but adds FFI lifecycle work without reducing the required C++/ORT build.
This experiment is a headless long-running stdin/stdout benchmark, **not** a
production service/protocol/Supervisor implementation.

Future ready/health/request/result/shutdown, crash detection, Job Object,
bounded restart and temp artifact ownership: **FEASIBLE**, not yet implemented
or claimed tested. The observed stable PID and cleanup support feasibility.
Normal cancellation can invalidate request ownership and discard a late result;
upstream callback can stop **between sentence batches**. A single ONNX Run is
synchronous and does not check the callback internally. The selected wrapper
does not expose an active OrtRunOptions termination handle. Therefore immediate
cooperative in-graph synthesis cancellation is **NOT PROVEN / NOT EXPOSED**.
Do not use process kill for ordinary Stop Voice. Existing Rust Audio stop can
remain immediate while synthesis completes/discards; newer termination support
would require a separate small, explicitly tested design in a later task.

## Evidence, negative attempts and validation

All model/audio/log/cache/binary outputs are ignored or external, not Git files.

- `tests/output/v47b3a-golden-v2/report.json` and two actual frontend/tensor traces.
- `tests/output/v47b3a-pypinyin.json`: external candidate incompatibility evidence.
- `tests/output/v47b3a-clean-coexist/run-zEuUkv/report.json`: successful visible matrix/20-run soak/resources; 48 TTS requests including optional hidden reference.
- `tests/output/v47b3a-clean-coexist/run-9ql2ff/report.json`: successful native playback/stop/recovery; 8 TTS requests.
- `tests/output/v47b3a-final-build-smoke/report.json`: final rebuild runtime regression.
- `tests/output/v47b3a-binary-audit-final/report.json`: final full binary/source/hash inventory.
- External `clean-build-final.log`: successful from-clean build without GPL units.

Negative attempts retained honestly: initial build missed two ORT header files,
then required small upstream utility TUs; corrected before successful build.
The first oracle shutdown used uppercase QUIT instead of existing lowercase
quit; generated evidence was retained, second run passed both complete oracles.
First Desktop probe failed because VS placed runtime DLLs under lib/Release;
explicit Release output directory fixed it in the experiment build recipe,
cleanup passed, and the subsequent full run passed. One launch substituted MODE
inside the MODEL environment name and failed before launching processes; fixed
the test command only. Pypinyin cannot read its JSON dictionaries from a zipped
wheel; external unpacking resolved that without installing it into Aurora.
No negative attempt is presented as a successful test or a production regression.

Tooling regression: **26 passed** (12 new / 14 existing) in the requested narrow
probe/fixture suite; Python compile checks, JS syntax, git diff --check and
all-untracked whitespace checks pass. No production source changed, so no
unnecessary full production rebuild/test/installer run was performed.

## Complete requested 98-field report

| # | Field | Actual result / boundary |
| ---: | --- | --- |
| 1 | Branch | refactor/aurora-v4 |
| 2 | HEAD | dd1ceb24b59d2ad26a934055c7d6554528828bbb |
| 3 | Local / Remote | Identical, live remote checked |
| 4 | Working tree | 0 tracked/staged changes; 23 untracked experiment/docs files, not globally clean |
| 5 | Original 13 inventory | Full paths/purpose/hash above, byte-identical |
| 6 | New files | 10, listed above; no production files |
| 7 | sherpa version / commit | v1.13.8 / 11afbd009a7f8c08f4bcf2fc1b265d0df4670fbf |
| 8 | Old eSpeak evidence | Actual exports/strings/static source graph, complete raw PE records |
| 9 | eSpeak dependency path | TTS root -> core -> static piper/eSpeak -> old C API DLL |
| 10 | piper path | static piper_phonemize + ucd in old general TTS build, absent clean target |
| 11 | Melo identity | existing melo-vits zh_en version 2, FP32 ONNX |
| 12 | Model hash | bf30582eb1b012250a35b1a4a80e7dfbcf8485e7bb9de0d95efbbeef0e4ad86d |
| 13 | Input contract | 7 actual captured inputs, int64 x/lengths/tones/sid and 3 float scales |
| 14 | tokens.txt | 112 phoneme/punctuation/blank symbols, actual map, not text tokenizer alone |
| 15 | Language markers | folded lang_id=3; no added language token; tone offsets in lexicon |
| 16 | Punctuation tokens | IDs 103–111 detailed above; unsupported symbols can drop |
| 17 | Golden Corpus | 9 fixed Chinese/numeric/date/English/mixed/symbol cases above |
| 18 | Old phonemes | Real debug frontend logs and first-case list above |
| 19 | Old tokens | Real OrtApi::Run traces, first-case full tensors above |
| 20 | Clean route | native full lexicon + original normalizer + original VITS model |
| 21 | Lexicon result | selected; 195828 entries, 20888 single Han entries, no fake corpus-only map |
| 22 | External result | pypinyin 0.55 MIT, actual evaluation; not a compatible complete pipeline |
| 23 | Normalization | date.fst then number.fst via unchanged kaldifst/OpenFst |
| 24 | Chinese | actual tokens match reference; dictionary/polyphone limitations remain |
| 25 | Numbers | 123 -> 一百二十三; 25.5 -> 二十五点五 |
| 26 | Dates | 2026年10月6日 -> 二零二六年十月六日 |
| 27 | English | existing CMU-derived words; unknown word spelling fallback, no eSpeak regression |
| 28 | Mixed | actual reference-equal tensors; language conditioning is existing model's |
| 29 | Token comparison | exact names/dtypes/shapes/all values, 12 Run calls per runtime |
| 30 | IDENTICAL | 9 |
| 31 | Equivalent | 0 |
| 32 | Different-valid | 0 |
| 33 | Invalid | 0 for chosen route; external raw pinyin 9 incompatible cases, not mixed into chosen count |
| 34 | Chosen API | existing typed Melo Run behind narrow eight-function experimental ABI |
| 35 | Direct tokens API | absent release and inspected pinned master |
| 36 | API source commit | proposed public direct-token API has no identified implementation commit; master audited 99ddefaa92129858b80a71a426903dd4215c83fa |
| 37 | CMake | explicit external sources, CPU /MD Release, all OpenFst extension/tool options off |
| 38 | Excluded targets | eSpeak/Piper/general sherpa-core/ASR/VAD/KWS/diarization/decoder/Torch/etc |
| 39 | Build | PASS, initial and final from-clean builds; warnings recorded |
| 40 | Binary size | host 76800; minimal API DLL 878592 bytes |
| 41 | DLL dependencies | official ORT + providers-shared inspected; Windows/CRT leaves separately recorded |
| 42 | Exports | 8 narrow SherpaOnnx functions; no general API replacement claim |
| 43 | Imports | host narrow ABI + Windows; API OrtGetApiBase + C++ CRT/Windows; raw records retained |
| 44 | eSpeak symbols | none in clean candidate artifacts |
| 45 | piper symbols | no phonemize functions; one metadata-only literal piper explained |
| 46 | GPL scan | no known GPL runtime source/target/export/import/dependency in clean graph |
| 47 | Dependency inventory | tables/graph plus actual recursively inspected PE manifests and exact-version notices |
| 48 | Every dependency license | known source/artifact declarations above; MPL-2/VC terms explicitly not called MIT |
| 49 | Unknown license count | 0 at documented technical declaration level, not a universal legal warranty |
| 50 | Redistribution | retain licenses/attribution/notices, comply with model/MPL/VC terms; not performed |
| 51 | Source offer | no introduced GPL whole-host offer; Eigen/MPL covered-source availability remains relevant |
| 52 | NOTICE | retain complete applicable sherpa/OpenFst/kaldifst/ORT/data notices; no packaging yet |
| 53 | Model redistribution | package declares MIT; retain license + data/lexicon notices; not shipped here |
| 54 | Legal review | LEGAL REVIEW RECOMMENDED; no independent-process GPL evasion argument |
| 55 | WAV generation | real reference/clean corpus, matrix, native playback and soak successful |
| 56 | Sample rate | 44100 Hz, unchanged |
| 57 | Channels | 1, PCM16 |
| 58 | Duration comparison | 7 equal; -0.975 ms / -171.451 ms two stochastic/silence differences |
| 59 | Integrity | finite float, complete RIFF/PCM read, nonzero RMS, no subjective pronunciation pass |
| 60 | 16 chars min/median/max | 0.746 / 0.761 / 0.768 seconds, 5 warm runs |
| 61 | 16 chars RTF | median 0.281 |
| 62 | 52 chars min/median/max | 2.347 / 2.387 / 2.413 seconds, 5 warm runs |
| 63 | 52 chars RTF | median 0.270 |
| 64 | 109 chars min/median/max | 4.930 / 4.971 / 5.037 seconds, 5 warm runs |
| 65 | 109 chars RTF | median 0.274 |
| 66 | Terminal -> audio ready | 5 short runs median 880 ms, max 1318 ms; not streaming first PCM |
| 67 | CPU | four threads, measured 393.7% one-core / approx 12.3% of 32 LPs |
| 68 | RAM | native ~468 MiB active WS / ~466 MiB idle, private ~538 MiB |
| 69 | GPU | CPU EP only; no TTS allocation observed; null counters remain null |
| 70 | VRAM | existing 4B 3020083200 bytes, Live2D 33501184; no measured TTS allocation |
| 71 | Live2D FPS | 57.93 active / 58.00 idle visible |
| 72 | LLM baseline | 72.761 tok/s median, 5 turns |
| 73 | Post-TTS | 72.723 tok/s median, 15 turns; after-soak 73.63 |
| 74 | First token | baseline median 62 ms, after median 63 ms; no sustained regression |
| 75 | Rust Audio | unchanged real native playback accepted clean WAV injection |
| 76 | Lip sync | actual audio-envelope mouth updates, not full phoneme lip sync |
| 77 | Mouth reset | zero after all natural completions and stop |
| 78 | Stop injection | real Stop, reset ~49.15 ms; following playback succeeds |
| 79 | 20-run soak | same PID 20828, 20/20 successes |
| 80 | RSS drift | first/last 489005056, delta 0; private delta 0 |
| 81 | Handles drift | 141 -> 141, delta 0 |
| 82 | Threads drift | 6 -> 6, delta 0 |
| 83 | Cleanup | all owned processes exit; ignored expected audio evidence retained, not leaked production temp |
| 84 | Runtime shape | independent minimal single-worker native child process recommended |
| 85 | Rust vs C++ | C++ child simplest; Rust Desktop supervision, no in-UI model FFI |
| 86 | Headless | proven benchmark, no GUI/HTTP required by voice host |
| 87 | Long-running | resident same-PID repeated requests / soak proven |
| 88 | Ready | benchmark READY proven; production ready contract FEASIBLE only |
| 89 | Health | FEASIBLE with worker/model state; not implemented |
| 90 | Cancel | request invalidate/discard and between-batch callback feasible; in-graph immediate abort not exposed/proven; no normal kill |
| 91 | Crash isolation | FEASIBLE via independent process; no new Supervisor implemented |
| 92 | Job Object | FEASIBLE Windows child ownership; not implemented here |
| 93 | Manual hearing | NOT MANUALLY VERIFIED |
| 94 | Production changed? | NO, zero tracked changes; old 13 files unchanged |
| 95 | Commit? | NO; no staging/push |
| 96 | WIP Glass | unchanged adeee5aa4949a47e62ba9f7a2cb708f50a361970 |
| 97 | Final decision | B — LICENSE-CLEAN + FUNCTIONAL LIMITATIONS |
| 98 | V4-7B.3B allowed? | May be separately authorized for Chinese-first integration; NOT started automatically |

**Stage V4-7B.3A — License-Clean Sherpa/Melo Runtime Feasibility: PASS — B.**
Stop here; wait for the next task. This does not approve packaging or claim human
listening acceptance, immediate in-graph cancellation, or future direct-token API.

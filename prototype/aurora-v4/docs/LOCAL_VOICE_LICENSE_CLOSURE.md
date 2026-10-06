# V4-7B.3 — Local Voice License Gate

Date: 2026-10-06.

**Gate 0: PASS. Gate 1: LICENSE BLOCKER (unresolved production licensing and
redistribution policy). Stage V4-7B.3: NOT PASS; integration not started.**

This is an engineering dependency/license audit, not a legal opinion. GPL does
not prohibit local/private use or commercial activity. The blocker is not a
new performance failure or a claim that sherpa/Melo can never be integrated.
It is the absence of an approved compliance boundary for the actual GPL-bearing
binary and a future linked Voice Host. Do not equate Apache/MIT source labels
with permission to redistribute the complete prebuilt runtime on those terms.

The user explicitly requires License Closure before production integration.
No Provider, Supervisor, Host, settings, IPC, audio, avatar or LLM code is changed.
No assets are downloaded again, moved, renamed, copied or deleted this stage.
No binary is built, no model inference is run, and no commit/push is made.

## Gate 0: verified baseline and assets

- Branch: `refactor/aurora-v4`.
- HEAD and live `git ls-remote` production branch:
  `dd1ceb24b59d2ad26a934055c7d6554528828bbb`.
- WIP Glass `wip/v4-5b1-edge-optics-experiment` remains
  `adeee5aa4949a47e62ba9f7a2cb708f50a361970`; no checkout or merge.
- No tracked/staged modifications. The original 12 untracked files are retained
  byte-for-byte; this new audit is the thirteenth. Working tree is not globally
  clean. No final Git closure is attempted before the integration gates pass.
- External root:
  `C:\Users\X\.cache\aurora-feasibility\v47b2-sherpa-melo-20261006`.
- Runtime directory: `sherpa-onnx-v1.13.8-win-x64-shared-MD-Release` under that
  external root; official Windows x64 CPU shared MD Release, version 1.13.8.
- Model directory: `vits-melo-tts-zh_en` under that external root. Existing
  float `model.onnx`, lexicon, tokens and rule FSTs are present, read-only use.
- No inference was repeated for version verification: exact getters/ORT 1.28.2
  were verified in V4-7B.2; this stage verifies asset identity against its hashes.

| Existing asset | Bytes | SHA-256 rechecked this stage |
| --- | ---: | --- |
| Runtime archive | 20494724 | `3e971a04b2e0ba4dfa53d381a006367ce8c9f5f09b4ae00043e9845c2baded22` |
| Model archive | 167006755 | `e58351ed7149f290a54534538badd4077cdbe6fddc964b24d0bee870415d1514` |
| model.onnx | 170429550 | `bf30582eb1b012250a35b1a4a80e7dfbcf8485e7bb9de0d95efbbeef0e4ad86d` |
| sherpa-onnx-c-api.dll | 4197376 | `f86ed1570de14b4750d29fb4f58cfaf5558f734040d73133da79dd6457ed77ff` |

### Original 12-file inventory, preserved

| File | SHA-256 at entry; must remain unchanged |
| --- | --- |
| prototype/aurora-v4/desktop/tests/local_voice_feasibility.mjs | `f32b2525f86be719787678c6d5103829006bcc047ec95315dd7c4f6842ab4878` |
| prototype/aurora-v4/desktop/tests/local_voice_performance.mjs | `ed7509648870a34400198af0ade03432827ecce935fdfe97e91e06cb46710e8f` |
| prototype/aurora-v4/desktop/tests/sherpa_melo_feasibility.mjs | `898b90e8d31b0c0f6628535c1353a948d0543640545bc63d2e68f2b1ceca228e` |
| prototype/aurora-v4/docs/LOCAL_VOICE_PERFORMANCE_FEASIBILITY.md | `b27261118ad926e25b558388a83e30337df808d1e6a92996de47c037b1d61e18` |
| prototype/aurora-v4/docs/LOCAL_VOICE_RUNTIME_AUDIT.md | `f66956bf6e73aa61b01cec37131a123211d17a2386f8c78af633e59b34de712e` |
| prototype/aurora-v4/docs/SHERPA_MELO_LOCAL_VOICE_FEASIBILITY.md | `d324d61fc8a0075d25e24a1dc702c894da12390c189c41bd3e38633b1207d444` |
| scripts/benchmark_sherpa_melo.cpp | `de89f308b2d6ec9c17d6489c4d6237088bca26557ffdc46ce2fd3c632ec135a1` |
| scripts/probe_local_cosyvoice.py | `22be9e34c772c7594f71cf323d5ec325022354584e7c35cf9d7c025f4d1c3ee4` |
| scripts/probe_sherpa_melo.py | `f7f6f56e2e1baa63cf8aedcd9347cd63345eb8b65ea2e1e16b6aa406b5280382` |
| scripts/voice_feasibility_sidecar/production_sidecar/server.py | `15b42220f6ea9b55f9ca461db22c2b4ff3e7900247ad05f6986fc5e72f6c3009` |
| tests/test_sherpa_melo_probe.py | `5f51ec063ff70f2a309d84ffe3ce3b0aa180275819b2aac1233a79e5244fc856` |
| tests/test_voice_feasibility_fixture.py | `ebe66f77f4c2cb5a586f6620f2862eef0d96f1719598157aebef6fdd1f9af22e` |

## Gate 1: actual dependency evidence

### A. Source license is not the complete binary license boundary

The pinned [sherpa LICENSE](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/LICENSE)
is Apache-2.0. [ORT 1.28.2](https://github.com/microsoft/onnxruntime/blob/v1.28.2/LICENSE)
is MIT and has a separate, extensive
[ThirdPartyNotices](https://github.com/microsoft/onnxruntime/blob/v1.28.2/ThirdPartyNotices.txt).
The downloaded runtime package contains 32 headers/libs/binaries, but no
LICENSE, NOTICE, COPYING or third-party-notice files. The separately retained
sherpa LICENSE from the feasibility stage is not a complete binary notice set.

The official [Windows x64 build workflow](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/.github/workflows/windows-x64.yaml)
uses a TTS-on build for the archive without a `-no-tts` suffix. Disabling the
eSpeak executable in that workflow does not disable its library.

The pinned dependency chain is:

1. [Root CMake](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/CMakeLists.txt)
   includes eSpeak and piper-phonemize when TTS is enabled.
2. [TTS core linkage](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/sherpa-onnx/csrc/CMakeLists.txt)
   links piper_phonemize into sherpa-onnx-core.
3. [piper dependency configuration](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/cmake/piper-phonemize.cmake)
   pins `f3ff95afc03640bc1399e113e83361192a2fafb4` and builds it static inside
   a shared sherpa build.
4. [eSpeak dependency configuration](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/cmake/espeak-ng-for-piper.cmake)
   pins `ed530aa113046142eb5115cf2fc9157854d0ffe1` and likewise builds static.
   This explicit sherpa pin, not the fallback version in piper's own external
   download code, is the relevant source baseline.
5. [piper's pinned CMake](https://github.com/csukuangfj/piper-phonemize/blob/f3ff95afc03640bc1399e113e83361192a2fafb4/CMakeLists.txt)
   links the eSpeak library (and static ucd).

### B. Verified against the actual DLL, not just a hypothetical source path

Read-only `dumpbin /exports` on the hash-identified C API DLL finds executable
exports including:

```text
espeak_Initialize
espeak_Cancel
espeak_Synth
espeak_Terminate
espeak_ng_Initialize
espeak_ng_Cancel
espeak_ng_Synthesize
espeak_ng_Terminate
```

It also exports piper's phonemize_eSpeak symbol. `dumpbin /dependents` finds
onnxruntime.dll and Windows/MSVC/UCRT dependencies, not an external espeak DLL;
this agrees with the static-link build chain. This is substantially stronger
evidence than searching for log strings alone. It is not a full linker-map SBOM.

The selected Melo frontend does not need eSpeak/dict files for the tested
requests. That affects execution, not the identity of code in the complete DLL.
Not calling these exports does not turn the prebuilt DLL into an
Apache/MIT-only binary. Similarly, a C ABI, dynamic loading, a separate process,
user-supplied assets or omission of binaries from Git is not by itself a proof
that all future linked-work/distribution obligations disappear.

The exact eSpeak fork's
[README](https://github.com/csukuangfj/espeak-ng/blob/ed530aa113046142eb5115cf2fc9157854d0ffe1/README.md)
identifies GPL-3.0-or-later. Its
[source header](https://github.com/csukuangfj/espeak-ng/blob/ed530aa113046142eb5115cf2fc9157854d0ffe1/src/libespeak-ng/espeak_api.c)
and [COPYING](https://github.com/csukuangfj/espeak-ng/blob/ed530aa113046142eb5115cf2fc9157854d0ffe1/COPYING)
confirm the grant. Its ucd dependency has GPL text too. Other included notices
(for example BSD compatibility code) must also be retained if applicable.

Upstream maintainers explicitly acknowledge this problem in
[issue #3731](https://github.com/k2-fsa/sherpa-onnx/issues/3731) and propose
removing these dependencies for a 2.0.0 release. This is not evidence that our
1.13.8 DLL has already removed them. Do not switch to a hypothetical new release
or patch/rebuild the inference runtime without a separate decision.

### C. Other licenses and attached model assets

| Component / asset | Verified license/source | Closure requirement |
| --- | --- | --- |
| sherpa-onnx source 1.13.8 | Apache-2.0, pinned LICENSE | Preserve license/copyright and applicable notices/changes; does not cover every linked dependency |
| ONNX Runtime 1.28.2 | MIT plus pinned ThirdPartyNotices | Ship MIT and applicable dependency notices; inspect actual prebuilt build manifest |
| piper-phonemize pinned fork | [MIT](https://github.com/csukuangfj/piper-phonemize/blob/f3ff95afc03640bc1399e113e83361192a2fafb4/LICENSE.md) | Retain Michael Hansen attribution; MIT wrapper does not replace eSpeak's GPL |
| eSpeak NG pinned fork / ucd | GPL-3.0-or-later / GPL text | GPL-compatible linked-work policy, exact Corresponding Source/build scripts and notices before distribution |
| kaldi-decoder v0.3.0 | [Apache-2.0](https://github.com/k2-fsa/kaldi-decoder/blob/v0.3.0/LICENSE) | Dependency notices and pinned source |
| kaldi-native-fbank v1.22.3 | [Apache-2.0](https://github.com/csukuangfj/kaldi-native-fbank/blob/v1.22.3/LICENSE) | Dependency notices and pinned source |
| simple-sentencepiece v0.7 | [Apache-2.0](https://github.com/pkufool/simple-sentencepiece/blob/v0.7/LICENSE) | Dependency notices and pinned source |
| OpenFst v1.8.5-2026-07-09 | [Apache-2.0](https://github.com/csukuangfj/openfst/blob/v1.8.5-2026-07-09/COPYING) | Copyright and applicable notices; generated rule asset provenance is separate |
| vits-melo-tts-zh_en model.onnx | Actual package MIT LICENSE, MyShell.ai 2024 | Model license/copyright must accompany distribution |
| tokens.txt / lexicon.txt | Package MIT; [pinned exporter](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/scripts/melo-tts/export-onnx.py) traces symbol/CMU/pypinyin inputs | Preserve derived-data attributions; exporter imports do not establish the exact versions used for this archive |
| English lexicon input | [Melo cmudict.rep header](https://github.com/myshell-ai/MeloTTS/blob/main/melo/text/cmudict.rep) permits research/commercial use and requests CMU acknowledgement | Preserve original CMU notice; this mutable source is provenance context, not a byte-exact archive reconstruction |
| Chinese lexicon inputs | [pypinyin MIT](https://github.com/mozillazg/python-pinyin/blob/master/LICENSE.txt), [pinyin-data MIT](https://github.com/mozillazg/pinyin-data/blob/master/LICENSE), [phrase data MIT](https://github.com/mozillazg/phrase-pinyin-data/blob/master/LICENSE) | Record exact derivative versions/attributions before shipping generated data |
| dict/* | Package describes CppJieba dictionaries; [CppJieba MIT](https://github.com/yanyiwu/cppjieba/blob/master/LICENSE), [jieba MIT](https://github.com/fxsjy/jieba/blob/master/LICENSE) | Preserve dictionary notices if shipping; current Melo frontend uses lexicon/phrase matcher, so do not ship unused dictionaries merely because archived |
| date/number/phone/new_heteronym FSTs | Package MIT declaration, no per-file build/provenance manifest | Record the actual rule generators/input versions and notices before a distribution approval; do not infer data license solely from OpenFst library license |
| Windows/MSVC/UCRT | Actual DLL import list checked; SDK/system runtime boundary | Follow Microsoft redistribution terms if shipping redist; do not copy arbitrary system DLLs |

This is a minimum source-based audit of relevant dependencies, not an exhaustive
attestation of every object in the prebuilt libraries. Upstream ORT notices,
symbol/source checks and package-level MIT declarations are useful evidence,
but not substitutes for a distribution manifest. No license exception or
extra permission removing the identified GPL obligation was found.

## Distribution boundary and required decision

Local/private execution is not declared forbidden. GPL sections 2 and 6
distinguish running a private copy from conveying object code and providing its
Corresponding Source. Apache-2.0 source can be combined under GPLv3-compatible
terms; the problem is an Apache/MIT-only distribution claim, not an assertion
that Apache-2.0 and GPLv3 can never coexist.

The repository has no tracked LICENSE/NOTICE/COPYING file defining an approved
new Host licensing policy. Do not silently choose or change the user's product
licensing, and do not assert that IPC automatically exempts the whole application.

| Future distribution item | Current decision |
| --- | --- |
| Existing GPL-bearing sherpa DLL | No unconditional installer approval; requires an approved GPL-compliant distribution/source/notice plan |
| New Voice Host linked to that DLL | Not created; its linked-work licensing/compliance boundary must be decided first |
| ORT / Melo model and permissive dependencies | Licenses permit conditional use/distribution; preserve notices and close provenance/build inventory; no binary package produced here |
| User-provided existing runtime/model | Private local use is possible; this is not an automatic exemption for distributing a newly linked Host or the dependencies |
| Git | No runtime/model/DLL/EXE/WAV/archive/secret/user data; no integration commit while gates are blocked |

Two possible next directions require explicit owner selection, not automatic
implementation in this audit:

1. Accept a GPL-compliant independent Voice Host, preserve complete relevant
   notices/Corresponding Source and obtain a reviewed aggregation/IPC boundary
   for Desktop. This does not automatically require relicensing all Aurora.
2. Require a no-GPL native runtime build. Authorize a separately pinned minimal
   build that demonstrably excludes eSpeak/piper, then rerun ABI, waveform,
   performance and license gates. No such clean build was attempted, and no
   claim is made that this release has a ready-made flag that accomplishes it.

Do not select another TTS framework/model, download another large runtime,
alter inference core, or continue production implementation just to bypass
this Gate. No requested runtime-lifecycle/cancel Gate has been marked passed.

## Validation of this audit-only stage

Entry/final checks: branch, HEAD, live remote HEAD, WIP pointer, original 12 hashes,
external archive/model/C API DLL hashes, zero tracked/staged changes, whitespace
checks and no runtime launched by this stage. No existing user process is killed.
Only this Markdown audit is added. No production tests, Release build, offline
production smoke or 50-request production soak is claimed; integration was not
started. Previous feasibility results remain previous-stage evidence, not
V4-7B.3 acceptance. Manual listening remains NOT MANUALLY VERIFIED.

## Required 98-item status report

`NOT RUN` / `NOT IMPLEMENTED` below means blocked before integration, not a
regression or a failed measurement. Baseline facts are explicitly marked.

| # | Field | This stage's actual result |
| ---: | --- | --- |
| 1 | Branch | refactor/aurora-v4 |
| 2 | Final commit | No new commit; HEAD dd1ceb24b59d2ad26a934055c7d6554528828bbb |
| 3 | Commit message | No new commit; baseline feat(v4): add avatar behavior and lip sync |
| 4 | Local / Remote | Equal at baseline HEAD; no push |
| 5 | Working tree | Zero tracked/staged changes; 13 untracked files; not globally clean |
| 6 | Modified / added count | 0 modified; 1 new audit doc |
| 7 | Original 12 untracked | Preserved byte-for-byte, neither deleted nor committed |
| 8 | sherpa version | Existing 1.13.8 asset retained; prior getter evidence, hashes rechecked |
| 9 | Runtime hash | 3e971a04b2e0ba4dfa53d381a006367ce8c9f5f09b4ae00043e9845c2baded22 |
| 10 | Runtime license | Apache source + MIT/permissive components + GPL-bearing eSpeak code in actual DLL; LICENSE BLOCKER |
| 11 | Model | vits-melo-tts-zh_en |
| 12 | Model hash | bf30582eb1b012250a35b1a4a80e7dfbcf8485e7bb9de0d95efbbeef0e4ad86d |
| 13 | Model license | Actual package MIT LICENSE, MyShell.ai 2024 |
| 14 | Distribution boundary | No unconditional binary/Host installer approval; owner compliance decision required |
| 15 | Host technology | NOT IMPLEMENTED; no route selected past License Gate |
| 16 | Executable/library ownership | NOT IMPLEMENTED; existing benchmark is not a production Host |
| 17 | LocalVoiceSupervisor | NOT IMPLEMENTED |
| 18 | State machine | NOT IMPLEMENTED |
| 19 | EAGER / LAZY | NOT SELECTED; production integration not started |
| 20 | Runtime discovery | NOT IMPLEMENTED; existing external path audited only |
| 21 | Model discovery | NOT IMPLEMENTED; existing external path audited only |
| 22 | Port / IPC | NOT IMPLEMENTED |
| 23 | Auth / isolation | NOT IMPLEMENTED |
| 24 | Readiness | NOT IMPLEMENTED |
| 25 | Health | NOT IMPLEMENTED |
| 26 | Crash detection | NOT IMPLEMENTED |
| 27 | Restart policy | NOT IMPLEMENTED |
| 28 | Job Object | No new Voice Host Job integration |
| 29 | Shutdown | No new Voice runtime; no process launched |
| 30 | Temp root | No production Voice temp root created |
| 31 | Artifact lifecycle | NOT IMPLEMENTED; no new audio generated |
| 32 | Local provider | NOT IMPLEMENTED |
| 33 | TTSRouter | Unchanged |
| 34 | Default/migration policy | Unchanged; no user settings touched |
| 35 | Edge role | Baseline production provider retained |
| 36 | Remote role | Compatibility code unchanged; no request/dependency introduced |
| 37 | LocalCosyVoiceProvider | NOT IMPLEMENTED; unchanged |
| 38 | Cancel contract | NOT IMPLEMENTED; prior native cancellation assessment remains feasibility-only |
| 39 | Stale suppression | No new integration; baseline unchanged |
| 40 | Concurrency policy | NOT IMPLEMENTED |
| 41 | CPU threads | No production setting added; previous-stage recommendation remains 4 |
| 42 | Stop synthesis | NOT RUN on a production Local path |
| 43 | Stop playback | No new-stage smoke; existing Rust Audio unchanged |
| 44 | Crash behavior | NOT RUN for a production Local Host |
| 45 | Runtime missing | NOT RUN for a production Local Host |
| 46 | Model missing | NOT RUN for a production Local Host |
| 47 | Corrupt model | NOT RUN; external model left unchanged |
| 48 | Timeout | NOT RUN for a production Local Host |
| 49 | voice.ipc | Baseline true in ProductionComposition; unchanged |
| 50 | voice.streaming_pcm | Baseline false; unchanged |
| 51 | cosyvoice_local | Baseline false; unchanged |
| 52 | Other capability | None added |
| 53 | Rust Audio | Unchanged; no new-stage integration smoke |
| 54 | Live2D lip sync | Unchanged; no new-stage integration smoke |
| 55 | Offline Local production smoke | NOT RUN / NOT IMPLEMENTED |
| 56 | Edge calls in Local smoke | N/A, no Local smoke; do not represent no smoke as a successful zero-call gate |
| 57 | Remote calls | No requests this audit; production Local zero-call gate NOT RUN |
| 58 | Cold Voice ready | NOT RUN; previous feasibility timing not production acceptance |
| 59 | First synthesis | NOT RUN |
| 60 | 16-char warm min/median/max | NOT RUN |
| 61 | 16-char RTF | NOT RUN |
| 62 | 52-char warm min/median/max | NOT RUN |
| 63 | 52-char RTF | NOT RUN |
| 64 | 109-char warm min/median/max | NOT RUN |
| 65 | 109-char RTF | NOT RUN |
| 66 | Terminal to audio-ready | NOT RUN |
| 67 | Stop Voice latency | NOT RUN |
| 68 | RAM | No new-stage production measurement |
| 69 | CPU | No new-stage production measurement |
| 70 | GPU | No new-stage production measurement |
| 71 | VRAM | No new-stage production measurement |
| 72 | LLM baseline tok/s | NOT RUN this stage |
| 73 | Local Voice resident tok/s | NOT RUN |
| 74 | Post-TTS tok/s | NOT RUN |
| 75 | First-token regression | NOT RUN this stage |
| 76 | Live2D FPS | NOT RUN this stage |
| 77 | 50-request soak | NOT RUN on a production Local path |
| 78 | Threads | No new Voice runtime; no growth test this stage |
| 79 | Handles | No new Voice runtime; no growth test this stage |
| 80 | Temp cleanup | No production temp files created; old ignored evidence retained |
| 81 | Residual processes | No process started/killed by this audit |
| 82 | Python tests | Not rerun for documentation-only Gate stop |
| 83 | Rust tests | Not rerun; source unchanged |
| 84 | Frontend tests | Not rerun; source unchanged |
| 85 | Voice tests | Not rerun; source unchanged |
| 86 | Audio tests | Not rerun; source unchanged |
| 87 | Live2D tests | Not rerun; source unchanged |
| 88 | Local Model regression | No source/runtime/model changes; no new smoke claimed |
| 89 | Legacy regression | No changes; no new smoke claimed |
| 90 | compileall | Not rerun; zero Python edits |
| 91 | Release build | NOT RUN, no production integration |
| 92 | git diff --check | PASS; new audit no-index whitespace check also PASS |
| 93 | Manual listening | NOT MANUALLY VERIFIED |
| 94 | Single speaker | Existing selected model has one fixed female speaker |
| 95 | Voice cloning | Not supported by selected model; no feature added |
| 96 | English/punctuation | Previous feasibility limitations retained; no lexicon/rule patch |
| 97 | Known limitations | GPL compliance policy/complete binary notices/provenance gate unresolved; production lifecycle and cancellation not implemented |
| 98 | Next step | Owner selects GPL-compliant isolated Host or separately authorized no-GPL build; close License Gate before resuming V4-7B.3 |

Stage V4-7B.3 — Offline Local Voice Runtime Integration: **NOT PASS**.
Gate 1: **LICENSE BLOCKER**. Stop before implementation/commit/push.

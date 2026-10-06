# V4-7B.3B Offline Local Voice Runtime Integration

Stage V4-7B.3B — Offline Local Voice Runtime Integration: **PASS**.

Evidence date: 2026-10-07, Windows x64, Ryzen 9 7940HX / Radeon RX 7600 XT. This report supersedes integration conclusions in preserved historical feasibility documents; their source bytes and stage-specific statuses remain unchanged.

The engineering gates passed. Human listening remains **NOT MANUALLY VERIFIED**. Git closure is recorded after the enclosing commit/push in the local closure artifact and the delivered final report.

## Required 103-field report

| # | Field | Result / evidence |
|---:|---|---|
| 1 | Branch | refactor/aurora-v4 |
| 2 | Starting HEAD | dd1ceb24b59d2ad26a934055c7d6554528828bbb |
| 3 | Final HEAD | Enclosing commit; exact post-push SHA is recorded in tests/output/v47b3b-git-closure.json and the delivered final report. |
| 4 | Commit | Enclosing commit; exact post-push SHA is recorded in tests/output/v47b3b-git-closure.json and the delivered final report. |
| 5 | Commit message | feat(v4): add supervised offline local voice |
| 6 | Local / Remote | Baseline equal; post-push equality is recorded in the Git closure artifact. |
| 7 | Working tree | 35 selected formal files; 12 historical B files remain untracked. Git closure follows this report. |
| 8 | 23 original untracked | A: 11 preserved byte-identical formal docs/build/audit files selected for commit. B: 12 byte-identical historical files preserved untracked. C: none among original 23. Nothing deleted. |
| 9 | Modified / added file count | 13 modified + 22 added = 35 selected formal files, including 11 historical A files. |
| 10 | Voice Host route | Independent Windows x64 C++17 host / minimal audited sherpa C ABI; CMake MSVC /MD. Broad official TTS DLL rejected by hash. |
| 11 | Host architecture | Headless, long-running, one inference worker and responsive control thread. Engine owns normalization, tokens, synthesis, WAV and metadata only. |
| 12 | LocalVoiceSupervisor | Rust Desktop sole lifecycle owner; Python owns no runtime processes. |
| 13 | State machine | STOPPED → STARTING → LOADING_MODEL → READY; asset/host errors DEGRADED, retry exhaustion FAILED, shutdown STOPPING → STOPPED. |
| 14 | EAGER / LAZY | BACKGROUND EAGER. Observed frontend present 673.0 ms; Chat ready 3628.8 ms. Disabled frontend 784.9 ms. DOM/CDP observation, not paint timing. |
| 15 | Asset discovery | %LOCALAPPDATA%/Aurora/runtime/voice/sherpa-melo-v1; absolute private developer override; exact SHA-256 pins before spawn. |
| 16 | Model discovery | %LOCALAPPDATA%/Aurora/models/melo-zh-en-v2/model.onnx; bounded exact asset names and pinned bytes. |
| 17 | Lexicon discovery | Pinned lexicon.txt and tokens.txt, date.fst then number.fst. Engine initialization before READY. |
| 18 | IPC | Rust ↔ native inherited stdin/stdout pipes; Python ↔ Rust bounded authenticated HTTP on 127.0.0.1 only. Complete WAV bytes, no arbitrary output path. |
| 19 | Dynamic port | OS-assigned loopback port 0; native child has no listening socket. |
| 20 | Authentication | Random 64-character token per Desktop broker lifecycle, inherited by Python only. Broker survives bounded native restarts; rotates on next broker start. |
| 21 | Readiness | loading/ready emitted by native engine after model, tokens and lexicon initialize; READY is not inferred from process existence. No startup synthesis. |
| 22 | Health | Native control-thread health command every 5 s; numeric resource snapshots, process exit monitoring every 200 ms; inference remains serial. |
| 23 | Crash detection | Child exit/load deadline detection independent of Chat; old epochs suppressed. |
| 24 | Restart policy | At most 2 automatic retries per lifecycle, 1 s then 3 s cooldown; third forced failure reaches FAILED. Actual native test passed. |
| 25 | Job Object | Existing Windows JobGuard with kill-on-job-close; actual abnormal Desktop exit left 0 owned processes. |
| 26 | Shutdown | Graceful shutdown request, wait ≤3 s, kill/wait bounded fallback; worker and WAV cleanup. Abrupt disk orphan reaped on next start. |
| 27 | Local Provider | LocalSherpaMeloProvider. Private client, timeout, logical cancellation, validated PCM16 WAV result; no process ownership. |
| 28 | TTSRouter routing | Existing router/composition extended with local_sherpa_melo. Edge and Remote retained, Fake remains injectable for tests. |
| 29 | Edge role | Network provider retained; default and existing explicit Edge selection preserved. |
| 30 | Remote role | remote_cosyvoice compatibility / legacy only; no old laptop required for Local path. |
| 31 | LocalCosyVoiceProvider | NOT IMPLEMENTED; no CosyVoice-local route or dependencies added. |
| 32 | Default migration | No forced migration; existing provider value and current Edge default unchanged. |
| 33 | Fallback | No automatic fallback introduced. Local smoke has fallback off; unavailable Local is diagnosed, never silently calls Edge. |
| 34 | Cancellation | A synthesis: immediate logical cancel, eventual discard. B playback: existing Audio stop. C Chat cancel before TTS: existing terminal gating. D shutdown: bounded lifecycle. E crash: pending failure. F stale: discard/cleanup. |
| 35 | Stale suppression | Existing generation ID + preparing revision hashed only as transport-safe key; existing playback identity and connection epoch retained. No parallel identity architecture. |
| 36 | Concurrency | One native synthesis worker; pending or native busy request rejected deterministically. Actual concurrent request test returns VOICE_BUSY. |
| 37 | CPU threads | ORT num_threads=4, CPU provider. Process thread count includes control/worker/OS threads and is not the inference thread setting. |
| 38 | Temp root | %LOCALAPPDATA%/Aurora/cache/local-voice/session-* with owner marker and exclusive Windows lease; Audio retains its existing independent request root. |
| 39 | Artifact cleanup | Host writes complete <safe-key>.wav. Rust reads bounded owned bytes then deletes. Python/existing Audio owns handoff/play receipt/Stop cleanup. Stale/crash/error/shutdown remove owned WAVs. Unknown/link/unowned content preserved. |
| 40 | Rust Audio | Existing rodio/cpal/WASAPI unchanged; real Local WAV decoded and played through production handoff. |
| 41 | Lip Sync | Existing real sample RMS → envelope → Live2D ParamMouthOpenY. Actual native GPU frames include nonzero mouth and zero; no second lip-sync implementation. |
| 42 | Stop playback | PASS; median 55.7 ms, max 123.4 ms; idle then mouth=0. |
| 43 | Stop synthesis | PASS; 59.9 ms to idle. Native old request finished but discarded counter increased; no old playback across 7 s observation. |
| 44 | Host crash | Actual native process forcibly killed during Release session; Desktop/Chat/4B/Live2D stayed working, conversation persisted. |
| 45 | Recovery | PASS; 4352.2 ms measured through intervening completed Chat and ready observation, then real synthesis/natural completion. Not isolated minimum restart latency. |
| 46 | Missing runtime | Release PASS; DEGRADED / VOICE_RUNTIME_MISSING, Chat completed, Voice unavailable, 0 Edge/Remote. |
| 47 | Missing model | Release PASS; DEGRADED / VOICE_MODEL_MISSING; same isolation. |
| 48 | Missing lexicon | Release PASS; DEGRADED / VOICE_LEXICON_MISSING; same isolation. |
| 49 | Corrupt model | Release PASS; DEGRADED / VOICE_ASSET_HASH_MISMATCH before native spawn; original model preserved. |
| 50 | Timeout | Provider timeout tests plus real native 50 ms request deadline return VOICE_TIMEOUT, cancel/discard and owned WAV cleanup. |
| 51 | Capabilities | voice.ipc=true; voice.streaming_pcm=false; cosyvoice_local=false. No inaccurate LocalCosyVoice capability; complete-artifact Local route available via settings/runtime. |
| 52 | GPL dependency scan | Production four PE binaries audited: imports/exports/strings + recursive closure; excluded runtime symbols 0. No known GPL runtime dependency found; generic model-format piper string distinguished from piper-phonemize. |
| 53 | MPL-2.0 obligations | ORT exact-version notices include Eigen MPL-2.0: covered-source availability and applicable notices/source obligations before distribution. Not a legal clearance. |
| 54 | Attribution manifest | native-voice/assets.json: name/version/hash/license/purpose/bytes, model provenance, Apache/MIT/CMU notices, complete ORT notices, Microsoft redistribution obligations. |
| 55 | Runtime/model hashes | All production assets checked against manifest; original feasibility hashes unchanged. Full SHA-256 table below. |
| 56 | Cold ready | Host reported ready 2904.4 ms; launch-to-observed READY 3924.4 ms. Filesystem cache was not purged; cold process start, not disk-cold benchmark. |
| 57 | First synthesis | 549.0 ms; actual first post-load request (not one of warm runs). |
| 58 | 16-char benchmark | 0.872 s median / 5 runs |
| 59 | 16-char RTF | 0.309 median; max 0.333 |
| 60 | 52-char benchmark | 2.593 s median / 5 runs |
| 61 | 52-char RTF | 0.294 median; max 0.299 |
| 62 | 109-char benchmark | 5.513 s median / 5 runs |
| 63 | 109-char RTF | 0.304 median; max 0.310 |
| 64 | Terminal → audio ready | Short warm median 903.4 ms, max 932.1 ms; all <2 s. Observed production speaking receipt, not acoustic onset. |
| 65 | Stop latency | Playback median 55.7 ms; synthesis 59.9 ms. Measured UI click → idle; mouth-zero separately asserted. |
| 66 | RAM | Private bytes and working sets sampled from actual owned processes; per-length arena high-water analysis below. Shared RAM totals are not added as unique physical usage. |
| 67 | CPU | Process counters measured; 100%=one logical CPU (7940HX 16 cores/32 threads). During-synthesis and idle samples below; isolated short windows, not whole-run average. |
| 68 | GPU | Vulkan 4B and D3D11 Live2D counters measured; Voice is CPU-only. Missing per-process counter values recorded as unavailable, not zero. |
| 69 | VRAM | Actual dedicated GPU process counters below; Voice counter unavailable. CPU-only inference is established by runtime configuration/dependency graph, not missing counters. |
| 70 | LLM baseline tok/s | 70.905 median / 5 disabled chats |
| 71 | Voice resident tok/s | 70.938 median / 5 chats; change 0.05% |
| 72 | Post-TTS tok/s | 68.712 median / 5 chats; change -3.09%; <15% regression. |
| 73 | First-token behavior | Frontend first delta and native model content timings recorded per request; medians below. First request retained separately; no claim of acoustic latency. |
| 74 | Live2D FPS | 57.86–58.00 in resource samples; real visible native host, mouth changes and resets captured. |
| 75 | 50/10/5 soak | PASS: exact 50×16, 10×52, 5×109 chars; complete WAV/Audio receipt, real mouth>0.05, Stop→mouth=0 each request, Host stays healthy; all RTF<1. |
| 76 | Handle drift | Per-length first/last values below; no increasing handle trend observed. |
| 77 | Thread drift | Per-length first/last values below; no increasing thread trend observed. |
| 78 | RAM drift | Length-dependent ORT arena allocation is retained. Short group plateaus; medium/long bounded high-water changes below. No sustained leak observed in these 65 requests; no unbounded-duration guarantee. |
| 79 | Temp residue | Normal exit 0 sessions/WAVs. Abnormal exit left one marked session; next startup observed it and removed it. This is deferred disk cleanup, not immediate abnormal-exit deletion. |
| 80 | Process residue | 0 owned survivors after normal, native crash/recovery, all four missing-asset cases and abnormal Desktop exit; ownership matched PID plus creation time. |
| 81 | Python tests | 1037 passed, 3 skipped opt-in legacy Edge/real-STT E2E cases (AURORA_RUN_REAL_VOICE_E2E/audio fixture not enabled). Collection excludes ignored tests/output third-party sources; isolated external basetemp. Real Local offline acceptance executed separately. |
| 82 | v4 tests | 185 passed: backend/protocol/Voice/Audio handoff/direct local provider/conversation/persistence/settings. |
| 83 | Rust Desktop tests | 65 passed, 2 ignored. Native Voice opt-in gate separately executed (7 passed including its 6 ordinary tests). Other ignored test requires legacy Ollama, outside offline acceptance. |
| 84 | Voice Host tests | 7 Rust supervisor tests including actual audited native assets: synthesis, busy, cancel/discard, timeout, 3 forced host crashes → 2 retries → FAILED, cleanup; production Release exercises same host. |
| 85 | Frontend tests | 34 passed; TypeScript/Vite production build passed. |
| 86 | Voice tests | New provider 6 cases plus existing source suite and v4 Voice 16 cases; identity/options/WAV/errors/cancel/timeout/default migration/schema covered. |
| 87 | Audio tests | Rust Audio 9 + envelope 2 passed in Desktop suite; v4 Rust-playback tests passed; actual WASAPI/Local playback and Stop/natural EOF tested. |
| 88 | Live2D tests | Native Rust host 4 passed; native CTest avatar_parameter_policy 1 passed; Desktop Live2D tests and actual GPU mouth/reset evidence passed. |
| 89 | Local Model regression | Existing supervisor tests passed; actual built-in Qwen3.5-4B Q4_K_M resident streaming in all smoke cases; throughput threshold passed. |
| 90 | Conversation regression | Persistence tests passed; all real chats completed/persisted including after Host crash. Isolated smoke user directory protects user conversations. |
| 91 | Settings regression | Single Python authority; Local enum validated across schema/Python/Rust/frontend; existing Edge default and selections preserved; round-trip tests passed. |
| 92 | Legacy regression | Supported existing source tests included; Edge/Remote/Fake implementation retained. No real network TTS acceptance claimed. |
| 93 | compileall | 282 selected formal Python files compiled with compileall after staging, all passed; generated caches ignored. |
| 94 | Release build | pnpm desktop tauri build --no-bundle PASS; custom-protocol production frontend. Native CMake Release PASS. No packaging/installer performed. Existing dead-code/linker notices retained. |
| 95 | Offline Release smoke | PASS: final actual Release EXE + production Python sidecar + built-in 4B + audited native Voice + existing Rust Audio + visible native Live2D. No provider/sidecar substitution, Ollama or LM Studio. |
| 96 | Edge request count | 0 |
| 97 | Remote request count | 0 |
| 98 | Manual listening | NOT MANUALLY VERIFIED. Automated source/runtime/audio/GPU evidence is not human listening or owner visual acceptance. |
| 99 | Single speaker | Fixed melo-fixed-0, API sid0 maps to model sid1; no voice cloning. |
| 100 | English / punctuation | Finite lexicon coverage; rare characters, English variants and special punctuation inherit V4-7B.3A limits. Chinese acceptance corpus passed; no universal pronunciation claim. |
| 101 | Legal review | LEGAL REVIEW RECOMMENDED. No absolute legal-safety claim; no distribution performed. |
| 102 | Known limits | Complete WAV only (no PCM streaming). Native ONNX inference may finish after Stop. Busy rejected during cancellation tail. Finite smoke/soak windows and single-device evidence; external assets required, no installer. |
| 103 | Next stage recommendation | Human listening acceptance and exact-distribution license/source closure should precede later release packaging. Stage stops here; no later feature work automatically started. |

## Warm performance (exact text lengths; 5 each)

| Chars | Median synthesis s | Median RTF | Max RTF | Median terminal→ready ms |
|---:|---:|---:|---:|---:|
| 16 | 0.872 | 0.309 | 0.333 | 903.4 |
| 52 | 2.593 | 0.294 | 0.299 | 2660.1 |
| 109 | 5.513 | 0.304 | 0.310 | 5584.9 |

## LLM comparison

| Condition | Median tok/s | Median frontend first delta ms | Samples |
|---|---:|---:|---:|
| Voice disabled | 70.905 | 81.6 | 5 |
| Voice READY resident | 70.938 | 96.6 | 5 |
| Post TTS | 68.712 | 89.4 | 5 |

## Finite soak resource drift

| Chars / count | Private bytes first → last | Handles first → last | Threads first → last | Max RTF |
|---|---|---|---|---:|
| 16 / 50 | 423260160 → 423223296 | 177 → 176 | 8 → 7 | 0.340 |
| 52 / 10 | 562454528 → 562454528 | 176 → 176 | 7 → 7 | 0.309 |
| 109 / 5 | 564207616 → 564137984 | 176 → 174 | 7 → 5 | 0.306 |

## Actual process resource samples

CPU is one-core percent; GPU engine values sum measured engines and do not imply whole-device occupancy. N/A means the process counter was unavailable. RAM columns are MiB.

| Phase | Process | Working set | CPU % | GPU engine % | Dedicated VRAM |
|---|---|---:|---:|---:|---:|
| resident_idle | aurora-live2d-host | 79.98 | 1.22 | 0.34 | 31.95 |
| resident_idle | aurora-local-voice-host | 293.41 | 0.00 | N/A | N/A |
| resident_idle | llama-server | 3099.63 | 0.00 | 0.00 | 2876.68 |
| during_synthesis | aurora-live2d-host | 78.80 | 6.07 | 0.36 | 31.95 |
| during_synthesis | aurora-local-voice-host | 465.04 | 371.30 | N/A | N/A |
| during_synthesis | llama-server | 3413.05 | 0.00 | 0.00 | 2904.93 |
| before_soak | aurora-live2d-host | 78.75 | 2.43 | 0.30 | 31.95 |
| before_soak | aurora-local-voice-host | 347.45 | 0.00 | N/A | N/A |
| before_soak | llama-server | 3519.32 | 9.71 | 23.75 | 2909.55 |
| after_soak | aurora-live2d-host | 78.74 | 6.10 | 0.32 | 31.95 |
| after_soak | aurora-local-voice-host | 466.16 | 0.00 | N/A | N/A |
| after_soak | llama-server | 3519.90 | 0.00 | 0.00 | 2909.55 |
| post_tts | aurora-live2d-host | 78.74 | 3.64 | 0.38 | 31.95 |
| post_tts | aurora-local-voice-host | 466.16 | 0.00 | N/A | N/A |
| post_tts | llama-server | 3525.57 | 0.00 | 0.00 | 2909.55 |

## Asset SHA-256 and obligations

| Asset | Version | SHA-256 | License | Purpose |
|---|---|---|---|---|
| aurora-local-voice-host.exe | aurora-1 | `9b901a02cd178565bec0efb5aa84c7d3152748857b05a30054f8c168e0c81fc4` | Aurora first-party | isolated synthesis host |
| sherpa-onnx-c-api.dll | sherpa-1.13.8-clean | `bb146780c7b946755810f28a5fb7dcf6321ae0d6bf18f7b507461a79c3396a3b` | Apache-2.0 with OpenFst and kaldifst notices | native CPU synthesis dependency |
| onnxruntime.dll | ORT-1.28.2 | `422d776ab0e3218260f7f628fcb84606aaa5c21116f720c8619a6da5e0b2e0f9` | MIT with exact-version transitive notices including Eigen MPL-2.0 | native CPU synthesis dependency |
| onnxruntime_providers_shared.dll | ORT-1.28.2 | `0190137dee4933261c065c5d030c3568a68c7aa43cad942b4726a07011738bc2` | MIT with exact-version transitive notices including Eigen MPL-2.0 | native CPU synthesis dependency |
| model.onnx | melo-vits-zh_en-v2 | `bf30582eb1b012250a35b1a4a80e7dfbcf8485e7bb9de0d95efbbeef0e4ad86d` | MIT | model/phoneme/lexicon data and attribution |
| tokens.txt | melo-vits-zh_en-v2 | `d18664a7e12bd7ea1022ddaf951e534e136815016c5a809d6b64156bffb4369d` | MIT | model/phoneme/lexicon data and attribution |
| lexicon.txt | melo-vits-zh_en-v2 | `7236884b02435ac5d10cf69b4be40a61b45aa676b5300f0e412f185748fee528` | MIT; generated lexicon includes CMU dictionary notice | model/phoneme/lexicon data and attribution |
| date.fst | aishell3-vits-low-2024-04-06@57345c0 | `eb8aa079ae3cb81d8f4404992f39d61a0cb990947512b5b8d1e54d1f6980e718` | Apache-2.0 | date/number normalization |
| number.fst | aishell3-vits-low-2024-04-06@57345c0 | `743f402181fcfebf76cc2f0546b71fa26476e626fbe4e460fb7b4c3a7a8bd5bd` | Apache-2.0 | date/number normalization |
| LICENSE | melo-vits-zh_en-v2 | `88a50e5a02bbc2a5c2f084dc19da751aa97b1690f5fda76cd8005c8634d1ca70` | MIT | model/phoneme/lexicon data and attribution |
| notices/KALDIFST-LICENSE | pinned exact source version | `a682d6efd1ee5dee08a8e405c233c2c198ea70ae0718129daa83ab58cfe31c5d` | component license/third-party notices | attribution and future distribution license closure |
| notices/OPENFST-COPYING | pinned exact source version | `4300529197035fd3452350718a0b8cee984e9412c9932d7f35fcde849fc97a4b` | component license/third-party notices | attribution and future distribution license closure |
| notices/ORT-LICENSE | pinned exact source version | `2f07c72751aed99790b8a4869cf2311df85a860b22ded05fa22803587a48922c` | component license/third-party notices | attribution and future distribution license closure |
| notices/ORT-ThirdPartyNotices.txt | pinned exact source version | `0e07b95f3a8d6230037707c5c4a2b554d12c4cb67369669ac255635528ffcee2` | component license/third-party notices | attribution and future distribution license closure |
| notices/SHERPA-LICENSE | pinned exact source version | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` | component license/third-party notices | attribution and future distribution license closure |

## Original 23-file closure

All 23 hashes rechecked unchanged. A files are selected formal sources; B files remain untracked. No original file deleted or overwritten. External runtime/model/binary/output files are C and remain outside Git.

| Category | Original path | Final disposition |
|---|---|---|
| B | `prototype/aurora-v4/desktop/tests/clean_melo_feasibility.mjs` | preserve historical experiment untracked; no deletion |
| B | `prototype/aurora-v4/desktop/tests/local_voice_feasibility.mjs` | preserve historical experiment untracked; no deletion |
| B | `prototype/aurora-v4/desktop/tests/local_voice_performance.mjs` | preserve historical experiment untracked; no deletion |
| B | `prototype/aurora-v4/desktop/tests/sherpa_melo_feasibility.mjs` | preserve historical experiment untracked; no deletion |
| A | `prototype/aurora-v4/docs/LICENSE_CLEAN_MELO_FEASIBILITY.md` | retain as formal audit/reproducible build source |
| A | `prototype/aurora-v4/docs/LOCAL_VOICE_LICENSE_CLOSURE.md` | retain as formal audit/reproducible build source |
| A | `prototype/aurora-v4/docs/LOCAL_VOICE_PERFORMANCE_FEASIBILITY.md` | retain as formal audit/reproducible build source |
| A | `prototype/aurora-v4/docs/LOCAL_VOICE_RUNTIME_AUDIT.md` | retain as formal audit/reproducible build source |
| A | `prototype/aurora-v4/docs/SHERPA_MELO_LOCAL_VOICE_FEASIBILITY.md` | retain as formal audit/reproducible build source |
| A | `scripts/audit_clean_melo.py` | retain as formal audit/reproducible build source |
| A | `scripts/benchmark_sherpa_melo.cpp` | retain as formal audit/reproducible build source |
| B | `scripts/probe_clean_melo.py` | preserve historical experiment untracked; no deletion |
| B | `scripts/probe_local_cosyvoice.py` | preserve historical experiment untracked; no deletion |
| B | `scripts/probe_permissive_phonemizer.py` | preserve historical experiment untracked; no deletion |
| B | `scripts/probe_sherpa_melo.py` | preserve historical experiment untracked; no deletion |
| A | `scripts/sherpa_melo_clean/CMakeLists.txt` | retain as formal audit/reproducible build source |
| A | `scripts/sherpa_melo_clean/clean_c_api.cpp` | retain as formal audit/reproducible build source |
| A | `scripts/sherpa_melo_clean/cpu_session.cpp` | retain as formal audit/reproducible build source |
| A | `scripts/sherpa_melo_clean/oracle_trace.cpp` | retain as formal audit/reproducible build source |
| B | `scripts/voice_feasibility_sidecar/production_sidecar/server.py` | preserve historical experiment untracked; no deletion |
| B | `tests/test_clean_melo_feasibility.py` | preserve historical experiment untracked; no deletion |
| B | `tests/test_sherpa_melo_probe.py` | preserve historical experiment untracked; no deletion |
| B | `tests/test_voice_feasibility_fixture.py` | preserve historical experiment untracked; no deletion |

## Local evidence artifacts

Raw outputs stay ignored and are not claimed as portable checked-in binaries. Production harness/build recipes and manifest are checked in. Automated captures are distinct from manual acceptance.

- Final 65-run Release path: `tests/output/v47b3b-offline/run-C6E6DY/report.json` (SHA-256 `d3fd0716de1e95dca39073a7591241b4568173a7c85ef83482fd37809e9ad4af`).
- Voice-disabled control: `tests/output/v47b3b-offline/run-uDpamg/report.json` (SHA-256 `f8459fe0caa3183af039bb1cbe5af04e070cb5b7a3eb8eb020ca61d821a9c22c`).
- Abrupt Desktop Job Object: `tests/output/v47b3b-offline/run-YI5zGE/report.json` (SHA-256 `b4a45f3ffde743a8223c9d57cc60fb4a4a0d5886ae1f6489fad12bfc8618f802`).
- Missing runtime: `tests/output/v47b3b-offline/run-94RNOz/report.json` (SHA-256 `f52201c407ecb567335107f3c597173814e5f0fe15b19f1367a8980a6008f22e`).
- Missing model: `tests/output/v47b3b-offline/run-xlDF5g/report.json` (SHA-256 `dd6c05967612af1284a5e27bc1e8c02c2f51927c7db4fcba3e2fc077af1bc8c5`).
- Missing lexicon: `tests/output/v47b3b-offline/run-B9RkL7/report.json` (SHA-256 `9cfc3d78458c549a9a87fef0068b03be93adaf8c75b7ba4ea1e9bf24aa05ded6`).
- Missing corrupt: `tests/output/v47b3b-offline/run-UbgQTU/report.json` (SHA-256 `bbde1886230fc4315115cbe07c3c817f7c3710c80d832230f4c9d48dfbbb4747`).

Final Release executable SHA-256: `ee5a92a4999b30c6ac711c17c0d02da93740b17cf48c764c7ea6064d91e2fedf`.

Final run provider counters: Local=85, Edge=0, Remote=0. Native GPU mouth frame maximum=0.5484; zero captured and each playback reset asserted.

Earlier harness attempts are preserved: a plain cargo Release build loaded the development URL, and an empty-prompt Send-button condition was too strict. Correct Tauri custom-protocol build and corrected readiness observation passed. Those failed harness attempts are not used as acceptance evidence.

Stage boundary: commit/push/verify this stage, then stop. WIP Glass remains adeee5aa4949a47e62ba9f7a2cb708f50a361970; no merge, packaging or later-stage implementation.

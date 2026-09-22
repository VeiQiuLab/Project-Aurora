# V4-6A validation — 2026-09-22

## Gate and scope

The initial gate passed on `refactor/aurora-v4` at
`e5effb9ef7176abab41c1566398732833fcf9cf6`, clean and equal to origin.
`wip/v4-5b1-edge-optics-experiment` remains at
`adeee5aa4949a47e62ba9f7a2cb708f50a361970`.

Implementation is limited to the isolated V4 desktop/sidecar/contracts,
runtime manifest/bootstrap, tests/docs, and one `.gitignore` entry.
No Stable `modules/`, default settings, Voice Node, speech execution, streaming
audio protocol, GPU driver or model file changes.

## Automated gates

| Gate | Result |
| --- | --- |
| V4 production sidecar + contracts | 155 passed |
| Rust unit/integration tests | 32 passed, 1 explicitly ignored legacy Ollama smoke |
| Frontend unit tests | 31 passed |
| Stable full source suite | 976 passed, 3 skipped |
| Python compileall | 262 tracked/new source files passed |
| default_settings JSON | Valid, file unchanged |
| Frontend TypeScript/Vite and Tauri Release build | Passed |
| UI fixture smoke | Passed: descriptors, conflict/offline/save/reload, rendering fallback |
| Geometry fixture | 20 groups passed; simulated 100/125/150/200% device scale |
| Legacy offline Release/WebView2 smoke | Passed: settings/save/reload, single-instance and native close |
| Diff whitespace | `git diff --check` passed using the repository's CRLF policy |

Source pytest excludes ignored `tests/output`, which contains unpacked historical
distributions and third-party test suites, not source tests. Running collection
over that artifact directory caused third-party import/duplicate-module errors;
no dependency or source change was made to accommodate those artifacts.

Unit tests use fixture executable/HTTP servers and do not load a real model.
Lifecycle tests cover readiness/auth, failed spawn/model discovery, crash/restart,
Job Object teardown, duplicate start, shutdown while loading, stale epochs, and
Python-start failure cleanup. Deterministic tests additionally cover shutdown
before the model start lock is acquired and stale owners unable to affect N+1.

Provider tests include SSE mapping/usage, malformed/incomplete/HTTP-error results,
blocked-body and blocked-header cancellation, timeout as failure, snapshot
restoration, request isolation/recovery, title mapping, foreground preemption,
and publication invalidation before transport abort. Diagnostics never retain
reasoning, response bodies, tokens or filesystem paths.

## Actual Windows/Vulkan/Release evidence

Environment: Windows, AMD Radeon RX 7600 XT, Vulkan0 reported 8176 MiB total
(7365 MiB free at the initial feasibility check). Official runtime b10964 was
installed independently of LM Studio and its checked bootstrap was executed.
Ollama was absent from PATH and no Ollama or LM Studio process was running.

`desktop/tests/local_runtime.mjs` launched the actual Release EXE with no provider
or backend-selection override, so it verified normal production/built-in defaults.
CDP was enabled only for the test's isolated WebView2 child. Synthetic data roots
were used; no real conversation, memory or settings content was mutated.

Passed:

- STARTING → actual model READY; Settings open/close during load.
- Real incremental chat, first delta earlier than terminal, no reasoning output.
- Same runtime PID reused across turns and a second desktop launch.
- Memory count 1, Knowledge count 1, RAG results 2 and enabled Persona in the
  fixture context. Second-turn history is transmitted and the test word recalled.
- Completed conversations saved and restored after WebView reload.
- Title persisted with `title_source=llm`, using the built-in runtime rather than
  a rule-only fallback. A rapid new foreground turn deferred the pending title.
- Stop after first content: cancelled, worker exited, active response false,
  then immediate next-turn recovery.
- Kill the verified owned model PID during generation: explicit
  `PROVIDER_UNAVAILABLE` failure (or registry `backend_lost` if its monitor wins),
  no successful partial result, Desktop and Python remain alive.
- Manual/internal restart replaces runtime PID, reloads and recovers chat.
- Normal desktop close during generation: no remaining owned children.
- `--kill-desktop` process-termination test during generation: Job Objects remove
  Python and llama-server; no remaining owned children or model handle.
- Original model size 2,707,513,696 and mtime_ns 1789384486659629200 preserved.
  Exclusive read open succeeds after exit. No copy, modification or second model.

Repeated-run timings (one representative run; short synthetic answers):

| Measurement | Observed |
| --- | --- |
| Fresh runtime process → loaded/API READY | 2509.7 ms |
| Desktop launch → full ready snapshot | 3231.5 ms |
| First turn: frontend first content / provider first content | 210.3 / 203.0 ms |
| Warm 1: frontend / provider first content | 272.1 / 235.0 ms |
| Warm 2: frontend / provider first content | 188.7 / 156.0 ms |
| Warm 3: frontend / provider first content | 156.0 / 157.0 ms |
| Prompt evaluation, first + warm ×3 | 194.270 / 196.192 / 143.378 / 124.720 ms |
| Derived completion tokens/s, first + warm ×3 | 77.9 / 80.6 / 97.1 / 97.0 |
| UI Stop → terminal | 36.8 ms; other passes approximately 12–45 ms |
| Runtime working set / private committed bytes | 3,462,139,904 / 4,266,659,840 |
| Runtime dedicated / shared GPU bytes | 3,114,192,896 / 18,227,200 |
| Automatic offload | 33/33 layers (observed, not configured as a constant) |
| Vulkan model buffer | 2571.63 MiB |
| KV / recurrent state buffers | 128.00 / 50.25 MiB |
| Vulkan compute buffer | 73.02 MiB |

The first-turn measurement is process-cold, not a reboot/OS-cache-cold benchmark.
The initial standalone feasibility load was about 5.17 s; subsequent loads were
usually 2.4–3.3 s. Eager loading trades this launch time and resident memory for
shorter first-chat delay. Tokens/s above is `completion_tokens / predicted_ms`,
derived from very short outputs, not a sustained throughput claim or SLA.
Independent frontend/Python clocks and their timer resolution can slightly
reverse nearby timing values; comparisons within one clock are the reliable ones.
No comparison to the old 9B/Ollama model is asserted.

Raw synthetic reports reside under ignored `tests/output/v46a-local`; the normal
and forced-exit reports record metrics and state, not generated text. UI-only
artifacts are in the pre-existing ignored V4-5B test-output locations.

## Boundaries and remaining limitations

- **Passed:** built-in conversation without installed/running Ollama and without
  LM Studio running; real transport, context, history, title, cancellation,
  failure/recovery and both exit mechanisms.
- **Acceptable:** developer bootstrap rather than installer; public loopback
  `/health` upstream; up to 5-second pre-registration TCP-connect timeout; fixed
  conservative 4096 context; manual restart; optional old embedding service may
  use its existing retrieval fallback. No automatic provider/model substitution.
- **No known blocker** for this Windows text-chat runtime stage after lifecycle
  review and regression. Rust emits a reserved-Degraded dead-code warning and
  an existing unused test-helper warning; neither is a build failure.
- **Not verified here:** clean-machine installer, other GPUs/models, long-context
  or OOM stress, true reboot-cold benchmark, multimodal projection, and manual
  native IME/drag/visual-smoothness acceptance. Browser fixtures and automated
  real WebView2 are explicitly distinguished from manual native GUI acceptance.

No Voice migration, audio streaming, B-3, RAG tuning, model market or next phase
was started. See [architecture and reproducible commands](V4_6A_LOCAL_RUNTIME.md).

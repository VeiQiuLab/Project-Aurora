# V4-3A validation — 2026-09-14

Branch: refactor/aurora-v4. Starting local/origin checkpoint:
79c0532b14562d71b9724ee7ab903fc2fddaa11e (accepted minimal desktop UI).
Scope: prototype/aurora-v4 only. Stable modules/widgets/main/default settings,
voice transport and accepted stylesheet: **zero changes**.

## Automated evidence

- Python sidecar + IPC contract: **48 passed** (mock 6, production 18, contract 24).
- Rust gateway/protocol/registry: **13 passed**, 1 opt-in real smoke ignored by
  default. Includes mock stream/cancel/crash/restart, production offline health,
  restart identity rotation, stale epoch rejection, startup/shutdown race and
  frontend private-field rejection. Opt-in real smoke separately passed.
- Frontend policy/conversation/IME tests: **9 passed**.
- Stable targeted regression: **86 passed**: Ollama policy, chat cancellation/
  turn gate, first-token/transport/pre-LLM diagnostics, settings migration/
  validation and memory/RAG settings. All test settings in disposable paths.
- compileall: **243 repository Python files passed**, tracked plus new source;
  excludes ignored dependency environments/build artifacts.
- TypeScript/Vite build and Tauri release no-bundle build: passed.
- git diff --check: passed. LF/CRLF notices are Git conversion warnings only.
- Contract examples: original 19 + production 2 validated against executable
  rules and Draft 2020-12 schema. No v2; optional health diagnostics documented.

Test environment: actual Python 3.12.14, websockets 17.1. Schema tests needed
jsonschema (installed in repo development venv; requirements-dev.txt records it).
Initial Stable regression hit an existing pytest-of-X temp-directory ACL error,
not a source failure; rerun with a new explicit basetemp passed all 86. No Stable
code was changed and therefore full source pytest was not required for this stage.

## Real Windows/Ollama evidence

Ran smoke_production_sidecar.py against the actual repository Settings snapshot
and built Windows desktop, without synthetic health data. Ollama was initially
offline: real composition reached DEGRADED, stayed alive, and crash/restart/
normal/forced desktop exit worked. Once the existing service was available,
online smoke succeeded. Sidecar has no auto-start behavior.

- Ollama 0.34.0, configured HTTP origin loopback:11434.
- Actual configured model qwen3.5:9b found in GET /api/tags.
- Actual settings_status=loaded; thinking off / think=false / keep_alive=30m,
  from the production policy, not a parallel resolver.
- Production state READY; chat_enabled=false; no generation command issued.
- GET /api/ps before = **[]**, after = **[]**. No resident model introduced by
  health, no 9B GPU load. This is model-inventory evidence, not a GPU profiler.
- Settings byte hash before/after equal; no production settings/log migration.
- Rust real gateway PID 39336 before deliberately crashing it; restart used a
  different PID, port, token and instance, tested by assertions. Old epoch rejected.
- Built desktop normal exit: owned Python PID 32468, no orphan after WM_CLOSE.
- Built desktop forced exit: owned Python PID 37404, no orphan after killing only
  desktop parent; Job Object reaped the sidecar.
- Both built desktop runs started from newly created non-repository temp cwd.
- Final process inspection found no Aurora v4 desktop/production sidecar residue.
- Stdout bootstrap-only checked by child integrations; stderr logs/tracebacks
  work. Rust diagnostics never expose IPC credentials/PID/port to frontend.

One initial lifecycle smoke failure was a **test harness** issue: it sent WM_CLOSE
to all desktop-owned helper windows. Restricting the close to this process's
actual Aurora main window fixed the smoke; no product shutdown workaround was
introduced. The corrected normal and forced exit paths both passed.

## Measurements (single-machine observations, not performance promises)

| Measurement | Online observation |
| --- | ---: |
| Built desktop process launch → sidecar READY | 532 / 547 ms |
| Built normal run Rust manager start → READY | 524.44 ms |
| Built normal run spawn → bootstrap | 176.71 ms |
| Built normal run bootstrap → READY | 2.25 ms |
| Real gateway test spawn → bootstrap | 177.89 ms |
| Real gateway test bootstrap → READY | 2.94 ms |
| GET tags probe | 15–31 ms |
| Crash detection → DISCONNECTED | 2.03 ms |
| Restart operation → READY after crash | 175.26 ms |
| Rust desktop working set | 29.52–29.72 MiB |
| WebView2 descendants summed working sets | 410.23–414.41 MiB |
| Production Python working set | 32.32–32.43 MiB |

Desktop readiness is a lifecycle/handshake measurement, not first visual paint.

Final rebuilt executable was rechecked before commit: READY, model installed,
settings hash unchanged, /api/ps still [] → [], and both exit paths again left
no Python orphan (normal PID 32136, forced PID 24972). This later startup sample
was 765/672 ms, built spawn→bootstrap 176.29 ms, bootstrap→READY 2.85 ms;
gateway restart→READY 161.74 ms, tags probe 31 ms. Later working sets were Rust
82.13–82.25 MiB, WebView2 414.46–418.42 MiB, Python 32.27–32.35 MiB. These
additional observations demonstrate why early working-set samples are not a
fixed memory budget; the earlier table is retained as the original observation.

Working sets include shared pages and early startup variation. No visual
re-acceptance or inference/first-token performance claim is made. Existing UI
style acceptance remains intact (CSS unchanged); only developer diagnostics and
mode-aware chat availability are added.

## Accepted limitations / next boundary

- Settings declaration-only loader is a checked source-development bridge,
  not a packaged backend distribution. Packaging should introduce an explicit
  injectable settings boundary. No Stable refactor was required in 3A.
- Health uses bounded read + per-socket timeout, not a general total-deadline
  client for hostile slow-drip servers. No automatic polling/service/model start.
- Source implementation inventory does not prove optional dependencies or
  inference readiness. Voice IPC/local CosyVoice remain false.
- Old strict v1 clients reject new optional diagnostics; paired gateway/sidecar
  deployment is required. Legacy/mock messages remain unchanged.
- Production chat, persistence, memory/RAG and voice execution remain disabled.

**Passed:** headless composition, read-only real settings/policy, offline and
online health, no model load, capabilities, lifecycle/foreign cwd, tests/build.

**Acceptable issues:** source-only settings bridge, paired-schema deployment,
startup/RAM measurements not broad benchmarks.

**Blockers:** none found for V4-3A.

**Not yet validated / intentionally excluded:** packaged deployment and real
chat/streaming/cancel via production v4 IPC (V4-3B), conversation persistence
(V4-3C), new UI visual acceptance. V4-3B may begin only on a new user instruction.

# V4-3B validation record

This record is for the direct-chat prototype only. Real-model checks are
manual and are not required by automated tests.

## Automated checks

The final source run excludes `tests/output`, which is a generated third-party
fixture tree containing optional dependencies and is not project source.

| Check | Result |
| --- | --- |
| production sidecar, direct-chat, and contract tests | 60 passed |
| chat/Ollama policy, cancellation, voice/runtime regression | 57 passed, 3 skipped |
| full source pytest (excluding generated `tests/output`) | 988 passed, 3 skipped |
| frontend policy and UI policy tests | 13 passed |
| TypeScript/Vite build | passed |
| Rust unit tests | 14 passed, 1 ignored (real smoke) |
| contract validation | passed |
| compileall of tracked and new Python sources | passed |
| `git diff --check` | passed |

No automated test calls a real model. Fixtures cover successful deltas,
reasoning suppression, sequence ownership, one-active-generation policy,
offline/model-missing mapping, blocked-read cancellation, cancellation races,
N+1 recovery, bounded-queue wake-up, shutdown cleanup, and headless import
safety.

## Windows real smoke

The production desktop was run with the configured Ollama model
`qwen3.5:9b`. The current host reported an AMD Radeon RX 7600 XT; the WMI
`AdapterRAM` value is a truncated 32-bit field and was not used as a capacity
claim. Ollama `/api/ps` reported `size_vram=5,490,081,790` bytes (about
5.11 GiB). A separate process-tree sample measured approximately 1,483.9 MiB
for the configured `ollama.exe` service, its `llama-server.exe`, and their
console hosts. An unrelated older `llama-server.exe` was excluded. The
observer's per-run legacy sample may undercount the service tree and is not
used as a full-runtime RAM claim.

Observed runs:

| Run | Outcome | Evidence |
| --- | --- | --- |
| Ollama offline | `failed / PROVIDER_UNAVAILABLE` | no POST; UI stayed responsive |
| cold direct chat | completed | first frontend delta 9,927 ms; load 9,728.6 ms; reasoning 0 |
| warm 1 | completed | first frontend delta 131.0 ms; load 2.15 ms |
| warm 2 | completed | first frontend delta 123.9 ms; load 2.28 ms |
| warm 3 | completed | first frontend delta 142.5 ms; load 1.76 ms |
| active Stop | `cancelled` | UI terminal in 37.7 ms; transport 0 ms; 582 deltas; Ollama logged task cancellation |
| cancel recovery | completed | visible response `恢复成功`; same Ollama service, no stale text |
| backend crash during generation | `backend_lost` | UI remained alive; 399 deltas were terminalized; sidecar disconnected |
| restart recovery | completed | new sidecar PID/instance; real chat succeeded |
| close during generation | normal close | desktop exit code 0; sidecar stopped; no orphan Python PID |

The first frontend delta precedes terminal completion in every successful
stream, proving incremental delivery. The crash/restart run was performed on
the same desktop instance after a real long generation. The close run then
started another long generation and closed the native window while tokens were
still arriving; the sidecar log showed its cancellation and normal shutdown.
The independent Ollama process remained available after desktop close.

## Interpretation

Passed: real incremental direct chat, hidden-thinking policy, cold/warm
behavior, explicit cancellation, stale-generation suppression, backend crash
isolation, restart recovery, and normal close cleanup.

Accepted limitations: first-token latency is model/runtime dependent; direct
chat intentionally has no context systems or persistence; wall-clock bridge
metrics are estimates; the `urlopen()` pre-header cancellation window remains
an urllib limitation. A transient Python logging traceback occurred during an
earlier smoke and did not affect the chat lifecycle; logging cleanup is
separate technical debt.

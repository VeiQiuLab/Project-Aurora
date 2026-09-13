# Stage V4-2 validation record

Date: 2026-09-13
Platform: Windows 11, `x86_64-pc-windows-msvc`

## Proven in this stage

- A release Tauri executable builds and starts as a responsive native window.
- The Rust gateway starts an isolated Python interpreter, accepts one bounded
  bootstrap line, authenticates a dynamic loopback WebSocket, negotiates IPC
  v1, and reaches `READY`.
- The mock backend emits 30 ordered deltas and exactly one terminal event.
- Cancel is acknowledged before `cancelled`; no post-ack delta reaches the
  current generation, and a new generation completes normally.
- Killing the Python process leaves the Rust registry alive, terminalizes the
  active generation as `backend_lost`, and an explicit restart reaches `READY`
  with a new child, token, port, and sidecar instance.
- Closing the manager performs bounded shutdown. Force-killing the desktop was
  also tested: the supervised Python PID exited with it, demonstrating the
  Windows kill-on-close Job Object boundary.
- Contract validation covers 19 examples and 18 schema tests. Rust, Python,
  and the small frontend keyboard policy have independent automated tests.
- A production build launched from outside the project working directory still
  discovers the prototype sidecar relative to the executable.

## Measured prototype data

The following values are indicative, not benchmarks. IPC timings vary between
runs and RAM/VRAM figures use Windows process counters.

| Item | Observed value |
| --- | ---: |
| Rust desktop working set, idle | 32.9 MB |
| WebView2 process group, idle | 402.0-402.1 MB |
| Python mock sidecar, idle | 27.3 MB |
| Whole process tree, idle | 469.1-469.2 MB |
| WebView2 GPU process dedicated memory | about 40.5 MB |
| Active display | 2560x1440 at 180 Hz |
| Sidecar spawn to bootstrap | 137.7 ms |
| Bootstrap to READY | 2.5 ms |
| Command to first mock delta | 46.7 ms |
| Cancel request to terminal | 0.7 ms |
| Backend crash to disconnected | 1.3 ms |
| Explicit restart to READY | 130.8 ms |

GPU attribution is approximate because Windows separates dedicated/shared GPU
memory and the WebView2 GPU process is shared within the application tree.

## Verification boundary

The source and automated policy tests cover custom titlebar commands, resize
configuration, maximized border removal, Mica/Frost, local Glass, Low GPU CSS
and native effect removal, focus styles, Enter, Shift+Enter, Escape, and IME
composition guards.

The available native computer-control surface returned no Windows applications
for this run. Therefore visual clicking/dragging, real Chinese candidate-window
interaction, resize/maximize at the desktop, Low GPU before/after comparison,
and multi-monitor movement are not claimed as manually verified here. The
window process itself was confirmed responsive and WebView2 reported DPI-aware
mode with a scale factor of 1 on the active display.

This limitation does not affect the process/IPC/crash-isolation proof, but the
native interaction checklist remains an acceptance gate before calling V4-2
fully complete or starting production sidecar migration.

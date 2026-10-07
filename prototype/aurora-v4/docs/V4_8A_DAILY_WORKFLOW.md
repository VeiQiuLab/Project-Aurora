# V4-8A — Companion Interaction / UX Integration

Scope: Desktop Daily-use Workflow. Explicit user authorization on 2026-10-07
accepts Candidate A. This document does not authorize V4-8B or Memory Productization.

Starting HEAD: `cd6660f35f0bd1565af87bf7582a13a9541019f4`.
Branch: `refactor/aurora-v4`. Live remote SHA matched before edits; tracked files
were clean. The 12 historical untracked files were inventoried and hashed in
`tests/output/v48a/git-start.json`; retain all of them.
WIP Glass `adeee5aa4949a47e62ba9f7a2cb708f50a361970` is untouched.

## Phase 0 — actual source and Windows audit

| Area | Baseline evidence and decision |
|---|---|
| Window lifecycle | `desktop/src-tauri/src/lib.rs`: main window commands operate on the existing window. Add explicit Show/Hide; no window construction. |
| Single instance | Single-instance plugin precedes setup; secondary launch restores existing main window. Reuse this path. |
| Close / exit | Existing titlebar Close invokes `window.close()`; `RunEvent::Exit` joins Avatar shutdown with Backend shutdown. Keep Close as Exit and add a separate Hide button. |
| Tray | No baseline tray entry; enable official Tauri tray feature with four product actions. |
| Shortcut | No baseline global shortcut. Stable Ctrl+Alt+Space always shows existing main window and focuses input. No keyboard hooks. |
| Focus | `desktop/src/main.ts` called `promptInput.focus()` on terminal completion and history load. Remove terminal focus and gate user-requested asynchronous focus on main-window visibility/focus. |
| Initial conversation | `ConversationStore.refreshSummaries` preserves a valid current ID but does not choose one on cold start. Select a remembered valid ID or first existing ID, then load history. |
| Creation / loading | Existing conversation commands and channel events own persistence. Guard overlapping user operations and show loading/error/empty states. |
| Send availability | Baseline send handler silently returned for empty ID while composer presentation did not guard it. Both presentation and send handler now require a ready conversation. |
| Draft | Baseline single textarea could cross conversation boundaries. Add session drafts keyed by conversation ID. Hiding retains the existing DOM. |
| Cancellation | Existing `chat_cancel` and registry ownership remain authoritative. Tray reads the current owner and calls this existing path. |
| Voice stop | Existing `voice_stop` stops generation-owned Rust Audio and sends Python voice stop. Retain it; distinguish Stop Reply / Stop Reading. |
| Model readiness | `modelConnectionAvailable` uses actual local model diagnostics independently of legacy Ollama. Reuse it and remove obsolete LM Studio/runtime-not-integrated copy. |
| Voice readiness | Rust LocalVoice snapshots include READY, startup and DEGRADED/error codes. Present these factual states and existing recovery. |
| Avatar readiness | Rust snapshots distinguish disabled, ready/visible, hidden and error. Existing recovery remains disable → enable; explain it in UI. |
| Settings focus | Opening is user-triggered. Returning to chat uses the same visibility/focus gate; internal refresh never requests focus. |
| Diagnostics | Keep development controls in their existing developer menu. Add an ordinary recovery entry and concise user-facing status without diagnostic payloads. |
| Ownership / cleanup | Rust retains window/process/runtime/audio/avatar ownership; Python retains chat/context/persistence/TTS semantics. Hide never calls shutdown; Exit uses the existing chain. |

Native source/environment inspection preceded edits. The existing Release was
observed via the native accessibility tree and screenshot, then closed through
its native Close button. Its recorded Desktop, Sidecar, Model, Voice and Avatar
processes exited. Current build environment is Rust 1.98.1.

## Dependency audit

Tauri remains pinned to 2.11.5 and the package MSRV remains 1.85.
An initial candidate global-shortcut 2.4.0 required Tauri 2.12, and dependency
resolution rejected it. After checking the official downloaded manifest, pin
global-shortcut **2.3.2** (Tauri requirement 2.10, MSRV 1.77.2).
No Tauri upgrade or ownership workaround was introduced.

The Windows shortcut backend is official `global-hotkey` 0.8.0. Its manifest,
the plugin and plugin build helper 2.6.3 declare Apache-2.0 OR MIT; the existing
tray-icon 0.24.2 declares MIT OR Apache-2.0. A test-only example uses the same
backend to occupy/release the shortcut and verify actual OS registration conflict.
Generated permission schemas describe plugin permissions; the main capability
grant remains `core:default` plus `core:window:allow-start-dragging`.

## Product behavior

- Tray: Show Aurora, Hide Chat, Stop Current Operation, Exit Aurora.
- Ctrl+Alt+Space: always restore/show/focus the existing main window, including
  when already shown. Registration failure has visible feedback and a tray fallback.
- Hide: main chat only. Keep conversation, unsent draft and Companion runtimes.
- Exit: existing shutdown chain. Titlebar Close means Exit, not Hide.
- Cold start: load valid remembered/first conversation; when none exists, explain
  explicit New Conversation and disable Send. Do not auto-create or replay voice.
- Drafts: separate per-conversation session drafts; clear only the sent owner's
  draft. No promise of unsent draft persistence across application exit.
- Focus: explicit Show/New/selection/settings return may focus input when the
  native main window is visible and focused. Background completion/readiness
  never restores the native window or focuses input.
- Stop: separate reply and reading controls; tray prioritizes an active reply,
  otherwise the current preparing/speaking voice. Offline/stopped backend is a
  safe no-op. Stale owners cannot cancel a newer request.
- Recovery: reuse existing backend restart; retain conversation/drafts. Avatar
  error explicitly explains disable → enable. Local sherpa/Melo is primary;
  Edge remains online; Remote is Compatibility / Legacy; LocalCosyVoice is
  NOT IMPLEMENTED.

## Acceptance gate

Status: **PASS — MANUAL NATIVE DESKTOP ACCEPTANCE COMPLETE**, 2026-10-08.
The user confirmed all ten required scenes. Normal Tray Exit and the complete
owned-process cleanup gate pass. Commit/push closure is authorized by the task;
full Git identities belong in `tests/output/v48a/v48a-acceptance-report.md`.

Observed checks so far:

- Frontend unit tests: 38 PASS.
- Real frontend with controlled IPC: `desktop/tests/workflow_ui.mjs` PASS
  (guards, independent drafts, stale history, focus decisions, both stops,
  model recovery and shortcut conflict feedback). This is not Windows focus proof.
- Existing unified frontend interaction/layout gate PASS.
- Shell geometry/interaction: 20 groups PASS at 100/125/150/200% device-scale
  simulation; these are browser layout checks, not native DPI acceptance.
- Rust library: 68 PASS, 2 existing opt-in tests ignored.
- Related Python/v4: 121 PASS; one existing pytest cache permission warning.
- Initial actual Release smoke: six show/hide cycles preserve draft/conversation
  and Avatar; each Sidecar/Model/Voice/Avatar count stays one; secondary launch
  restores the existing window; Exit leaves zero captured owned processes.
  Final Release SHA256:
  `E2217B58F9639A984BDD47CBEA23E7DF88FFA09DACE2D6E1A729A4B4D0788AB0`.
- Final Release conflict gate (`runtime-zslnqj`): actual OS shortcut conflict
  produces visible feedback; show/hide and single-instance checks pass; cleanup zero.
- Final Release missing-assets gate (`runtime-BD7R3F`): actual model, voice and
  Avatar unavailability is isolated and explained; cleanup zero.
- Native automation observations (`native-observations.json`): shortcut from
  another application restores main/input focus and draft; hide retains runtimes;
  generation stop reaches cancelled; Rust playback stop reaches idle; model
  failure/recovery and Avatar disable/enable recovery work; settings return
  focuses input; next real chat completes; native window remains unfocused
  before and after background completion. These are **NATIVE OBSERVED**, not
  user-manual PASS. That earlier handoff run has ended; it is not the final human
  acceptance run.

- Final manual run (`manual-20261008-061205`): user PASS for shortcut, Hide/Show,
  actual tray actions, conversation/draft continuity, background focus, generation
  Hide/Show, Stop Reply, Stop Reading, normal readiness wording, and Tray Exit.
  Each scene's user feedback is recorded separately in `acceptance-1.json`
  through `acceptance-10.json`.
- In the generation Hide/Show scene, the reply had completed by the hidden-state
  observation; the explicitly allowed final-reply-retention branch was verified.
  The request appeared once, previous messages and active conversation remained,
  and Desktop/Sidecar/Model/Voice/Avatar identities did not change.
- Background focus: automated short-reply attempts completed before native
  app switching; they are not counted as background-generation proof. The user
  then confirmed the requested manual generation-then-switch scene PASS. Native
  voice completion samples independently show no foreground restoration.
- Stop Reply reached cancelled; one observed UI-cancel-to-terminal sample was
  37 ms. The old reply remained unchanged after the next successful request.
- Stop Reading produced Rust Audio `stopped`, idle voice and zero Avatar mouth;
  the next Local Melo reply spoke and completed. No stale old speaking state
  returned during the captured next-request sequence.
- Final Tray Exit: user PASS; zero remaining captured owned identities. The
  manual run captured 15 identities; the union gate checked 53 identities from
  the final and earlier native observations, matching PID plus creation time.
  No process kill or fault injection was used during this manual round.

Implementation was frozen throughout manual acceptance. Before documentation
closure, the exact 16 tracked changes and 7 stage additions matched the previous
Git gate; source timestamps had not advanced past that gate, and the Release
SHA256 was unchanged. Existing passing tests remain applicable and were not
rerun merely for the documentation update.

Runtime evidence and final gate status belong in `tests/output/v48a`.
Native Windows observations and human acceptance must be recorded separately
from CDP/fixture results. Do not convert pending human acceptance into PASS.

## Explicit exclusions and retained limitations

No Memory productization/redesign/compression/deletion, QQ, LLM switching/Model
Manager, new TTS/CosyVoice/PCM streaming, G01/lexicon/phonemization changes,
Avatar interaction/dragging/bubbles/scheduler/look tracking, camera/audio
understanding/emotion/cloning/singing, runtime/audio/Live2D supervisor rewrites,
Packaging/Installer or Glass work.

Voice closeout remains USER ACCEPTED FOR CURRENT USE / ACCEPTED FOR CURRENT USE
WITH KNOWN LIMITATIONS: 35 human PASS, 0 Minor, 1 Major, 0 confirmed Blocker.
G01 percentage omission is Major; G05 99% passed, so percentage/symbol
pronunciation has at least one inconsistent edge case. H/Sequential/Stop matrix
was ended early by the user; never claim FULL MANUAL MATRIX PASS.
Single speaker, no voice cloning, limited lexicon/symbol support and limited
inference-internal cancellation remain. LEGAL REVIEW RECOMMENDED, including
ORT/MPL-2.0 obligations; this dependency inspection is not legal clearance.
Packaging and first-run delivery remain incomplete.

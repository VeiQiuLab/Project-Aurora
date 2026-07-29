# Project Aurora v2.7 Roadmap

## Baseline

Project Aurora v2.6.0 Stable is the frozen baseline for the v2.7 development
cycle.

v2.6.0 completed the current application structure:

- AppShell architecture
- Pages Layer
- Windows Layer
- i18n system
- Theme system
- Legacy `TEXT` cleanup
- Settings polish
- GitHub stable release

The v2.7 cycle must preserve this baseline. Runtime source changes should be
made only in scoped implementation phases after the target behavior is defined.

## Development Cycle

v2.7 is the next development cycle after v2.6.0 Stable. Its purpose is to
extend Aurora's intelligence and release discipline while keeping the v2.6
architecture stable.

v2.7 is not a promise that every planned capability will ship in one release.
The roadmap is intentionally phased so that incomplete or risky work can remain
outside the stable build until it is ready.

## Main Direction

The v2.7 direction includes:

- Memory 2.0
- Knowledge / RAG 2.0
- Conversation Intelligence
- Codex workflow standardization
- Release reliability

## Planning Principles

- Keep v2.6.0 Stable as the fallback reference.
- Preserve existing AppShell, Pages Layer, Windows Layer, i18n, and theme
  contracts.
- Prefer small, reviewable implementation phases.
- Avoid broad rewrites unless a phase explicitly approves them.
- Separate planning, implementation, validation, and release work.
- Do not merge partially implemented user-facing workflows into a stable
  release.

## Phase 0: Development Documentation

Goal:

- Establish v2.7 planning and workflow documents.
- Record the frozen v2.6.0 baseline.
- Define the expected Codex workflow for future work.

Scope:

- Documentation only.
- No runtime code changes.
- No version changes.
- No locale changes.

## Phase 1: Discovery and Design

Goal:

- Define concrete v2.7 feature candidates.
- Identify module ownership, data ownership, settings impact, locale impact,
  and migration risk.

Candidate design areas:

- Memory 2.0 data model and review flow.
- Knowledge / RAG 2.0 indexing, retrieval, and health checks.
- Conversation Intelligence signals and summaries.
- Codex workflow templates for implementation, review, and release.
- Release reliability checks and packaging expectations.

Output:

- Feature design notes.
- Risk list.
- Required checks.
- Deferred items list.

## Phase 2: Memory 2.0 Foundation

Goal:

- Improve memory behavior without breaking existing memory data.

Possible scope:

- Better memory review states.
- Memory quality metadata.
- Safer memory edit and delete workflows.
- Compatibility checks for existing memory files.

Constraints:

- Do not move runtime data paths without a migration plan.
- Do not block the GUI with memory processing.
- Keep user-facing strings in i18n.

## Phase 3: Knowledge / RAG 2.0 Foundation

Goal:

- Improve document knowledge and retrieval reliability.

Possible scope:

- Retrieval diagnostics.
- Index health checks.
- Better document metadata visibility.
- Safer rebuild and repair flows.

Constraints:

- Preserve existing knowledge data compatibility unless a migration is
  explicitly planned.
- Keep advanced diagnostics out of the default user workflow.
- Use background work for expensive indexing or checks.

## Phase 4: Conversation Intelligence

Goal:

- Make conversations easier to search, understand, and continue.

Possible scope:

- Conversation summaries.
- Context quality indicators.
- Improved continuation hints.
- Optional links between conversation, memory, and knowledge evidence.

Constraints:

- Preserve existing conversation storage compatibility.
- Keep privacy-sensitive behavior explicit and reviewable.
- Avoid hidden automation that changes user data without clear UI feedback.

## Phase 5: Workflow and Release Reliability

Goal:

- Standardize how Codex changes are planned, checked, reported, and released.

Possible scope:

- Repeatable static checks.
- i18n key alignment checks.
- Release checklist updates.
- Packaging verification.
- Clear changed-file and test reporting.

Constraints:

- Version changes happen only when a release phase explicitly requires them.
- Do not downgrade version numbers.
- Keep changelog and release metadata synchronized for formal releases.

## Release Rule

v2.7 stable release scope should be selected only after implementation phases
are validated. Features that are designed but not complete should remain
documented as deferred work rather than being shipped as unstable behavior.

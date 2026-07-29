# Project Aurora Codex Workflow

## Purpose

This document defines how Codex should work on Project Aurora during the v2.7
development cycle.

v2.6.0 Stable is the frozen baseline. Codex should preserve the v2.6 stable
structure and make only scoped, intentional changes.

## Start of Work

Codex must always check git status first:

```powershell
git status --short
```

Before editing, Codex should identify:

- Requested scope.
- Files likely to be touched.
- Whether runtime code, docs, locales, config, data, or release metadata are in
  scope.
- Existing uncommitted changes that must be preserved.

## Change Scope

Rules:

- Make small, scoped changes.
- Do not change unrelated files.
- Do not perform broad rewrites without explicit approval.
- Preserve v2.6 stable structure.
- Prefer existing modules, pages, windows, components, and helpers.
- Do not create duplicate Memory, Knowledge, Conversation, Remote, Settings, or
  i18n systems.

When the request is documentation-only, Codex must not modify runtime source
code.

## Version Safety

Rules:

- Do not downgrade version numbers.
- Do not modify `modules/version.py` unless the task explicitly requires a
  version or release change.
- For formal releases, update version metadata and changelog together according
  to the project version rules.
- v2.6.0 Stable remains the frozen baseline for v2.7 development planning.

## Runtime Architecture Safety

Rules:

- Preserve the AppShell architecture.
- Preserve the Pages Layer.
- Preserve the Windows Layer.
- Keep UI pages separated.
- Keep windows separated.
- Keep business logic in existing service modules where practical.
- Avoid large unrelated rewrites.
- Do not move runtime data paths without a migration plan.
- Do not block the GUI thread with network, process, indexing, or file-heavy
  work.

## i18n Workflow

Rules:

- All user-facing strings must use i18n.
- Do not reintroduce legacy `TEXT` dictionaries.
- Keep `zh_CN` and `en_US` locale keys aligned.
- Add new locale keys to both supported locale files in the same UI change.
- Do not modify locale JSON files for documentation-only tasks.

Recommended check when locale or UI text changes are made:

```powershell
python scripts/check_i18n.py
```

## Static Checks

After changes, Codex should run available static checks appropriate to the
scope.

Recommended checks:

```powershell
git diff --check
python -m compileall main.py modules widgets
python scripts/check_i18n.py
```

For documentation-only changes, `git diff --check` is usually sufficient unless
the task requests broader validation.

If a check cannot be run, Codex must report that honestly and explain the
limitation.

## Reporting

At completion, Codex should report:

- Changed files.
- What was created or updated.
- Checks performed.
- Untested parts or skipped checks.
- Whether runtime code was changed.

For v2.7 work, Codex should be especially explicit when a change touches:

- Runtime source code.
- `modules/version.py`.
- Locale JSON files.
- Runtime data.
- Build or release files.

## Git Hygiene

Rules:

- Preserve user changes.
- Do not revert unrelated work.
- Do not use destructive git operations unless explicitly requested.
- Show git status after completing the task when requested.
- Stage, commit, push, or open a pull request only when explicitly requested.

## Handoff Format

For normal development tasks, the completion report should include:

- Modified files.
- New or changed behavior.
- Test results.
- Known limitations.
- Suggested next version work when useful.

For documentation-only initialization, the report should also state that no
runtime code was changed.

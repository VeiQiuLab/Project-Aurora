# Project Aurora Development Guide

This guide defines stabilization rules for Project Aurora development. It is
intended to keep future v2.5 architecture work small, compatible, and easy to
review.

## Development Scope

- Work incrementally on the current project.
- Do not regenerate the application.
- Do not duplicate existing systems.
- Keep Chat, Memory, Knowledge, Conversation, Remote, Authentication, Persona,
  and Mobile Chat boundaries stable.
- Each new feature must declare its owning module, settings keys, locale keys,
  and test requirements.

## UI Text Rules

User-visible UI text must use localization keys.

Do not add:

```python
text="中文"
text="English"
```

Use:

```python
text=t("key")
```

Required rules:

- Add every new key to `locales/zh_CN.json`.
- Add every new key to `locales/en_US.json`.
- Locale files must be valid UTF-8 JSON.
- Missing translation keys must not crash the app.
- Logs, exception details, debug payload keys, and API field names do not need
  localization unless they are displayed directly in the UI.

Before committing UI text changes, run:

```powershell
python scripts/check_i18n.py
```

If Python is unavailable in the current execution environment, run equivalent
static checks and record the limitation.

## Theme Rules

Use `modules/ui_theme.py` for shared UI tokens.

Do not add:

```python
font=("Microsoft YaHei", 13)
```

Use existing tokens:

```python
FONT_TITLE
FONT_BODY
FONT_SMALL
COLOR_SUCCESS
COLOR_WARNING
COLOR_ERROR
COLOR_MUTED
```

Button styling should use shared helpers or `button_style()` instead of direct
per-window colors.

## Settings Rules

Prefer batch updates when saving multiple values:

```python
settings.update_many({
    "language": "zh_CN",
    "theme": "blue",
})
```

Avoid long runs of repeated `settings.set()` calls in one save handler.

Rules:

- Keep `settings.set()` backward compatible.
- Do not change `config/settings.json` format without a migration.
- Do not couple normal Settings save behavior to new Remote functionality.
- UI save buttons must write settings to disk and show success or failure state.

## Runtime Data Rules

Runtime data must not be committed.

Do not commit:

- `config/settings.json`
- `data/persona/*.json`
- `data/memory/*`
- `data/knowledge/*`
- `data/conversations/*`
- `data/remote/*.json`
- `__pycache__/`
- `*.pyc`

Allowed:

- `*.example.json`
- Documentation
- Source code
- Stable configuration templates

Do not move existing runtime data paths during stabilization work. Directory
layout migrations require a separate confirmed phase.

## Module Rules

Before adding or changing a feature, identify:

- Owning module.
- Config keys.
- Locale keys.
- Data files touched.
- User-visible behavior.
- Required tests or checks.

Do not create a second Memory, Knowledge, Conversation, Remote, or Settings
system. Extend the existing module unless a refactor phase explicitly approves
extraction.

## Stabilization Checks

Recommended checks before commit:

```powershell
git diff --check
python scripts/check_i18n.py
```

Also scan for common mojibake fragments from corrupted Chinese text and
replacement characters. Keep the bad sample strings out of documentation so
the scan itself does not produce false positives.

If Python is unavailable, report that limitation and complete the available
static checks.

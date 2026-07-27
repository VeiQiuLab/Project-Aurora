"""Shared UI font tokens for Project Aurora."""

FONT_FAMILY = "Microsoft YaHei UI"

FONT_TITLE = (FONT_FAMILY, 22, "bold")
FONT_APP_TITLE = (FONT_FAMILY, 24, "bold")
FONT_HEADER = (FONT_FAMILY, 16, "bold")
FONT_SECTION = (FONT_FAMILY, 15, "bold")
FONT_NORMAL = (FONT_FAMILY, 13)
FONT_NORMAL_BOLD = (FONT_FAMILY, 13, "bold")
FONT_SMALL = (FONT_FAMILY, 12)
FONT_SMALL_BOLD = (FONT_FAMILY, 12, "bold")

STATUS_COLORS = {
    "healthy": "#2E7D32",
    "warning": "#B26A00",
    "error": "#B3261E",
    "disabled": "#6B7280"
}

BUTTON_STYLES = {
    "primary": {
        "fg_color": "#2563EB",
        "hover_color": "#1D4ED8",
        "text_color": "white"
    },
    "secondary": {
        "fg_color": "#374151",
        "hover_color": "#4B5563",
        "text_color": "white"
    },
    "danger": {
        "fg_color": "#B3261E",
        "hover_color": "#8C1D18",
        "text_color": "white"
    }
}


def status_color(status):
    value = str(status or "").strip().casefold()
    if value in {"healthy", "ok", "online", "ready", "running", "passed", "success", "enabled"}:
        return STATUS_COLORS["healthy"]
    if value in {"warning", "missing", "not ready", "unknown"}:
        return STATUS_COLORS["warning"]
    if value in {"error", "failed", "offline", "blocked"}:
        return STATUS_COLORS["error"]
    return STATUS_COLORS["disabled"]


def button_style(kind="secondary"):
    return dict(BUTTON_STYLES.get(kind, BUTTON_STYLES["secondary"]))

"""Shared UI font tokens for Project Aurora."""

DEFAULT_FONT_FAMILY = "Microsoft YaHei UI"
FALLBACK_FONT_FAMILY = "Segoe UI"


def resolve_font_family(root=None):
    if root is None:
        return DEFAULT_FONT_FAMILY
    try:
        from tkinter import font as tkfont

        families = set(tkfont.families(root))
    except Exception:
        return DEFAULT_FONT_FAMILY
    if DEFAULT_FONT_FAMILY in families:
        return DEFAULT_FONT_FAMILY
    return FALLBACK_FONT_FAMILY


FONT_FAMILY = resolve_font_family()

FONT_TITLE = (FONT_FAMILY, 22, "bold")
FONT_APP_TITLE = (FONT_FAMILY, 24, "bold")
FONT_HEADER = (FONT_FAMILY, 16, "bold")
FONT_SECTION = (FONT_FAMILY, 15, "bold")
FONT_BODY = (FONT_FAMILY, 13)
FONT_NORMAL = (FONT_FAMILY, 13)
FONT_NORMAL_BOLD = (FONT_FAMILY, 13, "bold")
FONT_SMALL = (FONT_FAMILY, 12)
FONT_SMALL_BOLD = (FONT_FAMILY, 12, "bold")

COLOR_SUCCESS = "#2E7D32"
COLOR_WARNING = "#B26A00"
COLOR_ERROR = "#B3261E"
COLOR_MUTED = "#6B7280"
COLOR_BACKGROUND = "#111827"
COLOR_TEXT_PRIMARY = "#F3F4F6"
COLOR_TEXT_ON_LIGHT = "#111827"

WINDOW_DEFAULT_WIDTH = 1200
WINDOW_DEFAULT_HEIGHT = 760

SPACING_SMALL = 6
SPACING_MEDIUM = 12
SPACING_LARGE = 20

BUTTON_HEIGHT = 32
CONTROL_CORNER_RADIUS = 6
FORM_LABEL_WRAP = 320
FORM_CONTROL_WIDTH = 250

STATUS_COLORS = {
    "healthy": COLOR_SUCCESS,
    "warning": COLOR_WARNING,
    "error": COLOR_ERROR,
    "disabled": COLOR_MUTED
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

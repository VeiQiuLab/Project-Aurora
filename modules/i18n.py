"""Lightweight JSON-backed localization helpers."""

import json
from pathlib import Path


DEFAULT_LANGUAGE = "zh_CN"
FALLBACK_LANGUAGE = "en_US"
SUPPORTED_LANGUAGES = {"zh_CN", "en_US"}

_LOCALE_DIR = Path(__file__).resolve().parent.parent / "locales"
_language = DEFAULT_LANGUAGE
_cache = {}


def normalize_language(language):
    value = str(language or "").strip().lower().replace("-", "_")
    if value in {"english", "en", "en_us"}:
        return "en_US"
    if value in {"zh", "zh_cn", "chinese", "\u4e2d\u6587", "\u7b80\u4f53\u4e2d\u6587"}:
        return "zh_CN"
    return DEFAULT_LANGUAGE


def _load(language):
    normalized = normalize_language(language)
    if normalized in _cache:
        return _cache[normalized]
    path = _LOCALE_DIR / f"{normalized}.json"
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError, json.JSONDecodeError):
        data = {}
    _cache[normalized] = data if isinstance(data, dict) else {}
    return _cache[normalized]


def set_language(language):
    global _language
    _language = normalize_language(language)
    _load(_language)
    _load(FALLBACK_LANGUAGE)


def get_language():
    return _language


def t(key, default=None):
    text = _load(_language).get(key)
    if text is None:
        text = _load(FALLBACK_LANGUAGE).get(key)
    if text is None:
        text = default if default is not None else key
    return str(text)

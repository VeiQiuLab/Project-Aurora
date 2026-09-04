"""Localized presentation helpers for runtime diagnostics."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from modules.i18n import t as default_translate


_NAME_KEYS = {
    "core": "runtime_domain_core",
    "aurora_core": "runtime_domain_core",
    "local_ai": "runtime_domain_local_ai",
    "knowledge": "runtime_domain_knowledge",
    "voice": "runtime_domain_voice",
    "ollama": "runtime_item_ollama",
    "local_ai_service": "runtime_item_local_ai_service",
    "chat_model": "chat_model",
    "embedding_model": "runtime_item_embedding",
    "ffmpeg": "runtime_item_ffmpeg",
    "microphone": "runtime_item_microphone",
    "stt": "runtime_item_stt",
    "whisper_model": "runtime_item_whisper_model",
    "tts": "runtime_item_tts",
    "playback": "runtime_item_playback",
}

_STATUS_KEYS = {
    "Ready": "runtime_status_ready",
    "Missing": "runtime_status_missing",
    "Offline": "runtime_status_offline",
    "Optional": "runtime_status_optional",
    "Degraded": "runtime_status_not_ready",
}


def _text(translate: Callable[[str], str], key: str, fallback: str) -> str:
    value = str(translate(key))
    return fallback if value == key else value


def runtime_status_text(status: Any, translate=default_translate) -> str:
    value = str(status or "Degraded")
    return _text(translate, _STATUS_KEYS.get(value, "runtime_status_not_ready"), value)


def model_mode_text(mode: Any, translate=default_translate) -> str:
    normalized = str(mode or "manual").strip().casefold()
    key = "runtime_mode_auto" if normalized == "auto" else "runtime_mode_manual"
    return _text(translate, key, "Auto" if normalized == "auto" else "Manual")


def runtime_item_name(item: Mapping[str, Any], translate=default_translate) -> str:
    key = str(item.get("key") or "")
    fallback = str(item.get("name") or key)
    translation_key = _NAME_KEYS.get(key)
    return _text(translate, translation_key, fallback) if translation_key else fallback


def runtime_item_detail(item: Mapping[str, Any], translate=default_translate) -> str:
    key = str(item.get("key") or "")
    status = str(item.get("status") or "Degraded")
    data = item.get("data") if isinstance(item.get("data"), Mapping) else {}
    enabled = data.get("enabled")

    if key in {"core", "aurora_core"}:
        return _text(translate, "runtime_detail_core_ready", "Aurora Core is ready.")
    if key == "local_ai":
        model = str(data.get("chat_model") or "").strip()
        if status == "Ready":
            template = _text(translate, "runtime_detail_local_ai_ready", "Chat is ready with {model}.")
            return template.format(model=model)
        return _text(translate, "runtime_detail_local_ai_not_ready", "Local AI is not ready.")
    if key == "knowledge":
        translation_key = "runtime_detail_knowledge_ready" if enabled else "runtime_detail_knowledge_disabled"
        return _text(translate, translation_key, str(item.get("detail") or ""))
    if key == "voice":
        if enabled is False:
            return _text(translate, "runtime_detail_voice_disabled", "Voice is not enabled.")
        translation_key = "runtime_detail_voice_ready" if status == "Ready" else "runtime_detail_voice_not_ready"
        return _text(translate, translation_key, str(item.get("detail") or ""))
    if key in {"chat_model", "embedding_model"}:
        model = str(data.get("configured") or "").strip()
        if status == "Ready" and model:
            template = _text(translate, "runtime_detail_model_ready", "{model} · {mode}")
            return template.format(model=model, mode=model_mode_text(data.get("mode"), translate))
        if key == "embedding_model" and status == "Optional":
            return _text(translate, "runtime_detail_embedding_optional", "Embedding is optional and not configured.")
        translation_key = "runtime_detail_chat_missing" if key == "chat_model" else "runtime_detail_embedding_missing"
        return _text(translate, translation_key, str(item.get("detail") or ""))
    if status == "Optional" and key in {"microphone", "stt", "whisper_model", "tts", "playback"}:
        return _text(translate, "runtime_detail_voice_component_skipped", "Voice is off; this item was not checked.")
    if key == "ollama":
        path = str(data.get("path") or "").strip()
        translation_key = "runtime_detail_ollama_ready" if status == "Ready" else "runtime_detail_ollama_missing"
        return _text(translate, translation_key, str(item.get("detail") or "")).format(path=path)
    if key == "local_ai_service":
        translation_key = "runtime_detail_service_ready" if status == "Ready" else "runtime_detail_service_offline"
        return _text(translate, translation_key, str(item.get("detail") or ""))
    if key == "ffmpeg":
        path = str(data.get("path") or "").strip()
        translation_key = "runtime_detail_ffmpeg_ready" if status == "Ready" else "runtime_detail_ffmpeg_missing"
        return _text(translate, translation_key, str(item.get("detail") or "")).format(path=path)
    if status == "Ready":
        return _text(translate, "runtime_detail_component_ready", "Ready.")
    if status in {"Missing", "Degraded", "Offline"}:
        return _text(translate, f"runtime_detail_{key}_missing", str(item.get("detail") or ""))
    return str(item.get("detail") or "")


def localized_runtime_item(item: Mapping[str, Any], translate=default_translate) -> dict[str, str]:
    return {
        "name": runtime_item_name(item, translate),
        "status": runtime_status_text(item.get("status"), translate),
        "detail": runtime_item_detail(item, translate),
    }

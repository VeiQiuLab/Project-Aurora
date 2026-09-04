"""Startup diagnostics for first-run and release readiness checks."""

from __future__ import annotations

from typing import Any

from modules.app_paths import (
    CONFIG_DIR,
    CONVERSATIONS_DIR,
    KNOWLEDGE_DIR,
    LOG_DIR,
    MEMORY_DIR,
    PERSONA_DIR,
)
from modules.runtime_dependencies import RuntimeDependencyManager


def initialization_check(settings: Any) -> list[dict[str, str]]:
    """Return user-facing startup checks without changing runtime behavior."""

    checks = [
        _path_check("配置目录", CONFIG_DIR),
        _ai_check(settings),
        _voice_check(settings),
        _storage_check(),
    ]
    return checks


def _path_check(name, path):
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return {"name": name, "status": "error", "detail": str(error)}
    return {"name": name, "status": "healthy", "detail": str(path)}


def _ai_check(settings):
    chat_model = str(settings.get("chat_model", "") or "").strip()
    embedding_model = str(settings.get("embedding_model", "") or "").strip()
    if chat_model and embedding_model:
        return {"name": "AI 环境", "status": "healthy", "detail": "模型配置已就绪"}
    return {"name": "AI 环境", "status": "warning", "detail": "首次启动需要选择模型"}


def _voice_check(settings):
    report = RuntimeDependencyManager(settings).check_voice_requirements()
    if report["ready"]:
        return {"name": "Voice 环境", "status": "healthy", "detail": "语音依赖已就绪"}
    missing = ", ".join(item["name"] for item in report["missing"])
    return {"name": "Voice 环境", "status": "warning", "detail": f"缺少组件: {missing}"}
def _storage_check():
    paths = [CONVERSATIONS_DIR, MEMORY_DIR, KNOWLEDGE_DIR, PERSONA_DIR, LOG_DIR]
    for path in paths:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return {"name": "存储路径", "status": "error", "detail": str(error)}
    return {"name": "存储路径", "status": "healthy", "detail": str(CONVERSATIONS_DIR.parent)}

"""Reuse the actual production chat module without its eager settings import.

No rewritten HTTP/NDJSON/policy/cancellation implementation. This is the same
source-only bridge as V4-3A, with a private request-settings namespace.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ChatRequest:
    request_id: str
    session_id: str
    generation_id: str
    text: str = field(repr=False)
    conversation_id: str | None = None
    history: tuple[dict[str, str], ...] = field(default_factory=tuple, repr=False)


def load_chat_boundary(root: Path, settings):
    path = root / "modules/chat.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    expected = ast.parse(
        "import copy\nimport json\nimport math\nimport socket\nimport threading\n"
        "import urllib.error\nimport urllib.request\nfrom time import monotonic\n"
        "from modules.ollama_request_policy import resolve_ollama_request_policy\n"
        "from modules.settings import settings\n"
    ).body
    imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    if [ast.dump(n) for n in imports] != [ast.dump(n) for n in expected]:
        raise RuntimeError("CHAT_IMPORT_BOUNDARY_CHANGED")
    for node in tree.body:
        if isinstance(node, ast.Assign):
            ast.literal_eval(node.value)  # only the audited constant tables
        elif not isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef, ast.FunctionDef)):
            raise RuntimeError("CHAT_IMPORT_BOUNDARY_CHANGED")
    tree.body.remove(imports[-1])  # replace ONLY the eager singleton dependency
    namespace = {"__name__": "aurora_v4_direct_chat", "settings": settings}
    exec(compile(tree, str(path), "exec"), namespace)
    return namespace


class DirectChatAdapter:
    def __init__(self, composition):
        self.composition = composition
        self.api = load_chat_boundary(composition.root, composition.settings)

    def new_handle(self, stop_event, diagnostics):
        return self.api["StreamingRequestHandle"](stop_event, diagnostics)

    def prepare_context(self, history=(), context_snapshot=None):
        # Context is prepared by the headless production adapter.  Keep
        # conversation history as structured messages so it is never duplicated
        # inside the system prompt.
        system_context = getattr(context_snapshot, "system_context", None)
        if system_context is None and isinstance(context_snapshot, dict):
            system_context = context_snapshot.get("system_context")
        session = self.api["ChatSession"](system_context=system_context) if system_context else self.api["ChatSession"]()
        if history:
            session.replace(history)
        else:
            session.messages = []
        if system_context:
            session.set_system_context(system_context)
        return session

    def stream(self, request, model, handle, on_chunk, context_snapshot=None):
        done_seen = False

        def observe(record):
            nonlocal done_seen
            done_seen = done_seen or record["done"]

        history = tuple(request.history)
        # Text equality is not turn identity: preserve repeated historical turns.
        persisted_history = self.prepare_context(history).snapshot()
        session = self.prepare_context(history, context_snapshot)
        history_length = len(session.snapshot())
        result = self.api["stream_chat"](
            model, request.text, session, on_chunk, handle.stop_event,
            request_handle=handle, collect_memory_candidates=False, raw_line_observer=observe,
        )
        if not handle.cancelled and not done_seen:
            raise self.api["ChatError"]("Incomplete production stream.", category="invalid_response")
        # Retrieved context is ephemeral model input. Never persist it in the
        # system message exposed by conversation.get to Rust/WebView.
        return result, persisted_history + session.snapshot()[history_length:]

    @staticmethod
    def error_code(error):
        return {
            "ollama_unavailable": "PROVIDER_UNAVAILABLE",
            "model_unavailable": "MODEL_UNAVAILABLE",
            "model_capability": "MODEL_UNAVAILABLE",
            "timeout": "REQUEST_TIMEOUT",
            "not_found": "NOT_FOUND",
            "invalid_conversation": "INVALID_CONVERSATION",
            "persistence_failed": "PERSISTENCE_FAILED",
        }.get(getattr(error, "category", None), "INTERNAL_ERROR")

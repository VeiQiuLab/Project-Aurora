"""Direct production imports with explicit request-local settings injection."""
from __future__ import annotations

from functools import partial
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
    from modules import chat
    return {"ChatSession": chat.ChatSession, "ChatError": chat.ChatError,
            "StreamingRequestHandle": chat.StreamingRequestHandle,
            "stream_chat": partial(chat.stream_chat, settings_store=settings),
            "chat_with_messages": partial(chat.chat_with_messages, settings_store=settings)}


class DirectChatAdapter:
    def __init__(self, composition):
        self.composition = composition
        self.api = load_chat_boundary(composition.root, composition.settings)
        if composition.local_provider is not None:
            self.api.update(stream_chat=composition.local_provider.stream_chat,
                            chat_with_messages=composition.local_provider.chat_with_messages)

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
        settings = getattr(context_snapshot, "settings", None) or self.composition.settings.snapshot()
        result = self.api["stream_chat"](
            model, request.text, session, on_chunk, handle.stop_event,
            request_handle=handle, collect_memory_candidates=False, raw_line_observer=observe,
            settings_store=settings,
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
            "provider_unavailable": "PROVIDER_UNAVAILABLE",
            "model_unavailable": "MODEL_UNAVAILABLE",
            "model_capability": "MODEL_UNAVAILABLE",
            "timeout": "REQUEST_TIMEOUT",
            "not_found": "NOT_FOUND",
            "invalid_conversation": "INVALID_CONVERSATION",
            "persistence_failed": "PERSISTENCE_FAILED",
        }.get(getattr(error, "category", None), "INTERNAL_ERROR")

"""Headless conversation persistence boundary for the v4 production sidecar.

The sidecar is the only production owner of conversation JSON.  This module
deliberately calls only the primitive ``ConversationManager`` list/load/save
methods; it never enters the legacy UI's title, intelligence, or memory
pipelines.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from modules.app_paths import CONVERSATIONS_DIR


CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
ALLOWED_ROLES = {"system", "user", "assistant"}


class ConversationError(ValueError):
    """Safe, client-facing conversation persistence error."""

    def __init__(self, code: str, message: str = "Conversation operation failed."):
        super().__init__(message)
        self.code = code


def validate_conversation_id(value: object) -> str:
    if not isinstance(value, str) or not CONVERSATION_ID_RE.fullmatch(value):
        raise ConversationError("INVALID_REQUEST", "Invalid conversation ID.")
    return value


class ConversationPersistence:
    """A lazy, headless adapter over the existing Aurora JSON store."""

    def __init__(self, base_path: Path | None = None):
        self.directory = Path(base_path) if base_path is not None else CONVERSATIONS_DIR
        self._manager = None
        # ``create`` follows the legacy materialize-on-first-save behavior:
        # the identity exists for this sidecar lifetime before a JSON file is
        # written.  Keep that distinction so a genuinely missing ID still
        # returns NOT_FOUND while the newly-created UI conversation can accept
        # its first turn.
        self._ephemeral_ids: set[str] = set()

    @property
    def manager(self):
        if self._manager is None:
            # Importing ConversationManager is intentionally deferred until a
            # conversation RPC/chat actually needs persistence.  Its existing
            # constructor ensures the configured production directory exists.
            from modules.conversation import ConversationManager

            self._manager = ConversationManager(self.directory)
        return self._manager

    @staticmethod
    def _message_dto(message: object) -> dict[str, str] | None:
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        if role not in ALLOWED_ROLES:
            return None
        content = message.get("content", "")
        if not isinstance(content, str):
            content = str(content or "")
        return {"role": role, "content": content}

    def _messages(self, data: dict) -> list[dict[str, str]]:
        raw = data.get("messages", [])
        if not isinstance(raw, list):
            raise ConversationError("INVALID_CONVERSATION", "Conversation messages are invalid.")
        return [dto for item in raw if (dto := self._message_dto(item)) is not None]

    @staticmethod
    def _metadata(data: dict, conversation_id: str, message_count: int) -> dict:
        return {
            "conversation_id": conversation_id,
            "title": str(data.get("title") or "New Conversation"),
            "created_at": str(data.get("created_at") or data.get("created_time") or ""),
            "updated_at": str(data.get("updated_at") or data.get("updated_time") or ""),
            "message_count": message_count,
            "model": str(data.get("model") or ""),
        }

    def list_metadata(self) -> list[dict]:
        records: list[dict] = []
        # Use filenames as opaque IDs.  A malformed embedded JSON id can never
        # redirect a read outside the configured directory.
        for path in sorted(self.directory.glob("*.json")):
            conversation_id = path.stem
            if not CONVERSATION_ID_RE.fullmatch(conversation_id):
                continue
            try:
                data = self.manager.load(conversation_id)
                messages = self._messages(data)
                records.append(self._metadata(data, conversation_id, len(messages)))
            except (OSError, UnicodeError, ValueError, TypeError):
                # One damaged history file is isolated from the rest of the
                # list.  The filename and body are intentionally not logged.
                continue
        return sorted(records, key=lambda item: item["updated_at"], reverse=True)

    def get(self, conversation_id: object) -> dict:
        conversation_id = validate_conversation_id(conversation_id)
        try:
            data = self.manager.load(conversation_id)
        except FileNotFoundError as error:
            raise ConversationError("NOT_FOUND", "Conversation was not found.") from error
        except (OSError, UnicodeError, ValueError, TypeError) as error:
            raise ConversationError("INVALID_CONVERSATION", "Conversation data is invalid.") from error
        messages = self._messages(data)
        metadata = self._metadata(data, conversation_id, len(messages))
        return {**metadata, "messages": messages}

    def history(self, conversation_id: object) -> list[dict[str, str]]:
        if conversation_id is None:
            return []
        conversation_id = validate_conversation_id(conversation_id)
        try:
            return self.get(conversation_id)["messages"]
        except ConversationError as error:
            if error.code == "NOT_FOUND" and conversation_id in self._ephemeral_ids:
                return []
            raise

    def create(self) -> dict:
        # Preserve the legacy materialization-on-first-save behavior: creating
        # a blank v4 conversation allocates an opaque identity but no file.
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conversation_id = uuid.uuid4().hex
        self._ephemeral_ids.add(conversation_id)
        return {
            "conversation_id": conversation_id,
            "title": "New Conversation",
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
            "model": "",
        }

    def save_completed(
        self,
        conversation_id: object,
        model: str,
        messages: list[dict],
    ) -> dict:
        conversation_id = validate_conversation_id(conversation_id)
        normalized = [dto for item in messages if (dto := self._message_dto(item)) is not None]
        if not normalized:
            raise ConversationError("INVALID_CONVERSATION", "Completed conversation is empty.")
        try:
            current = self.manager.load(conversation_id)
            title = str(current.get("title") or "New Conversation")
            created_at = current.get("created_at") or current.get("created_time")
            metadata = current.get("metadata") if isinstance(current.get("metadata"), dict) else None
        except FileNotFoundError:
            title, created_at, metadata = "New Conversation", None, None
        except (OSError, UnicodeError, ValueError, TypeError) as error:
            raise ConversationError("INVALID_CONVERSATION", "Conversation data is invalid.") from error
        try:
            saved = self.manager.save(
                conversation_id,
                model,
                normalized,
                title=title,
                created_at=created_at,
                metadata=metadata,
            )
        except (OSError, UnicodeError, ValueError, TypeError) as error:
            raise ConversationError("PERSISTENCE_FAILED", "Conversation could not be saved.") from error
        self._ephemeral_ids.discard(conversation_id)
        return self._metadata(saved, conversation_id, len(normalized))

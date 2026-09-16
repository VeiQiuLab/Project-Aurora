"""V4-3A production entrypoint, using the already tested IPC v1 transport."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Source-checkout entrypoint must work even when started from a foreign cwd.
SIDECAR_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SIDECAR_ROOT.parents[2]
if not (REPO_ROOT / "modules" / "app_paths.py").is_file():
    raise RuntimeError("AURORA_SOURCE_ROOT_NOT_FOUND")
sys.path[:0] = [str(SIDECAR_ROOT), str(REPO_ROOT)]

from mock_sidecar.server import MockSidecar, _required_environment, serve_sidecar
from production_sidecar.composition import ProductionComposition
from production_sidecar.chat_execution import ChatExecution
from production_sidecar.conversations import ConversationError
from production_sidecar.post_turn import PostTurnCoordinator
from modules.settings_service import SettingsError

LOGGER = logging.getLogger("aurora-v4-production")


class ProductionSidecar(MockSidecar):
    """Reuse authentication/validation/lifecycle, never the mock chat generator."""

    def __init__(self, token: str, composition: ProductionComposition):
        super().__init__(token, 0)
        self.composition = composition
        self.chat = ChatExecution(self)
        self._metadata_connections = set()
        self._event_loop = None
        self.composition.post_turn = PostTurnCoordinator(composition, self.chat.adapter.api, self.metadata_changed)

    def metadata_changed(self, metadata):
        if self._event_loop is not None and not self._event_loop.is_closed():
            self._event_loop.call_soon_threadsafe(lambda: asyncio.create_task(self._send_metadata(metadata)))

    async def _send_metadata(self, metadata):
        if self.composition.post_turn.closed:
            return
        for connection in tuple(self._metadata_connections):
            try:
                await self.send(connection, {"protocol": "aurora-ipc", "version": 1,
                    "type": "conversation.changed", "payload": {"conversation": metadata}})
            except Exception:
                self._metadata_connections.discard(connection)

    def capabilities(self):
        return self.composition.capabilities()

    async def dispatch(self, connection, message):
        kind = message["type"]
        if kind not in {"settings.get.request", "settings.update.request"}:
            return await super().dispatch(connection, message)
        self._event_loop = asyncio.get_running_loop()
        self._metadata_connections.add(connection)
        try:
            if kind == "settings.get.request":
                result = await asyncio.to_thread(self.composition.settings.describe)
                response_type = "settings.get.response"
            else:
                result = await asyncio.to_thread(self.composition.settings.apply_patch,
                    message["payload"]["patch"], message["payload"]["expected_revision"])
                response_type = "settings.update.response"
                LOGGER.info("event=settings_updated revision=%s count=%s", result["revision"], len(result["changed_keys"]))
            await self.send(connection, {"protocol": "aurora-ipc", "version": 1, "type": response_type,
                "request_id": message["request_id"], "payload": result})
            if kind == "settings.update.request" and result["changed_keys"]:
                for observer in tuple(self._metadata_connections):
                    try:
                        await self.send(observer, {"protocol": "aurora-ipc", "version": 1,
                            "type": "settings.changed", "payload": result})
                    except Exception:
                        self._metadata_connections.discard(observer)
        except SettingsError as error:
            LOGGER.info("event=settings_update_rejected code=%s", error.code)
            await self.send_error(connection, code=error.code, message="Settings operation could not complete.",
                                  retryable=error.code == "CONFLICT", envelope=message)
        except (OSError, ValueError, TypeError):
            LOGGER.info("event=settings_persist_failed code=PERSISTENCE_ERROR")
            await self.send_error(connection, code="PERSISTENCE_ERROR",
                message="Settings operation could not complete.", retryable=False, envelope=message)

    def backend_state(self):
        return self.composition.state

    async def health_payload(self):
        diagnostics = await self.composition.refresh()
        return {**await super().health_payload(), "diagnostics": diagnostics}

    async def start_chat(self, connection, message):
        self._event_loop = asyncio.get_running_loop()
        self._metadata_connections.add(connection)
        await self.chat.start(connection, message)

    async def cancel_chat(self, connection, message):
        await self.chat.cancel(connection, message)

    async def conversation_list(self, connection, message):
        self._event_loop = asyncio.get_running_loop()
        self._metadata_connections.add(connection)
        try:
            conversations = await asyncio.to_thread(self.composition.conversations.list_metadata)
            await self.send(connection, {
                "protocol": "aurora-ipc", "version": 1,
                "type": "conversation.list.response", "request_id": message["request_id"],
                "payload": {"conversations": conversations},
            })
        except Exception:
            await self.send_error(connection, code="INTERNAL_ERROR",
                                  message="Conversation list failed.", retryable=True,
                                  envelope=message)

    async def conversation_get(self, connection, message):
        try:
            conversation = await asyncio.to_thread(
                self.composition.conversations.get,
                message["payload"]["conversation_id"],
            )
            await self.send(connection, {
                "protocol": "aurora-ipc", "version": 1,
                "type": "conversation.get.response", "request_id": message["request_id"],
                "payload": {"conversation": conversation},
            })
        except ConversationError as error:
            await self.send_error(connection, code=error.code,
                                  message=str(error), retryable=error.code == "NOT_FOUND",
                                  envelope=message)
        except Exception:
            await self.send_error(connection, code="INTERNAL_ERROR",
                                  message="Conversation load failed.", retryable=True,
                                  envelope=message)

    async def conversation_create(self, connection, message):
        try:
            conversation = await asyncio.to_thread(self.composition.conversations.create)
            await self.send(connection, {
                "protocol": "aurora-ipc", "version": 1,
                "type": "conversation.create.response", "request_id": message["request_id"],
                "payload": {"conversation": conversation},
            })
        except Exception:
            await self.send_error(connection, code="INTERNAL_ERROR",
                                  message="Conversation creation failed.", retryable=True,
                                  envelope=message)

    async def cancel_all(self):
        self.composition.post_turn.close()
        await self.chat.close()

    async def handle_connection(self, connection):
        try:
            await super().handle_connection(connection)
        finally:
            self._metadata_connections.discard(connection)
            await self.chat.close(connection)


async def run():
    token, versions = _required_environment()
    composition = ProductionComposition()
    try:
        await composition.refresh()
        await serve_sidecar(ProductionSidecar(token, composition), versions)
    finally:
        composition.close()


def main():
    try:
        asyncio.run(run())
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception:
        LOGGER.exception("event=production_startup_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

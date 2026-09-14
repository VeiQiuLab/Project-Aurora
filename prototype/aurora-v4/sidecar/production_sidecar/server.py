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

LOGGER = logging.getLogger("aurora-v4-production")


class ProductionSidecar(MockSidecar):
    """Reuse authentication/validation/lifecycle, never the mock chat generator."""

    def __init__(self, token: str, composition: ProductionComposition):
        super().__init__(token, 0)
        self.composition = composition
        self.chat = ChatExecution(self)

    def capabilities(self):
        return self.composition.capabilities()

    def backend_state(self):
        return self.composition.state

    async def health_payload(self):
        diagnostics = await self.composition.refresh()
        return {**await super().health_payload(), "diagnostics": diagnostics}

    async def start_chat(self, connection, message):
        await self.chat.start(connection, message)

    async def cancel_chat(self, connection, message):
        await self.chat.cancel(connection, message)

    async def cancel_all(self):
        await self.chat.close()

    async def handle_connection(self, connection):
        try:
            await super().handle_connection(connection)
        finally:
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

"""Entry point for the relay appservice.

Usage::

    python -m appservice
"""

from __future__ import annotations

import asyncio
import logging

from mautrix.appservice import AppService
from mautrix.types import EventType

from .config import RelayConfig
from .event_map import EventMap
from .handler import RelayHandler
from .puppet import PuppetManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("relay")

# Background cleanup interval (6 hours).
_CLEANUP_INTERVAL = 6 * 3600


async def main() -> None:
    """Create the :class:`AppService` and start the HTTP server."""
    config = RelayConfig.from_env()
    log.info("Portal rooms: %s", config.portal_rooms)
    log.info("Hub room: %s", config.hub_room_id)

    # Open the event ID mapping database.
    event_map = EventMap(config.db_path)
    await event_map.open()

    appservice = AppService(
        server=config.homeserver_url,
        domain=config.domain,
        as_token=config.as_token,
        hs_token=config.hs_token,
        bot_localpart=config.bot_localpart,
        id="relay-bot",
    )

    puppet_manager = PuppetManager(appservice=appservice, domain=config.domain)

    handler = RelayHandler(
        appservice=appservice,
        puppet_manager=puppet_manager,
        portal_rooms=config.portal_rooms,
        hub_room_id=config.hub_room_id,
        event_map=event_map,
    )

    @appservice.matrix_event_handler
    async def on_event(event) -> None:
        """Dispatch incoming Matrix events to the relay handler."""
        if event.type == EventType.ROOM_MESSAGE:
            await handler.handle_message(event)
        elif event.type == EventType.REACTION:
            await handler.handle_reaction(event)

    # Ensure the bot has joined all rooms.
    log.info("Starting appservice on 0.0.0.0:8009")
    await appservice.start(host="0.0.0.0", port=8009)

    for room_id in (*config.portal_rooms, config.hub_room_id):
        try:
            await appservice.intent.ensure_joined(room_id)
            log.info("Bot joined %s", room_id)
        except Exception:
            log.exception("Failed to join %s", room_id)

    # Periodic cleanup of old event mappings.
    async def cleanup_loop() -> None:
        while True:
            await asyncio.sleep(_CLEANUP_INTERVAL)
            try:
                await event_map.cleanup(max_age_days=30)
            except Exception:
                log.exception("Event map cleanup failed")

    cleanup_task = asyncio.create_task(cleanup_loop())

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Shutting down")
    finally:
        cleanup_task.cancel()
        await appservice.stop()
        await event_map.close()


if __name__ == "__main__":
    asyncio.run(main())

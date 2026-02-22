"""WhatsApp ↔ Hub relay bot.

Copies messages between the WhatsApp portal room and the superbridge hub room
so that WhatsApp traffic flows to/from Discord, Telegram, and Matrix.

mautrix-whatsapp's megabridge architecture doesn't support plumbing a WhatsApp
group into an existing room, so this bot bridges the gap by relaying messages
between the two rooms with sender attribution.
"""

import asyncio
import logging
import os
import re
import sys

from nio import AsyncClient, MatrixRoom, RoomMessageText

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("relay")

# --- Configuration (all via environment variables) ---

HOMESERVER = os.environ["MATRIX_HOMESERVER"]
USER = os.environ["MATRIX_USER"]
PASSWORD = os.environ.get("MATRIX_PASSWORD", "")
ACCESS_TOKEN = os.environ.get("MATRIX_ACCESS_TOKEN", "")
WHATSAPP_ROOM = os.environ["WHATSAPP_ROOM_ID"]
HUB_ROOM = os.environ["HUB_ROOM_ID"]

# Bridge bot Matrix user localparts — messages from these are already relayed
# by the bridges themselves, so we must not double-relay them.
BRIDGE_BOT_LOCALPARTS = {"whatsappbot", "discordbot", "telegrambot", "signalbot"}

# Patterns to detect messages that already carry relay attribution to avoid
# re-wrapping relayed text.  Matches both:
#   - Bold markdown: "**Name (Platform):** …"  (this bot's format)
#   - Plain colon:   "Name: …"                 (Discord relay-mode webhook format)
ATTRIBUTION_RE = re.compile(
    r"^\*\*.+\(.*\):\*\*"  # bold attribution from this bot
    r"|"
    r"^[A-Z][A-Za-z0-9_ ]+: ",  # plain "Name: msg" from Discord relay mode
)


def _is_bridge_puppet(user_id: str) -> bool:
    """Return True if *user_id* belongs to a bridge puppet or bot.

    Bridge puppets follow the pattern ``@_<bridgename>_<id>:domain``.
    Bridge bots are the well-known bot users listed above.
    """
    localpart = user_id.split(":")[0].lstrip("@")
    if localpart in BRIDGE_BOT_LOCALPARTS:
        return True
    # Puppet users created by mautrix bridges start with an underscore prefix
    # like _whatsapp_, _discord_, _telegram_, _signal_.
    if localpart.startswith(("_whatsapp_", "_discord_", "_telegram_", "_signal_")):
        return True
    return False


def _platform_label(user_id: str) -> str:
    """Infer the originating platform from a Matrix user ID.

    Bridge puppet MXIDs contain a platform prefix (e.g. ``@_discord_123:domain``).
    For native Matrix users we fall back to "Matrix".
    """
    localpart = user_id.split(":")[0].lstrip("@")
    for prefix, name in (
        ("_discord_", "Discord"),
        ("_telegram_", "Telegram"),
        ("_signal_", "Signal"),
        ("_whatsapp_", "WhatsApp"),
    ):
        if localpart.startswith(prefix):
            return name
    return "Matrix"


def _display_name(room: MatrixRoom, user_id: str) -> str:
    """Best-effort display name for *user_id* in *room*."""
    member = room.users.get(user_id)
    if member and member.display_name:
        return member.display_name
    # Fallback: strip the leading '@' and domain from the MXID.
    return user_id.split(":")[0].lstrip("@")


def make_on_message(client: AsyncClient, my_user_id: str):
    """Build the ``on_message`` callback closed over *client* and *my_user_id*.

    Extracted from ``main()`` so that the callback can be tested without running
    the full startup sequence.
    """

    async def on_message(room: MatrixRoom, event: RoomMessageText) -> None:
        # Ignore our own messages.
        if event.sender == my_user_id:
            return

        # Ignore bridge bots and puppet users — the bridges handle those.
        if _is_bridge_puppet(event.sender):
            return

        # Ignore messages that already have relay attribution.
        if ATTRIBUTION_RE.match(event.body):
            return

        sender = _display_name(room, event.sender)

        if room.room_id == WHATSAPP_ROOM:
            target = HUB_ROOM
            label = "WhatsApp"
        elif room.room_id == HUB_ROOM:
            target = WHATSAPP_ROOM
            # Try to infer the originating platform from the sender's MXID so
            # the WhatsApp side sees "Nick (Telegram)" instead of "Nick (Matrix)"
            # for messages that arrived via another bridge.
            label = _platform_label(event.sender)
        else:
            return

        attributed = f"**{sender} ({label}):** {event.body}"
        log.info("Relay %s → %s: %s", room.room_id, target, attributed[:120])
        try:
            await client.room_send(
                target,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": attributed},
            )
        except Exception:
            log.exception("Failed to relay message to %s", target)

    return on_message


async def main() -> None:
    client = AsyncClient(HOMESERVER, USER)

    if ACCESS_TOKEN:
        client.access_token = ACCESS_TOKEN
        client.user_id = USER
        log.info("Using access token for %s on %s", USER, HOMESERVER)
    elif PASSWORD:
        log.info("Logging in as %s on %s", USER, HOMESERVER)
        resp = await client.login(PASSWORD)
        if hasattr(resp, "access_token"):
            log.info("Login successful")
        else:
            log.error("Login failed: %s", resp)
            sys.exit(1)
    else:
        log.error("Set MATRIX_ACCESS_TOKEN or MATRIX_PASSWORD")
        sys.exit(1)

    my_user_id: str = client.user_id

    # Join both rooms (no-op if already joined).
    for room_id in (WHATSAPP_ROOM, HUB_ROOM):
        join_resp = await client.join(room_id)
        log.info("Join %s: %s", room_id, join_resp)

    # Run an initial sync so we don't replay old history.
    log.info("Running initial sync …")
    await client.sync(timeout=10_000, full_state=True)
    log.info("Initial sync done — listening for messages")

    client.add_event_callback(
        make_on_message(client, my_user_id), RoomMessageText
    )

    # Sync forever.
    await client.sync_forever(timeout=30_000)


if __name__ == "__main__":
    asyncio.run(main())

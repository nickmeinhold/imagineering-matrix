"""Loop prevention for the relay appservice.

Three layers of filtering prevent message loops:

1. **Own messages**: Ignore messages from the bot itself and its puppet users.
2. **Bridge entities**: In portal rooms, ignore bridge bots. In the hub room,
   ignore both bridge bots and bridge puppet users.
3. **Attribution patterns**: Ignore messages that already carry relay attribution
   (e.g. ``**Name (Platform):** …``).
"""

from __future__ import annotations

import re

# Bridge bot Matrix user localparts.
BRIDGE_BOT_LOCALPARTS = frozenset({
    "whatsappbot", "discordbot", "telegrambot", "signalbot",
})

# Bridge puppet MXID prefixes (created by mautrix bridges).
BRIDGE_PUPPET_PREFIXES = (
    "_whatsapp_", "_discord_", "_telegram_", "_signal_",
)

# Relay puppet MXID prefix (created by this appservice).
RELAY_PUPPET_PREFIX = "_relay_"

# Matches both:
#   - Bold markdown: "**Name (Platform):** …"  (this bot's format)
#   - Plain colon:   "Name: …"                 (Discord relay-mode webhook format)
ATTRIBUTION_RE = re.compile(
    r"^\*\*.+\(.*\):\*\*"
    r"|"
    r"^[A-Z][A-Za-z0-9_ ]+: ",
)


def is_own_message(sender: str, bot_mxid: str) -> bool:
    """Layer 1: True if the sender is the bot itself."""
    return sender == bot_mxid


def is_relay_puppet(user_id: str) -> bool:
    """Layer 1b: True if the user is one of our relay puppet users."""
    localpart = user_id.split(":")[0].lstrip("@")
    return localpart.startswith(RELAY_PUPPET_PREFIX)


def is_bridge_bot(user_id: str) -> bool:
    """Layer 2: True if the user is a well-known bridge bot account."""
    localpart = user_id.split(":")[0].lstrip("@")
    return localpart in BRIDGE_BOT_LOCALPARTS


def is_bridge_puppet(user_id: str) -> bool:
    """Layer 2: True if the user is a bridge puppet or bot.

    Bridge puppets follow the pattern ``@_<bridgename>_<id>:domain``.
    Bridge bots are the well-known bot users.
    """
    localpart = user_id.split(":")[0].lstrip("@")
    if localpart in BRIDGE_BOT_LOCALPARTS:
        return True
    return localpart.startswith(BRIDGE_PUPPET_PREFIXES)


def has_attribution(body: str) -> bool:
    """Layer 3: True if the message body already has relay attribution."""
    return bool(ATTRIBUTION_RE.match(body))


def platform_label(user_id: str) -> str:
    """Infer the originating platform from a Matrix user ID.

    Bridge puppet MXIDs contain a platform prefix (e.g. ``@_discord_123:domain``).
    For native Matrix users we return ``"Matrix"``.
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


def should_ignore_in_portal(sender: str, body: str, bot_mxid: str) -> bool:
    """Return True if the event should be ignored in a portal room.

    Portal rooms use lighter filtering: bridge puppets ARE the real users
    in megabridge portals and must be relayed.  Only bridge bots are filtered.
    """
    if is_own_message(sender, bot_mxid):
        return True
    if is_relay_puppet(sender):
        return True
    if is_bridge_bot(sender):
        return True
    if has_attribution(body):
        return True
    return False


def should_ignore_in_hub(sender: str, body: str, bot_mxid: str) -> bool:
    """Return True if the event should be ignored in the hub room.

    The hub uses heavier filtering: both bridge bots and bridge puppet users
    are filtered because the bridges handle them natively.
    """
    if is_own_message(sender, bot_mxid):
        return True
    if is_relay_puppet(sender):
        return True
    if is_bridge_puppet(sender):
        return True
    if has_attribution(body):
        return True
    return False

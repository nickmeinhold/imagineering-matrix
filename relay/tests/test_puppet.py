"""Unit tests for puppet user management.

Verifies deterministic MXID generation, display name setting (no platform
suffix), avatar syncing, and member state event scoping (hub only for updates,
single join-with-profile for first entry).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from appservice.puppet import PuppetManager


DOMAIN = "example.com"


@pytest.fixture()
def manager() -> PuppetManager:
    """A PuppetManager with a mock AppService."""
    appservice = MagicMock()
    appservice.intent = MagicMock()
    return PuppetManager(appservice=appservice, domain=DOMAIN)


# ---------------------------------------------------------------------------
# MXID generation
# ---------------------------------------------------------------------------


class TestMxidGeneration:
    """Puppet MXIDs are deterministic and collision-resistant."""

    def test_mxid_starts_with_relay_prefix(self, manager: PuppetManager):
        mxid = manager.mxid_for("whatsapp", "@_whatsapp_12345:example.com")
        assert mxid.startswith("@_relay_")

    def test_mxid_contains_platform(self, manager: PuppetManager):
        mxid = manager.mxid_for("whatsapp", "@_whatsapp_12345:example.com")
        assert "_relay_whatsapp_" in mxid

    def test_mxid_ends_with_domain(self, manager: PuppetManager):
        mxid = manager.mxid_for("whatsapp", "@_whatsapp_12345:example.com")
        assert mxid.endswith(f":{DOMAIN}")

    def test_same_input_same_output(self, manager: PuppetManager):
        """The same sender always produces the same puppet MXID."""
        a = manager.mxid_for("whatsapp", "@_whatsapp_12345:example.com")
        b = manager.mxid_for("whatsapp", "@_whatsapp_12345:example.com")
        assert a == b

    def test_different_senders_different_mxids(self, manager: PuppetManager):
        a = manager.mxid_for("whatsapp", "@_whatsapp_12345:example.com")
        b = manager.mxid_for("whatsapp", "@_whatsapp_67890:example.com")
        assert a != b

    def test_different_platforms_different_mxids(self, manager: PuppetManager):
        """Same user ID on different platforms produces different puppets."""
        a = manager.mxid_for("whatsapp", "@alice:example.com")
        b = manager.mxid_for("signal", "@alice:example.com")
        assert a != b

    def test_mxid_for_native_matrix_user(self, manager: PuppetManager):
        """Native Matrix users also get deterministic puppet MXIDs."""
        mxid = manager.mxid_for("matrix", "@nick:example.com")
        assert mxid.startswith("@_relay_matrix_")

    def test_hash_is_8_chars(self, manager: PuppetManager):
        """The hash portion is 8 hex characters."""
        mxid = manager.mxid_for("whatsapp", "@_whatsapp_12345:example.com")
        # Format: @_relay_{platform}_{hash8}:{domain}
        localpart = mxid.split(":")[0].lstrip("@")
        # Remove prefix "_relay_whatsapp_"
        hash_part = localpart.removeprefix("_relay_whatsapp_")
        assert len(hash_part) == 8
        assert all(c in "0123456789abcdef" for c in hash_part)


# ---------------------------------------------------------------------------
# Intent management
# ---------------------------------------------------------------------------


class TestGetIntent:
    """get_intent() returns an IntentAPI for the puppet and ensures it's set up."""

    async def test_returns_intent(self, manager: PuppetManager):
        intent = AsyncMock()
        intent.ensure_registered = AsyncMock()
        intent.set_displayname = AsyncMock()
        intent.ensure_joined = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        result = await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!room:example.com",
        )

        assert result is intent

    async def test_ensures_registered(self, manager: PuppetManager):
        intent = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!room:example.com",
        )

        intent.ensure_registered.assert_awaited_once()

    async def test_sets_display_name(self, manager: PuppetManager):
        """Display name is just the name — no platform suffix."""
        intent = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!room:example.com",
        )

        intent.set_displayname.assert_awaited_once_with("Alice")

    async def test_first_join_uses_state_event(self, manager: PuppetManager):
        """First entry to a room uses a single state event (join + profile)."""
        intent = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!room:example.com",
        )

        # Joined via state event, not ensure_joined.
        intent.send_state_event.assert_awaited_once()
        intent.ensure_joined.assert_not_awaited()

    async def test_subsequent_call_uses_ensure_joined(self, manager: PuppetManager):
        """Same room + same profile on second call uses ensure_joined."""
        intent = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!room:example.com",
        )
        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!room:example.com",
        )

        # State event only on first call, ensure_joined on second.
        assert intent.send_state_event.await_count == 1
        assert intent.ensure_joined.await_count == 1

    async def test_caches_intent(self, manager: PuppetManager):
        """Same puppet MXID returns the same intent on subsequent calls."""
        intent = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        first = await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!room:example.com",
        )
        second = await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!another:example.com",
        )

        # user() is only called once due to caching.
        assert manager._appservice.intent.user.call_count == 1
        # Each new room gets a state event for first join.
        assert intent.send_state_event.await_count == 2

    async def test_display_name_not_updated_when_unchanged(self, manager: PuppetManager):
        """If the display name hasn't changed, don't call set_displayname again."""
        intent = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!room:example.com",
        )
        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!room:example.com",
        )

        # set_displayname called only once since name didn't change.
        assert intent.set_displayname.await_count == 1

    async def test_display_name_updated_when_changed(self, manager: PuppetManager):
        """If the display name changes, update it."""
        intent = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!room:example.com",
        )
        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice Smith",
            room_id="!room:example.com",
        )

        assert intent.set_displayname.await_count == 2


# ---------------------------------------------------------------------------
# First join carries profile (single event)
# ---------------------------------------------------------------------------


class TestFirstJoinProfile:
    """First entry to any room sends a single m.room.member with profile."""

    async def test_first_join_carries_displayname(self, manager: PuppetManager):
        intent = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!portal:example.com",
        )

        call = intent.send_state_event.await_args
        content = call.args[3] if len(call.args) > 3 else call.kwargs.get("content")
        assert content["displayname"] == "Alice"
        assert content["membership"] == "join"

    async def test_first_join_carries_avatar(self, manager: PuppetManager):
        intent = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            avatar_url="mxc://example.com/avatar",
            room_id="!portal:example.com",
        )

        call = intent.send_state_event.await_args
        content = call.args[3] if len(call.args) > 3 else call.kwargs.get("content")
        assert content["avatar_url"] == "mxc://example.com/avatar"

    async def test_first_join_without_avatar(self, manager: PuppetManager):
        """No avatar URL produces an empty string in the member event."""
        intent = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!portal:example.com",
        )

        call = intent.send_state_event.await_args
        content = call.args[3] if len(call.args) > 3 else call.kwargs.get("content")
        assert content["avatar_url"] == ""

    async def test_each_room_gets_its_own_first_join(self, manager: PuppetManager):
        """Joining two different rooms sends a state event for each."""
        intent = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!room1:example.com",
        )
        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!room2:example.com",
        )

        assert intent.send_state_event.await_count == 2
        intent.ensure_joined.assert_not_awaited()


# ---------------------------------------------------------------------------
# Profile update scoping (hub vs portal)
# ---------------------------------------------------------------------------


class TestProfileUpdateScoping:
    """After first join, profile updates only re-sync in the hub room."""

    async def test_profile_change_resyncs_in_hub(self, manager: PuppetManager):
        """sync_member_state=True re-sends state event on profile change."""
        intent = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!hub:example.com",
            sync_member_state=True,
        )
        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice Smith",
            room_id="!hub:example.com",
            sync_member_state=True,
        )

        # First join + profile update = 2 state events.
        assert intent.send_state_event.await_count == 2
        intent.ensure_joined.assert_not_awaited()

    async def test_profile_change_skipped_in_portal(self, manager: PuppetManager):
        """sync_member_state=False skips re-sync on profile change."""
        intent = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            room_id="!portal:example.com",
        )
        await manager.get_intent(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice Smith",
            room_id="!portal:example.com",
        )

        # Only the first join, not the profile update.
        assert intent.send_state_event.await_count == 1
        # Falls back to ensure_joined for the second call.
        assert intent.ensure_joined.await_count == 1

    async def test_unchanged_profile_uses_ensure_joined(self, manager: PuppetManager):
        """Same profile on repeated calls uses ensure_joined (no-op)."""
        intent = AsyncMock()
        manager._appservice.intent.user.return_value = intent

        for _ in range(3):
            await manager.get_intent(
                platform="whatsapp",
                sender="@_whatsapp_12345:example.com",
                display_name="Alice",
                room_id="!hub:example.com",
                sync_member_state=True,
            )

        # State event only on first call.
        assert intent.send_state_event.await_count == 1
        # ensure_joined on subsequent 2 calls.
        assert intent.ensure_joined.await_count == 2

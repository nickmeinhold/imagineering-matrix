"""Tests for the ``main()`` authentication branching logic."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import relay_bot


class _SyncForeverExit(Exception):
    """Raised by the mock ``sync_forever`` to break out of ``main()``."""


class TestAuthFlow:
    """Verify that ``main()`` picks the right auth strategy."""

    async def test_access_token_skips_login(self, monkeypatch):
        """When MATRIX_ACCESS_TOKEN is set, ``client.login`` is never called."""
        monkeypatch.setattr(relay_bot, "ACCESS_TOKEN", "syt_fake_token")
        monkeypatch.setattr(relay_bot, "PASSWORD", "")

        mock_client = AsyncMock()
        mock_client.user_id = relay_bot.USER
        mock_client.add_event_callback = MagicMock()
        mock_client.sync_forever = AsyncMock(side_effect=_SyncForeverExit)

        with patch("relay_bot.AsyncClient", return_value=mock_client):
            with pytest.raises(_SyncForeverExit):
                await relay_bot.main()

        mock_client.login.assert_not_awaited()
        assert mock_client.access_token == "syt_fake_token"

    async def test_password_calls_login(self, monkeypatch):
        """When only MATRIX_PASSWORD is set, ``client.login`` is called."""
        monkeypatch.setattr(relay_bot, "ACCESS_TOKEN", "")
        monkeypatch.setattr(relay_bot, "PASSWORD", "hunter2")

        mock_client = AsyncMock()
        mock_client.user_id = relay_bot.USER
        # login returns an object with access_token attr on success.
        mock_client.login.return_value = AsyncMock(access_token="syt_new")
        mock_client.add_event_callback = MagicMock()
        mock_client.sync_forever = AsyncMock(side_effect=_SyncForeverExit)

        with patch("relay_bot.AsyncClient", return_value=mock_client):
            with pytest.raises(_SyncForeverExit):
                await relay_bot.main()

        mock_client.login.assert_awaited_once_with("hunter2")

    async def test_access_token_sets_user_id(self, monkeypatch):
        """Regression: access token path must set ``client.user_id`` directly.

        Before the fix, only the password path populated ``user_id`` (via
        ``client.login``).  The access token path must assign it explicitly
        so that ``my_user_id`` — used for loop prevention — is correct.
        """
        monkeypatch.setattr(relay_bot, "ACCESS_TOKEN", "syt_fake_token")
        monkeypatch.setattr(relay_bot, "PASSWORD", "")

        mock_client = AsyncMock()
        mock_client.user_id = relay_bot.USER
        mock_client.add_event_callback = MagicMock()
        mock_client.sync_forever = AsyncMock(side_effect=_SyncForeverExit)

        with patch("relay_bot.AsyncClient", return_value=mock_client):
            with pytest.raises(_SyncForeverExit):
                await relay_bot.main()

        assert mock_client.user_id == relay_bot.USER

    async def test_login_failure_exits(self, monkeypatch):
        """Regression: a failed ``client.login`` must call ``sys.exit(1)``.

        The login response lacks an ``access_token`` attribute on failure.
        """
        monkeypatch.setattr(relay_bot, "ACCESS_TOKEN", "")
        monkeypatch.setattr(relay_bot, "PASSWORD", "wrong-password")

        mock_client = AsyncMock()
        # Simulate a failed login: response has no access_token attribute.
        mock_client.login.return_value = MagicMock(spec=[])

        with patch("relay_bot.AsyncClient", return_value=mock_client):
            with pytest.raises(SystemExit) as exc_info:
                await relay_bot.main()

        assert exc_info.value.code == 1

    async def test_no_credentials_exits(self, monkeypatch):
        """When neither token nor password is set, ``sys.exit(1)`` is called."""
        monkeypatch.setattr(relay_bot, "ACCESS_TOKEN", "")
        monkeypatch.setattr(relay_bot, "PASSWORD", "")

        mock_client = AsyncMock()

        with patch("relay_bot.AsyncClient", return_value=mock_client):
            with pytest.raises(SystemExit) as exc_info:
                await relay_bot.main()

        assert exc_info.value.code == 1

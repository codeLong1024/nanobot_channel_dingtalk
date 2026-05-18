"""Tests for DingTalkChannel streaming integration."""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot_channel_dingtalk.channel import DingTalkChannel


@pytest.fixture
def channel():
    """Create a channel with minimal config."""
    config = {
        "enabled": True,
        "client_id": "test_client",
        "client_secret": "test_secret",
        "log_level": "INFO",
        "enable_marker_processing": True,
    }
    bus = MagicMock()
    ch = DingTalkChannel(config, bus)
    return ch


class TestChannelInit:
    """Channel initialization with streaming state."""

    def test_card_client_none_initially(self, channel):
        assert channel.card_client is None

    def test_card_manager_none_initially(self, channel):
        assert channel.card_manager is None

    def test_pending_cards_empty(self, channel):
        assert channel._pending_cards == {}

    def test_card_enabled_empty(self, channel):
        assert channel._card_enabled == {}

    def test_sender_has_pending_cards_ref(self, channel):
        assert channel.sender._pending_cards is channel._pending_cards

    def test_background_tasks(self, channel):
        assert channel._background_tasks == set()


class TestChannelOnMessage:
    """_on_message streaming metadata."""

    @pytest.mark.asyncio
    async def test_wants_stream_when_card_enabled(self, channel):
        channel._card_enabled["chat_1"] = True
        with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
            await channel._on_message(
                content="hello",
                sender_id="user1",
                sender_name="User",
                chat_id="chat_1",
                media=None,
            )
            _, kwargs = mock_handle.call_args
            assert kwargs["metadata"]["_wants_stream"] is True

    @pytest.mark.asyncio
    async def test_no_wants_stream_when_card_disabled(self, channel):
        channel._card_enabled["chat_1"] = False
        with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
            await channel._on_message(
                content="hello",
                sender_id="user1",
                sender_name="User",
                chat_id="chat_1",
                media=None,
            )
            _, kwargs = mock_handle.call_args
            assert kwargs["metadata"].get("_wants_stream") is None

    @pytest.mark.asyncio
    async def test_wants_stream_defaults_false(self, channel):
        with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
            await channel._on_message(
                content="hello",
                sender_id="user1",
                sender_name="User",
                chat_id="unknown_chat",
                media=None,
            )
            _, kwargs = mock_handle.call_args
            assert kwargs["metadata"].get("_wants_stream") is None


class TestChannelStart:
    """Channel start initializes card infrastructure."""

    @pytest.mark.asyncio
    async def test_start_initializes_card_client_and_manager(self, channel):
        """Verify start() initializes card_client and card_manager before entering the stream loop."""
        # _client.start() blocks forever (real SDK behavior).
        # We create a future that never resolves, run start() as a task,
        # yield to let it reach the await, then cancel.
        async def never_return():
            await asyncio.Future()  # hangs forever

        with (
            patch("nanobot_channel_dingtalk.channel.DINGTALK_AVAILABLE", True),
            patch("nanobot_channel_dingtalk.channel.Credential"),
            patch("nanobot_channel_dingtalk.channel.DingTalkStreamClient") as mock_cls,
            patch.object(channel.sender, "setup") as mock_setup,
        ):
            mock_cls.return_value.start = never_return
            task = asyncio.create_task(channel.start())
            # Yield so start() completes init and enters _client.start()
            await asyncio.sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

            assert channel.card_client is not None
            assert channel.card_manager is not None
            mock_setup.assert_called_once()
            assert mock_setup.call_args[0][1] is channel.card_manager


class TestChannelStop:
    """Channel stop cleans up card client."""

    @pytest.mark.asyncio
    async def test_stop_closes_card_client(self, channel):
        channel.card_client = MagicMock()
        channel.card_client.close = AsyncMock()
        channel._http = MagicMock()
        channel._http.aclose = AsyncMock()
        channel.sender = MagicMock()
        channel.sender.close = AsyncMock()

        await channel.stop()
        channel.card_client.close.assert_awaited_once()

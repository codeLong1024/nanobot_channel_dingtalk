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

    def test_sender_has_pending_cards_ref(self, channel):
        assert channel.sender._pending_cards is channel._pending_cards

    def test_background_tasks(self, channel):
        assert channel._background_tasks == set()


class TestChannelOnMessage:
    """_on_message streaming metadata and parameter forwarding."""

    @pytest.mark.asyncio
    async def test_wants_stream_not_set_by_on_message(self, channel):
        """_wants_stream is now delegated to BaseChannel._handle_message."""
        with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
            await channel._on_message(
                content="hello",
                sender_id="user1",
                sender_name="User",
                chat_id="chat_1",
                media=None,
            )
            _, kwargs = mock_handle.call_args
            assert "_wants_stream" not in kwargs["metadata"]

    @pytest.mark.asyncio
    async def test_conversation_type_dm(self, channel):
        """is_dm=True → conversation_type is '1'."""
        with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
            await channel._on_message(
                content="hello",
                sender_id="user1",
                sender_name="User",
                chat_id="user1",
                media=None,
                is_dm=True,
            )
            _, kwargs = mock_handle.call_args
            assert kwargs["metadata"]["conversation_type"] == "1"

    @pytest.mark.asyncio
    async def test_conversation_type_group(self, channel):
        """is_dm=False → conversation_type is '2'."""
        with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
            await channel._on_message(
                content="hello",
                sender_id="user1",
                sender_name="User",
                chat_id="conv_123",
                media=None,
                is_dm=False,
            )
            _, kwargs = mock_handle.call_args
            assert kwargs["metadata"]["conversation_type"] == "2"

    @pytest.mark.asyncio
    async def test_is_dm_and_session_key_forwarded(self, channel):
        """is_dm and session_key are forwarded to _handle_message."""
        with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
            await channel._on_message(
                content="hello",
                sender_id="user1",
                sender_name="User",
                chat_id="conv_123",
                media=None,
                is_dm=False,
                session_key="dingtalk:group:user1@conv_123",
            )
            _, kwargs = mock_handle.call_args
            assert kwargs["is_dm"] is False
            assert kwargs["session_key"] == "dingtalk:group:user1@conv_123"

    @pytest.mark.asyncio
    async def test_is_dm_and_session_key_defaults(self, channel):
        """is_dm defaults to False, session_key defaults to None."""
        with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
            await channel._on_message(
                content="hello",
                sender_id="user1",
                sender_name="User",
                chat_id="chat_1",
                media=None,
            )
            _, kwargs = mock_handle.call_args
            assert kwargs["is_dm"] is False
            assert kwargs["session_key"] is None


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

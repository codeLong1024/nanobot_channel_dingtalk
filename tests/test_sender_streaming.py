"""Tests for DingTalkSender streaming (AI Card) paths."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot_channel_dingtalk.sender import DingTalkSender


@pytest.fixture
def sender():
    """Create a DingTalkSender with mocked card_manager and token."""
    config = MagicMock()
    config.client_id = "test_client"
    config.client_secret = "test_secret"
    config.enable_marker_processing = True
    config.enable_media_upload = True
    config.media_max_mb = 20

    logger = MagicMock()
    http = MagicMock()

    card_mgr = MagicMock()
    card_mgr.stream_content = AsyncMock()
    card_mgr.finish_streaming = AsyncMock()
    card_mgr.finalize_card = AsyncMock(return_value=True)

    pending = {}

    s = DingTalkSender(
        config=config,
        logger=logger,
        http_client=http,
        card_manager=card_mgr,
        pending_cards=pending,
    )

    s.get_access_token = AsyncMock(return_value="test_token")
    s._send_markdown_text = AsyncMock(return_value=True)
    s._send_msg_media_refs = AsyncMock()

    return s


def make_msg(chat_id: str, content: str = "", media: list | None = None, metadata: dict | None = None):
    """Create a mock message object."""
    msg = MagicMock()
    msg.chat_id = chat_id
    msg.content = content
    msg.media = media or []
    msg.metadata = metadata or {}
    return msg


class TestSenderStreamingDelta:
    """Path 1: Streaming delta accumulates content and pushes to card."""

    @pytest.mark.asyncio
    async def test_stream_delta_accumulates(self, sender):
        sender._pending_cards["chat_1"] = "card_1"
        msg = make_msg("chat_1", "Hello", metadata={"_stream_delta": True})

        await sender.send(msg)
        assert sender._streaming_buffers["chat_1"] == "Hello"
        sender._card_manager.stream_content.assert_awaited_once_with("card_1", "Hello")

    @pytest.mark.asyncio
    async def test_stream_delta_multiple_chunks(self, sender):
        sender._pending_cards["chat_1"] = "card_1"
        await sender.send(make_msg("chat_1", "Hello", metadata={"_stream_delta": True}))
        await sender.send(make_msg("chat_1", " World", metadata={"_stream_delta": True}))

        assert sender._streaming_buffers["chat_1"] == "Hello World"
        assert sender._card_manager.stream_content.await_count == 2
        second_call = sender._card_manager.stream_content.await_args_list[1]
        assert second_call.args[1] == "Hello World"

    @pytest.mark.asyncio
    async def test_stream_delta_no_card(self, sender):
        msg = make_msg("chat_1", "Hello", metadata={"_stream_delta": True})
        await sender.send(msg)
        assert "chat_1" not in sender._streaming_buffers
        sender._card_manager.stream_content.assert_not_awaited()


class TestSenderStreamingEnd:
    """Path 2: Streaming end finalizes the card."""

    @pytest.mark.asyncio
    async def test_stream_end_finalizes(self, sender):
        sender._pending_cards["chat_1"] = "card_1"
        sender._streaming_buffers["chat_1"] = "Hello World"

        await sender.send(make_msg("chat_1", "", metadata={"_stream_end": True}))

        sender._card_manager.stream_content.assert_awaited_once_with("card_1", "Hello World")
        sender._card_manager.finish_streaming.assert_awaited_once_with("card_1", "Hello World")
        assert "card_1" not in sender._pending_cards
        assert "chat_1" in sender._streamed_chats

    @pytest.mark.asyncio
    async def test_stream_end_resuming_skips(self, sender):
        sender._pending_cards["chat_1"] = "card_1"
        await sender.send(make_msg("chat_1", "", metadata={"_stream_end": True, "_resuming": True}))
        sender._card_manager.finish_streaming.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stream_end_empty_buffer(self, sender):
        sender._pending_cards["chat_1"] = "card_1"
        await sender.send(make_msg("chat_1", "Direct", metadata={"_stream_end": True}))
        sender._card_manager.stream_content.assert_awaited_once_with("card_1", "Direct")


class TestSenderProgressSkip:
    """Path 3: Progress messages are skipped when card is pending."""

    @pytest.mark.asyncio
    async def test_progress_skipped_with_card(self, sender):
        sender._pending_cards["chat_1"] = "card_1"
        await sender.send(make_msg("chat_1", "Working...", metadata={"_progress": True}))
        sender._send_markdown_text.assert_not_awaited()
        assert "card_1" in sender._pending_cards.values()

    @pytest.mark.asyncio
    async def test_retry_wait_skipped(self, sender):
        sender._pending_cards["chat_1"] = "card_1"
        await sender.send(make_msg("chat_1", "Retrying...", metadata={"_retry_wait": True}))
        sender._send_markdown_text.assert_not_awaited()


class TestSenderNonStreamingWithCard:
    """Path 4: Non-streaming message with pending card calls finalize_card."""

    @pytest.mark.asyncio
    async def test_finalize_card_called(self, sender):
        sender._pending_cards["chat_1"] = "card_1"
        await sender.send(make_msg("chat_1", "Final answer"))

        sender._card_manager.finalize_card.assert_awaited_once_with("card_1", "Final answer")
        assert "card_1" not in sender._pending_cards

    @pytest.mark.asyncio
    async def test_media_only_preserves_card(self, sender):
        sender._pending_cards["chat_1"] = "card_1"
        await sender.send(make_msg("chat_1", "file.jpg", media=["file.jpg"]))

        sender._card_manager.finalize_card.assert_not_awaited()
        assert sender._pending_cards.get("chat_1") == "card_1"
        sender._send_msg_media_refs.assert_awaited_once()


class TestSenderFallbackMarkdown:
    """Path 5: No card — fallback to markdown."""

    @pytest.mark.asyncio
    async def test_markdown_sent(self, sender):
        await sender.send(make_msg("chat_1", "Plain text"))
        sender._send_markdown_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_content_skipped(self, sender):
        await sender.send(make_msg("chat_1", ""))
        sender._send_markdown_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_streamed_chat_skips_markdown(self, sender):
        sender._streamed_chats["chat_1"] = True
        await sender.send(make_msg("chat_1", "Already streamed"))
        sender._send_markdown_text.assert_not_awaited()


class TestSenderMarkChatStreamed:
    """_mark_chat_streamed LRU tracking."""

    def test_mark_chat_streamed_adds(self, sender):
        sender._mark_chat_streamed("chat_1")
        assert "chat_1" in sender._streamed_chats

    def test_mark_chat_streamed_moves_to_end(self, sender):
        sender._streamed_chats["old"] = True
        sender._streamed_chats["new"] = True
        sender._mark_chat_streamed("old")
        assert list(sender._streamed_chats.keys()) == ["new", "old"]

    def test_lru_eviction(self, sender):
        sender._STREAMED_CHAT_MAX = 3
        for i in range(5):
            sender._mark_chat_streamed(f"chat_{i}")
        assert len(sender._streamed_chats) == 3
        assert "chat_0" not in sender._streamed_chats
        assert "chat_1" not in sender._streamed_chats
        assert "chat_4" in sender._streamed_chats


class TestSenderMediaPipeline:
    """Media pipeline runs for non-streaming content."""

    @pytest.mark.asyncio
    async def test_media_pipeline_skipped_for_stream_delta(self, sender):
        sender._pending_cards["chat_1"] = "card_1"
        with patch("nanobot_channel_dingtalk.sender.process_local_images") as mock_proc:
            await sender.send(make_msg("chat_1", "delta", metadata={"_stream_delta": True}))
            mock_proc.assert_not_called()

    @pytest.mark.asyncio
    async def test_media_pipeline_runs_for_normal(self, sender):
        with patch("nanobot_channel_dingtalk.sender.process_local_images") as mock_proc:
            mock_proc.return_value = "processed"
            await sender.send(make_msg("chat_1", "normal content"))
            mock_proc.assert_called_once()

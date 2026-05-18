"""Tests for CardManager."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nanobot_channel_dingtalk.card_client import DingTalkCardClient
from nanobot_channel_dingtalk.card_manager import CardManager


@pytest.fixture
def mock_client():
    """Create a DingTalkCardClient with mocked HTTP."""
    client = DingTalkCardClient(access_token_fn=AsyncMock(return_value="test_token"))
    mock_http = MagicMock(spec=httpx.AsyncClient)
    mock_http.is_closed = False  # prevent ensure_async_client() from creating real HTTP
    ok_resp = MagicMock(spec=httpx.Response)
    ok_resp.status_code = 200
    ok_resp.text = '{"success": true, "result": [{}]}'
    ok_resp.json.return_value = {"success": True, "result": [{}]}
    mock_http.post = AsyncMock(return_value=ok_resp)
    mock_http.put = AsyncMock(return_value=ok_resp)
    client.async_http = mock_http
    return client


@pytest.fixture
def cm(mock_client):
    return CardManager(mock_client)


class TestCardManagerInit:
    """CardManager basic init."""

    def test_generate_track_id(self):
        tid = CardManager.generate_track_id()
        assert tid.startswith("card_")
        assert "_" in tid

    def test_random_str(self):
        s = CardManager._random_str(6)
        assert len(s) == 6
        assert isinstance(s, str)

    def test_random_str_default(self):
        s = CardManager._random_str()
        assert len(s) == 8


class TestCardManagerCreate:
    """Card creation flow."""

    @pytest.mark.asyncio
    async def test_create_card_success(self, cm, mock_client):
        cid = await cm.create_card(
            card_instance_id="test_card_1",
            robot_code="robot1",
            target={"openConversationId": "conv123"},
        )
        assert cid == "test_card_1"
        assert mock_client.async_http.post.call_count == 2

    @pytest.mark.asyncio
    async def test_create_card_failure(self, cm, mock_client):
        fail_resp = MagicMock(spec=httpx.Response)
        fail_resp.status_code = 500
        fail_resp.text = "Server Error"
        fail_resp.request = MagicMock()
        mock_client.async_http.post = AsyncMock(return_value=fail_resp)

        with pytest.raises(httpx.HTTPStatusError, match="Server error"):
            await cm.create_card(
                card_instance_id="fail_card",
                robot_code="robot1",
                target={"openConversationId": "conv123"},
            )

    @pytest.mark.asyncio
    async def test_create_card_delivery_rejected(self, cm, mock_client):
        ok_create = MagicMock(spec=httpx.Response)
        ok_create.status_code = 200
        ok_create.text = '{"success": true}'
        ok_create.json.return_value = {"success": True}

        fail_deliver = MagicMock(spec=httpx.Response)
        fail_deliver.status_code = 200
        fail_deliver.text = '{"success": false, "result": [{"errorMsg": "no permission"}]}'
        fail_deliver.json.return_value = {"success": False, "result": [{"errorMsg": "no permission"}]}

        mock_client.async_http.post = AsyncMock(side_effect=[ok_create, fail_deliver])

        with pytest.raises(RuntimeError, match="Card delivery rejected"):
            await cm.create_card(
                card_instance_id="rejected",
                robot_code="robot1",
                target={"openConversationId": "conv123"},
            )


class TestCardManagerStreaming:
    """Streaming flow."""

    @pytest.mark.asyncio
    async def test_start_streaming(self, cm, mock_client):
        await cm.start_streaming("card_1", "思考中...")
        mock_client.async_http.put.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stream_content(self, cm, mock_client):
        await cm.stream_content("card_1", "Hello")
        mock_client.async_http.put.assert_awaited_once()
        call_kwargs = mock_client.async_http.put.call_args[1]
        assert call_kwargs["json"]["outTrackId"] == "card_1"
        assert call_kwargs["json"]["content"] == "Hello"
        assert call_kwargs["json"]["isFull"] is True

    @pytest.mark.asyncio
    async def test_finish_streaming(self, cm, mock_client):
        await cm.finish_streaming("card_1", "Done")
        mock_client.async_http.put.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fail_card(self, cm, mock_client):
        await cm.fail_card("card_1", "Something went wrong")
        mock_client.async_http.put.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fail_card_error_safe(self, cm):
        client = DingTalkCardClient(access_token_fn=AsyncMock(return_value="token"))
        fail_resp = MagicMock(spec=httpx.Response)
        fail_resp.status_code = 500
        fail_resp.text = "Error"
        mock_http = MagicMock(spec=httpx.AsyncClient)
        mock_http.is_closed = False
        mock_http.put = AsyncMock(return_value=fail_resp)
        client.async_http = mock_http
        cm2 = CardManager(client)
        await cm2.fail_card("card_2", "error")

    @pytest.mark.asyncio
    async def test_stream_content_qps_retry(self, cm, mock_client):
        qps_resp = MagicMock(spec=httpx.Response)
        qps_resp.status_code = 403
        qps_resp.text = "QpsLimit exceeded"
        qps_resp.request = MagicMock()

        ok_resp = MagicMock(spec=httpx.Response)
        ok_resp.status_code = 200
        ok_resp.text = "OK"

        mock_client.async_http.put = AsyncMock(side_effect=[
            httpx.HTTPStatusError("QPS", request=MagicMock(), response=qps_resp),
            ok_resp,
        ])

        await cm.stream_content("card_1", "retry content")
        assert mock_client.async_http.put.call_count == 2


class TestCardManagerNonStreaming:
    """Non-streaming finalize fallback."""

    @pytest.mark.asyncio
    async def test_finalize_card_success(self, cm, mock_client):
        ok = await cm.finalize_card("card_1", "Final content")
        assert ok is True
        assert mock_client.async_http.put.call_count == 2

    @pytest.mark.asyncio
    async def test_finalize_card_failure(self, cm, mock_client):
        fail_resp = MagicMock(spec=httpx.Response)
        fail_resp.status_code = 500
        fail_resp.text = "Error"
        fail_resp.request = MagicMock()
        mock_client.async_http.put = AsyncMock(return_value=fail_resp)

        ok = await cm.finalize_card("card_1", "Final")
        assert ok is False

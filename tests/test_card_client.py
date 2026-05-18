"""Tests for DingTalkCardClient."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nanobot_channel_dingtalk.card_client import DingTalkCardClient


class TestDingTalkCardClientInit:
    """CardClient initialization defaults."""

    def test_default_init(self):
        client = DingTalkCardClient()
        assert client.api_base == "https://api.dingtalk.com"
        assert client.api_url == "https://api.dingtalk.com/v1.0"
        assert client._cached_token is None
        assert client.async_http is None

    def test_custom_init(self):
        client = DingTalkCardClient(
            api_base="https://custom.api.com",
            access_token_fn=lambda: "token",
            proxy_url="http://proxy:8080",
        )
        assert client.api_base == "https://custom.api.com"
        assert client.api_url == "https://custom.api.com/v1.0"


class TestDingTalkCardClientToken:
    """Token refresh and validation."""

    @pytest.mark.asyncio
    async def test_ensure_valid_token_refreshes(self):
        mock_fn = AsyncMock(return_value="fresh_token")
        client = DingTalkCardClient(access_token_fn=mock_fn)
        token = await client.ensure_valid_token()
        assert token == "fresh_token"
        assert client._cached_token == "fresh_token"
        mock_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ensure_valid_token_uses_cache(self):
        client = DingTalkCardClient()
        client._cached_token = "cached_token"
        client._token_obtained_at = 9999999999.0  # far future
        token = await client.ensure_valid_token()
        assert token == "cached_token"

    @pytest.mark.asyncio
    async def test_ensure_valid_token_raises_without_fn(self):
        client = DingTalkCardClient()
        with pytest.raises(RuntimeError, match="Unable to obtain access token"):
            await client.ensure_valid_token()

    @pytest.mark.asyncio
    async def test_get_headers_async(self):
        mock_fn = AsyncMock(return_value="test_token")
        client = DingTalkCardClient(access_token_fn=mock_fn)
        headers = await client.get_headers_async()
        assert headers["Content-Type"] == "application/json"
        assert headers["x-acs-dingtalk-access-token"] == "test_token"


class TestDingTalkCardClientHTTP:
    """HTTP client lifecycle."""

    @pytest.mark.asyncio
    async def test_ensure_async_client_creates(self):
        client = DingTalkCardClient()
        http = await client.ensure_async_client()
        assert http is not None
        assert not http.is_closed
        await client.close()

    @pytest.mark.asyncio
    async def test_ensure_async_client_reuses(self):
        client = DingTalkCardClient()
        http1 = await client.ensure_async_client()
        http2 = await client.ensure_async_client()
        assert http1 is http2
        await client.close()

    @pytest.mark.asyncio
    async def test_close(self):
        client = DingTalkCardClient()
        await client.ensure_async_client()
        await client.close()
        assert client.async_http is None or client.async_http.is_closed


class TestDingTalkCardClientErrorHandling:
    """Unified API error handling."""

    @pytest.mark.asyncio
    async def test_ok_response_no_error(self):
        client = DingTalkCardClient()
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        # Should not raise
        await client.check_response(resp, "test")

    @pytest.mark.asyncio
    async def test_403_qps_limit(self):
        client = DingTalkCardClient()
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 403
        resp.text = "QpsLimit exceeded"
        resp.request = MagicMock()
        with pytest.raises(httpx.HTTPStatusError, match="QPS limit"):
            await client.check_response(resp, "test")

    @pytest.mark.asyncio
    async def test_500_server_error(self):
        client = DingTalkCardClient()
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 500
        resp.text = "Internal Server Error"
        resp.request = MagicMock()
        with pytest.raises(httpx.HTTPStatusError, match="Server error"):
            await client.check_response(resp, "test")

    @pytest.mark.asyncio
    async def test_400_client_error(self):
        client = DingTalkCardClient()
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 400
        resp.text = "Bad Request"
        resp.request = MagicMock()
        with pytest.raises(httpx.HTTPStatusError, match="Client error"):
            await client.check_response(resp, "test")

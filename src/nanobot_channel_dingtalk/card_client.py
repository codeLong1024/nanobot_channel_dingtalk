"""DingTalk HTTP API client — wraps token management, headers, and error handling.

Adapted to use DingTalkSender.get_access_token() for token acquisition.
"""

from __future__ import annotations

import time
from typing import Any

import httpx


class DingTalkCardClient:
    """DingTalk AI Card HTTP client.

    Responsibilities:
    - Token auto-refresh (5 min ahead)
    - Async HTTP client lifecycle
    - Header construction with token injection
    - Unified API error handling
    """

    def __init__(
        self,
        api_base: str = "https://api.dingtalk.com",
        access_token_fn: Any = None,
        proxy_url: str | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self._access_token_fn = access_token_fn
        self._cached_token: str | None = None
        self._token_obtained_at: float = 0.0
        self._token_ttl: float = 7200.0
        self._proxy_url = proxy_url

        self.async_http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # HTTP client lifecycle
    # ------------------------------------------------------------------

    async def ensure_async_client(self) -> httpx.AsyncClient:
        """Ensure the async HTTP client exists."""
        if self.async_http is None or self.async_http.is_closed:
            kwargs: dict[str, Any] = {"timeout": 30}
            if self._proxy_url:
                kwargs["proxies"] = self._proxy_url
            self.async_http = httpx.AsyncClient(**kwargs)
        return self.async_http

    async def close(self) -> None:
        if self.async_http and not self.async_http.is_closed:
            await self.async_http.aclose()

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def _refresh_token(self) -> str | None:
        """Fetch a fresh access token via the provided callable."""
        if not self._access_token_fn:
            return None
        try:
            token = await self._access_token_fn()
            return token
        except Exception:
            return None

    async def ensure_valid_token(self) -> str:
        """Return a valid token, refreshing if needed (5 min ahead)."""
        elapsed = time.time() - self._token_obtained_at
        remaining = self._token_ttl - elapsed

        if self._cached_token and remaining > 300:
            return self._cached_token

        new_token = await self._refresh_token()
        if new_token:
            self._cached_token = new_token
            self._token_obtained_at = time.time()
            return new_token

        if self._cached_token:
            return self._cached_token

        raise RuntimeError("Unable to obtain access token")

    async def get_headers_async(self) -> dict[str, str]:
        """Build authorized headers (async, with token refresh)."""
        token = await self.ensure_valid_token()
        return {
            "Content-Type": "application/json",
            "x-acs-dingtalk-access-token": token,
        }

    # ------------------------------------------------------------------
    # Unified error handling
    # ------------------------------------------------------------------

    async def check_response(
        self,
        resp: httpx.Response,
        operation: str = "API call",
    ) -> None:
        """Raise HTTPStatusError on non-2xx responses."""
        if resp.status_code == 403 and "QpsLimit" in resp.text:
            raise httpx.HTTPStatusError(
                f"QPS limit: {resp.status_code}", request=resp.request, response=resp,
            )
        elif resp.status_code >= 500:
            raise httpx.HTTPStatusError(
                f"Server error: {resp.status_code}", request=resp.request, response=resp,
            )
        elif resp.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Client error: {resp.status_code}", request=resp.request, response=resp,
            )

    # ------------------------------------------------------------------
    # API URL helper
    # ------------------------------------------------------------------

    @property
    def api_url(self) -> str:
        """DingTalk API v1.0 base URL."""
        return f"{self.api_base}/v1.0"


__all__ = ["DingTalkCardClient"]

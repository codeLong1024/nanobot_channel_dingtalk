"""DingTalk Channel main class.

Uses Stream SDK (WebSocket) for message receiving.
Uses HTTP API (via DingTalkSender) for sending messages.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from loguru import logger as _loguru

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from .auth import (
    DINGTALK_AVAILABLE,
    ChatbotMessage,
    Credential,
    DingTalkStreamClient,
)
from .card_client import DingTalkCardClient
from .card_manager import CardManager
from .config import VALID_LOG_LEVELS, DingTalkConfig
from .message import NanobotDingTalkHandler
from .rate_limiter import RateLimiter
from .sender import DingTalkSender
from .session import build_session_key, is_group_session


# Log format matching nanobot framework's CLI style
_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <5}</level> | "
    "<cyan>{extra[channel]}</cyan> | "
    "<level>{message}</level>"
)


class DingTalkChannel(BaseChannel):
    """
    DingTalk channel using Stream Mode (SDK) for message receiving
    and HTTP API for message sending.
    """

    name = "nano_dingtalk"
    display_name = "Nano DingTalk"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return DingTalkConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = DingTalkConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: DingTalkConfig = config
        self._apply_log_level()
        self._client: Any = None
        self._http: httpx.AsyncClient | None = None

        self._background_tasks: set[asyncio.Task] = set()

        # Rate limiter
        self.rate_limiter = RateLimiter(max_qps=20)

        # Card manager + card client (lazy — init in start())
        self.card_client: DingTalkCardClient | None = None
        self.card_manager: CardManager | None = None

        # Pending cards per chat_id — used by sender to update cards
        self._pending_cards: dict[str, str] = {}
        # Whether AI Card was successfully created per-chat
        self._card_enabled: dict[str, bool] = {}

        # Sender
        self.sender = DingTalkSender(
            config, self.logger,
            pending_cards=self._pending_cards,
        )

    def _apply_log_level(self) -> None:
        """按 config.log_level 为本插件单独添加 DEBUG sink，不影响框架全局级别。

        框架默认 handler 级别为 INFO（除非 -v/--verbose 启动）。
        此方法新增一个 filter handler，仅捕捉 nanobot_channel_dingtalk 模块的
        DEBUG 消息，避免与框架 handler 重复输出 INFO+ 消息。
        """
        level = self.config.log_level.upper()
        if level not in VALID_LOG_LEVELS:
            level = "INFO"

        # 清除上一次的 debug handler
        if hasattr(self, '_debug_sink_id'):
            _loguru.remove(self._debug_sink_id)
            self._debug_sink_id = None

        if level == "DEBUG":
            self._debug_sink_id = _loguru.add(
                sys.stderr,
                format=_LOG_FORMAT,
                level="DEBUG",
                filter=lambda r: (
                    r["name"].startswith("nanobot_channel_dingtalk")
                    and r["level"].name == "DEBUG"
                ),
                colorize=None,
            )

    def set_token_provider(self, provider: Callable[[], Awaitable[str | None]]) -> None:
        """设置共享 Token 提供者（如 DingTalkAPI.get_access_token），
        消除 DingTalkSender 与 DingTalkAPI 间重复的 OAuth2 请求。"""
        self.sender.set_token_provider(provider)

    async def start(self) -> None:
        """Start the DingTalk bot."""
        if not DINGTALK_AVAILABLE:
            self.logger.error(
                "Stream SDK not installed. Run: pip install dingtalk-stream"
            )
            return

        if not self.config.client_id or not self.config.client_secret:
            self.logger.error("client_id and client_secret not configured")
            return

        self._running = True
        if self.config.proxy_url:
            self._http = httpx.AsyncClient(proxies=self.config.proxy_url)
            self.logger.info("HTTP client using proxy: {}", self.config.proxy_url)
        else:
            self._http = httpx.AsyncClient()

        # Initialize card client + card manager
        self.card_client = DingTalkCardClient(
            access_token_fn=self.sender.get_access_token,
            proxy_url=self.config.proxy_url,
        )
        self.card_manager = CardManager(self.card_client)

        # Wire up sender with http client and card manager
        self.sender.setup(self._http, self.card_manager)

        self.logger.info(
            "Initializing Stream Client with Client ID: {}...",
            self.config.client_id,
        )
        credential = Credential(self.config.client_id, self.config.client_secret)
        self._client = DingTalkStreamClient(credential)

        # Register handler (uses ChatbotHandler from SDK)
        handler = NanobotDingTalkHandler(self)
        self._client.register_callback_handler(ChatbotMessage.TOPIC, handler)

        self.logger.info("bot started with Stream Mode")

        while self._running:
            try:
                await self._client.start()
            except Exception as e:
                self.logger.warning("stream error: {}", e)
            if self._running:
                delay = 3 + random.uniform(0, 4)  # jittered 3-7s
                self.logger.info("Reconnecting stream in {:.1f} seconds...", delay)
                await asyncio.sleep(delay)

    async def stop(self) -> None:
        """Stop the DingTalk bot."""
        self._running = False
        if self.card_client:
            await self.card_client.close()
        if self._http:
            await self._http.aclose()
            self._http = None
        if self.sender:
            await self.sender.close()
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through DingTalk."""
        await self.sender.send(msg)

    async def send_delta(self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None) -> None:
        """Forward streaming deltas to DingTalkSender.

        The ChannelManager routes ``_stream_delta`` and ``_stream_end``
        messages to ``send_delta`` rather than ``send`` (see
        ``ChannelManager._send_once``).  Without this override, the
        default no-op in ``BaseChannel`` would silently drop every
        streaming chunk.
        """
        await self.sender.send(
            OutboundMessage(
                channel=self.name,
                chat_id=chat_id,
                content=delta,
                metadata=metadata or {},
            )
        )

    async def _on_message(
        self,
        content: str,
        sender_id: str,
        sender_name: str,
        chat_id: str,
        media: list[str] | None = None,
    ) -> None:
        """Handle incoming message — enables streaming for AI Card flow."""
        try:
            self.logger.info("inbound: {} from {}", content, sender_name)

            metadata: dict[str, Any] = {
                "sender_name": sender_name,
                "channel": "nano_dingtalk",
                "platform": "dingtalk",
                "conversation_type": "2" if is_group_session(chat_id) else "1",
            }

            # Only enable streaming when AI Card was successfully created (per-chat lookup)
            if self._card_enabled.get(chat_id, False):
                metadata["_wants_stream"] = True

            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=str(content),
                media=media,
                metadata=metadata,
            )
        except Exception:
            self.logger.exception("Error publishing message")

    # ------------------------------------------------------------------
    # Robot code
    # ------------------------------------------------------------------

    def _get_robot_code(self) -> str:
        robot_code = os.getenv("DINGTALK_ROBOT_CODE")
        if robot_code:
            return robot_code
        if hasattr(self, "_client") and self._client is not None:
            client_robot = getattr(self._client, "robot_code", None)
            if client_robot:
                return client_robot
        return self.config.client_id

    async def _get_token_and_robot(self) -> tuple[str | None, str]:
        token = await self.sender.get_access_token()
        return token, self._get_robot_code()


__all__ = ["DingTalkChannel", "DingTalkConfig", "build_session_key"]

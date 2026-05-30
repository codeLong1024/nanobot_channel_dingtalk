"""DingTalk message sending and media handling.

This module handles:
- Sending markdown text messages
- Sending media (images, files, videos)
- Media upload to DingTalk
- Remote media fetching with SSRF protection
- File download from DingTalk
- AI Card streaming (typing effect via /card/streaming)
"""

from __future__ import annotations

import json
import mimetypes
from collections import OrderedDict
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from .media.download import download_dingtalk_file
from .media.fetch import read_media_bytes
from .media.helpers import (
    guess_filename,
    guess_upload_type,
    is_http_url,
    normalize_upload_payload,
)
from .media.image_processor import process_local_images, process_bare_image_paths
from .media.markers import (
    process_audio_markers,
    process_video_markers,
    upload_and_replace_file_markers,
)
from .media.raw_path import process_raw_media_paths
from .media.upload import upload_media
from .session import is_group_session, parse_group_session
from .token import TokenManager

from .emotion_handler import recall_thinking_emoji as _recall_thinking_emoji
from .emotion_hook import DingTalkEmotionHook, EmotionContext


class DingTalkSender:
    """Handles sending messages and media via DingTalk API.

    Thin orchestrator that delegates to specialized modules:
    - :mod:`.media.helpers` for extension/upload helpers
    - :mod:`.media.fetch` for remote media fetching
    - :mod:`.media.download` for file download from DingTalk
    - :mod:`.media.upload` for media upload to DingTalk
    - :mod:`.token` for access token management

    Streaming (AI Card):
    - Manages AI Card lifecycle for agent streaming output
    - 5-path send: streaming delta / streaming end / progress skip /
      non-streaming w/ card / markdown fallback
    """

    # Cap for _streamed_chats to prevent unbounded memory growth
    _STREAMED_CHAT_MAX = 5000

    def __init__(
        self,
        config: Any,
        logger: Any,
        http_client: httpx.AsyncClient | None = None,
        card_manager: Any = None,
        pending_cards: dict[str, str] | None = None,
        token_provider: Callable[[], Awaitable[str | None]] | None = None,
        emotion_contexts: dict[str, EmotionContext] | None = None,
    ):
        self.config = config
        self.logger = logger
        self._http = http_client
        self._card_manager = card_manager
        self._pending_cards = pending_cards if pending_cards is not None else {}
        self._emotion_contexts = emotion_contexts if emotion_contexts is not None else {}
        self._token_manager = TokenManager(
            client_id=config.client_id,
            client_secret=config.client_secret,
            http=http_client,
            logger=logger,
            token_provider=token_provider,
        )

        # Streaming state per chat_id
        self._streaming_buffers: dict[str, str] = {}  # chat_id → accumulated content
        self._streamed_chats: OrderedDict[str, bool] = OrderedDict()  # LRU, bounded
        # Current sender_user_id (unionId) for batchSend API (set per-message in send())
        self._current_sender_user_id: str | None = None

    def setup(self, http_client: httpx.AsyncClient, card_manager: Any = None) -> None:
        """Configure HTTP client and card manager after construction."""
        self._http = http_client
        self._token_manager.http = http_client
        if card_manager is not None:
            self._card_manager = card_manager

    async def read_media_bytes(self, media_ref: str, **kwargs: Any) -> tuple[bytes | None, str | None, str | None]:
        """Read media bytes from URL or local file. Delegates to :func:`media.fetch.read_media_bytes`."""
        return await read_media_bytes(self._http, media_ref, self.logger, **kwargs)

    def set_token_provider(self, provider: Callable[[], Awaitable[str | None]]) -> None:
        """设置共享 Token 提供者（如 DingTalkAPI.get_access_token），消除重复 HTTP 调用。"""
        self._token_manager.token_provider = provider

    async def close(self) -> None:
        """Release HTTP client reference."""
        self._http = None

    # ==================== Token Management ====================

    async def get_access_token(self) -> str | None:
        """Get or refresh Access Token — delegates to TokenManager."""
        return await self._token_manager.get_access_token()

    # ==================== File Download from DingTalk ====================

    async def download_dingtalk_file(
        self,
        download_code: str,
        filename: str,
        sender_id: str,
        *,
        retries: int = 2,
        connect_timeout: float = 15.0,
        read_timeout: float = 120.0,
    ) -> str | None:
        """Download a DingTalk file to the media directory, return local path.

        Delegates to :func:`media.download.download_dingtalk_file`.
        """
        token = await self.get_access_token()
        return await download_dingtalk_file(
            http=self._http,
            token=token,
            client_id=self.config.client_id,
            download_code=download_code,
            filename=filename,
            sender_id=sender_id,
            logger=self.logger,
            retries=retries,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )

    # ==================== Media Upload ====================

    async def upload_media(
        self,
        token: str,
        data: bytes,
        media_type: str,
        filename: str,
        content_type: str | None,
        agent_id: str | None = None,
    ) -> str | None:
        """Upload media to DingTalk and return media_id.

        Delegates to :func:`media.upload.upload_media`.
        """
        return await upload_media(
            http=self._http,
            token=token,
            data=data,
            media_type=media_type,
            filename=filename,
            logger=self.logger,
            agent_id=agent_id or self.config.client_id,
        )

    # ==================== Message Sending ====================

    async def _send_batch_message(
        self,
        token: str,
        chat_id: str,
        msg_key: str,
        msg_param: dict[str, Any],
        card_data: dict[str, Any] | None = None,
    ) -> bool:
        """Send a batch message (private or group).

        For private chat, ``userIds`` is sourced from
        ``self._current_sender_user_id`` (set per-message in :meth:`send`),
        then falls back to ``chat_id``.
        """
        headers = {"x-acs-dingtalk-access-token": token}
        if is_group_session(chat_id):
            _, conversation_id = parse_group_session(chat_id)
            url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
            payload: dict[str, Any] = {
                "robotCode": self.config.client_id,
                "openConversationId": conversation_id or chat_id,
                "msgKey": msg_key,
                "msgParam": json.dumps(msg_param, ensure_ascii=False),
            }
            if card_data is not None:
                payload["cardData"] = card_data
        else:
            url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
            uid = self._current_sender_user_id or chat_id
            payload = {
                "robotCode": self.config.client_id,
                "userIds": [uid],
                "msgKey": msg_key,
                "msgParam": json.dumps(msg_param, ensure_ascii=False),
            }
            if card_data is not None:
                payload["cardData"] = card_data

        try:
            resp = await self._http.post(url, json=payload, headers=headers)
            body = resp.text
            if resp.status_code != 200:
                self.logger.error("send failed msgKey={} status={} body={}", msg_key, resp.status_code, body[:500])
                return False
            try:
                result = resp.json()
            except Exception:
                result = {}
            errcode = result.get("errcode")
            if errcode not in (None, 0):
                self.logger.error("send api error msgKey={} errcode={} body={}", msg_key, errcode, body[:500])
                return False
            self.logger.debug("message sent to {} with msgKey={}", chat_id, msg_key)
            return True
        except httpx.TransportError:
            self.logger.exception("network error sending message msgKey={}", msg_key)
            raise
        except Exception:
            self.logger.exception("Error sending message msgKey={}", msg_key)
            return False

    async def _send_markdown_text(self, token: str, chat_id: str, content: str) -> bool:
        """Send markdown text message."""
        return await self._send_batch_message(
            token,
            chat_id,
            "sampleMarkdown",
            {"text": content, "title": "Nanobot Reply"},
        )

    async def _send_media_ref(self, token: str, chat_id: str, media_ref: str) -> bool:
        """Send a media reference (URL or local file)."""
        media_ref = (media_ref or "").strip()
        if not media_ref:
            return True

        upload_type = guess_upload_type(media_ref)

        # Try sending image URL directly
        if upload_type == "image" and is_http_url(media_ref):
            ok = await self._send_batch_message(
                token,
                chat_id,
                "sampleImageMsg",
                {"photoURL": media_ref},
            )
            if ok:
                return True
            self.logger.warning("image url send failed, trying upload fallback: {}", media_ref)

        # Read and upload media
        data, filename, content_type = await read_media_bytes(self._http, media_ref, self.logger)
        if not data:
            self.logger.error("media read failed: {}", media_ref)
            return False

        filename = filename or guess_filename(media_ref, upload_type)
        data, filename, content_type = normalize_upload_payload(filename, data, content_type, self.logger)
        file_type = Path(filename).suffix.lower().lstrip(".")
        if not file_type:
            guessed = mimetypes.guess_extension(content_type or "")
            file_type = (guessed or ".bin").lstrip(".")
        if file_type == "jpeg":
            file_type = "jpg"

        media_id = await self.upload_media(
            token=token,
            data=data,
            media_type=upload_type,
            filename=filename,
            content_type=content_type,
        )
        if not media_id:
            return False

        # Send image with media_id
        if upload_type == "image":
            ok = await self._send_batch_message(
                token,
                chat_id,
                "sampleImageMsg",
                {"photoURL": media_id},
            )
            if ok:
                return True
            self.logger.warning("image media_id send failed, falling back to file: {}", media_ref)

        # Send as file
        return await self._send_batch_message(
            token,
            chat_id,
            "sampleFile",
            {"mediaId": media_id, "fileName": filename, "fileType": file_type},
        )

    async def _send_msg_media_refs(
        self, token: str, chat_id: str, media_refs: list[str],
    ) -> None:
        """Send a list of media references as native DingTalk file messages.

        Each ref is processed by :meth:`_send_media_ref`; failures are logged
        and a fallback text message is sent instead.
        """
        for media_ref in media_refs:
            ok = await self._send_media_ref(token, chat_id, media_ref)
            if ok:
                continue
            self.logger.error("media send failed for {}", media_ref)
            filename = guess_filename(media_ref, guess_upload_type(media_ref))
            await self._send_markdown_text(
                token, chat_id,
                f"[Attachment send failed: {filename}]",
            )

    async def send(self, msg: Any) -> None:
        """Send an outbound message.

        Five paths:
        1. **Streaming delta** (``_stream_delta``): accumulate content
           and push to AI Card via ``card_manager.stream_content()`` — typing effect.
        2. **Streaming end** (``_stream_end``, no resume): final push + ``finish_streaming()``.
        3. **Progress/status messages** (``_progress``, ``_retry_wait``): silently
           skipped when a card is pending — they must NOT pop the card.
        4. **Non-streaming with card**: pop and finalize/fail the card.
        5. **Non-streaming without card**: fallback to markdown (and optional media).

        **Media pipeline** (applied to non-streaming content before sending):
        1. ``process_local_images()``      — replace Markdown image paths
        2. ``process_bare_image_paths()``  — handle bare image paths
        3. ``process_video_markers()``     — process [DINGTALK_VIDEO]
        4. ``process_audio_markers()``     — process [DINGTALK_AUDIO]
        5. ``upload_and_replace_file_markers()`` — process [DINGTALK_FILE]
        6. ``process_raw_media_paths()``   — handle remaining bare paths (safety net)
        7. Send cleaned text via card/markdown
        8. Send media references via native DingTalk API
        """
        token = await self.get_access_token()
        if not token:
            return

        metadata = msg.metadata or {}
        chat_id = msg.chat_id
        self._current_sender_user_id = metadata.get("sender_user_id") or metadata.get("sender_staff_id")
        card_id = self._pending_cards.get(chat_id) if self._pending_cards else None

        # ============ Rich media preprocessing pipeline ============
        # Apply to non-streaming, final content only
        content = msg.content or ""
        if (
            not metadata.get("_stream_delta")
            and content
            and self.config.enable_marker_processing
        ):
            try:
                # 1. Process Markdown images
                content = await process_local_images(content, self, token, self.logger)

                # 2. Process bare image paths
                content = await process_bare_image_paths(content, self, token, self.logger)

                # 3. Process video markers
                content = await process_video_markers(
                    content, token, self, chat_id, self.logger,
                )

                # 4. Process audio markers
                content = await process_audio_markers(
                    content, token, self, chat_id, self.logger,
                )

                # 5. Process file markers
                content = await upload_and_replace_file_markers(
                    content, self, token, self.logger,
                )

                # 6. Process remaining raw paths
                content = await process_raw_media_paths(
                    content, self, token, chat_id, self.logger,
                )
            except Exception:
                self.logger.exception("media pipeline error, continuing with original content")

        # --- 1. Streaming delta: accumulate + push to card ---
        if card_id and metadata.get("_stream_delta"):
            if chat_id not in self._streaming_buffers:
                self._streaming_buffers[chat_id] = ""
                # First stream delta → ✍️ 输出中
                await self._trigger_emotion(chat_id, "writing")
            # Cap per-chat buffer at 100 KB to prevent unbounded growth
            prev = self._streaming_buffers[chat_id]
            delta = msg.content or ""
            if len(prev) + len(delta) > 100_000:
                self.logger.warning("[STREAM] Buffer overflow for chat={}, truncating", chat_id)
                delta = delta[: max(0, 100_000 - len(prev))]
            self._streaming_buffers[chat_id] = prev + delta
            accumulated = self._streaming_buffers[chat_id]
            if self._card_manager:
                try:
                    await self._card_manager.stream_content(card_id, accumulated)
                except Exception:
                    self.logger.debug("[STREAM] stream_content error", exc_info=True)
            return

        # --- 2. Streaming end: finalize card ---
        if card_id and metadata.get("_stream_end"):
            if metadata.get("_resuming"):
                await self._trigger_emotion(chat_id, "tool")  # 🔧 工具调用中
                return  # tool call — more to come
            await self._trigger_emotion(chat_id, "done")  # ✅ 已完成
            self._pending_cards.pop(chat_id, None)
            accumulated = self._streaming_buffers.pop(chat_id, "") or (msg.content or "")
            if accumulated.strip() and self._card_manager:
                try:
                    await self._card_manager.stream_content(card_id, accumulated)
                    await self._card_manager.finish_streaming(card_id, accumulated)
                except Exception:
                    self.logger.warning("[STREAM] finish failed, falling back to markdown", exc_info=True)
                    # Fallback: send content as markdown to prevent double-send
                    if accumulated.strip():
                        await self._send_markdown_text(token, chat_id, accumulated.strip())
                    self._cleanup_chat_context(chat_id)
                    return
            else:
                # No content — just finish
                if self._card_manager:
                    try:
                        await self._card_manager.finish_streaming(card_id, accumulated)
                    except Exception:
                        pass
            self._mark_chat_streamed(chat_id)
            self._cleanup_chat_context(chat_id)
            return

        # --- 3. Progress / status messages: silently skip ---
        if metadata.get("_progress") or metadata.get("_retry_wait"):
            self.logger.debug(
                "[SKIP] Skipping progress/status message for chat={}", chat_id,
            )
            return

        # --- 4. Non-streaming: pop and finalize ---
        popped_id = self._pending_cards.pop(chat_id, None) if self._pending_cards else None
        if popped_id and self._card_manager and content and content.strip():
            # If this message carries media refs, it's a tool-driven file/attachment
            # delivery.  Don't consume the AI Card — keep it pending.
            if msg.media:
                self._pending_cards[chat_id] = popped_id  # restore card
                await self._send_msg_media_refs(token, chat_id, msg.media)
                return

            self.logger.debug("[CARD] Finalizing card {} for chat={}", popped_id, chat_id)
            ok = await self._card_manager.finalize_card(popped_id, content.strip())
            if ok:
                await self._send_msg_media_refs(token, chat_id, msg.media or [])
                self._cleanup_chat_context(chat_id)
                return
            self.logger.warning("[CARD] finalize_card failed, falling back to markdown")

        # Skip markdown if streaming already delivered via card
        if chat_id in self._streamed_chats:
            self._streamed_chats.pop(chat_id, None)
            await self._send_msg_media_refs(token, chat_id, msg.media or [])
            return

        # Fall back to markdown
        if content and content.strip():
            self.logger.info("[SEND] Markdown to chat={} ({} chars)", chat_id, len(content))
            await self._send_markdown_text(token, chat_id, content.strip())

        await self._send_msg_media_refs(token, chat_id, msg.media or [])
        # Non-streaming fallback: recall initial 🤔 thinking emoji
        await self._recall_emotion(chat_id)

    # ------------------------------------------------------------------
    # Streaming chat tracking (bounded LRU via OrderedDict)
    # ------------------------------------------------------------------

    def _mark_chat_streamed(self, chat_id: str) -> None:
        """Record a chat as having completed AI Card streaming, with LRU eviction."""
        self._streamed_chats[chat_id] = True
        self._streamed_chats.move_to_end(chat_id)
        while len(self._streamed_chats) > self._STREAMED_CHAT_MAX:
            self._streamed_chats.popitem(last=False)

    # ------------------------------------------------------------------
    # Per-chat context cleanup
    # ------------------------------------------------------------------

    def _cleanup_chat_context(self, chat_id: str) -> None:
        """Clean up per-chat state after message processing is complete."""
        self._emotion_contexts.pop(chat_id, None)

    # ------------------------------------------------------------------
    # Emotion-driven feedback (multi-status emoji)
    # ------------------------------------------------------------------

    async def _trigger_emotion(self, chat_id: str, state_name: str) -> None:
        """Update the DingTalk emotion for *chat_id* to *state_name*.

        Silently skips if no :class:`EmotionContext` exists (e.g. non-card
        reply path).  Exceptions are logged but never propagated.
        """
        ctx = self._emotion_contexts.get(chat_id)
        if ctx is None:
            return
        try:
            hook = DingTalkEmotionHook(ctx)
            await hook.update(state_name)
        except Exception:
            self.logger.exception(
                "[Emotion] Failed to update '{}' for chat={}", state_name, chat_id,
            )

    async def _recall_emotion(self, chat_id: str) -> None:
        """Force-recall the DingTalk emotion for *chat_id* (non-streaming fallback).

        Used when the message flow ends without ever entering a streaming path,
        ensuring the initial 🤔 thinking emoji is always cleaned up.
        """
        ctx = self._emotion_contexts.get(chat_id)
        if ctx is None:
            return
        try:
            await _recall_thinking_emoji(
                ctx.http_client, ctx.token, ctx.robot_code,
                ctx.open_msg_id, ctx.open_conversation_id,
            )
        except Exception:
            self.logger.exception("[Emotion] recall failed for chat={}", chat_id)
        self._cleanup_chat_context(chat_id)


__all__ = ["DingTalkSender"]

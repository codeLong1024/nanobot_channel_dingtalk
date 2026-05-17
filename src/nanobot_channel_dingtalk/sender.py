"""DingTalk message sending and media handling.

This module handles:
- Sending markdown text messages
- Sending media (images, files, videos)
- Media upload to DingTalk
- Remote media fetching with SSRF protection
- File download from DingTalk
"""

from __future__ import annotations

import json
import mimetypes
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


class DingTalkSender:
    """Handles sending messages and media via DingTalk API.

    Thin orchestrator that delegates to specialized modules:
    - :mod:`.media.helpers` for extension/upload helpers
    - :mod:`.media.fetch` for remote media fetching
    - :mod:`.media.download` for file download from DingTalk
    - :mod:`.media.upload` for media upload to DingTalk
    - :mod:`.token` for access token management
    """

    def __init__(
        self,
        config: Any,
        logger: Any,
        http_client: httpx.AsyncClient | None = None,
        token_provider: Callable[[], Awaitable[str | None]] | None = None,
    ):
        self.config = config
        self.logger = logger
        self._http = http_client
        self._token_manager = TokenManager(
            client_id=config.client_id,
            client_secret=config.client_secret,
            http=http_client,
            logger=logger,
            token_provider=token_provider,
        )

    def setup(self, http_client: httpx.AsyncClient) -> None:
        """Configure HTTP client after construction."""
        self._http = http_client
        self._token_manager.http = http_client

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

        For ``sampleCardMsg``, the actual card JSON goes in ``card_data.cardJson``
        and ``msg_param`` should be ``{}``.  For other types (e.g. ``sampleMarkdown``)
        the content lives in ``msg_param`` and ``card_data`` is unused.
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
            payload = {
                "robotCode": self.config.client_id,
                "userIds": [chat_id],
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

        Media pipeline (applied to content before sending):
        1. ``process_local_images()``      — replace Markdown image paths
        2. ``process_bare_image_paths()``  — handle bare image paths
        3. ``process_video_markers()``     — process [DINGTALK_VIDEO]
        4. ``process_audio_markers()``     — process [DINGTALK_AUDIO]
        5. ``upload_and_replace_file_markers()`` — process [DINGTALK_FILE]
        6. ``process_raw_media_paths()``   — handle remaining bare paths (safety net)
        7. Send cleaned text via markdown
        8. Send media references via native DingTalk API
        """
        token = await self.get_access_token()
        if not token:
            return

        chat_id = msg.chat_id

        # ============ Rich media preprocessing pipeline ============
        content = msg.content or ""
        if content and self.config.enable_marker_processing:
            try:
                content = await process_local_images(content, self, token, self.logger)
                content = await process_bare_image_paths(content, self, token, self.logger)
                content = await process_video_markers(
                    content, self._http, token, self, chat_id, self.logger,
                )
                content = await process_audio_markers(
                    content, self._http, token, self, chat_id, self.logger,
                )
                content = await upload_and_replace_file_markers(
                    content, self, token, self.logger,
                )
                content = await process_raw_media_paths(
                    content, self, token, chat_id, self.logger,
                )
            except Exception:
                self.logger.exception("media pipeline error, continuing with original content")

        # Send markdown
        if content and content.strip():
            self.logger.info("[SEND] Markdown to chat={} ({} chars)", chat_id, len(content))
            await self._send_markdown_text(token, chat_id, content.strip())

        await self._send_msg_media_refs(token, chat_id, msg.media or [])


__all__ = ["DingTalkSender"]

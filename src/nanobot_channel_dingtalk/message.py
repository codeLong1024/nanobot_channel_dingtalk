"""DingTalk message handling — using ChatbotHandler (SDK) for stream-based processing.

Coordinates ConversationQueue, EmotionHandler, and message routing.
"""

from __future__ import annotations

import json as _json
import time as _time
from dataclasses import dataclass, field
from typing import Any, Callable

from .auth import (
    AckMessage,
    ChatbotHandler,
    ChatbotMessage,
    CallbackMessage,
    DINGTALK_AVAILABLE,
)
from .card_manager import CardManager
from .emotion_handler import (
    add_thinking_emoji,
    recall_thinking_emoji,
)
from .emotion_hook import EmotionContext
from .media.file_parser import parse_file_content
from .session_manager import ConversationQueue
from .session import build_session_key


@dataclass
class ParsedMessage:
    """Lightweight data container for parsed message context."""
    content: str
    sender_id: str
    sender_name: str
    conversation_type: str | None
    conversation_id: str | None
    chat_id: str
    session_key: str
    msg_id: str
    raw_message: CallbackMessage
    media: list[str] = field(default_factory=list)


class NanobotDingTalkHandler(ChatbotHandler):
    """
    DingTalk Stream message handler.

    Responsibilities:
    - Parse incoming messages (text, image, file, richText)
    - Enqueue for serial processing per conversation
    - Coordinate emoji feedback
    """

    def __init__(self, channel: "DingTalkChannel"):
        super().__init__()
        self.channel = channel
        self.conversation_queue = ConversationQueue()

    async def process(self, message: CallbackMessage):
        """Quick parse + enqueue — returns ACK immediately."""
        try:
            self.channel.logger.debug(
                "[DEBUG RAW] message.data = {}",
                _json.dumps(message.data, ensure_ascii=False, indent=2, default=str),
            )
            chatbot_msg = ChatbotMessage.from_dict(message.data)

            content, file_paths = await self._extract_message_content(
                chatbot_msg, message,
            )

            if not content:
                self.channel.logger.warning(
                    "Received empty or unsupported message type: {}",
                    chatbot_msg.message_type,
                )
                return AckMessage.STATUS_OK, "OK"

            sender_id = chatbot_msg.sender_staff_id or chatbot_msg.sender_id
            sender_name = chatbot_msg.sender_nick or "Unknown"

            conversation_type = message.data.get("conversationType")
            conversation_id = (
                message.data.get("conversationId")
                or message.data.get("openConversationId")
            )
            # chat_id: pure routing identifier (conversation_id for groups, sender_id for DM)
            chat_id = conversation_id or sender_id
            # session_key: full session key for agent loop (includes channel prefix)
            session_key = build_session_key(sender_id, conversation_type, conversation_id)
            msg_id = (
                getattr(chatbot_msg, "message_id", "")
                or message.data.get("messageId", "")
            )

            self.channel.logger.info(
                "Received message from {} ({}): {}", sender_name, sender_id, content,
            )

            parsed = ParsedMessage(
                content=content,
                sender_id=sender_id,
                sender_name=sender_name,
                conversation_type=conversation_type,
                conversation_id=conversation_id,
                chat_id=chat_id,
                session_key=session_key,
                msg_id=msg_id,
                media=file_paths,
                raw_message=message,
            )

            await self.conversation_queue.enqueue_message(
                conversation_id or sender_id or chat_id,
                parsed,
                self._handle_message,
            )

            return AckMessage.STATUS_OK, "OK"

        except Exception:
            self.channel.logger.exception("Error processing message")
            return AckMessage.STATUS_OK, "Error"

    # ------------------------------------------------------------------
    # Download error handling
    # ------------------------------------------------------------------

    async def _send_download_error(
        self,
        sender_uid_fn: Callable[[], str],
        media_type: str,
        filename: str,
    ) -> None:
        """Send download failure error message to user, skip AI processing.
        
        Args:
            sender_uid_fn: Callable returning sender's UID.
            media_type: Human-readable media type (e.g. "文件", "图片").
            filename: Name of the failed file.
        """
        sender_id = sender_uid_fn()
        token = await self.channel.sender.get_access_token()
        if token:
            error_msg = (
                f"⚠️ **{media_type}下载失败**\n\n"
                f"文件名: {filename}\n"
                f"原因: 无法从钉钉服务器下载文件，请检查网络或联系管理员。"
            )
            await self.channel.sender._send_markdown_text(
                token, sender_id, error_msg,
            )
        self.channel.logger.warning(
            "{} download failed — error sent to user: file={}, sender={}",
            media_type, filename, sender_id,
        )

    # ------------------------------------------------------------------
    # Content extraction helpers (split from process for readability)
    # ------------------------------------------------------------------

    async def _extract_message_content(
        self,
        chatbot_msg: ChatbotMessage,
        message: CallbackMessage,
    ) -> tuple[str, list[str]]:
        """Extract text content and file paths from an incoming message."""
        # Common sender ID helper
        def _sender_uid() -> str:
            return chatbot_msg.sender_staff_id or chatbot_msg.sender_id or "unknown"

        # Extract text content
        content = ""
        if chatbot_msg.text:
            content = chatbot_msg.text.content.strip()
        elif chatbot_msg.extensions.get("content", {}).get("recognition"):
            content = chatbot_msg.extensions["content"]["recognition"].strip()
        if not content:
            content = message.data.get("text", {}).get("content", "").strip()

        file_paths: list[str] = []

        msg_type = chatbot_msg.message_type

        if msg_type == "picture" and chatbot_msg.image_content:
            content, file_paths = await self._handle_picture(
                chatbot_msg, message, _sender_uid, content,
            )

        elif msg_type == "audio":
            content, file_paths = await self._handle_audio(
                chatbot_msg, message, _sender_uid, content,
            )

        elif msg_type == "file":
            content, file_paths = await self._handle_file(
                chatbot_msg, message, _sender_uid, content,
            )

        elif msg_type == "video":
            content, file_paths = await self._handle_video(
                chatbot_msg, message, _sender_uid, content,
            )

        elif msg_type == "richText" and chatbot_msg.rich_text_content:
            content, file_paths = await self._handle_rich_text(
                chatbot_msg, message, _sender_uid, content,
            )

        # File content parsing (inject into LLM context)
        if self.channel.config.enable_file_parsing and file_paths:
            for fp in list(file_paths):
                parsed = await parse_file_content(fp)
                if parsed:
                    max_chars = self.channel.config.max_file_parse_chars
                    snippet = parsed.text[:max_chars]
                    self.channel.logger.info(
                        "Parsed file content: format=%s size=%d chars=%d",
                        parsed.format, parsed.file_size, len(parsed.text),
                    )
                    content = f"{content}\n\n[文件内容: {parsed.file_name}]\n{snippet}"

        return content, file_paths

    async def _handle_picture(
        self,
        chatbot_msg: ChatbotMessage,
        message: CallbackMessage,
        sender_uid_fn,
        content: str,
    ) -> tuple[str, list[str]]:
        """Handle picture message type."""
        file_paths: list[str] = []
        download_code = chatbot_msg.image_content.download_code
        if download_code:
            fp = await self.channel.sender.download_dingtalk_file(
                download_code, "image.jpg", sender_uid_fn(),
            )
            if fp:
                file_paths.append(fp)
                content = content or "[Image]"
            else:
                await self._send_download_error(sender_uid_fn(), "图片", "image.jpg")
                return "", []  # skip AI processing
        return content, file_paths

    async def _handle_audio(
        self,
        chatbot_msg: ChatbotMessage,
        message: CallbackMessage,
        sender_uid_fn,
        content: str,
    ) -> tuple[str, list[str]]:
        """Handle audio message type."""
        file_paths: list[str] = []
        # Voice: prefer recognition text
        recognition = (
            message.data.get("content", {}).get("recognition", "")
            or chatbot_msg.extensions.get("content", {}).get("recognition", "")
        )
        if recognition:
            content = recognition.strip()

        download_code = message.data.get("downloadCode", "")
        if download_code:
            fp = await self.channel.sender.download_dingtalk_file(
                download_code, f"voice_{int(_time.time())}.amr", sender_uid_fn(),
            )
            if fp:
                file_paths.append(fp)
        return content, file_paths

    async def _handle_file(
        self,
        chatbot_msg: ChatbotMessage,
        message: CallbackMessage,
        sender_uid_fn,
        content: str,
    ) -> tuple[str, list[str]]:
        """Handle file message type.
        
        On download failure: send error message directly to user (skip AI),
        then return empty content to bypass agent processing.
        """
        file_paths: list[str] = []
        download_code = (
            message.data.get("content", {}).get("downloadCode")
            or message.data.get("downloadCode")
        )
        fname = (
            message.data.get("content", {}).get("fileName")
            or message.data.get("fileName")
            or "file"
        )
        if download_code:
            fp = await self.channel.sender.download_dingtalk_file(
                download_code, fname, sender_uid_fn(),
            )
            if fp:
                file_paths.append(fp)
                content = content or "[File]"
            else:
                await self._send_download_error(sender_uid_fn(), "文件", fname)
                return "", []  # skip AI processing
        return content, file_paths

    async def _handle_video(
        self,
        chatbot_msg: ChatbotMessage,
        message: CallbackMessage,
        sender_uid_fn,
        content: str,
    ) -> tuple[str, list[str]]:
        """Handle video message type."""
        file_paths: list[str] = []
        content = content or "[Video]"
        download_code = message.data.get("downloadCode", "")
        if download_code:
            fp = await self.channel.sender.download_dingtalk_file(
                download_code, f"video_{int(_time.time())}.mp4", sender_uid_fn(),
            )
            if fp:
                file_paths.append(fp)
        return content, file_paths

    async def _handle_rich_text(
        self,
        chatbot_msg: ChatbotMessage,
        message: CallbackMessage,
        sender_uid_fn,
        content: str,
    ) -> tuple[str, list[str]]:
        """Handle richText message type."""
        file_paths: list[str] = []
        rich_list = chatbot_msg.rich_text_content.rich_text_list or []
        for item in rich_list:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                t = item.get("text", "").strip()
                if t:
                    content = (content + " " + t).strip() if content else t
            elif item.get("downloadCode"):
                dc = item["downloadCode"]
                fname = item.get("fileName") or "file"
                fp = await self.channel.sender.download_dingtalk_file(
                    dc, fname, sender_uid_fn(),
                )
                if fp:
                    file_paths.append(fp)
                    content = content or "[File]"
        return content, file_paths

    # ------------------------------------------------------------------
    # Message processing
    # ------------------------------------------------------------------

    async def _handle_message(self, parsed: "ParsedMessage") -> None:
        """Process a single message (called by SessionManager worker).

        Flow:
        1. Add 🤔 thinking emoji
        2. Create AI Card (if available)
        3. Start streaming (INPUTING status — shows "思考中...")
        4. Forward to agent — streaming deltas go to card via sender
        5. On error: fail_card
        """
        robot_code = self.channel._get_robot_code()
        msg_id = parsed.msg_id
        http = self.channel._http

        # Extract openConversationId
        raw_data = getattr(parsed.raw_message, "data", {}) or {}
        open_conv_id = (
            raw_data.get("openConversationId")
            if isinstance(raw_data, dict)
            else None
        ) or parsed.conversation_id or ""

        # Get access token
        token = (
            await self.channel.sender.get_access_token()
            if self.channel.sender
            else None
        )

        # Step 1: Add 🤔 thinking emoji
        if http and token:
            await add_thinking_emoji(
                http, token, robot_code, msg_id, open_conv_id,
            )

        # Store emotion context for multi-state updates during streaming
        emotion_ctx = EmotionContext(
            http_client=http,
            token=token,
            robot_code=robot_code,
            open_msg_id=msg_id,
            open_conversation_id=open_conv_id,
        ) if http and token else None
        if emotion_ctx:
            existing = self.channel._emotion_contexts.get(parsed.chat_id)
            if existing is not None:
                self.channel.logger.warning(
                    "[Emotion] Overwriting existing context for chat={} (old_msg={}, new_msg={})",
                    parsed.chat_id, existing.open_msg_id, emotion_ctx.open_msg_id,
                )
            self.channel._emotion_contexts[parsed.chat_id] = emotion_ctx

        # Step 2: Create AI Card + Step 3: Start streaming
        card_instance_id: str | None = None
        card_manager = self.channel.card_manager
        if card_manager and http and token:
            try:
                is_group = parsed.conversation_type == "2"
                target = (
                    {"openConversationId": open_conv_id}
                    if is_group
                    else {"receiverUserId": parsed.sender_id}
                )

                track_id = CardManager.generate_track_id()
                cid = await card_manager.create_card(
                    card_instance_id=track_id,
                    robot_code=robot_code,
                    target=target,
                )
                card_instance_id = cid
                self.channel._pending_cards[parsed.chat_id] = cid
                self.channel.logger.info(
                    "[CARD] Created AI Card {} for chat={}", cid, parsed.chat_id,
                )

                # Start streaming — card shows "思考中..." initially
                await card_manager.start_streaming(cid, "思考中...")

            except Exception as e:
                self.channel.logger.warning(
                    "[CARD] AI Card setup failed: {}", e,
                )
                self.channel.logger.debug("[CARD] Setup traceback", exc_info=True)

        try:
            # Step 4: Forward to agent — streaming output handled by sender
            # Determine is_dm: single chat (conversation_type == "1") → DM
            is_dm = parsed.conversation_type != "2"
            async with self.channel.rate_limiter:
                await self.channel._on_message(
                    parsed.content,
                    parsed.sender_id,
                    parsed.sender_name or "Unknown",
                    parsed.chat_id,
                    media=parsed.media,
                    is_dm=is_dm,
                    session_key=parsed.session_key,
                )

            self.channel.logger.info(
                "[DISPATCH] Message dispatched to agent [user={}]", parsed.sender_id,
            )

        except Exception as e:
            self.channel.logger.exception(
                "[ERROR] Processing message failed: {}", e,
            )
            if card_manager and card_instance_id:
                try:
                    await card_manager.fail_card(card_instance_id, str(e))
                except Exception:
                    pass
            # On error, recall emoji immediately (sender won't do it)
            if http and token:
                await recall_thinking_emoji(
                    http, token, robot_code, msg_id, open_conv_id,
                )
        # NOTE: Do NOT clean up _emotion_contexts here.
        # The finally block would run after channel._on_message() returns,
        # but that only enqueues the message — the Agent Loop hasn't
        # processed it yet.  Cleanup is now done in sender.py when the
        # stream actually ends (_stream_end event).


__all__ = ["NanobotDingTalkHandler", "ParsedMessage"]

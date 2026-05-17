"""Thinking emoji management for DingTalk messages.

Adds a 🤔 thinking emoji to the message while processing, and recalls
it when done — providing visual feedback that the bot is working.

Uses DingTalk Robot Emotion API:
- POST /v1.0/robot/emotion/reply    (add)
- POST /v1.0/robot/emotion/recall   (recall)

Reference: docs/dingtalk/emotion_reply.py
"""

from __future__ import annotations

from typing import Any

from loguru import logger

_EMOTION_PAYLOAD: dict[str, Any] = {
    "emotionType": 2,
    "emotionName": "🤔思考中",
    "textEmotion": {
        "emotionId": "2659900",
        "emotionName": "🤔思考中",
        "text": "🤔思考中",
        "backgroundId": "im_bg_1",
    },
}


def _build_body(
    robot_code: str,
    open_msg_id: str,
    open_conversation_id: str,
) -> dict[str, Any]:
    """Build the emotion API request body (matching reference)."""
    return {
        "robotCode": robot_code,
        "openMsgId": open_msg_id,
        "openConversationId": open_conversation_id,
        **_EMOTION_PAYLOAD,
    }


async def _emotion_api_request(
    http_client: Any,
    token: str,
    robot_code: str,
    open_msg_id: str,
    open_conversation_id: str,
    action: str = "add",
) -> None:
    """Send an emotion API request to DingTalk.

    Args:
        action: ``"add"`` → POST /robot/emotion/reply,
                ``"recall"`` → POST /robot/emotion/recall.
    """
    if not open_msg_id or not open_conversation_id:
        logger.warning(
            "[Emotion] Skipped (%s): missing open_msg_id=%s or open_conversation_id=%s",
            action, open_msg_id, open_conversation_id,
        )
        return

    endpoint = "reply" if action == "add" else "recall"
    url = f"https://api.dingtalk.com/v1.0/robot/emotion/{endpoint}"

    body = _build_body(robot_code, open_msg_id, open_conversation_id)
    headers = {
        "x-acs-dingtalk-access-token": token,
        "Content-Type": "application/json",
    }

    try:
        resp = await http_client.post(url, json=body, headers=headers, timeout=5)
        if resp.status_code == 200:
            logger.debug("[Emotion] %s success: msgId=%s", action, open_msg_id)
        else:
            logger.warning(
                "[Emotion] %s failed: status=%s, body=%s",
                action, resp.status_code, resp.text[:200],
            )
    except Exception as e:
        logger.warning("[Emotion] %s error (non-fatal): %s", action, e)


async def add_thinking_emoji(
    http_client: Any,
    token: str,
    robot_code: str,
    open_msg_id: str,
    open_conversation_id: str,
) -> None:
    """Add a 🤔 thinking emoji to the message via HTTP API."""
    await _emotion_api_request(
        http_client, token, robot_code,
        open_msg_id, open_conversation_id,
        action="add",
    )


async def recall_thinking_emoji(
    http_client: Any,
    token: str,
    robot_code: str,
    open_msg_id: str,
    open_conversation_id: str,
) -> None:
    """Recall the thinking emoji from the message via HTTP API."""
    await _emotion_api_request(
        http_client, token, robot_code,
        open_msg_id, open_conversation_id,
        action="recall",
    )


__all__ = [
    "add_thinking_emoji",
    "recall_thinking_emoji",
]

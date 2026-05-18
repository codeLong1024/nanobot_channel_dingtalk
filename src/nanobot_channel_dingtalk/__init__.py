"""DingTalk channel plugin for nanobot.

A BaseChannel implementation for DingTalk with AI Card streaming
and rich media support.
"""

from nanobot_channel_dingtalk.card_client import DingTalkCardClient
from nanobot_channel_dingtalk.card_manager import CardManager
from nanobot_channel_dingtalk.channel import DingTalkChannel
from nanobot_channel_dingtalk.config import DingTalkConfig
from nanobot_channel_dingtalk.models import AICardInstance, AICardStatus

__all__ = [
    "CardManager",
    "DingTalkCardClient",
    "DingTalkChannel",
    "DingTalkConfig",
    "AICardInstance",
    "AICardStatus",
]


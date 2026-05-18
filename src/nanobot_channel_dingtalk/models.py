"""Data models for DingTalk AI Card operations."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class AICardStatus:
    """DingTalk AI Card status codes."""
    PROCESSING = "1"
    INPUTING = "2"
    FINISHED = "3"
    EXECUTING = "4"
    FAILED = "5"


@dataclass
class AICardInstance:
    """Card instance data class."""
    card_instance_id: str
    robot_code: str
    target: dict[str, Any]
    created_at: float = field(default_factory=time.time)
    status: str = AICardStatus.PROCESSING


__all__ = ["AICardStatus", "AICardInstance"]

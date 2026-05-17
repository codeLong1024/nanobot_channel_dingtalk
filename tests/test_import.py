"""Smoke test — verify the plugin can be discovered by the framework."""

import importlib
import sys
from pathlib import Path


def test_package_import():
    """Package-level exports are importable."""
    from nanobot_channel_dingtalk import DingTalkChannel, DingTalkConfig

    assert DingTalkChannel.name == "nano_dingtalk"
    assert DingTalkChannel.__bases__[0].__name__ == "BaseChannel"
    assert DingTalkConfig is not None


def test_config_defaults():
    """Default config contains required fields."""
    from nanobot_channel_dingtalk.config import DingTalkConfig

    cfg = DingTalkConfig()
    assert cfg.enabled is False
    assert cfg.log_level == "INFO"
    assert cfg.client_id == ""
    assert cfg.client_secret == ""


def test_entry_point(monkeypatch):
    """Plugin entry point is discoverable by nanobot framework."""
    from nanobot_channel_dingtalk import DingTalkChannel

    eps = importlib.metadata.entry_points(group="nanobot.channels")
    match = [ep for ep in eps if ep.name == "nano_dingtalk"]
    assert len(match) == 1, f"Expected 1 entry_point, got {len(match)}: {[ep.name for ep in eps]}"

    cls = match[0].load()
    assert cls is DingTalkChannel


def test_valid_log_levels():
    """VALID_LOG_LEVELS contains expected values."""
    from nanobot_channel_dingtalk.config import VALID_LOG_LEVELS

    assert VALID_LOG_LEVELS == {"DEBUG", "INFO", "WARNING", "ERROR"}


def test_media_subpackage():
    """media subpackage imports cleanly."""
    from nanobot_channel_dingtalk.media import (
        IMAGE_EXTENSIONS,
        TEXT_FILE_EXTENSIONS,
        MEDIA_MSG_TYPES,
    )

    assert isinstance(IMAGE_EXTENSIONS, (set, frozenset))
    assert isinstance(TEXT_FILE_EXTENSIONS, (set, frozenset))
    assert isinstance(MEDIA_MSG_TYPES, (set, frozenset))

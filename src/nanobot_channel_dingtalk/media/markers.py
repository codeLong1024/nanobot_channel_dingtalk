"""Outbound marker processing — ported from services/media/video.ts, audio.ts, file.ts.

Processes special DingTalk markers embedded in AI response text:

- ``[DINGTALK_VIDEO]{"path":"..."}[/DINGTALK_VIDEO]`` — upload video, extract
  thumbnail (via ffmpeg), and send a native video message.
- ``[DINGTALK_AUDIO]{"path":"..."}[/DINGTALK_AUDIO]`` — upload audio, extract
  duration (via ffprobe), and send a native voice message.
- ``[DINGTALK_FILE]{"path":"...","fileName":"...","fileType":"..."}[/DINGTALK_FILE]``
  — upload file and replace the marker with ``[附件: name]`` in the text.

All markers are removed from the output text after processing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..sender import DingTalkSender

from . import constants as C


# ---------------------------------------------------------------------------
# Video markers
# ---------------------------------------------------------------------------


async def process_video_markers(
    text: str,
    token: str,
    sender: DingTalkSender,
    chat_id: str,
    logger: Optional[logging.Logger] = None,
) -> str:
    """Process ``[DINGTALK_VIDEO]`` markers in AI response text.

    For each marker:
    1. Extract video path from JSON payload.
    2. Read and upload video file to DingTalk.
    3. Extract thumbnail via ffmpeg (fallback silently if unavailable).
    4. Extract video duration via ffprobe.
    5. Send a native video message (mediaId + thumbMediaId + duration).
    6. Remove the marker from the text.

    Returns:
        Text with all video markers removed.
    """
    _log = logger or _get_logger()
    markers_found = list(C.VIDEO_MARKER_RE.finditer(text))

    for match in markers_found:
        try:
            payload = json.loads(match.group(1))
            video_path: str = payload.get("path", "")
            if not video_path:
                continue

            data, filename, content_type = await sender.read_media_bytes(video_path)
            if not data:
                _log.warning("video marker: could not read %s", video_path)
                continue

            # Upload video
            media_id = await sender.upload_media(
                token=token, data=data,
                media_type="video", filename=filename or "video.mp4",
                content_type=content_type,
            )
            if not media_id:
                _log.warning("video marker: upload failed for %s", video_path)
                continue

            # Extract thumbnail (optional, ffmpeg)
            thumb_media_id: Optional[str] = None
            duration: float = 0
            try:
                thumb_path = await _extract_video_thumbnail(video_path)
                if thumb_path:
                    thumb_data = await asyncio.to_thread(thumb_path.read_bytes)
                    thumb_media_id = await sender.upload_media(
                        token=token, data=thumb_data,
                        media_type="image", filename="thumbnail.jpg",
                        content_type="image/jpeg",
                    )
                duration = await _extract_video_duration(video_path)
            except (FileNotFoundError, ImportError):
                _log.debug("ffmpeg/ffprobe not available, skipping thumbnail/duration for %s", video_path)
            except Exception:
                _log.debug("thumbnail/duration extraction failed for %s", video_path, exc_info=True)

            # Send native video message
            await _send_video_message(
                sender, token, chat_id,
                media_id=media_id,
                thumb_media_id=thumb_media_id or "",
                duration=duration,
            )

        except (json.JSONDecodeError, KeyError) as e:
            _log.warning("Invalid video marker: %s", e)
            continue

    return C.VIDEO_MARKER_RE.sub("", text)


async def _extract_video_thumbnail(video_path: str | Path) -> Optional[Path]:
    """Extract a video thumbnail at the 1-second mark using ffmpeg.

    Requires ``ffmpeg`` binary in ``PATH``.  Returns ``None`` if ffmpeg is
    unavailable or extraction fails.
    """
    video = Path(video_path)
    if not video.exists():
        return None

    thumb = video.with_suffix(".thumbnail.jpg")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-ss", "1",
        "-vframes", "1",
        "-q:v", "2",
        str(thumb),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode == 0 and thumb.exists():
            return thumb
    except FileNotFoundError:
        pass
    return None


async def _extract_video_duration(video_path: str | Path) -> float:
    """Extract video duration in seconds using ffprobe.

    Requires ``ffprobe`` binary in ``PATH``.  Returns ``0`` on failure.
    """
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(video_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        info = json.loads(stdout)
        return float(info.get("format", {}).get("duration", 0))
    except (FileNotFoundError, json.JSONDecodeError, ValueError, KeyError):
        return 0.0


async def _send_video_message(
    sender: DingTalkSender,
    token: str,
    chat_id: str,
    *,
    media_id: str,
    thumb_media_id: str,
    duration: float,
) -> bool:
    """Send a native video message via DingTalk batch messages API.

    Uses ``sampleVideo`` as ``msgKey``.
    """
    msg_param = {
        "mediaId": media_id,
        "thumbMediaId": thumb_media_id,
        "duration": int(duration),
    }
    return await sender._send_batch_message(
        token, chat_id, "sampleVideo", msg_param,
        sender_staff_id=getattr(sender, '_current_sender_staff_id', None),
    )


# ---------------------------------------------------------------------------
# Audio markers
# ---------------------------------------------------------------------------


async def process_audio_markers(
    text: str,
    token: str,
    sender: DingTalkSender,
    chat_id: str,
    logger: Optional[logging.Logger] = None,
) -> str:
    """Process ``[DINGTALK_AUDIO]`` markers in AI response text.

    For each marker:
    1. Extract audio path from JSON payload.
    2. Read and upload audio file (media_type='voice').
    3. Extract duration via ffprobe.
    4. Send a native voice message.
    5. Remove the marker from the text.

    Returns:
        Text with all audio markers removed.
    """
    _log = logger or _get_logger()
    markers_found = list(C.AUDIO_MARKER_RE.finditer(text))

    for match in markers_found:
        try:
            payload = json.loads(match.group(1))
            audio_path: str = payload.get("path", "")
            if not audio_path:
                continue

            data, filename, content_type = await sender.read_media_bytes(audio_path)
            if not data:
                _log.warning("audio marker: could not read %s", audio_path)
                continue

            media_id = await sender.upload_media(
                token=token, data=data,
                media_type="voice", filename=filename or "audio.amr",
                content_type=content_type,
            )
            if not media_id:
                _log.warning("audio marker: upload failed for %s", audio_path)
                continue

            duration_ms = await _extract_audio_duration(audio_path)

            await _send_audio_message(
                sender, token, chat_id,
                media_id=media_id,
                duration=duration_ms,
            )

        except (json.JSONDecodeError, KeyError) as e:
            _log.warning("Invalid audio marker: %s", e)
            continue

    return C.AUDIO_MARKER_RE.sub("", text)


async def _extract_audio_duration(audio_path: str | Path) -> int:
    """Extract audio duration in **milliseconds** using ffprobe.

    Requires ``ffprobe`` binary in ``PATH``.  Returns ``0`` on failure.
    """
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(audio_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        info = json.loads(stdout)
        duration_sec = float(info.get("format", {}).get("duration", 0))
        return int(duration_sec * 1000)
    except (FileNotFoundError, json.JSONDecodeError, ValueError, KeyError):
        return 0


async def _send_audio_message(
    sender: DingTalkSender,
    token: str,
    chat_id: str,
    *,
    media_id: str,
    duration: int,
) -> bool:
    """Send a native voice message via DingTalk batch messages API.

    Uses ``sampleVoice`` as ``msgKey``.
    """
    msg_param = {
        "mediaId": media_id,
        "duration": duration,
    }
    return await sender._send_batch_message(
        token, chat_id, "sampleVoice", msg_param,
        sender_staff_id=getattr(sender, '_current_sender_staff_id', None),
    )


# ---------------------------------------------------------------------------
# File markers
# ---------------------------------------------------------------------------


async def upload_and_replace_file_markers(
    text: str,
    sender: DingTalkSender,
    token: str,
    logger: Optional[logging.Logger] = None,
) -> str:
    """Process ``[DINGTALK_FILE]`` markers — upload and replace with text.

    Two modes (matching TS reference):
    - **Upload + replace** (default): upload file, replace marker with ``[附件: filename]``.
    - **Process + send**: upload and send as independent file message (caller's choice).

    Returns:
        Text with all file markers replaced.
    """
    _log = logger or _get_logger()

    async def _replacer(match: re.Match) -> str:
        try:
            payload = json.loads(match.group(1))
            path = payload.get("path", "")
            file_name = payload.get("fileName", Path(path).name)
            if not path:
                return ""

            data, filename, content_type = await sender.read_media_bytes(path)
            if not data:
                _log.warning("file marker: could not read %s", path)
                return ""

            media_id = await sender.upload_media(
                token=token, data=data,
                media_type="file", filename=filename,
                content_type=content_type,
            )
            if media_id:
                return f"[附件: {file_name}]"
            _log.warning("file marker: upload failed for %s", path)
            return ""

        except (json.JSONDecodeError, KeyError) as e:
            _log.warning("Invalid file marker: %s", e)
            return ""

    return await _async_re_sub(C.FILE_MARKER_RE, _replacer, text)


async def _async_re_sub(
    pattern: re.Pattern,
    async_replacer,
    text: str,
) -> str:
    """Apply an async replacer function over all regex matches.

    ``re.sub`` does not support ``async`` callables, so we iterate manually.
    """
    result_parts: list[str] = []
    last_end = 0
    for match in pattern.finditer(text):
        result_parts.append(text[last_end:match.start()])
        replacement = await async_replacer(match)
        result_parts.append(replacement)
        last_end = match.end()
    result_parts.append(text[last_end:])
    return "".join(result_parts)


def _get_logger() -> logging.Logger:
    return logging.getLogger(__name__)


__all__ = [
    "process_video_markers",
    "process_audio_markers",
    "upload_and_replace_file_markers",
]

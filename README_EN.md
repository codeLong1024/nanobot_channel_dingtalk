<div align="center">

# nanobot-channel-dingtalk

**DingTalk AI Card Streaming Channel for Nanobot AI Agent**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CI](https://github.com/codeLong1024/nanobot_channel_dingtalk/workflows/CI/badge.svg)](https://github.com/codeLong1024/nanobot_channel_dingtalk/actions)
[![DingTalk](https://img.shields.io/badge/DingTalk-Stream%20SDK-blueviolet)](https://open.dingtalk.com/)
[![Nanobot](https://img.shields.io/badge/Nanobot-0.2.0%2B-orange)](https://github.com/HKUDS/nanobot)

**Nano DingTalk Channel Plugin** — Provides AI Card streaming output, emotion feedback, rich media and enhanced capabilities for [Nanobot AI Agent Framework](https://github.com/HKUDS/nanobot).

</div>

---

## ✨ Features

### Core Features

| Feature | Description |
|---------|-------------|
| **🃏 AI Card Streaming** | Agent streaming output with typing effect via DingTalk AI Card |
| **😊 Emotion Feedback** | 🤔 thinking emoji on receive → recall on reply complete |
| **🖼️ Rich Media** | Images, audio, video, files, richText, OCR parsing |
| **📁 File Parsing** | Auto-parse attached files into LLM context |
| **🔒 Rate Limiting** | 20 QPS built-in, compatible with Nanobot's outbound coalescing |
| **📋 Session Queue** | Per-conversation serial processing with ConversationQueue |

### Technical Highlights

- **Typewriter Effect**: Incremental streaming push based on DingTalk AI Card for natural and smooth output experience
- **Multi-Status Emoji**: Supports state transition feedback 🤔 thinking → ✍️ writing → ✅ completed
- **Error Isolation**: Automatic fallback to Markdown when card operations fail, ensuring messages are not blocked
- **Smart Rate Limiting**: Built-in 20 QPS rate limiter, compatible with Nanobot's outbound coalescing mechanism

---

## 📦 Installation

```bash
# from PyPI (once published)
# pip install nanobot-channel-dingtalk

# from source
pip install git+https://github.com/codeLong1024/nanobot_channel_dingtalk.git

# update from GitHub to latest
pip install --upgrade git+https://github.com/codeLong1024/nanobot_channel_dingtalk.git
```

Verify:

```bash
python -c "from nanobot.channels.registry import discover_all; print('nano_dingtalk' in discover_all())"
# True
```

---

## ⚙️ Configuration

```json
{
  "channels": {
    "nano_dingtalk": {
      "enabled": true,
      "client_id": "your-dingtalk-client-id",
      "client_secret": "your-dingtalk-client-secret",
      "streaming": true,
      "enable_emotion": true,
      "log_level": "INFO"
    }
  }
}
```

### Config Reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `false` | Enable/disable channel |
| `client_id` | string | — | DingTalk robot Client ID |
| `client_secret` | string | — | DingTalk robot Client Secret |
| `streaming` | bool | `true` | Enable AI Card streaming output (typing effect) |
| `log_level` | string | `"INFO"` | Per-channel log level: `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `enable_emotion` | bool | `true` | Enable multi-status emotion feedback (🤔→✍️→✅) |
| `enable_file_parsing` | bool | `true` | Auto-parse file content to LLM |
| `max_file_parse_chars` | int | `20000` | Max chars for file parsing |
| `proxy_url` | string | — | HTTP proxy (e.g. `"http://proxy:8080"`) |
| `allow_from` | string[] | `["*"]` | Allowed sender IDs |

### Coexistence with Built-in DingTalk

Both `dingtalk` (built-in) and `nano_dingtalk` (plugin) appear in `nanobot plugins list`.
**Do NOT enable both** — a DingTalk robot can only have one connection.

Recommended: disable the built-in in config:

```json
{
  "channels": {
    "dingtalk": { "enabled": false },
    "nano_dingtalk": {
      "enabled": true,
      "client_id": "..."
    }
  }
}
```

---

## 🚀 Usage

```bash
nanobot run -c config.json
# → "Nano DingTalk channel enabled"
```

### Debug Logging

Two ways to see debug output:

1. **Global**: `nanobot run -v` (framework-wide DEBUG)
2. **Per-channel** (recommended): set `"log_level": "DEBUG"` in config
   - Adds an isolated DEBUG sink for `nanobot_channel_dingtalk` module only
   - No duplication with the framework's INFO+ handler

### View Channels

```bash
nanobot plugins list
# dingtalk      (builtin)
# nano_dingtalk (plugin)

nanobot channels status
```

---

## 🃏 AI Card Streaming

Channel includes **DingTalk AI Card** streaming output support. Typewriter effect is automatically applied when the Agent generates content.

### Data Flow

```
User message → Stream SDK → _handle_message()
  → 1. 🤔 Add thinking emoji
  → 2. EmotionContext storage (for multi-status emoji updates)
  → 3. CardManager.create_card() (create + deploy card)
  → 4. CardManager.start_streaming("Thinking...")
  → 5. Agent processing (always enables _wants_stream)
       ├── Incremental chunk → sender._stream_delta → CardManager.stream_content() → typewriter effect
       └── End → sender._stream_end → CardManager.finish_streaming()
  → 6. On completion → Recycle 🤔 thinking emoji + clean context
  → 7. On failure → CardManager.fail_card() + immediate emoji recall
```

### Non-Streaming Fallback

When the Agent returns complete content directly, it is automatically displayed via AI Card in one go. If card operations fail, it falls back to a regular Markdown message.

### Error Isolation

- Card creation failure → Fallback to regular message, does not block message processing
- Streaming push 403 QPS rate limit → Automatic retry once
- Streaming/card operation exception → Fallback to Markdown sending
- Exceptions are logged to log (no longer silently swallowed)

---

## 📁 Module Structure

```
src/nanobot_channel_dingtalk/
├── __init__.py              # DingTalkChannel / DingTalkConfig / CardManager / DingTalkCardClient
├── channel.py               # DingTalkChannel(BaseChannel)
├── config.py                # Pydantic config model (with streaming field)
├── auth.py                  # DingTalk Stream SDK wrapper
├── token.py                 # TokenManager (OAuth2 token lifecycle)
├── sender.py                # Message sending orchestrator (5-path: streaming delta/end/progress/card/markdown)
├── message.py               # Message parsing + handling (AI Card creation + streaming setup)
├── emotion_handler.py       # 🤔 thinking / recall emoji
├── emotion_hook.py          # EmotionContext + DingTalkEmotionHook (multi-status emoji)
├── rate_limiter.py          # 20 QPS rate limiter
├── session.py               # Session key utilities
├── session_manager.py       # ConversationQueue (with error logging)
├── models.py                # AI Card data models (AICardStatus, AICardInstance)
├── card_client.py           # DingTalk Card API HTTP client (token + error handling)
├── card_manager.py          # AI Card lifecycle manager (create/stream/finish/fail/finalize)
└── media/                   # Rich media pipeline
    ├── __init__.py
    ├── constants.py         # Regex patterns, extension maps
    ├── helpers.py           # Pure functions: URL detection, upload helpers
    ├── fetch.py             # SSRF-protected remote media fetching
    ├── upload.py            # Normal + chunked upload to DingTalk
    ├── download.py          # File download from DingTalk
    ├── file_parser.py       # File content → LLM context
    ├── image_processor.py   # Resize / crop / base64
    ├── markers.py           # [audio][video][file] marker handling
    └── raw_path.py          # Raw path processing
```

---

## 🔧 Development

```bash
git clone https://github.com/codeLong1024/nanobot_channel_dingtalk.git
cd nanobot_channel_dingtalk
pip install -e .
python -m pytest tests/ -v
```

---

## 📚 References

- [Nanobot AI Agent Framework](https://github.com/HKUDS/nanobot) — Lightweight AI Agent Framework with pluggable channel architecture
- [DingTalk OpenClaw Connector](https://github.com/DingTalk-Real-AI/dingtalk-openclaw-connector) — Official reference for emotion feedback design (MIT)
- [DingTalk AI Card API](https://open.dingtalk.com/document/orgapp/stream-typing-users-output-content) — Interactive card streaming interface documentation
- [DingTalk Stream SDK](https://open.dingtalk.com/document/orgapp/stream-mode-configuration) — Stream mode configuration guide

## 🔍 Related Projects

- [Nanobot](https://github.com/HKUDS/nanobot) — Multi-channel AI Agent Framework
- [DingTalk Open Platform](https://open.dingtalk.com/) — DingTalk Open Platform Official Documentation

---

## 🙏 Acknowledgements

Emotion feedback design is inspired by the official [dingtalk-openclaw-connector](https://github.com/DingTalk-Real-AI/dingtalk-openclaw-connector) project (MIT). Thanks to the DingTalk team for their open-source contributions.

---

<p align="center">MIT Licensed · <a href="https://github.com/codeLong1024/nanobot_channel_dingtalk">nanobot-channel-dingtalk</a></p>

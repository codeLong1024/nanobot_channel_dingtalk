<div align="center">

# nanobot-channel-dingtalk

**钉钉 AI Card 流式输出插件 | DingTalk AI Card Streaming Channel for Nanobot AI Agent**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CI](https://github.com/codeLong1024/nanobot_channel_dingtalk/workflows/CI/badge.svg)](https://github.com/codeLong1024/nanobot_channel_dingtalk/actions)

**钉钉 Nano 通道插件** — 为 [Nanobot AI Agent Framework](https://github.com/HKUDS/nanobot) 提供 AI Card 流式输出、情绪表情、富媒体等增强能力。

[![DingTalk](https://img.shields.io/badge/DingTalk-Stream%20SDK-blueviolet)](https://open.dingtalk.com/)
[![Nanobot](https://img.shields.io/badge/Nanobot-Channel%20Plugin-orange)](https://github.com/HKUDS/nanobot)

</div>

---

## ✨ Features

### 核心功能 Core Features

| Feature | Description |
|---------|-------------|
| **🃏 AI Card Streaming** | Agent streaming output with typing effect via DingTalk AI Card (钉钉 AI 卡片流式输出) |
| **😊 Emotion Feedback** | 🤔 thinking emoji on receive → recall on reply complete (情绪表情反馈) |
| **🖼️ Rich Media** | Images, audio, video, files, richText, OCR parsing (富媒体支持) |
| **📁 File Parsing** | Auto-parse attached files into LLM context (文件自动解析) |
| **🔒 Rate Limiting** | 20 QPS built-in, compatible with Nanobot's outbound coalescing (速率限制) |
| **📋 Session Queue** | Per-conversation serial processing with ConversationQueue (会话队列管理) |

### 技术亮点 Technical Highlights

- **打字机效果 Typewriter Effect**: 基于钉钉 AI Card 的增量流式推送，实现自然流畅的输出体验
- **多状态表情 Multi-Status Emoji**: 支持 🤔思考 → ✍️写作 → ✅完成 的状态切换反馈
- **错误隔离 Error Isolation**: 卡片操作失败自动降级 Markdown，保障消息不堵塞
- **智能限流 Smart Rate Limiting**: 内置 20 QPS 限流器，兼容 Nanobot 出站合并机制

---

## 📦 Installation

```bash
# from PyPI (once published)
# pip install nanobot-channel-dingtalk

# from source
pip install git+https://github.com/codeLong1024/nanobot_channel_dingtalk.git
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

Channel 内置 **DingTalk AI Card** 流式输出支持，Agent 生成内容时自动实现打字机效果。

### 数据流

```
用户消息 → Stream SDK → _handle_message()
  → 1. 🤔 添加思考表情
  → 2. EmotionContext 存储（供多状态表情更新）
  → 3. CardManager.create_card()（创建 + 投放卡片）
  → 4. CardManager.start_streaming("思考中...")
  → 5. Agent 处理（始终启用 _wants_stream）
       ├── 增量 chunk → sender._stream_delta → CardManager.stream_content() → 打字机效果
       └── 结束 → sender._stream_end → CardManager.finish_streaming()
  → 6. 完成时 → 回收 🤔 思考表情 + 清理上下文
  → 7. 失败时 → CardManager.fail_card() + 立即回收表情
```

### 非流式回退

Agent 直接返回完整内容时，自动通过 AI Card 一次性展示；若卡片操作失败，降级为普通 Markdown 消息。

### 错误隔离

- 卡片创建失败 → 降级为普通消息，不堵塞消息处理
- 流式推送 403 QPS 限流 → 自动重试一次
- 流式/卡片操作异常 → 降级 Markdown 发送
- 异常会被记录到日志（不再静默吞噬）

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
├── models.py                # [NEW] AI Card data models (AICardStatus, AICardInstance)
├── card_client.py           # [NEW] DingTalk Card API HTTP client (token + error handling)
├── card_manager.py          # [NEW] AI Card lifecycle manager (create/stream/finish/fail/finalize)
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
- [DingTalk Open Platform](https://open.dingtalk.com/) — 钉钉开放平台

---

## 🙏 Acknowledgements

Emotion feedback design is inspired by the official [dingtalk-openclaw-connector](https://github.com/DingTalk-Real-AI/dingtalk-openclaw-connector) project (MIT). Thanks to the DingTalk team for their open-source contributions.

---

<p align="center">MIT Licensed · <a href="https://github.com/codeLong1024/nanobot_channel_dingtalk">nanobot-channel-dingtalk</a></p>

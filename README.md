<div align="center">

# nanobot-channel-dingtalk

**钉钉 AI Card 流式输出插件**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CI](https://github.com/codeLong1024/nanobot_channel_dingtalk/workflows/CI/badge.svg)](https://github.com/codeLong1024/nanobot_channel_dingtalk/actions)
[![DingTalk](https://img.shields.io/badge/DingTalk-Stream%20SDK-blueviolet)](https://open.dingtalk.com/)
[![Nanobot](https://img.shields.io/badge/Nanobot-Channel%20Plugin-orange)](https://github.com/HKUDS/nanobot)

**钉钉 Nano 通道插件** — 为 [Nanobot AI Agent Framework](https://github.com/HKUDS/nanobot) 提供 AI Card 流式输出、情绪表情、富媒体等增强能力。

</div>

---

## ✨ 功能特性

### 核心功能

| 功能 | 说明 |
|------|------|
| **🃏 AI Card 流式输出** | Agent 流式输出,钉钉 AI 卡片打字机效果 |
| **😊 情绪表情反馈** | 🤔 接收时添加思考表情 → 回复完成后回收 |
| **🖼️ 富媒体支持** | 图片、音频、视频、文件、richText、OCR 解析 |
| **📁 文件自动解析** | 自动解析附件内容到 LLM 上下文 |
| **🔒 速率限制** | 内置 20 QPS,兼容 Nanobot 出站合并机制 |
| **📋 会话队列管理** | 基于 ConversationQueue 的单会话串行处理 |

### 技术亮点

- **打字机效果**: 基于钉钉 AI Card 的增量流式推送,实现自然流畅的输出体验
- **多状态表情**: 支持 🤔思考 → ✍️写作 → ✅完成 的状态切换反馈
- **错误隔离**: 卡片操作失败自动降级 Markdown,保障消息不堵塞
- **智能限流**: 内置 20 QPS 限流器,兼容 Nanobot 出站合并机制

---

## 📦 安装

```bash
# 从 PyPI 安装 (发布后)
# pip install nanobot-channel-dingtalk

# 从源码安装
pip install git+https://github.com/codeLong1024/nanobot_channel_dingtalk.git
```

验证安装:

```bash
python -c "from nanobot.channels.registry import discover_all; print('nano_dingtalk' in discover_all())"
# True
```

---

## ⚙️ 配置

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

### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `false` | 启用/禁用通道 |
| `client_id` | string | — | 钉钉机器人 Client ID |
| `client_secret` | string | — | 钉钉机器人 Client Secret |
| `streaming` | bool | `true` | 启用 AI Card 流式输出 (打字机效果) |
| `log_level` | string | `"INFO"` | 通道日志级别: `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `enable_emotion` | bool | `true` | 启用多状态表情反馈 (🤔→✍️→✅) |
| `enable_file_parsing` | bool | `true` | 自动解析文件内容到 LLM |
| `max_file_parse_chars` | int | `20000` | 文件解析最大字符数 |
| `proxy_url` | string | — | HTTP 代理 (e.g. `"http://proxy:8080"`) |
| `allow_from` | string[] | `["*"]` | 允许的发送者 ID 列表 |

### 与内置钉钉通道共存

`dingtalk` (内置) 和 `nano_dingtalk` (插件) 会同时出现在 `nanobot plugins list` 中。
**不要同时启用两者** — 一个钉钉机器人只能有一个连接。

建议在配置中禁用内置通道:

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

## 🚀 使用

```bash
nanobot run -c config.json
# → "Nano DingTalk channel enabled"
```

### 调试日志

两种查看调试输出的方式:

1. **全局调试**: `nanobot run -v` (框架级 DEBUG)
2. **通道级调试** (推荐): 在配置中设置 `"log_level": "DEBUG"`
   - 仅为 `nanobot_channel_dingtalk` 模块添加独立的 DEBUG 日志
   - 不会与框架的 INFO+ 处理器重复

### 查看通道

```bash
nanobot plugins list
# dingtalk      (builtin)
# nano_dingtalk (plugin)

nanobot channels status
```

---

## 🃏 AI Card 流式输出

通道内置 **DingTalk AI Card** 流式输出支持,Agent 生成内容时自动实现打字机效果。

### 数据流

```
用户消息 → Stream SDK → _handle_message()
  → 1. 🤔 添加思考表情
  → 2. EmotionContext 存储 (供多状态表情更新)
  → 3. CardManager.create_card() (创建 + 投放卡片)
  → 4. CardManager.start_streaming("思考中...")
  → 5. Agent 处理 (始终启用 _wants_stream)
       ├── 增量 chunk → sender._stream_delta → CardManager.stream_content() → 打字机效果
       └── 结束 → sender._stream_end → CardManager.finish_streaming()
  → 6. 完成时 → 回收 🤔 思考表情 + 清理上下文
  → 7. 失败时 → CardManager.fail_card() + 立即回收表情
```

### 非流式回退

Agent 直接返回完整内容时,自动通过 AI Card 一次性展示;若卡片操作失败,降级为普通 Markdown 消息。

### 错误隔离

- 卡片创建失败 → 降级为普通消息,不堵塞消息处理
- 流式推送 403 QPS 限流 → 自动重试一次
- 流式/卡片操作异常 → 降级 Markdown 发送
- 异常会被记录到日志 (不再静默吞噬)

---

## 📁 模块结构

```
src/nanobot_channel_dingtalk/
├── __init__.py              # DingTalkChannel / DingTalkConfig / CardManager / DingTalkCardClient
├── channel.py               # DingTalkChannel(BaseChannel)
├── config.py                # Pydantic 配置模型 (含 streaming 字段)
├── auth.py                  # 钉钉 Stream SDK 封装
├── token.py                 # TokenManager (OAuth2 token 生命周期)
├── sender.py                # 消息发送编排器 (5 路径: streaming delta/end/progress/card/markdown)
├── message.py               # 消息解析 + 处理 (AI Card 创建 + 流式设置)
├── emotion_handler.py       # 🤔 思考表情 / 回收表情
├── emotion_hook.py          # EmotionContext + DingTalkEmotionHook (多状态表情)
├── rate_limiter.py          # 20 QPS 限流器
├── session.py               # Session 键工具函数
├── session_manager.py       # ConversationQueue (含错误日志)
├── models.py                # AI Card 数据模型 (AICardStatus, AICardInstance)
├── card_client.py           # 钉钉 Card API HTTP 客户端 (token + 错误处理)
├── card_manager.py          # AI Card 生命周期管理 (create/stream/finish/fail/finalize)
└── media/                   # 富媒体处理管线
    ├── __init__.py
    ├── constants.py         # 正则表达式、扩展名映射
    ├── helpers.py           # 纯函数: URL 检测、上传辅助
    ├── fetch.py             # SSRF 保护的远程媒体获取
    ├── upload.py            # 普通 + 分块上传到钉钉
    ├── download.py          # 从钉钉下载文件
    ├── file_parser.py       # 文件内容 → LLM 上下文
    ├── image_processor.py   # 缩放 / 裁剪 / base64
    ├── markers.py           # [audio][video][file] 标记处理
    └── raw_path.py          # 原始路径处理
```

---

## 🔧 开发

```bash
git clone https://github.com/codeLong1024/nanobot_channel_dingtalk.git
cd nanobot_channel_dingtalk
pip install -e .
python -m pytest tests/ -v
```

---

## 📚 参考资料

- [Nanobot AI Agent Framework](https://github.com/HKUDS/nanobot) — 支持可插拔通道架构的轻量级 AI Agent 框架
- [DingTalk OpenClaw Connector](https://github.com/DingTalk-Real-AI/dingtalk-openclaw-connector) — 情绪表情反馈设计参考 (MIT 协议)
- [DingTalk AI Card API](https://open.dingtalk.com/document/orgapp/stream-typing-users-output-content) — 交互式卡片流式输出接口文档
- [DingTalk Stream SDK](https://open.dingtalk.com/document/orgapp/stream-mode-configuration) — 流模式配置指南

## 🔍 相关项目

- [Nanobot](https://github.com/HKUDS/nanobot) — 多通道 AI Agent 框架
- [钉钉开放平台](https://open.dingtalk.com/) — 钉钉开放平台官方文档

---

## 🙏 致谢

情绪表情反馈设计灵感来源于官方 [dingtalk-openclaw-connector](https://github.com/DingTalk-Real-AI/dingtalk-openclaw-connector) 项目 (MIT 协议)。感谢钉钉团队开源贡献。

---

<p align="center">MIT 协议 · <a href="https://github.com/codeLong1024/nanobot_channel_dingtalk">nanobot-channel-dingtalk</a></p>

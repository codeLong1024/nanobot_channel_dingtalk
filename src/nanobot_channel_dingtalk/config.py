"""DingTalk channel configuration and constants."""

from pydantic import ConfigDict, Field
from nanobot.config.schema import Base

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}

# Constants for media handling
DINGTALK_MAX_REMOTE_MEDIA_BYTES = 20 * 1024 * 1024
DINGTALK_MAX_REMOTE_MEDIA_REDIRECTS = 3


class DingTalkConfig(Base):
    """DingTalk channel configuration using Stream mode."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    log_level: str = "INFO"
    """通道日志级别：DEBUG / INFO / WARNING / ERROR。设为 DEBUG 可查看 HTTP 请求、流式增量等详细信息。"""
    allow_from: list[str] = Field(default_factory=list)
    allow_remote_media_redirects: bool = False
    remote_media_redirect_allowed_hosts: list[str] = Field(default_factory=list)

    # ============ 媒体上传配置 ============
    enable_media_upload: bool = True  # 媒体上传总开关
    media_max_mb: int = 20  # 最大媒体文件 MB
    enable_chunk_upload: bool = True  # 大文件分块上传开关
    chunk_size_kb: int = 5120  # 分块大小（默认 5MB）
    media_local_roots: list[str] = Field(
        default_factory=list,
    )  # 本地媒体根目录（相对路径解析）

    # ============ 文件解析配置 ============
    enable_file_parsing: bool = False  # 入站文件内容解析开关
    max_file_parse_chars: int = 2000  # 文件解析注入最大字符数

    # ============ AI Agent 标记处理配置 ============
    enable_marker_processing: bool = True  # AI 回复标记处理开关
    enable_video_thumbnail: bool = True  # 视频封面生成开关

    # ============ 代理配置 ============
    proxy_url: str | None = None
    """HTTP 代理地址 (如 "http://proxy.example.com:8080")。

    专属钉钉场景下，文件下载 URL 指向内部文件服务器（如 ddoss.dingtalk.*），
    通常需要走公司代理才能连通。设置此值后，所有 HTTP 请求将经过该代理。

    如果留空则直连（默认行为）。如需更精细控制，可设置 http_proxy /
    https_proxy 环境变量（httpx 会自动读取）。
    """

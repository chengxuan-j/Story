"""Story 项目配置。

API Key 与 MySQL 连接信息一律从系统环境变量读取，不写明文、不依赖 .env。
- DASHSCOPE_API_KEY：DashScope API Key
- MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE：MySQL 连接
其余参数有合理默认值，可用同名环境变量覆盖。
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings:
    """轻量配置对象：优先读环境变量，其次默认值。"""

    @property
    def qwen_api_key(self) -> str:
        return (os.getenv("DASHSCOPE_API_KEY") or "").strip()

    @property
    def qwen_base_url(self) -> str:
        return os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")

    @property
    def qwen_model(self) -> str:
        return os.getenv("QWEN_MODEL", "qwen-plus")

    @property
    def qwen_analysis_model(self) -> str:
        return os.getenv("QWEN_ANALYSIS_MODEL", "qwen-flash")

    @property
    def qwen_vision_model(self) -> str:
        return os.getenv("QWEN_VISION_MODEL", "qwen3-vl-plus")

    @property
    def request_timeout(self) -> float:
        try:
            return float(os.getenv("REQUEST_TIMEOUT", "60"))
        except ValueError:
            return 60.0

    @property
    def tts_model(self) -> str:
        return os.getenv("TTS_MODEL", "qwen-audio-3.0-tts-flash")

    @property
    def tts_voice(self) -> str:
        return os.getenv("TTS_VOICE", "longanhuan_v3.6")

    @property
    def asr_model(self) -> str:
        return os.getenv("ASR_MODEL", "paraformer-v2")

    @property
    def storyboard_seconds(self) -> int:
        try:
            return int(os.getenv("STORYBOARD_SECONDS", "60"))
        except ValueError:
            return 60

    # ---------- MySQL ----------
    @property
    def mysql_host(self) -> str:
        return os.getenv("MYSQL_HOST", "127.0.0.1")

    @property
    def mysql_port(self) -> int:
        try:
            return int(os.getenv("MYSQL_PORT", "3306"))
        except ValueError:
            return 3306

    @property
    def mysql_user(self) -> str:
        return os.getenv("MYSQL_USER", "root")

    @property
    def mysql_password(self) -> str:
        return os.getenv("MYSQL_PASSWORD", "")

    @property
    def mysql_database(self) -> str:
        return os.getenv("MYSQL_DATABASE", "story")

    @property
    def mysql_charset(self) -> str:
        return os.getenv("MYSQL_CHARSET", "utf8mb4")

    def mysql_dsn(self, *, include_db: bool = True) -> dict:
        """aiomysql.connect 的连接参数字典。"""
        cfg = {
            "host": self.mysql_host,
            "port": self.mysql_port,
            "user": self.mysql_user,
            "password": self.mysql_password,
            "charset": self.mysql_charset,
            "autocommit": False,
        }
        if include_db:
            cfg["db"] = self.mysql_database
        return cfg


_settings = Settings()


def get_settings() -> Settings:
    return _settings

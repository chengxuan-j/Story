"""MySQL 数据层（aiomysql）：故事表 + 短片故事板表。

连接信息从系统环境变量读取（MYSQL_HOST/PORT/USER/PASSWORD/DATABASE）。
启动时自动建库（若不存在）与建表。
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import aiomysql

from app.config import get_settings

# 建表语句（MySQL 语法：AUTO_INCREMENT，TEXT 够用）
CREATE_STORIES = """
CREATE TABLE IF NOT EXISTS stories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255) NOT NULL DEFAULT '',
    summary TEXT NOT NULL,
    raw_dialogue TEXT NOT NULL,
    input_type VARCHAR(20) NOT NULL DEFAULT 'text',
    era_tags TEXT NOT NULL DEFAULT ('[]'),
    time_value VARCHAR(100) NOT NULL DEFAULT '',
    place VARCHAR(200) NOT NULL DEFAULT '',
    emotion_tone VARCHAR(50) NOT NULL DEFAULT '',
    created_at VARCHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

CREATE_COMPILATIONS = """
CREATE TABLE IF NOT EXISTS compilations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255) NOT NULL DEFAULT '',
    perspective VARCHAR(30) NOT NULL DEFAULT 'first_person',
    status VARCHAR(30) NOT NULL DEFAULT 'queued',
    story_ids TEXT NOT NULL DEFAULT ('[]'),
    prompt_package LONGTEXT NULL,
    created_at VARCHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@asynccontextmanager
async def get_db():
    """每个请求一个连接，自动提交/回滚并关闭。"""
    s = get_settings()
    conn = await aiomysql.connect(**s.mysql_dsn())
    cur = await conn.cursor(aiomysql.DictCursor)
    try:
        yield conn, cur
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


async def init_db() -> None:
    """自动建库 + 建表。连到 server（不指定 db）先 CREATE DATABASE。"""
    s = get_settings()
    # 1) 连 server 建库
    conn = await aiomysql.connect(**s.mysql_dsn(include_db=False))
    try:
        cur = await conn.cursor()
        await cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{s.mysql_database}` "
            f"DEFAULT CHARACTER SET {s.mysql_charset} COLLATE utf8mb4_unicode_ci"
        )
        await cur.close()
        await conn.commit()
    finally:
        conn.close()

    # 2) 连库建表
    conn = await aiomysql.connect(**s.mysql_dsn())
    try:
        cur = await conn.cursor()
        await cur.execute(CREATE_STORIES)
        await cur.execute(CREATE_COMPILATIONS)
        await cur.close()
        await conn.commit()
    finally:
        conn.close()


# ---------- 行 → dict ----------

def story_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    try:
        raw = json.loads(row.get("raw_dialogue") or "[]")
    except (TypeError, json.JSONDecodeError):
        raw = []
    try:
        eras = json.loads(row.get("era_tags") or "[]")
    except (TypeError, json.JSONDecodeError):
        eras = []
    return {
        "id": row["id"],
        "title": row["title"],
        "summary": row["summary"],
        "raw_dialogue": raw,
        "input_type": row["input_type"],
        "era_tags": eras,
        "time_value": row["time_value"],
        "place": row["place"],
        "emotion_tone": row["emotion_tone"],
        "created_at": row["created_at"],
    }


class StoryObj:
    """把 story 字典包成对象，供 storyboard.py 的 getattr(story, ...) 访问。"""

    def __init__(self, data: dict[str, Any]) -> None:
        for key, value in data.items():
            setattr(self, key, value)


def to_story_obj(row: dict[str, Any]) -> StoryObj:
    return StoryObj(story_to_dict(row))


def compilation_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    try:
        ids = json.loads(row.get("story_ids") or "[]")
    except (TypeError, json.JSONDecodeError):
        ids = []
    pkg: Optional[dict] = None
    if row.get("prompt_package"):
        try:
            pkg = json.loads(row["prompt_package"])
        except (TypeError, json.JSONDecodeError):
            pkg = None
    return {
        "id": row["id"],
        "title": row["title"],
        "perspective": row["perspective"],
        "status": row["status"],
        "story_ids": ids,
        "prompt_package": pkg,
        "created_at": row["created_at"],
        "video_url": None,   # 契约：不生成真实视频
        "rendered": False,
    }

"""时代词表加载与归一（从原项目原样移植）。

data/era_lexicon.json 给出规范时代名 + 同义词，用于分镜排序按时代轴。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

LEXICON_PATH = Path(BASE_DIR) / "data" / "era_lexicon.json"

_cache: Optional[dict[str, Any]] = None
_synonym_index: dict[str, str] = {}


def load() -> dict[str, Any]:
    global _cache, _synonym_index
    if _cache is not None:
        return _cache
    try:
        with open(LEXICON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("读取 era_lexicon.json 失败，时代词表降级为空: %s", e)
        data = {"version": 0, "eras": []}
    index: dict[str, str] = {}
    for era in data.get("eras", []):
        name = era.get("name", "")
        if not name:
            continue
        index[name] = name
        for syn in era.get("synonyms", []):
            index[syn] = name
    _cache = data
    _synonym_index = index
    return data


def eras() -> list[dict[str, Any]]:
    return list(load().get("eras", []))


def canonicalize(tag: str) -> Optional[str]:
    if not tag:
        return None
    load()
    tag = tag.strip()
    if tag in _synonym_index:
        return _synonym_index[tag]
    for syn, name in _synonym_index.items():
        if syn and (syn in tag or tag in syn):
            return name
    return None


def normalize_tags(tags: Any) -> tuple[list[str], list[str]]:
    canonical: list[str] = []
    unmapped: list[str] = []
    if not isinstance(tags, list):
        return canonical, unmapped
    for raw in tags:
        text = str(raw).strip()
        if not text:
            continue
        name = canonicalize(text)
        if name:
            if name not in canonical:
                canonical.append(name)
        elif text not in unmapped:
            unmapped.append(text)
    return canonical, unmapped


def era_meta(name: str) -> Optional[dict[str, Any]]:
    for era in eras():
        if era.get("name") == name:
            return era
    return None

"""从口语/书面时间串里抠出年份（从原项目 timeline.py 原样移植的 parse_year）。"""
from __future__ import annotations

import re
from typing import Optional

_CN_DIGITS = {
    "〇": "0", "零": "0", "一": "1", "二": "2", "两": "2", "三": "3",
    "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
}
_ARABIC_YEAR = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)")
_CN_YEAR = re.compile(r"[〇零一二三四五六七八九]{4}")
_ARABIC_DECADE = re.compile(r"(?<!\d)(\d{2})\s*年代?(?!\d)")
_CN_DECADE = re.compile(r"([一二三四五六七八九])\s*十\s*年代?")


def parse_year(text: str) -> Optional[int]:
    """从口语/书面时间串里抠出一个年份；抠不出返回 None。

    覆盖：`1973年` / `一九七三年` / `二〇〇〇年` / `七十年代` /
    `上世纪80年代` / `两千年`。世纪敏感词会把两位数年代锚到 19xx。
    """
    if not text:
        return None
    raw = str(text)

    m = _ARABIC_YEAR.search(raw)
    if m:
        return int(m.group(1))

    m = _CN_YEAR.search(raw)
    if m:
        year = int("".join(_CN_DIGITS[c] for c in m.group(0)))
        if 1900 <= year <= 2100:
            return year

    if "两千年" in raw or "两千零" in raw:
        return 2000

    for_1900s = bool(re.search(r"上世纪|上个世纪|上一世纪", raw))
    m = _ARABIC_DECADE.search(raw)
    if m:
        n = int(m.group(1))
        base = 1900 if for_1900s or n >= 30 else 2000
        return base + n

    m = _CN_DECADE.search(raw)
    if m:
        decade = int(_CN_DIGITS[m.group(1)])
        return 1900 + decade * 10

    return None

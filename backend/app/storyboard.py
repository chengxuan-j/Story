"""M5 故事板编排器（契约6：只到提示词，不生成任何画面）。

输入一批**已留档（archived）**的故事 → 排成一条 60 秒左右的故事板 →
输出结构化 `prompt_package`，状态止于 `prompt_ready`。

分工刻意做成"代码管骨架、LLM 管血肉"：

| 谁 | 管什么 | 为什么 |
|---|---|---|
| 代码 | 选定哪些故事、按时代轴排序、每段多长、总时长、镜头号 | 要可控可测，不能交给模型 |
| LLM  | 旁白、剧本、分镜内容、美术设定、逐镜头提示词 | 这是创作，但必须落在代码给的框子里 |

**时长由代码分配、不采信 LLM**：模型给的秒数加起来永远不等于 60，
而且这次多 3 秒、下次少 5 秒，前端进度条就没法对齐。镜头时长直接取
代码分配的那份，`shot_list` 的秒数之和恒等于 `total_seconds`。

LLM 输出一律视为不可信输入，六段交付物逐个后校验：

1. `narration` 必须第一人称、且与老人原话足够接近，否则回退用原句（契约4）；
2. 画面 / 视频提示词 / 美术设定里出现人脸类词 → 逐短语剔除，剔空用安全兜底（契约6 延伸）；
3. `disclaimer` 缺失 → 强制补默认文案，不允许没有免责声明；
4. `source_evidence` 一律用代码写入的老人原话，不采信模型（免得编造出处）；
5. `shot_list` / `video_prompts` 的镜头号由代码按段序生成，模型乱序也不影响对齐；
6. `render_engine` / `video_url` 恒为 null——只出文字提示词，不接任何生成服务。

降级：LLM 不可用 → 按时代轴线性拼接，六段仍全部存在（内容用原话 / 兜底），
`status` 仍是 `prompt_ready`，前端不会拿到半截结构。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional, Sequence

from app.json_utils import parse_json_loose
from app.llm import LLMError, QwenClient
from app import era_lexicon
from app.prompts import STORYBOARD_SYSTEM_PROMPT
from app.time_utils import parse_year

logger = logging.getLogger(__name__)

DEFAULT_TOTAL_SECONDS = 60
MIN_SCENE_SECONDS = 4
MAX_SCENE_SECONDS = 25
MAX_SCENES = 12

# 一镜最少 2 秒：低于这个时长在成片里等于闪一下，观众看不清
MIN_SHOT_SECONDS = 2
MAX_SHOTS = 12

NARRATION_MAX_LEN = 45
VISUAL_MAX_LEN = 60

# 旁白与原话的最低相似度：低于它说明模型改写了事实，回退用原句（契约4）
NARRATION_MIN_SIMILARITY = 0.30

# 第三人称指代：模型把主角写成了"她/他/老人"，就是违约（契约4）。
# 不说"必须含『我』"——中文主语省略是常态，"那时候买米买面都得要粮票"
# 本来就是老人自己的原话，硬要求含"我"会误杀一大片合格旁白。
THIRD_PERSON_MARKERS = ("她", "他", "老人", "老人家", "阿姨", "奶奶", "爷爷", "大伯", "大妈")

# 人脸类词：命中即剔除所在短语（契约6 延伸——不描述具体人脸）。
# 刻意**不**把裸的"特写"放进来：导演表里"手部特写""钥匙特写"是正常景别，
# 真正要拦的是"面部特写""脸部特写"——它们本身就带"面部/脸"，已经被拦住了。
FACE_BAN_WORDS = (
    "脸", "面部", "面容", "面孔", "五官", "相貌", "长相", "肖像", "容貌", "满面",
    "portrait", "face", "headshot",
)

# 创作层的细分字段用同一套词表（原来这里还多禁了"特写"，会误杀手部/物件特写）
FACE_FEATURE_WORDS = FACE_BAN_WORDS

# 免责声明：后校验发现缺失就补这句，不允许没有免责声明
DEFAULT_DISCLAIMER = (
    "本片由老人讲述的回忆整理而成，画面为示意；时间与细节以老人本人说法为准。"
)

# 画面兜底（不含人脸，只写环境）
VISUAL_FALLBACK = "年代感的生活环境空镜，柔和自然光，暖黄色调，胶片质感，远景"

_PHRASE_SPLIT = re.compile(r"[，,。；;、\n]+")


# ---------------------------------------------------------------------------
# 纯函数：排序 / 时长 / 后校验
# ---------------------------------------------------------------------------

def story_sort_key(story) -> tuple:
    """时代轴排序键：先按最早时代的起始年，再按故事自身的年份，最后按 id。

    与 M3 时代轴口径一致——故事板让老人看到的时间顺序，必须和他自己
    在回忆录里看到的一致，否则同一件事在两处顺序不同，很困惑。
    """
    canonical, _ = era_lexicon.normalize_tags(getattr(story, "era_tags", None))
    era_start = 9999
    for name in canonical:
        meta = era_lexicon.era_meta(name) or {}
        start = meta.get("start_year") or 9999
        era_start = min(era_start, start)
    year = parse_year(getattr(story, "time_value", "") or "") or 9999
    return (era_start, year, getattr(story, "id", 0) or 0)


def original_quote(story) -> str:
    """老人在这个话题上说过的话（第一人称原话），没有就用 summary。"""
    for turn in (getattr(story, "raw_dialogue", None) or []):
        if isinstance(turn, dict) and turn.get("role") == "user":
            text = str(turn.get("content") or "").strip()
            if text:
                return text
    return str(getattr(story, "summary", "") or "").strip()


def allocate_durations(count: int, total_seconds: int = DEFAULT_TOTAL_SECONDS) -> list[int]:
    """把总时长平均分给每段，并夹在 [MIN, MAX] 之间。

    整数平均，余数补给前几段，保证 **各段之和恰好等于总时长**
    （除非段数太多导致每段都顶到下限——那时总长会超，是真实的取舍，
    调用方从 `planned_total` 能看到实际值）。
    """
    if count <= 0:
        return []
    per = min(MAX_SCENE_SECONDS, max(MIN_SCENE_SECONDS, total_seconds // count))
    durations = [per] * count
    remainder = total_seconds - per * count
    i = 0
    while remainder > 0 and per < MAX_SCENE_SECONDS:
        durations[i % count] += 1
        remainder -= 1
        i += 1
    return durations


def split_duration(total: int, count: int, min_each: int = MIN_SHOT_SECONDS) -> list[int]:
    """把一场的秒数整数拆给该场的 `count` 个镜头，和恒等于 `total`。

    余数补给前几镜（3 秒拆 2 镜 → [2, 1] 会低于下限，所以先降镜头数：
    时长不够就少切两刀，而不是切出 1 秒的废镜）。
    """
    if count <= 0:
        return [max(0, total)]
    usable = min(count, max(1, total // max(1, min_each))) if total > 0 else 1
    base = total // usable
    durations = [base] * usable
    for i in range(total - base * usable):
        durations[i] += 1
    return durations


def _bigrams(text: str) -> set[str]:
    chars = re.sub(r"[^\u4e00-\u9fff]", "", text or "")
    return {chars[i:i + 2] for i in range(len(chars) - 1)}


def similarity(a: str, b: str) -> float:
    """字符 bigram 覆盖率（0~1）。用覆盖率而非 Jaccard：原话更长时不该被罚。"""
    ab, bb = _bigrams(a), _bigrams(b)
    if not ab or not bb:
        return 0.0
    return len(ab & bb) / len(ab)


def _strip_face_features(text: str, fallback: str = VISUAL_FALLBACK) -> str:
    """剔除含五官/面孔词的短语，但保留"特写"这类景别词。"""
    raw = str(text or "").strip()
    if not raw:
        return fallback
    kept = []
    for phrase in _PHRASE_SPLIT.split(raw):
        phrase = phrase.strip()
        if not phrase:
            continue
        lowered = phrase.lower()
        if any(word in lowered for word in FACE_FEATURE_WORDS):
            continue
        kept.append(phrase)
    result = "，".join(kept)[:VISUAL_MAX_LEN].strip("，")
    return result or fallback


def sanitize_visual_prompt(text: str, fallback: str = VISUAL_FALLBACK) -> str:
    """剔除含人脸类词的短语；剔空则用兜底。

    逐短语剔除而不是整条丢弃：模型常常只在一处顺手写了"脸上带着笑"，
    整条扔掉会白费掉其余很好的场景描述。
    """
    raw = str(text or "").strip()
    if not raw:
        return fallback
    kept: list[str] = []
    for phrase in _PHRASE_SPLIT.split(raw):
        phrase = phrase.strip()
        if not phrase:
            continue
        lowered = phrase.lower()
        if any(word in lowered for word in FACE_BAN_WORDS):
            continue
        kept.append(phrase)
    result = "，".join(kept)[:VISUAL_MAX_LEN].strip("，")
    return result or fallback


def introduces_third_person(text: str, original: str) -> bool:
    """模型是否把老人改写成了第三人称。

    只在「老人原话里本来没有这个指代词」时才算违约——原话里说
    「跟他是在厂里认识的」，那个"他"指的是老伴，模型照用没问题。
    """
    return any(m in text and m not in original for m in THIRD_PERSON_MARKERS)


def pick_narration(candidate: str, original: str) -> tuple[str, str]:
    """选定旁白。返回 `(旁白, 来源)`，来源 ∈ {original, model, summary}。

    契约4「优先老人原话」在这里落地：模型把老人写成了第三人称、
    或者改写幅度过大（相似度低于阈值），就退回老人原话——
    宁可粗糙，不能失真。
    """
    original = (original or "").strip()
    text = str(candidate or "").strip()

    if not text:
        return (original or "")[:NARRATION_MAX_LEN], "original" if original else "summary"

    drifted = bool(original) and introduces_third_person(text, original)
    too_far = bool(original) and similarity(text, original) < NARRATION_MIN_SIMILARITY
    if drifted or too_far:
        if original:
            return original[:NARRATION_MAX_LEN], "original"
        return text[:NARRATION_MAX_LEN], "model"
    return text[:NARRATION_MAX_LEN], "model"


def build_scene_plan(stories: Sequence, total_seconds: int = DEFAULT_TOTAL_SECONDS) -> list[dict]:
    """纯函数：选出故事、排好序、分好时长。这是交由 LLM 展开的骨架。"""
    ordered = sorted(stories, key=story_sort_key)[:MAX_SCENES]
    durations = allocate_durations(len(ordered), total_seconds)
    plan: list[dict] = []
    for story, seconds in zip(ordered, durations):
        canonical, _ = era_lexicon.normalize_tags(getattr(story, "era_tags", None))
        plan.append({
            "story_id": getattr(story, "id", 0),
            "era": canonical[0] if canonical else "",
            "title": getattr(story, "title", "") or "",
            "display_time": (
                str(getattr(story, "time_value", "") or "")
                or (canonical[0] if canonical else "")
            ),
            "original": original_quote(story),
            "summary": getattr(story, "summary", "") or "",
            "place": getattr(story, "place", "") or "",
            "emotion_tone": getattr(story, "emotion_tone", "") or "",
            "duration_seconds": seconds,
        })
    return plan


# ---------------------------------------------------------------------------
# 六段交付物的装配（LLM 输出视为不可信）
# ---------------------------------------------------------------------------

def _str(value: Any, limit: int = 200) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _dict_list(value: Any) -> list[dict]:
    """只收 dict 元素，其他一律丢掉——模型偶尔会把字符串塞进数组。"""
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, dict)]


def _str_list(value: Any, limit: int = 200) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x).strip()[:limit] for x in value if str(x).strip()]


def build_script(data: dict, plan: list[dict]) -> list[dict]:
    """交付2：剧本。场次顺序按 plan，不采信模型给的排序。"""
    raw = _dict_list(data.get("script"))
    by_no = {int(x.get("scene_no", 0)): x for x in raw
             if str(x.get("scene_no", "")).isdigit()}
    out = []
    for index, item in enumerate(plan, 1):
        src = by_no.get(index, raw[index - 1] if index <= len(raw) else {})
        out.append({
            "scene_no": index,
            "story_id": item["story_id"],
            "time": _str(src.get("time"), 60) or item["display_time"],
            "place": _str(src.get("place"), 60) or item["place"],
            "characters": _str(src.get("characters"), 100),
            "action": _str(src.get("action"), 200),
            "dialogue": _str(src.get("dialogue"), 200),
            "narration": pick_narration(src.get("narration", ""), item["original"])[0],
        })
    return out

def build_shot_list(data: dict, plan: list[dict]) -> list[dict]:
    """交付3：分镜表。镜头号 / 秒数 / 归属场次全部由代码生成。

    一场可以拆多镜（"手伸向门锁"→"钥匙停住"→"抬头看门口"是三镜），
    所以镜头数不等于场次数。每场的秒数由 `split_duration` 整数拆给该场的
    各个镜头，**余数补给前几镜**，保证全片各镜秒数之和恒等于 `total_seconds`
    ——截图里那种"01/3秒 + 04/3秒"的表，秒数必须能对上全片时长。
    """
    raw = _dict_list(data.get("shot_list"))[:MAX_SHOTS]

    # 按 scene_no 归组；模型没给（或全给了非法值）就按顺序均摊到各场
    groups: list[list[dict]] = [[] for _ in plan]
    has_valid_no = any(
        str(x.get("scene_no", "")).isdigit()
        and 1 <= int(x["scene_no"]) <= len(plan) for x in raw
    )
    if has_valid_no:
        for x in raw:
            tag = str(x.get("scene_no", ""))
            if tag.isdigit() and 1 <= int(tag) <= len(plan):
                groups[int(tag) - 1].append(x)
    elif raw and plan:
        for i, x in enumerate(raw):
            groups[min(len(plan) - 1, i * len(plan) // len(raw))].append(x)

    out: list[dict] = []
    shot_no = 0
    for index, item in enumerate(plan, 1):
        # 该场一条都没给 → 兜一镜，宁可画面空也不要少一段
        group = groups[index - 1] or [{}]
        for src, seconds in zip(group, split_duration(item["duration_seconds"], len(group))):
            shot_no += 1
            out.append({
                "shot_no": shot_no,
                "scene_no": index,
                "story_id": item["story_id"],
                # 秒数取代码拆分的那份，模型写的秒数一律不用
                "duration_seconds": seconds,
                "shot_size": _str(src.get("shot_size"), 40),
                "visual": sanitize_visual_prompt(src.get("visual", "")),
                # 这两列是截图里的核心：这一镜给观众什么信息、怎么切
                "audience": _str(src.get("audience"), 120),
                "transition": _str(src.get("transition"), 120),
                "action": _str(src.get("action"), 120),
                "dialogue": _str(src.get("dialogue"), 120),
                "ambience": _str(src.get("ambience"), 120),
            })
    return out


def build_art_design(data: dict) -> dict:
    """交付4：美术设定。人物描述走"只禁五官不禁景别"的宽松剔除。"""
    raw = data.get("art_design") if isinstance(data.get("art_design"), dict) else {}
    characters = []
    for c in _dict_list(raw.get("characters"))[:MAX_SCENES]:
        characters.append({
            "name": _str(c.get("name"), 40),
            "age": _str(c.get("age"), 40),
            "hair": _str(c.get("hair"), 60),
            "costume": _str(c.get("costume"), 120),
            "traits": _strip_face_features(c.get("traits", ""), ""),
        })
    scenes = []
    for s in _dict_list(raw.get("scenes"))[:MAX_SCENES]:
        scenes.append({
            "name": _str(s.get("name"), 60),
            "description": sanitize_visual_prompt(s.get("description", "")),
        })
    props = []
    for p in _dict_list(raw.get("props"))[:MAX_SCENES]:
        props.append({
            "name": _str(p.get("name"), 60),
            "description": _str(p.get("description"), 120),
        })
    return {"characters": characters, "scenes": scenes, "props": props}


def build_video_prompts(data: dict, shots: list[dict], plan: list[dict]) -> list[dict]:
    """交付5：逐镜头提示词。**跟着分镜表走，一条不漏一条不多**。

    分镜表可以一场拆多镜，所以这里不能按场次出 4 条——必须与 `shot_list`
    的镜头号严格对齐，否则导演拿到的第 7 条提示词对不上第 7 镜。
    """
    raw = _dict_list(data.get("video_prompts"))
    by_no = {int(x.get("shot_no", 0)): x for x in raw
             if str(x.get("shot_no", "")).isdigit()}
    era_by_scene = {i + 1: p["era"] for i, p in enumerate(plan)}
    out = []
    for index, shot in enumerate(shots, 1):
        src = by_no.get(index, raw[index - 1] if index <= len(raw) else {})
        era = era_by_scene.get(shot["scene_no"], "")
        out.append({
            "shot_no": index,
            "prompt": _strip_face_features(
                src.get("prompt", ""),
                f"{era or '年代感'}的生活环境空镜，柔和自然光，暖黄色调，胶片质感，远景",
            ),
        })
    return out


def build_qa_notes(data: dict) -> dict:
    """交付6：待确认与改编说明。两种清单去重、限长。"""
    raw = data.get("qa_notes") if isinstance(data.get("qa_notes"), dict) else {}
    return {
        "uncertain": _str_list(raw.get("uncertain"))[:MAX_SCENES],
        "adapted": _str_list(raw.get("adapted"))[:MAX_SCENES],
    }


def _fallback_synopsis(plan: list[dict]) -> str:
    titles = "、".join(p["title"] for p in plan[:3] if p["title"])
    return f"一位老人讲起从前的事：{titles}。画面为示意，细节以老人说法为准。" if titles else ""


def assemble_package(
    data: Optional[dict],
    plan: list[dict],
    *,
    perspective: str = "first_person",
    llm_used: bool = False,
    requested_seconds: int = DEFAULT_TOTAL_SECONDS,
) -> dict:
    """把（可能没有、可能残缺的）LLM 输出与代码骨架合成为最终提示词包。

    六段交付物 + 旧字段一次性给全；任何一段缺失都有降级内容，
    前端拿到的永远是一个结构完整的包。
    """
    data = data if isinstance(data, dict) else {}
    raw_scenes = data.get("scenes") if isinstance(data.get("scenes"), list) else []

    # 按 story_id 对齐；对不上就按位置兜底，绝不因为模型乱序就丢段
    by_id: dict[Any, dict] = {}
    for item in raw_scenes:
        if isinstance(item, dict) and item.get("story_id") is not None:
            by_id.setdefault(item["story_id"], item)

    scenes: list[dict] = []
    for index, item in enumerate(plan):
        raw = by_id.get(item["story_id"])
        if raw is None and index < len(raw_scenes) and isinstance(raw_scenes[index], dict):
            raw = raw_scenes[index]
        raw = raw or {}

        narration, source = pick_narration(raw.get("narration", ""), item["original"])
        scenes.append({
            "index": index + 1,
            "story_id": item["story_id"],
            "era": item["era"],
            "title": item["title"],
            "display_time": item["display_time"],
            "place": item["place"],
            "emotion_tone": item["emotion_tone"],
            # 代码分配，不采信 LLM
            "duration_seconds": item["duration_seconds"],
            "narration": narration,
            # "original" 表示这句是老人原话，UI 可以标出来
            "narration_source": source,
            "visual_prompt": sanitize_visual_prompt(raw.get("visual_prompt", "")),
            # 出处由代码写死，不采信模型（免得编造来源）
            "source_evidence": item["original"] or item["summary"],
        })

    total = sum(s["duration_seconds"] for s in scenes)
    title = str(data.get("title") or "").strip()[:24]
    if not title:
        title = plan[0]["title"] if plan else "我的一段日子"
    pkg_perspective = str(data.get("perspective") or "").strip()
    if pkg_perspective not in ("first_person", "third_person"):
        pkg_perspective = perspective

    synopsis = _str(data.get("synopsis"), 400) or _fallback_synopsis(plan)
    # 先出分镜表，逐镜头提示词跟着它的镜头号走（一场可拆多镜）
    shot_list = build_shot_list(data, plan)

    return {
        # ------- 旧字段：前端播放器 / 复制按钮依赖，保持不变 -------
        "title": title,
        "perspective": pkg_perspective,
        "total_seconds": total,
        # 段数太少时会顶到 MAX_SCENE_SECONDS，实际总长可能短于请求值。
        # 两个数都留着，前端能如实显示，不假装凑够了 60 秒。
        "requested_seconds": requested_seconds,
        "disclaimer": _str(data.get("disclaimer"), 300) or DEFAULT_DISCLAIMER,
        "scenes": scenes,
        "render_engine": None,          # 契约6：不接任何生成服务
        "llm_used": llm_used,
        # ------- 新字段：用户要求的人设六段交付物 -------
        "synopsis": synopsis,
        "script": build_script(data, plan),
        "shot_list": shot_list,
        "art_design": build_art_design(data),
        "video_prompts": build_video_prompts(data, shot_list, plan),
        "qa_notes": build_qa_notes(data),
    }


# ---------------------------------------------------------------------------
# 编排器
# ---------------------------------------------------------------------------

class StoryboardBuilder:
    """一次 LLM 调用产出整个 prompt_package；不可用时线性降级。"""

    def __init__(self, client: Optional[QwenClient] = None) -> None:
        self.client = client or QwenClient()

    @property
    def is_configured(self) -> bool:
        return bool(getattr(self.client, "is_configured", False))

    def _user_message(self, plan: list[dict]) -> str:
        blocks = []
        for i, item in enumerate(plan, 1):
            blocks.append(
                f"【第 {i} 段】story_id={item['story_id']}"
                f"\n时代：{item['era'] or '未定位'}｜时间：{item['display_time'] or '不详'}"
                f"｜地点：{item['place'] or '不详'}｜情绪：{item['emotion_tone'] or '平淡'}"
                f"\n标题：{item['title'] or '（无）'}"
                f"\n老人原话：{item['original'] or item['summary'] or '（无）'}"
            )
        return (
            f"共 {len(plan)} 段，按【交付2】到【交付6】的顺序把每一段展开，"
            f"并给出逐镜头提示词。story_id 必须原样带回。\n"
            f"分镜表请把整条片子拆成 8-12 镜，每镜标 scene_no 说明它属于第几段，"
            f"不要写时长。\n\n"
            + "\n\n".join(blocks)
        )

    async def build(
        self, stories: Sequence, *, total_seconds: int = DEFAULT_TOTAL_SECONDS
    ) -> dict:
        """编排成 prompt_package。空输入返回空包（不抛错）。"""
        plan = build_scene_plan(stories, total_seconds)
        if not plan:
            return assemble_package(None, [], llm_used=False,
                                    requested_seconds=total_seconds)

        messages = [
            {"role": "system", "content": STORYBOARD_SYSTEM_PROMPT},
            {"role": "user", "content": self._user_message(plan)},
        ]
        try:
            raw = await self.client.chat(messages, temperature=0.7, max_tokens=4096)
        except LLMError as e:
            logger.warning("故事板编排调用失败，走线性降级: %s", e)
            return assemble_package(None, plan, llm_used=False,
                                    requested_seconds=total_seconds)

        data = parse_json_loose(raw)
        if data is None:
            logger.warning("故事板返回非 JSON，走线性降级。原文前 120 字：%s", raw[:120])
            return assemble_package(None, plan, llm_used=False,
                                    requested_seconds=total_seconds)

        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict):
            return assemble_package(None, plan, llm_used=False,
                                    requested_seconds=total_seconds)

        package = assemble_package(data, plan, llm_used=True,
                                   requested_seconds=total_seconds)
        banned = sum(
            1 for s in package["scenes"]
            if s["visual_prompt"] == VISUAL_FALLBACK
        )
        if banned:
            logger.info("故事板：%d 段画面提示因含人脸描述被剔除并兜底", banned)
        return package

"""短片草稿箱的对话式引导：小忆顺着老人说的话，接一句、推一句。

定位很窄：**只负责"小忆下一句说什么"**，不存故事、不改原文、不做总结。
故事存不存、存成什么样，仍然走 create_story 那条确定的路。

话术人设（用户提供的「陪聊」部分）：
- 像会聊天、懂捧场的晚辈：自然亲切的口语，跟着老人的节奏走；
- 夸到具体的地方——从老人讲出的细节里找回应，不用"真不容易"这类空洞套话；
- 用小问题推进：问先后、还原画面、留住有味道的原话；
- 让老人掌握方向：他跳到另一段就顺着聊；遗憾委屈先接住感受。

实现仍是「LLM 出话 + 硬校验 + 规则兜底」三段式。LLM 输出一律视为不可信：
- 长度 / 问号数 / 真问句 / 空洞套话 / 重复，任一不过退规则句；
- 转场邀请（offer）**只有老人先给出收尾信号才生效**，不采信模型单独判断——
  否则模型会在故事刚开头就催着"做成短片"，这正是要防的。

不设轮次上限：老人愿意讲就一直陪着讲，讲完自己点保存。任何时候点保存，
都按当前全部原话存下来。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional, Sequence

from app.json_utils import parse_json_loose
from app.llm import LLMError, QwenClient

logger = logging.getLogger(__name__)

# 单轮话术上限（两三句，口语）。原来是 40 字单句，现在放宽到能具体回应。
MAX_REPLY_LEN = 120

# 每轮最多一个问题：超出说明模型在"连珠炮提问"，老人接不住。
MAX_QUESTION_MARKS = 1

# 往前推的问句：轮流用，避免连着几轮都是"后来呢"。
PROGRESS_QUESTIONS = (
    "后来呢？",
    "再往后呢？",
    "那之后呢？",
    "接着又出了什么事？",
    "再往后就怎么样了？",
)

# 补细节的问句（只在故事停下来、或者老人主动回忆时用）
RULE_QUESTIONS = {
    "time": "这事是哪一年的事？",
    "place": "那地方在哪儿？",
    "people": "当时还有谁在？",
    "detail": "那会儿是怎么个情形？",
    "feeling": "那时候心里什么滋味？",
}

# 空洞套话：不分对象、放在谁身上都成立的句子，一律不要。
# 注意：这不禁止"夸到具体"——"您这手真巧，一件旧棉袄变出两双手套"是具体的，放行。
BANNED_CLICHES = ("听着就", "听起来", "真不容易", "真够呛", "太不容易", "真辛苦")

# 老人明显不想说这段时的转向句（不追问，不勉强）
AVOID_MARKERS = ("不记得", "记不清", "忘了", "不想说", "别问了", "没啥好说")
AVOID_REPLY = "那咱不聊这个。您年轻时最常去的是哪儿？"

# 沉重话题（有人离世、离别、病痛）：这时候催"后来又出了什么事"太伤人，
# 换成一句贴人的问法——不是套话，是真的在问他当时怎么过的。
HEAVY_MARKERS = ("去世", "过世", "走了", "没了", "不在了", "病重", "住院", "葬礼", "临走")
HEAVY_REPLIES = (
    "您后来去送他了吗？",
    "那段日子您是怎么过来的？",
    "后来您还常想起他吗？",
)

# 收尾信号：老人说这些，才允许发出"做成短片"的转场邀请。
# 这是硬门槛——模型说破天也不能越过它自己催收尾。
WRAP_MARKERS = (
    "就这些", "就这些了", "说完了", "讲完了", "差不多了",
    "先这样", "今天就说到这儿", "暂时想不起来了", "想不起别的了", "没别的了",
)

# 转场邀请（第二节）：一句话复述重点 + 问一句愿不愿意做成短剧。
WRAP_REPLY = "这段我听明白了，想帮您留住。您愿意把它做成一段小短剧吗？"

SYSTEM_PROMPT = """你是「小忆」，陪老人聊往事的晚辈。老人正在讲自己的一段经历，
你要像坐在旁边听故事一样接话，让他愿意一直往下讲。

【怎么接话】
- 像一个会聊天、懂捧场的晚辈：用自然、亲切的口语，跟着老人说话的节奏走。
- 每轮**两三句话，通常只问一个问题**。顺着老人刚提到的人、物件、动作
  或一句话往下聊。他说得起劲时，只接一句「后来呢？您接着说。」也行。
- **夸到具体的地方，可以带点俏皮**：从他讲出的经历里挑一件值得回应的事。
  比如他说「旧棉袄拆了给两个孩子各缝一双手套」，就接「您这手真巧，
  一件旧棉袄还能变出两双手套。孩子们戴上以后跟您说什么了？」
- 他讲遗憾或委屈，先接住那份感受，再留余地——让他能继续讲、换话题或歇一歇。
- **用小问题推进**：想弄清先后问「那之后您先去了哪儿？」；
  想还原画面问「您推开门，先看见了什么？」；
  想留住有味道的台词问「他说的哪句话，您到现在还记得？」

【规则】
- 禁止空洞套话：「听着就……」「听起来……」「真不容易」「真够呛」这类
  放在谁身上都成立的句子不要。要夸就夸具体那件事。
- 共情只依据他说过的话，不要自己猜季节、天气、身体感受，
  也别替他补出没说过的场景。
- 遇到模糊的年份、地名或方言，**优先沿用老人的说法**；只有细节
  影响理解时，才用一句话确认。
- 他跳到另一段回忆，先顺着聊，别硬拽回来。
- 他回避（"不记得了""不想说"），轻轻转个方向，别硬问。
- 碰到有人去世、生重病、离别，别催"后来又出了什么事"。
  换一句贴人的问法：「您后来去送他了吗？」「那段日子您是怎么过来的？」
  不讲道理，也不劝他"想开点"。
- 没有轮次限制：他愿意讲就一直陪着讲，不要说"差不多了""要不要保存"。

【转场——只有他说完才做】
只有当老人明确表示这段讲完了（"就这些""说完了""先这样"之类），
才用一句话复述你听到的重点，再问：
「这段我想帮您留住。您愿意把它做成一段小短剧吗？」
他说"行/好"就交给创作环节；他还想聊，就继续陪聊。
**他没说收尾，绝对不要主动提做成短剧。**

【输出】只输出一个 JSON 对象，不要输出其他任何文字
{{"reply": "自然的一到三句话，最多一个问号", "move": "progress|detail|feeling|wrap",
  "offer": false}}

`offer` 只有在老人明确说了收尾时才为 true；其余情况一律 false。"""


def _norm(text: str) -> str:
    """比对重复用：去掉标点空白。"""
    return re.sub(r"[\s，。、！？,.!?…~～\"'“”‘’]", "", text or "")


def _user_text(turns: Sequence[dict]) -> str:
    return "\n".join(
        str(t.get("content") or "") for t in turns if t.get("role") == "user"
    )


def _last_user_text(turns: Sequence[dict]) -> str:
    for t in reversed(list(turns)):
        if t.get("role") == "user":
            return str(t.get("content") or "")
    return ""


def _asked(turns: Sequence[dict]) -> list[str]:
    return [str(t.get("content") or "") for t in turns if t.get("role") == "assistant"]


def wants_to_wrap(turns: Sequence[dict]) -> bool:
    """老人是否已经表示这段讲完了。转场邀请的唯一硬门槛。"""
    return any(m in _last_user_text(turns) for m in WRAP_MARKERS)


def rule_reply(turns: Sequence[dict]) -> dict[str, Any]:
    """规则兜底：永远能给出下一句。LLM 不可用时也能接住话。"""
    asked = _asked(turns)
    asked_norm = {_norm(a) for a in asked}
    last_user = _last_user_text(turns)

    # 收尾：规则句也遵守"只有老人说完才转场"的门槛
    if wants_to_wrap(turns):
        return {"question": WRAP_REPLY, "focus": "wrap", "done": False,
                "offer": True, "source": "rule"}

    if any(m in last_user for m in AVOID_MARKERS):
        return {"question": AVOID_REPLY, "focus": "progress",
                "done": False, "offer": False, "source": "rule"}

    # 沉重话题优先：这时候"后来又出了什么事"会显得冷漠
    if any(m in last_user for m in HEAVY_MARKERS):
        for q in HEAVY_REPLIES:
            if _norm(q) not in asked_norm:
                return {"question": q, "focus": "feeling",
                        "done": False, "offer": False, "source": "rule"}

    # 推进优先：前两轮直接往前推，之后按"推进 / 补细节"交替
    round_no = len(asked)
    question = ""
    if round_no < 2:
        for q in PROGRESS_QUESTIONS:
            if _norm(q) not in asked_norm:
                question = q
                break
    if not question:
        candidates = (
            list(PROGRESS_QUESTIONS[round_no % len(PROGRESS_QUESTIONS):])
            + list(PROGRESS_QUESTIONS[: round_no % len(PROGRESS_QUESTIONS)])
            + [RULE_QUESTIONS[k] for k in ("people", "place", "detail", "feeling", "time")]
        )
        for q in candidates:
            if _norm(q) not in asked_norm:
                question = q
                break
    if not question:
        question = "后来又想到什么了？"

    return {"question": question, "focus": "progress", "done": False,
            "offer": False, "source": "rule"}


def _transcript(turns: Sequence[dict]) -> str:
    lines = []
    for t in turns:
        who = "老人" if t.get("role") == "user" else "小忆"
        lines.append(f"{who}：{str(t.get('content') or '').strip()}")
    return "\n".join(lines)


# 问句特征词：模型常把一句感叹硬加问号（"那真够早的？"），那种句子接不住话。
_QUESTION_MARKERS = (
    "呢", "吗", "什么", "怎么", "咋", "哪", "谁", "几", "多少", "为什么", "如何", "是不是", "有没有",
)


def _question_marks(q: str) -> int:
    return q.count("？") + q.count("?")


def _looks_like_question(q: str) -> bool:
    """结尾是问号，且带疑问词——否则就是陈述句硬加问号。"""
    if not q.endswith(("？", "?")):
        return False
    return any(m in q for m in _QUESTION_MARKERS)


def _tail(q: str) -> str:
    """取一句话里的问句部分（"您这手真巧。后来呢？" → "后来呢？"）。"""
    return q.split("。")[-1]


def _vary_progress(q: str, asked: Sequence[str]) -> str:
    """上一句已经问过"后来呢？"时换一种说法，别让老人听着像复读机。"""
    prev_tails = {_norm(_tail(a)) for a in asked}
    if _norm(_tail(q)) not in prev_tails:
        return q
    for cand in PROGRESS_QUESTIONS:
        if _norm(cand) not in prev_tails:
            head = q[: q.rfind("。") + 1] if "。" in q else ""
            varied = f"{head}{cand}"
            return varied if len(varied) <= MAX_REPLY_LEN else cand
    return q


def _clean_reply(raw: Any, asked: Sequence[str] = ()) -> Optional[str]:
    """校验模型给的话：短、口语、最多一个真问句、不是空洞套话、不复述。

    命中套话时先尝试砍掉套话那半句保留后面的具体回应；
    砍不出来就判不合格，退规则句。
    """
    if not isinstance(raw, str):
        return None
    q = raw.strip().strip("「」\"'“”")
    q = re.sub(r"\s+", "", q)
    if not q or "\n" in q:
        return None
    if len(q) > MAX_REPLY_LEN:
        return None
    if _question_marks(q) > MAX_QUESTION_MARKS:
        return None
    # 有问号时，问号所在的那一句必须是真问句（堵住"那真够早的？"）
    if _question_marks(q) == 1 and not _looks_like_question(_tail(q)):
        return None
    for w in BANNED_CLICHES:
        if w in q:
            tail = q.split("。", 1)[1] if "。" in q else ""
            if tail and (_question_marks(tail) == 0 or _looks_like_question(tail)):
                q = tail
            else:
                return None
            break
    return _vary_progress(q, asked)


async def next_reply(
    turns: Sequence[dict], *, client: Optional[Any] = None
) -> dict[str, Any]:
    """给出小忆的下一句话。

    返回 `{question, focus, done, offer, source}`；`question` 字段名保持不变，
    前端当"小忆说的话"用。`done` 恒为 False——这条链路不自动收尾。
    `offer` 是转场邀请标记，只有老人先给出收尾信号才可能为 True。
    """
    turns = list(turns)
    asked_norm = {_norm(a) for a in _asked(turns)}

    llm = client or QwenClient()
    last_user = _last_user_text(turns)
    wrapped = wants_to_wrap(turns)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "这是到目前为止的对话：\n"
                f"{_transcript(turns)}\n\n"
                f"老人刚说的是：{last_user}\n"
                + ("他已经表示这段讲完了。\n" if wrapped else "他还在讲，没有收尾。\n")
                + "\n请先接住他说的话，再自然往下聊。"
                + ("他用了收尾的话，按【转场】那段做。\n" if wrapped else "不要提做成短剧。\n")
            ),
        },
    ]
    try:
        raw = await llm.chat(
            messages,
            model=getattr(llm, "analysis_model", None) or None,
            temperature=0.7,
            max_tokens=320,
        )
        data = parse_json_loose(raw)
        if isinstance(data, dict):
            q = _clean_reply(data.get("reply") or data.get("question"), _asked(turns))
            # offer 由规则复核：模型说 true 但老人没收尾，一律压回 false
            offer = wrapped and bool(data.get("offer"))
            if q and _norm(q) not in asked_norm:
                return {"question": q, "focus": "wrap" if offer else "detail",
                        "done": False, "offer": offer, "source": "llm"}
        q = _clean_reply(raw, _asked(turns))
        if q and _norm(q) not in asked_norm:
            return {"question": q, "focus": "detail", "done": False,
                    "offer": False, "source": "llm"}

        logger.info("追问输出不合格，退规则句 raw=%s", str(raw)[:120])
    except LLMError as e:
        logger.warning("追问调用失败，退规则句：%s", e)
    except Exception as e:  # noqa: BLE001 - 兜底不能把接口打挂
        logger.warning("追问异常，退规则句：%s", e)

    return rule_reply(turns)


# 兼容旧调用名（接口层已改为 next_reply）
next_question = next_reply

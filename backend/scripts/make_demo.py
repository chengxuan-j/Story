"""离线演示：把一段真实对话跑完整条创作链路，产出可看的成稿。

不调任何外部 API，也不依赖 MySQL：
- 对话与 4 段往事读 `data/demo/conversation.json`
- 创作输出读 `data/demo/llm_output.json`（模拟 LLM 返回，含刻意留的脏数据）
- 走的是线上同一套 `build_scene_plan` + `assemble_package`，
  所以"时长一致 / 人脸剔除 / 镜头号对齐 / 降级兜底"这些约束是真的在跑，不是写死的样例

用法：
    cd backend && python scripts/make_demo.py
产物：
    docs/demo/一双手套-成稿.md
    docs/demo/一双手套-分镜表.html
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import storyboard as sb  # noqa: E402

DATA = BACKEND_DIR / "data" / "demo"
OUT = BACKEND_DIR.parent / "docs" / "demo"


def load(name: str) -> dict:
    with open(DATA / name, "r", encoding="utf-8") as f:
        return json.load(f)


def as_story(raw: dict) -> SimpleNamespace:
    """把 JSON 里的一段往事变成编排器认识的 story 对象（字段与 DB 行同名）。"""
    return SimpleNamespace(
        id=raw["id"],
        title=raw.get("title", ""),
        era_tags=raw.get("era_tags") or [],
        time_value=raw.get("time_value", ""),
        place=raw.get("place", ""),
        emotion_tone=raw.get("emotion_tone", ""),
        summary=raw.get("summary", ""),
        raw_dialogue=raw.get("raw_dialogue") or [],
    )


def money(n: int) -> str:
    return f"{n:02d}"


def to_markdown(conv: dict, pkg: dict) -> str:
    lines: list[str] = []
    add = lines.append

    add(f"# {pkg['title']}")
    add("")
    add(pkg["synopsis"])
    add("")
    add(f"**全片约 {pkg['total_seconds']} 秒 · {len(pkg['shot_list'])} 个镜头 · "
        f"{len(pkg['script'])} 场**")
    add("")
    add("---")
    add("")

    add("## 一、对话记录（这段故事是怎么聊出来的）")
    add("")
    for turn in conv["turns"]:
        who = "小忆" if turn["role"] == "assistant" else "老人"
        add(f"**{who}**：{turn['content']}")
        add("")

    add("---")
    add("")
    add("## 二、片名与故事简介")
    add("")
    add(f"**{pkg['title']}**")
    add("")
    add(pkg["synopsis"])
    add("")

    add("## 三、短剧剧本")
    add("")
    for sc in pkg["script"]:
        add(f"### 第 {sc['scene_no']} 场　{sc['time']}｜{sc['place']}")
        add("")
        if sc["characters"]:
            add(f"- 出场人物：{sc['characters']}")
        if sc["action"]:
            add(f"- 可见动作：{sc['action']}")
        if sc["dialogue"]:
            add(f"- 对白：{sc['dialogue']}")
        if sc["narration"]:
            add(f"- 旁白（第一人称）：{sc['narration']}")
        add("")

    add("## 四、分镜表")
    add("")
    add("| 镜号 / 成片时长 | 画面 | 观众看什么、知道什么 | 怎么切 |")
    add("| --- | --- | --- | --- |")
    for s in pkg["shot_list"]:
        size = f"{s['shot_size']}。" if s["shot_size"] else ""
        visual = f"{size}{s['visual']}"
        if s["dialogue"]:
            visual += f"（{s['dialogue']}）"
        if s["ambience"]:
            visual += f"<br>环境声：{s['ambience']}"
        add(f"| {money(s['shot_no'])} / {s['duration_seconds']} 秒 | {visual} "
            f"| {s['audience'] or '—'} | {s['transition'] or '—'} |")
    add("")
    add(f"合计：{sum(s['duration_seconds'] for s in pkg['shot_list'])} 秒，"
        f"与全片 {pkg['total_seconds']} 秒一致（秒数由代码分配，不采信模型）。")
    add("")

    add("## 五、人物与场景美术设定")
    add("")
    add("### 人物")
    add("")
    for c in pkg["art_design"]["characters"]:
        bits = [b for b in [c["age"], c["hair"], c["costume"], c["traits"]] if b]
        add(f"- **{c['name']}**：{'；'.join(bits)}")
    add("")
    add("### 场景")
    add("")
    for s in pkg["art_design"]["scenes"]:
        add(f"- **{s['name']}**：{s['description']}")
    add("")
    add("### 道具")
    add("")
    for p in pkg["art_design"]["props"]:
        add(f"- **{p['name']}**：{p['description']}")
    add("")

    add("## 六、逐镜头视频生成提示词")
    add("")
    for v in pkg["video_prompts"]:
        add(f"{money(v['shot_no'])}. {v['prompt']}")
    add("")

    add("## 七、待确认与改编说明")
    add("")
    add("**需要跟老人确认的**")
    add("")
    for x in pkg["qa_notes"]["uncertain"]:
        add(f"- {x}")
    add("")
    add("**为拍摄补写的内容（改编）**")
    add("")
    for x in pkg["qa_notes"]["adapted"]:
        add(f"- {x}")
    add("")
    add("---")
    add("")
    add(pkg["disclaimer"])
    add("")
    return "\n".join(lines)


def to_html(conv: dict, pkg: dict) -> str:
    rows = []
    for s in pkg["shot_list"]:
        size = f'<span class="size">{s["shot_size"]}</span>' if s["shot_size"] else ""
        amb = f'<div class="amb">环境声：{s["ambience"]}</div>' if s["ambience"] else ""
        dlg = f'<div class="dlg">「{s["dialogue"]}」</div>' if s["dialogue"] else ""
        rows.append(
            "<tr>"
            f'<td class="no">拍 {money(s["shot_no"])}<span class="dur">/ {s["duration_seconds"]} 秒</span></td>'
            f'<td class="vis">{size}{s["visual"]}{dlg}{amb}</td>'
            f'<td>{s["audience"] or "—"}</td>'
            f'<td>{s["transition"] or "—"}</td>'
            "</tr>"
        )

    scenes_html = []
    for sc in pkg["script"]:
        meta = "｜".join(x for x in [sc["time"], sc["place"]] if x)
        body = []
        if sc["characters"]:
            body.append(f'<p><span>出场人物</span>{sc["characters"]}</p>')
        if sc["action"]:
            body.append(f'<p><span>可见动作</span>{sc["action"]}</p>')
        if sc["dialogue"]:
            body.append(f'<p><span>对白</span>{sc["dialogue"]}</p>')
        if sc["narration"]:
            body.append(f'<p><span>旁白</span>{sc["narration"]}</p>')
        scenes_html.append(
            f'<div class="scene"><h3>第 {sc["scene_no"]} 场　{meta}</h3>{"".join(body)}</div>'
        )

    chars = "".join(
        f'<li><b>{c["name"]}</b>：{"；".join(x for x in [c["age"], c["hair"], c["costume"], c["traits"]] if x)}</li>'
        for c in pkg["art_design"]["characters"]
    )
    places = "".join(
        f'<li><b>{s["name"]}</b>：{s["description"]}</li>' for s in pkg["art_design"]["scenes"]
    )
    props = "".join(
        f'<li><b>{p["name"]}</b>：{p["description"]}</li>' for p in pkg["art_design"]["props"]
    )
    prompts = "".join(
        f'<li><b>{money(v["shot_no"])}</b>{v["prompt"]}</li>' for v in pkg["video_prompts"]
    )
    uncertain = "".join(f"<li>{x}</li>" for x in pkg["qa_notes"]["uncertain"]) or "<li>无</li>"
    adapted = "".join(f"<li>{x}</li>" for x in pkg["qa_notes"]["adapted"]) or "<li>无</li>"

    chat = "".join(
        f'<div class="turn {t["role"]}"><b>{"小忆" if t["role"] == "assistant" else "老人"}</b>'
        f'<p>{t["content"]}</p></div>'
        for t in conv["turns"]
    )

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{pkg["title"]} · 短剧创作稿</title>
<style>
  :root {{ --ink:#1c1b19; --muted:#6b675f; --line:#e3e0d8; --bg:#fbfaf7; --accent:#8a5a2b; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;
    line-height:1.65; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:48px 28px 72px; }}
  header {{ border-bottom:2px solid var(--ink); padding-bottom:20px; margin-bottom:34px; }}
  h1 {{ font-size:30px; margin:0 0 10px; letter-spacing:.02em; }}
  .syn {{ font-size:16px; color:#3d3a34; margin:0 0 8px; }}
  .meta {{ font-size:13px; color:var(--muted); }}
  h2 {{ font-size:19px; margin:44px 0 14px; padding-left:10px;
        border-left:4px solid var(--accent); }}
  h3 {{ font-size:15px; margin:20px 0 8px; color:#3d3a34; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; background:#fff; }}
  thead th {{ text-align:left; font-weight:600; padding:12px 10px; color:#3d3a34;
    border-bottom:1px solid var(--line); }}
  tbody td {{ padding:14px 10px; border-bottom:1px solid var(--line);
    vertical-align:top; color:#33302b; }}
  tbody tr:hover {{ background:#fdfcf9; }}
  td.no {{ white-space:nowrap; font-variant-numeric:tabular-nums; color:#33302b; width:96px; }}
  td.no .dur {{ display:block; color:var(--muted); font-size:12.5px; }}
  td.vis {{ width:300px; }}
  .size {{ display:inline-block; font-size:12px; color:var(--accent); margin-right:4px; }}
  .dlg {{ margin-top:6px; color:#5a5348; }}
  .amb {{ margin-top:4px; color:var(--muted); font-size:12.5px; }}
  .scene {{ background:#fff; border:1px solid var(--line); border-radius:8px;
    padding:14px 18px; margin-bottom:12px; }}
  .scene p {{ margin:4px 0; font-size:14px; }}
  .scene span {{ display:inline-block; min-width:64px; color:var(--muted); font-size:12.5px; }}
  ul {{ padding-left:20px; font-size:14px; }}
  li {{ margin:5px 0; }}
  ol.prompts {{ padding-left:22px; font-size:13.5px; }}
  ol.prompts li {{ margin:7px 0; color:#33302b; }}
  ol.prompts b {{ color:var(--accent); margin-right:8px; font-variant-numeric:tabular-nums; }}
  .chat {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px 18px; }}
  .turn {{ display:flex; gap:10px; padding:6px 0; }}
  .turn b {{ flex:0 0 34px; font-size:13px; color:var(--muted); }}
  .turn p {{ margin:0; font-size:14px; }}
  .turn.user p {{ color:#1c1b19; }}
  .note {{ font-size:12.5px; color:var(--muted); margin-top:10px; }}
  footer {{ margin-top:48px; padding-top:16px; border-top:1px solid var(--line);
    font-size:12.5px; color:var(--muted); }}
</style></head>
<body><div class="wrap">
<header>
  <h1>{pkg["title"]}</h1>
  <p class="syn">{pkg["synopsis"]}</p>
  <p class="meta">全片约 {pkg["total_seconds"]} 秒 · {len(pkg["shot_list"])} 个镜头 · {len(pkg["script"])} 场
   · 第一人称旁白</p>
</header>

<h2>一、这段故事是怎么聊出来的</h2>
<div class="chat">{chat}</div>

<h2>二、短剧剧本</h2>
{"".join(scenes_html)}

<h2>三、分镜表</h2>
<table>
  <thead><tr><th>镜号 / 成片时长</th><th>画面</th><th>观众看什么、知道什么</th><th>怎么切</th></tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>
<p class="note">合计 {sum(s["duration_seconds"] for s in pkg["shot_list"])} 秒，
与全片 {pkg["total_seconds"]} 秒一致。秒数由代码分配、不采信模型写的数字。</p>

<h2>四、人物与场景美术设定</h2>
<h3>人物</h3><ul>{chars}</ul>
<h3>场景</h3><ul>{places}</ul>
<h3>道具</h3><ul>{props}</ul>

<h2>五、逐镜头视频生成提示词</h2>
<ol class="prompts">{prompts}</ol>

<h2>六、待确认与改编说明</h2>
<h3>需要跟老人确认的</h3><ul>{uncertain}</ul>
<h3>为拍摄补写的内容（改编）</h3><ul>{adapted}</ul>

<footer>{pkg["disclaimer"]}</footer>
</div></body></html>
"""


def main() -> int:
    conv = load("conversation.json")
    data = load("llm_output.json")

    stories = [as_story(s) for s in conv["stories"]]
    plan = sb.build_scene_plan(stories, total_seconds=60)
    pkg = sb.assemble_package(data, plan, llm_used=True, requested_seconds=60)

    shots = pkg["shot_list"]
    total = pkg["total_seconds"]

    # ---- 把后校验的效果当场断言出来，证明不是摆样子 ----
    assert sum(s["duration_seconds"] for s in shots) == total, "各镜秒数之和 ≠ 全片时长"
    assert all(s["duration_seconds"] >= sb.MIN_SHOT_SECONDS for s in shots), "出现短于 2 秒的废镜"
    assert len(pkg["video_prompts"]) == len(shots), "逐镜头提示词数量与分镜数不一致"
    assert [v["shot_no"] for v in pkg["video_prompts"]] == [s["shot_no"] for s in shots]
    assert pkg["render_engine"] is None, "render_engine 必须是 null（不生成视频）"
    assert pkg["disclaimer"], "免责声明不能为空"
    # 模型在 llm_output.json 里混入了"面部描述"和自带秒数 —— 必须已被拦掉
    leaked = [s["shot_no"] for s in shots if any(w in s["visual"] for w in ("脸", "面部", "面孔"))]
    assert not leaked, f"第 {leaked} 镜的人脸描述没剔干净"

    OUT.mkdir(parents=True, exist_ok=True)
    md_path = OUT / f"{pkg['title']}-成稿.md"
    html_path = OUT / f"{pkg['title']}-分镜表.html"
    md_path.write_text(to_markdown(conv, pkg), encoding="utf-8")
    html_path.write_text(to_html(conv, pkg), encoding="utf-8")

    print(f"场次 {len(pkg['script'])}｜镜头 {len(shots)}｜总时长 {total} 秒")
    print("各镜秒数：", [s["duration_seconds"] for s in shots])
    print("秒数合计：", sum(s["duration_seconds"] for s in shots))
    print("旁白来源：", [s["narration_source"] for s in pkg["scenes"]])
    print("写入：", md_path)
    print("写入：", html_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

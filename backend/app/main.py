"""Story 项目后端：对话记录故事 → 生成分镜提示词包。

单用户、无登录；数据存 MySQL（连接信息读系统环境变量）。API Key 从系统环境变量读取。
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app import era_lexicon, story_chat
from app.config import get_settings
from app.db import (
    compilation_to_dict,
    get_db,
    init_db,
    now_iso,
    story_to_dict,
    to_story_obj,
)
from app.llm import QwenClient
from app.speech import SpeechClient, SpeechError
from app.storyboard import StoryboardBuilder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("story")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    await init_db()
    logger.info("Story 后端就绪 mysql=%s:%s/%s key_configured=%s",
                s.mysql_host, s.mysql_port, s.mysql_database, bool(s.qwen_api_key))
    yield


app = FastAPI(title="Story - 故事短片工作台", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    s = get_settings()
    return {
        "status": "ok",
        "api_configured": bool(s.qwen_api_key),
        "model": s.qwen_model,
        "db": f"mysql://{s.mysql_host}:{s.mysql_port}/{s.mysql_database}",
    }


# ---------- 故事对话：小忆下一句 ----------

@app.post("/api/story/next")
async def story_next(body: dict):
    turns = body.get("turns") or []
    if not isinstance(turns, list):
        raise HTTPException(status_code=422, detail="turns 必须是数组")
    clean = [
        {"role": str(t.get("role", "")), "content": str(t.get("content", ""))}
        for t in turns if isinstance(t, dict)
    ]
    return await story_chat.next_reply(clean)


# ---------- 故事：保存 / 列表 / 删除 ----------

@app.post("/api/stories")
async def create_story(body: dict):
    content = str(body.get("content", "")).strip()
    if len(content) < 2:
        raise HTTPException(status_code=422, detail="故事至少需要 2 个字")
    first_line = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")
    title = str(body.get("title", "")).strip() or (
        first_line[:20] + ("…" if len(first_line) > 20 else "")
    )
    input_type = "voice" if body.get("input_type") == "voice" else "text"

    turns = body.get("turns") or []
    if isinstance(turns, list) and turns:
        raw = [
            {"role": str(t.get("role", "")), "content": str(t.get("content", ""))}
            for t in turns if isinstance(t, dict) and str(t.get("content", "")).strip()
        ]
    else:
        raw = [{"role": "user", "content": content}]
    if raw:
        raw[0]["input_type"] = input_type

    async with get_db() as (conn, cur):
        await cur.execute(
            "INSERT INTO stories (title, summary, raw_dialogue, input_type, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (title, content, json.dumps(raw, ensure_ascii=False), input_type, now_iso()),
        )
        new_id = cur.lastrowid
        await cur.execute("SELECT * FROM stories WHERE id=%s", (new_id,))
        row = await cur.fetchone()
    return story_to_dict(row)


@app.get("/api/stories")
async def list_stories():
    async with get_db() as (conn, cur):
        await cur.execute("SELECT * FROM stories ORDER BY id DESC")
        rows = await cur.fetchall()
    return [story_to_dict(r) for r in rows]


@app.delete("/api/stories/{story_id}")
async def delete_story(story_id: int):
    async with get_db() as (conn, cur):
        await cur.execute("SELECT id, story_ids FROM compilations")
        comps = await cur.fetchall()
        deleted_comps = 0
        for c in comps:
            try:
                ids = json.loads(c["story_ids"] or "[]")
            except (TypeError, json.JSONDecodeError):
                ids = []
            if story_id in ids:
                await cur.execute("DELETE FROM compilations WHERE id=%s", (c["id"],))
                deleted_comps += 1
        await cur.execute("DELETE FROM stories WHERE id=%s", (story_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="故事不存在")
    return {"deleted": True, "id": story_id, "deleted_compilations": deleted_comps}


# ---------- 分镜短片：生成 / 列表 / 详情 / 删除 ----------

@app.post("/api/compilations")
async def create_compilation(body: dict):
    """把已保存的故事排成一条短片故事板（状态止于 prompt_ready）。"""
    async with get_db() as (conn, cur):
        await cur.execute("SELECT id FROM stories ORDER BY id")
        all_ids = [r["id"] for r in await cur.fetchall()]
        wanted = body.get("story_ids")
        ids = [int(x) for x in wanted] if isinstance(wanted, list) and wanted else all_ids
        ids = [i for i in ids if i in all_ids]
        if not ids:
            raise HTTPException(status_code=409, detail="还没有故事，先保存一段再来做短片")
        placeholders = ",".join(["%s"] * len(ids))
        await cur.execute(
            f"SELECT * FROM stories WHERE id IN ({placeholders})", ids
        )
        stories = [to_story_obj(r) for r in await cur.fetchall()]

        total_seconds = body.get("total_seconds")
        try:
            total_seconds = int(total_seconds) if total_seconds else get_settings().storyboard_seconds
        except (TypeError, ValueError):
            total_seconds = get_settings().storyboard_seconds
        total_seconds = min(total_seconds, get_settings().storyboard_seconds * 3)

        perspective = str(body.get("perspective", "first_person"))
        title = str(body.get("title", "")).strip() or "我的一段日子"

        await cur.execute(
            "INSERT INTO compilations (title, perspective, status, story_ids, prompt_package, created_at) "
            "VALUES (%s, %s, 'queued', %s, NULL, %s)",
            (title, perspective, json.dumps(ids), now_iso()),
        )
        comp_id = cur.lastrowid

    builder = StoryboardBuilder()
    package = await builder.build(stories, total_seconds=total_seconds)

    async with get_db() as (conn, cur):
        await cur.execute(
            "UPDATE compilations SET status='prompt_ready', prompt_package=%s WHERE id=%s",
            (json.dumps(package, ensure_ascii=False), comp_id),
        )
        await cur.execute("SELECT * FROM compilations WHERE id=%s", (comp_id,))
        row = await cur.fetchone()
    logger.info("分镜生成完成 comp=%s 段数=%d llm=%s",
                comp_id, len(package.get("scenes", [])), package.get("llm_used"))
    return compilation_to_dict(row)


@app.get("/api/compilations")
async def list_compilations():
    async with get_db() as (conn, cur):
        await cur.execute("SELECT * FROM compilations ORDER BY id DESC")
        rows = await cur.fetchall()
    return [compilation_to_dict(r) for r in rows]


@app.get("/api/compilations/{comp_id}")
async def get_compilation(comp_id: int):
    async with get_db() as (conn, cur):
        await cur.execute("SELECT * FROM compilations WHERE id=%s", (comp_id,))
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="短片不存在")
    return compilation_to_dict(row)


@app.delete("/api/compilations/{comp_id}")
async def delete_compilation(comp_id: int):
    async with get_db() as (conn, cur):
        await cur.execute("DELETE FROM compilations WHERE id=%s", (comp_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="短片不存在")
    return {"deleted": True, "id": comp_id}


# ---------- 语音：ASR 转写 / TTS 旁白 ----------

@app.post("/api/speech/transcribe")
async def transcribe(file: UploadFile = File(...)):
    data = await file.read()
    client = SpeechClient()
    try:
        text = await client.transcribe(data, file.filename or "audio.webm")
    except SpeechError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"text": text}


@app.post("/api/speech/tts")
async def tts(body: dict):
    text = str(body.get("text", ""))
    client = SpeechClient()
    try:
        url = await client.synthesize(text)
    except SpeechError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"audio_url": url}

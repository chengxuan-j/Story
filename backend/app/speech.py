"""DashScope 语音服务（从原项目精简）：ASR 上传→提交→轮询，TTS 一步返回 URL。

API Key 从系统环境变量 DASHSCOPE_API_KEY 读取，直连 DashScope（trust_env=False）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

TTS_ENDPOINT = "/api/v1/services/audio/tts/SpeechSynthesizer"
ASR_ENDPOINT = "/api/v1/services/audio/asr/transcription"
UPLOAD_ENDPOINT = "/api/v1/uploads"
TASKS_ENDPOINT = "/api/v1/tasks"

ASR_PENDING = "PENDING"
ASR_RUNNING = "RUNNING"
ASR_SUCCEEDED = "SUCCEEDED"
ASR_FAILED = "FAILED"
ASR_CANCELED = "CANCELED"
ASR_NO_VALID_FRAGMENT = "SUCCESS_WITH_NO_VALID_FRAGMENT"


class SpeechError(Exception):
    pass


class SpeechClient:
    def __init__(self) -> None:
        s = get_settings()
        self.api_key = s.qwen_api_key
        self.timeout = s.request_timeout
        self.speech_base = "https://dashscope.aliyuncs.com"
        self.asr_model = s.asr_model
        self.tts_model = s.tts_model
        self.tts_voice = s.tts_voice
        self._http: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=self.timeout, trust_env=False)
        return self._http

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h = {"Authorization": f"Bearer {self.api_key}"}
        if extra:
            h.update(extra)
        return h

    # ---------------- TTS ----------------

    async def synthesize(self, text: str) -> str:
        """文字转语音，返回音频 URL（24h 有效）。"""
        if not self.api_key:
            raise SpeechError("未配置 DASHSCOPE_API_KEY 系统环境变量。")
        if not text or not text.strip():
            raise SpeechError("旁白为空，无法合成语音。")
        payload = {
            "model": self.tts_model,
            "input": {"text": text, "voice": self.tts_voice, "format": "mp3"},
        }
        try:
            resp = await self._client().post(
                f"{self.speech_base}{TTS_ENDPOINT}",
                json=payload,
                headers=self._headers(),
            )
        except httpx.HTTPError as e:
            raise SpeechError(f"TTS 网络错误: {e}") from e
        if resp.status_code != 200:
            raise SpeechError(f"TTS 返回 HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()["output"]["audio"]["url"]
        except (json.JSONDecodeError, KeyError) as e:
            raise SpeechError(f"TTS 响应结构异常: {resp.text[:200]}") from e

    # ---------------- ASR ----------------

    async def _upload_audio(self, audio_bytes: bytes, filename: str) -> str:
        suffix = os.path.splitext(filename or "")[1].lower()
        if suffix not in (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"):
            suffix = ".wav"
        mime = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
                ".flac": "audio/flac", ".ogg": "audio/ogg",
                ".opus": "audio/ogg"}.get(suffix, "audio/wav")

        client = self._client()
        r = await client.get(
            f"{self.speech_base}{UPLOAD_ENDPOINT}",
            headers=self._headers(),
            params={"action": "getPolicy", "model": self.asr_model},
        )
        if r.status_code != 200:
            raise SpeechError(f"取上传策略失败: HTTP {r.status_code} {r.text[:200]}")
        policy = r.json()["data"]

        key = f"{policy['upload_dir']}/{uuid.uuid4().hex}{suffix}"
        files = {
            "OSSAccessKeyId": (None, policy["oss_access_key_id"]),
            "Signature": (None, policy["signature"]),
            "policy": (None, policy["policy"]),
            "x-oss-object-acl": (None, policy["x_oss_object_acl"]),
            "x-oss-forbid-overwrite": (None, policy["x_oss_forbid_overwrite"]),
            "key": (None, key),
            "success_action_status": (None, "200"),
            "file": (f"audio{suffix}", audio_bytes, mime),
        }
        up = await client.post(policy["upload_host"], files=files)
        if up.status_code != 200:
            raise SpeechError(f"上传音频失败: HTTP {up.status_code} {up.text[:200]}")
        return f"oss://{key}"

    async def _submit_transcription(self, oss_url: str) -> str:
        payload: Dict[str, Any] = {
            "model": self.asr_model,
            "input": {"file_urls": [oss_url]},
            "parameters": {"language_hints": ["zh"]},
        }
        r = await self._client().post(
            f"{self.speech_base}{ASR_ENDPOINT}",
            json=payload,
            headers=self._headers({
                "X-DashScope-Async": "enable",
                "X-DashScope-OssResourceResolve": "enable",
            }),
        )
        if r.status_code != 200:
            raise SpeechError(f"提交转写失败: HTTP {r.status_code} {r.text[:200]}")
        return r.json()["output"]["task_id"]

    async def _fetch_result(self, task_id: str) -> Dict[str, Any]:
        r = await self._client().get(
            f"{self.speech_base}{TASKS_ENDPOINT}/{task_id}",
            headers=self._headers({"X-DashScope-Async": "enable"}),
        )
        if r.status_code != 200:
            raise SpeechError(f"查询转写任务失败: HTTP {r.status_code}")
        out = r.json().get("output", {})
        status = out.get("task_status", ASR_PENDING)
        if status == ASR_SUCCEEDED:
            try:
                trans_url = out["results"][0]["transcription_url"]
                tr = await self._client().get(trans_url)
                texts = [t["text"] for t in tr.json().get("transcripts", [])]
                return {"status": status, "text": "".join(texts).strip(), "error": None}
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                return {"status": ASR_FAILED, "text": None, "error": f"解析结果失败: {e}"}
        if status in (ASR_FAILED, ASR_CANCELED):
            code = out.get("code", "")
            msg = ("未识别到有效语音（录音可能静音或太短）"
                   if code == ASR_NO_VALID_FRAGMENT else f"转写失败: code={code}")
            return {"status": status, "text": None, "error": msg}
        return {"status": status, "text": None, "error": None}

    async def transcribe(self, audio_bytes: bytes,
                         filename: str = "audio.wav") -> str:
        """音频转文字（上传 → 提交 → 轮询）。"""
        if not self.api_key:
            raise SpeechError("未配置 DASHSCOPE_API_KEY 系统环境变量。")
        if len(audio_bytes) < 1024:
            raise SpeechError("录音太短（<1KB），可能没录到声音。")
        logger.info("ASR 收到音频: %d 字节, filename=%s", len(audio_bytes), filename)
        oss_url = await self._upload_audio(audio_bytes, filename)
        task_id = await self._submit_transcription(oss_url)
        deadline = asyncio.get_event_loop().time() + self.timeout
        while asyncio.get_event_loop().time() < deadline:
            res = await self._fetch_result(task_id)
            if res["status"] == ASR_SUCCEEDED:
                return res["text"] or ""
            if res["status"] in (ASR_FAILED, ASR_CANCELED):
                raise SpeechError(res["error"] or "转写任务失败")
            await asyncio.sleep(1.0)
        raise SpeechError(f"转写任务超时（>{self.timeout}s）")

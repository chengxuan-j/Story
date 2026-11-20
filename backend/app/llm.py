"""Qwen API 封装（从原项目精简）：OpenAI 兼容端点，直连优先，带连接池与参数重试。

API Key 从系统环境变量 DASHSCOPE_API_KEY 读取，日志中绝不输出。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用相关错误。"""


class QwenClient:
    def __init__(self) -> None:
        s = get_settings()
        self.api_key = s.qwen_api_key
        self.base_url = s.qwen_base_url
        self.model = s.qwen_model
        self.analysis_model = s.qwen_analysis_model
        self.timeout = s.request_timeout
        self._clients: Dict[bool, httpx.AsyncClient] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _client(self, trust_env: bool) -> httpx.AsyncClient:
        c = self._clients.get(trust_env)
        if c is None or c.is_closed:
            c = httpx.AsyncClient(timeout=self.timeout, trust_env=trust_env)
            self._clients[trust_env] = c
        return c

    async def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        if not self.api_key:
            raise LLMError("未配置 DASHSCOPE_API_KEY 系统环境变量。")

        payload: Dict[str, Any] = {
            "model": kwargs.get("model") or self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.8),
        }
        if "max_tokens" in kwargs:
            payload["max_tokens"] = kwargs["max_tokens"]

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        logger.info("Qwen 请求 model=%s messages=%d", payload["model"], len(messages))
        try:
            client = self._client(trust_env=False)
            resp = await client.post(url, json=payload, headers=headers)
            # 兼容个别模型不接受某些参数：去掉后重试
            for opt in ("temperature",):
                if resp.status_code != 400 or opt not in payload or opt not in resp.text:
                    break
                payload.pop(opt, None)
                resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            return (data["choices"][0]["message"]["content"] or "").strip()
        except httpx.TimeoutException as e:
            raise LLMError(f"调用超时: {e}") from e
        except (KeyError, IndexError, ValueError) as e:
            raise LLMError(f"响应结构异常: {e}") from e

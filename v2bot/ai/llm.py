"""Minimal OpenAI-compatible chat client (works with OpenAI, OpenRouter, Groq, DeepSeek, local servers...)."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json

import aiohttp
from cryptography.fernet import Fernet, InvalidToken

from ..config import ENV


def _fernet() -> Fernet:
    # key derived from BOT_TOKEN + ADMIN_ID: secrets never leave GitHub secrets, DB only holds ciphertext
    seed = f"{ENV.bot_token}:{ENV.admin_id}:kill_pv2".encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(seed).digest()))


def encrypt(s: str) -> str:
    return _fernet().encrypt(s.encode()).decode()


def decrypt(s: str) -> str:
    if not s:
        return ""
    try:
        return _fernet().decrypt(s.encode()).decode()
    except (InvalidToken, ValueError):
        return ""


class LLMError(Exception):
    pass


class LLM:
    def __init__(self, base_url: str, api_key: str, model: str, temperature: float = 0.3):
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/v1") and "/v1/" not in self.base_url and "openai" not in self.base_url:
            pass  # many providers accept without /v1; user supplies full base url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    def _hdr(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "HTTP-Referer": "https://github.com", "X-Title": "kill_pv2"}

    async def list_models(self) -> list[str]:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{self.base_url}/models", headers=self._hdr(), timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status != 200:
                    raise LLMError(f"HTTP {r.status}: {(await r.text())[:200]}")
                data = await r.json()
        items = data.get("data") or data.get("models") or []
        ids = []
        for it in items:
            mid = it.get("id") if isinstance(it, dict) else str(it)
            if mid:
                ids.append(mid)
        return sorted(set(ids))

    async def chat(self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 4096) -> dict:
        body: dict = {"model": self.model, "messages": messages, "temperature": self.temperature, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        last_err = None
        for attempt in range(4):
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(f"{self.base_url}/chat/completions", headers=self._hdr(), json=body,
                                      timeout=aiohttp.ClientTimeout(total=180)) as r:
                        txt = await r.text()
                        if r.status == 429 or r.status >= 500:
                            last_err = f"HTTP {r.status}: {txt[:200]}"
                            await asyncio.sleep(3 * (attempt + 1))
                            continue
                        if r.status != 200:
                            # some providers reject tools -> retry once without
                            if tools and attempt == 0 and ("tool" in txt.lower() or "function" in txt.lower()):
                                body.pop("tools", None); body.pop("tool_choice", None)
                                continue
                            raise LLMError(f"HTTP {r.status}: {txt[:400]}")
                        data = json.loads(txt)
                        choice = (data.get("choices") or [{}])[0]
                        msg = choice.get("message") or {}
                        usage = data.get("usage") or {}
                        return {"content": msg.get("content") or "", "tool_calls": msg.get("tool_calls") or [],
                                "usage": usage, "finish": choice.get("finish_reason")}
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_err = str(e)
                await asyncio.sleep(2 * (attempt + 1))
        raise LLMError(last_err or "unknown error")

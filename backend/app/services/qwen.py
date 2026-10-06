"""Alibaba Cloud Model Studio (Qwen) client, OpenAI-compatible mode.

Used ONLY for writing: report wording, the help assistant and tier explanations.
It never receives an MRI image and has no part in classification.
Every call streams. The API key stays on the server.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import AsyncIterator

import httpx

from app.config import get_settings

def parse_json(text: str):
    """Pull the first JSON object/array out of a model reply."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
        if not m:
            raise ValueError("no JSON in model reply")
        return json.loads(m.group(1))


class QwenClient:
    name = "qwen"

    def __init__(self) -> None:
        s = get_settings()
        self.s = s
        self.http = httpx.AsyncClient(base_url=s.dashscope_base, timeout=httpx.Timeout(60, connect=10),
                                      headers={"Authorization": f"Bearer {s.dashscope_key}"})

    async def stream(self, messages: list[dict], *, model: str | None = None, temperature: float = 0.2,
                     max_tokens: int = 900) -> AsyncIterator[str]:
        body = {"model": model or self.s.qwen_text_model, "messages": messages, "stream": True,
                "temperature": temperature, "max_tokens": max_tokens, "enable_thinking": False}
        async with self.http.stream("POST", "/chat/completions", json=body) as r:
            if r.status_code >= 400:
                detail = (await r.aread()).decode(errors="ignore")[:200]
                raise RuntimeError(f"Model Studio returned {r.status_code}: {detail}")
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    delta = json.loads(payload)["choices"][0]["delta"].get("content")
                except (ValueError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta

    async def complete(self, messages: list[dict], **kw) -> str:
        return "".join([t async for t in self.stream(messages, **kw)])


class MockQwen:
    """Offline text provider (mock mode and tests)."""

    name = "mock-qwen"

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.fail = False

    async def stream(self, messages, **kw) -> AsyncIterator[str]:
        if self.fail:
            raise RuntimeError("mock failure")
        text = self.reply(messages)
        for word in re.findall(r"\S+\s*", text):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield word

    def reply(self, messages) -> str:
        last = messages[-1]["content"]
        last = last if isinstance(last, str) else " ".join(p.get("text", "") for p in last)
        if last.startswith("Confirmed fields"):
            # No offline language model: the report writer falls back to its fixed template.
            raise RuntimeError("mock provider does not draft reports")
        if "Return JSON" in last or "JSON only" in last:
            return "[]"
        return ("NeuroQueue sorts brain MRI scans into Urgent, Review and Routine so the most pressing ones are read first. "
                "It is decision support only: every scan is still read by a radiologist.")

    async def complete(self, messages, **kw) -> str:
        return "".join([t async for t in self.stream(messages, **kw)])


_instance = None


def get_qwen():
    global _instance
    if _instance is None:
        _instance = QwenClient() if get_settings().use_qwen else MockQwen(delay=0.02)
    return _instance


def set_qwen(q) -> None:
    global _instance
    _instance = q

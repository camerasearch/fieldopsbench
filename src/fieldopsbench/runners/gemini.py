"""Gemini runner — raw aiohttp POST to the Gemini API."""

from __future__ import annotations

import os
import time

import aiohttp

from ..schema import EvalCase, TraceRecord
from . import EVAL_SYSTEM_PROMPT, _make_trace, backoff_retry

_API_KEY = os.getenv("GEMINI_API_KEY", "")
_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

_COST_PER_1K_INPUT = 0.002
_COST_PER_1K_OUTPUT = 0.012


class Runner:
    def __init__(self, model: str = "gemini-3.1-pro-preview"):
        self.model = model
        if not _API_KEY:
            raise RuntimeError("GEMINI_API_KEY is required for the Gemini runner")

    async def run_case(self, case: EvalCase) -> TraceRecord:
        user_content = case.user_query
        if case.jurisdiction:
            user_content += f"\n\nJurisdiction: {case.jurisdiction}"

        url = f"{_BASE_URL}/{self.model}:generateContent?key={_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": user_content}]}],
            "systemInstruction": {"parts": [{"text": EVAL_SYSTEM_PROMPT}]},
            "generationConfig": {"temperature": 0, "maxOutputTokens": 4096},
        }
        headers = {"Content-Type": "application/json"}

        start = time.monotonic()

        async def _call():
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    body = await resp.json()
                    return resp.status, body

        body = await backoff_retry(_call)
        latency_ms = (time.monotonic() - start) * 1000

        text = ""
        candidates = body.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            for p in parts:
                if isinstance(p, dict) and "text" in p and not p.get("thought"):
                    text += p["text"]

        usage = body.get("usageMetadata", {})
        input_tok = usage.get("promptTokenCount", 0)
        output_tok = usage.get("candidatesTokenCount", 0)
        total_tok = usage.get("totalTokenCount", 0) or (input_tok + output_tok)
        cost = (input_tok / 1000) * _COST_PER_1K_INPUT + (output_tok / 1000) * _COST_PER_1K_OUTPUT

        return _make_trace(
            case.id,
            response_text=text,
            model=self.model,
            total_tokens=total_tok,
            latency_ms=latency_ms,
            estimated_cost_usd=round(cost, 6),
        )

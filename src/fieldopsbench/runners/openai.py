"""OpenAI runner — raw aiohttp POST to chat completions, no SDK dependency."""

from __future__ import annotations

import os
import time

import aiohttp

from ..schema import EvalCase, TraceRecord
from . import EVAL_SYSTEM_PROMPT, _make_trace, backoff_retry

_API_KEY = os.getenv("OPENAI_API_KEY", "")
_BASE_URL = "https://api.openai.com/v1/chat/completions"

_COST_PER_1K_INPUT = 0.0025
_COST_PER_1K_OUTPUT = 0.015


class Runner:
    def __init__(self, model: str = "gpt-5.4"):
        self.model = model
        if not _API_KEY:
            raise RuntimeError("OPENAI_API_KEY is required for the OpenAI runner")

    async def run_case(self, case: EvalCase) -> TraceRecord:
        user_content = case.user_query
        if case.jurisdiction:
            user_content += f"\n\nJurisdiction: {case.jurisdiction}"

        payload = {
            "model": self.model,
            "max_completion_tokens": 4096,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": EVAL_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_API_KEY}",
        }

        start = time.monotonic()

        async def _call():
            async with aiohttp.ClientSession() as session:
                async with session.post(_BASE_URL, json=payload, headers=headers) as resp:
                    body = await resp.json()
                    return resp.status, body

        body = await backoff_retry(_call)
        latency_ms = (time.monotonic() - start) * 1000

        text = body["choices"][0]["message"]["content"] or ""
        usage = body.get("usage", {})
        input_tok = usage.get("prompt_tokens", 0)
        output_tok = usage.get("completion_tokens", 0)
        total_tok = input_tok + output_tok
        cost = (input_tok / 1000) * _COST_PER_1K_INPUT + (output_tok / 1000) * _COST_PER_1K_OUTPUT

        return _make_trace(
            case.id,
            response_text=text,
            model=self.model,
            total_tokens=total_tok,
            latency_ms=latency_ms,
            estimated_cost_usd=round(cost, 6),
        )

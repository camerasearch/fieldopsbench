"""Thin, provider-neutral chat completion layer.

One function, :func:`complete`, sends a system prompt plus a list of
user/assistant messages (each optionally carrying images) to a provider and
returns the text with token usage. The closed-book runners, the usefulness
judge, and the simulated user all go through it.

No sampling parameters are sent: several current models reject ``temperature``
outright, so every provider runs at its defaults. Results are therefore not
bit-reproducible; use ``--trials`` to measure run-to-run variance.
"""

from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass, field
from typing import Any

import aiohttp

MAX_OUTPUT_TOKENS = 8192
_RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504, 529})
_TIMEOUT = aiohttp.ClientTimeout(total=600)


@dataclass
class Message:
    role: str  # "user" | "assistant"
    text: str
    images: list[tuple[str, str]] = field(default_factory=list)  # (media_type, base64)


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class ProviderError(RuntimeError):
    """The provider returned an error or an unusable response."""


def _require_key(env: str) -> str:
    key = os.getenv(env, "")
    if not key:
        raise ProviderError(f"{env} is not set")
    return key


async def _post_json(url: str, payload: dict, headers: dict, *, max_retries: int = 4) -> dict:
    """POST with exponential backoff on rate limits and transient server errors."""
    last = "no attempt made"
    for attempt in range(max_retries + 1):
        try:
            async with (
                aiohttp.ClientSession(timeout=_TIMEOUT) as session,
                session.post(url, json=payload, headers=headers) as resp,
            ):
                if 200 <= resp.status < 300:
                    return await resp.json()
                last = f"HTTP {resp.status}: {(await resp.text())[:500]}"
                if resp.status not in _RETRYABLE_STATUS:
                    raise ProviderError(last)
        except (TimeoutError, aiohttp.ClientError) as e:
            last = f"{type(e).__name__}: {e}"
        if attempt < max_retries:
            await asyncio.sleep(min(2**attempt + random.uniform(0, 1), 30.0))
    raise ProviderError(last)


# -- Anthropic --------------------------------------------------------------


async def _anthropic(model: str, system: str, messages: list[Message], max_tokens: int) -> Completion:
    import anthropic

    client = anthropic.AsyncAnthropic(max_retries=4)
    content: list[dict[str, Any]] = []
    for m in messages:
        blocks: list[dict[str, Any]] = [
            {"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}}
            for mt, data in m.images
        ]
        blocks.append({"type": "text", "text": m.text})
        content.append({"role": m.role, "content": blocks})

    try:
        response = await client.messages.create(
            model=model, max_tokens=max_tokens, system=system, messages=content
        )
    except anthropic.APIError as e:
        raise ProviderError(f"{type(e).__name__}: {e}") from e

    text = "".join(b.text for b in response.content if b.type == "text")
    if response.stop_reason == "refusal" and not text:
        # A declined request is the model's answer for this case; no fallback
        # model is used, so the score stays attributable to the model under test.
        text = "[The model declined to answer this request.]"
    return Completion(text, response.usage.input_tokens, response.usage.output_tokens)


# -- OpenAI-compatible (OpenAI, xAI) ----------------------------------------


async def _openai_compatible(
    url: str, key_env: str, tokens_param: str,
    model: str, system: str, messages: list[Message], max_tokens: int,
) -> Completion:
    chat: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        if m.images:
            parts: list[dict[str, Any]] = [
                {"type": "image_url", "image_url": {"url": f"data:{mt};base64,{data}"}}
                for mt, data in m.images
            ]
            parts.append({"type": "text", "text": m.text})
            chat.append({"role": m.role, "content": parts})
        else:
            chat.append({"role": m.role, "content": m.text})

    body = await _post_json(
        url,
        {"model": model, "messages": chat, tokens_param: max_tokens},
        {"Authorization": f"Bearer {_require_key(key_env)}"},
    )
    try:
        text = body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderError(f"unexpected response shape: {str(body)[:300]}") from e
    usage = body.get("usage") or {}
    return Completion(text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))


async def _openai(model: str, system: str, messages: list[Message], max_tokens: int) -> Completion:
    return await _openai_compatible(
        "https://api.openai.com/v1/chat/completions", "OPENAI_API_KEY", "max_completion_tokens",
        model, system, messages, max_tokens,
    )


async def _xai(model: str, system: str, messages: list[Message], max_tokens: int) -> Completion:
    return await _openai_compatible(
        "https://api.x.ai/v1/chat/completions", "XAI_API_KEY", "max_tokens",
        model, system, messages, max_tokens,
    )


# -- Google Gemini -----------------------------------------------------------


async def _google(model: str, system: str, messages: list[Message], max_tokens: int) -> Completion:
    contents = []
    for m in messages:
        parts: list[dict[str, Any]] = [
            {"inlineData": {"mimeType": mt, "data": data}} for mt, data in m.images
        ]
        parts.append({"text": m.text})
        contents.append({"role": "model" if m.role == "assistant" else "user", "parts": parts})

    body = await _post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"maxOutputTokens": max_tokens},
        },
        # Header, not ?key=, so the key never lands in logs or error messages.
        {"x-goog-api-key": _require_key("GEMINI_API_KEY")},
    )
    candidates = body.get("candidates") or []
    parts = (candidates[0].get("content") or {}).get("parts", []) if candidates else []
    text = "".join(p["text"] for p in parts if isinstance(p, dict) and "text" in p and not p.get("thought"))
    usage = body.get("usageMetadata") or {}
    return Completion(
        text,
        usage.get("promptTokenCount", 0),
        usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
    )


PROVIDERS = {"anthropic": _anthropic, "openai": _openai, "google": _google, "xai": _xai}

PROVIDER_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",
    "xai": "XAI_API_KEY",
}


def parse_model_spec(spec: str) -> tuple[str, str]:
    """Split ``provider:model-id`` and validate the provider."""
    provider, sep, model = spec.partition(":")
    if not sep or not model or provider not in PROVIDERS:
        raise ValueError(
            f"invalid model spec {spec!r}; expected provider:model-id with provider in "
            f"{sorted(PROVIDERS)}"
        )
    return provider, model


async def complete(
    spec: str, system: str, messages: list[Message], *, max_tokens: int = MAX_OUTPUT_TOKENS
) -> Completion:
    """Run one chat completion against ``provider:model-id``."""
    provider, model = parse_model_spec(spec)
    return await PROVIDERS[provider](model, system, messages, max_tokens)

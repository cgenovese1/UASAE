"""
UASAE AI Client — abstraction over any OpenAI-compatible LLM endpoint.

Routes through ARGUS LiteLLM by default. The model and base_url are
configurable so the provider is fully swappable without touching callers.

Security: secrets are loaded from settings, never passed as arguments
from untrusted sources. Artifact content is treated as data in the
user/assistant message, never injected into the system prompt.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, TypeVar

import httpx
import structlog
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.core.config import settings

log = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class AIUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    latency_ms: float = 0.0


class AIMessage(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str


class AIResponse(BaseModel):
    content: str
    usage: AIUsage
    raw: dict[str, Any] = {}


class AIClient:
    """
    Thin async wrapper over any OpenAI-compatible /chat/completions endpoint.

    Usage:
        client = AIClient()
        response = await client.chat([
            AIMessage(role="system", content="You are a requirements analyst."),
            AIMessage(role="user", content=document_text),
        ])

    For structured output, use chat_structured() which validates the
    response against a Pydantic model schema.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = (base_url or settings.litellm_base_url).rstrip("/")
        self._api_key = api_key or settings.litellm_api_key
        self._model = model or settings.default_model
        self._timeout = timeout
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AIClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def chat(
        self,
        messages: list[AIMessage],
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
    ) -> AIResponse:
        payload: dict[str, Any] = {
            "model": model or self._model,
            "messages": [m.model_dump() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        t0 = time.monotonic()
        resp = await self._http.post(
            f"{self._base_url}/chat/completions",
            json=payload,
        )
        latency_ms = (time.monotonic() - t0) * 1000

        resp.raise_for_status()
        data = resp.json()

        usage_data = data.get("usage", {})
        usage = AIUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
            model=data.get("model", payload["model"]),
            latency_ms=latency_ms,
        )

        content = data["choices"][0]["message"]["content"]

        log.debug(
            "ai_chat_complete",
            model=usage.model,
            total_tokens=usage.total_tokens,
            latency_ms=round(latency_ms),
        )

        return AIResponse(content=content, usage=usage, raw=data)

    async def chat_structured(
        self,
        messages: list[AIMessage],
        output_model: type[T],
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> tuple[T, AIUsage]:
        """
        Chat and parse the response into a Pydantic model.
        Requests JSON output and validates against the schema.
        """
        schema = output_model.model_json_schema()
        schema_str = json.dumps(schema, indent=2)

        augmented = list(messages)
        augmented.append(
            AIMessage(
                role="user",
                content=(
                    f"\n\nRespond with a single JSON object that conforms exactly to "
                    f"this schema (no markdown, no explanation):\n{schema_str}"
                ),
            )
        )

        response = await self.chat(
            augmented,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        raw_content = response.content.strip()
        # Strip markdown code fences if the model includes them despite json_object mode
        if raw_content.startswith("```"):
            raw_content = raw_content.split("```")[1]
            if raw_content.startswith("json"):
                raw_content = raw_content[4:]

        parsed = output_model.model_validate_json(raw_content)
        return parsed, response.usage

    async def stream(
        self,
        messages: list[AIMessage],
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        payload = {
            "model": model or self._model,
            "messages": [m.model_dump() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with self._http.stream(
            "POST", f"{self._base_url}/chat/completions", json=payload
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload_str = line[6:].strip()
                if payload_str == "[DONE]":
                    break
                chunk = json.loads(payload_str)
                delta = chunk["choices"][0].get("delta", {}).get("content", "")
                if delta:
                    yield delta

"""model.py — Unified LLM client for Fracture.

All LLM calls go through ModelClient. No other module makes direct API calls.
Supports two providers:
  - "claude"  — Anthropic Messages API
  - "local"   — OpenAI-compatible chat completions endpoint
"""

from __future__ import annotations

import json
import os
import re

import httpx

from fracture.types import ModelConfig


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class JsonParseError(Exception):
    """Raised when call_json() cannot parse the LLM response as JSON."""

    def __init__(self, raw_response: str) -> None:
        self.raw_response = raw_response
        super().__init__(f"Failed to parse LLM response as JSON: {raw_response!r}")


# ---------------------------------------------------------------------------
# ModelClient
# ---------------------------------------------------------------------------

class ModelClient:
    """Async LLM client — Claude API or OpenAI-compatible local endpoint."""

    def __init__(self, config: ModelConfig) -> None:
        """Initialize with provider config."""
        self._config = config

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def call(self, system_prompt: str, user_message: str) -> str:
        """Send a prompt, return the raw text response."""
        if self._config.provider == "claude":
            return await self._call_claude(system_prompt, user_message)
        else:
            return await self._call_local(system_prompt, user_message)

    async def call_json(self, system_prompt: str, user_message: str) -> dict:
        """Send a prompt, parse response as JSON.

        Strips markdown code fences (```json ... ```) before parsing.
        Raises JsonParseError if the response is not valid JSON.
        """
        raw = await self.call(system_prompt, user_message)
        cleaned = _strip_markdown_fences(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            raise JsonParseError(raw_response=raw)

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    async def _call_claude(self, system_prompt: str, user_message: str) -> str:
        """Call the Anthropic Messages API."""
        api_key = os.environ[self._config.claude_api_key_env]
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": self._config.claude_model,
            "max_tokens": self._config.max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=body,
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]

    async def _call_local(self, system_prompt: str, user_message: str) -> str:
        """Call an OpenAI-compatible local LLM endpoint."""
        headers: dict[str, str] = {"content-type": "application/json"}
        if self._config.local_api_key:
            headers["Authorization"] = f"Bearer {self._config.local_api_key}"

        body = {
            "model": self._config.local_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self._config.max_tokens,
        }
        url = f"{self._config.local_endpoint}/chat/completions"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                json=body,
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    """Remove surrounding ```json / ``` fences and trim whitespace."""
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped

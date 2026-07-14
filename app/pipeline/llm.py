"""Thin OpenAI-compatible chat client used for NVIDIA NIM endpoints.

Set NVIDIA_API_KEY (and optionally NVIDIA_BASE_URL / NVIDIA_MODEL) to enable
LLM-backed schema design and synthesis. Without a key the pipeline runs in
fully-offline fallback mode.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import httpx

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "meta/llama-3.1-70b-instruct"


def raise_for_status_with_body(resp: httpx.Response) -> None:
    """Like ``resp.raise_for_status()`` but fold the response body into the
    error message. Providers put the actual reason there (NVIDIA returns
    ``403 ... "Authorization failed"`` for a bad key vs ``401`` for a missing
    one), which the stock httpx message discards - leaving only a bare status."""
    if not resp.is_error:
        return
    body = resp.text.strip()
    message = f"{resp.status_code} {resp.reason_phrase} for {resp.request.url}"
    if body:
        message += f": {body[:400]}"
    raise httpx.HTTPStatusError(message, request=resp.request, response=resp)


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("NVIDIA_API_KEY", "")
        self.base_url = (base_url or os.environ.get("NVIDIA_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.model = model or os.environ.get("NVIDIA_MODEL", DEFAULT_MODEL)

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        with httpx.Client(timeout=120) as client:
            resp = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            raise_for_status_with_body(resp)
            data = resp.json()
        return data["choices"][0]["message"]["content"]


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of an LLM response."""
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    text = text.strip()
    # Try direct parse first, then scan for the outermost bracket pair.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("No parseable JSON found in model response")


def ensure_json_object(text: str) -> dict[str, Any]:
    """Extract JSON and ensure it's an object (dict), not an array."""
    result = extract_json(text)
    if isinstance(result, list):
        # If it's an array, take the first element if it's an object
        if result and isinstance(result[0], dict):
            return result[0]
        # Otherwise return empty dict
        return {}
    if isinstance(result, dict):
        return result
    return {}

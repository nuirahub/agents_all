"""
OpenAI Responses API provider adapter.
Implements the Provider protocol for OpenAI and OpenRouter.
"""
from __future__ import annotations

import json
from typing import Any, Generator

import requests as http_requests

from core.domain import TokenUsage
from infra.provider_types import ProviderRequest, ProviderResponse, StreamEvent


def _items_to_input(items: list[dict]) -> list[dict]:
    """Map internal items to OpenAI Responses API input format."""
    out: list[dict] = []
    for item in items:
        t = item.get("type")
        if t == "message":
            role = item.get("role", "user")
            content = item.get("content", "")
            if isinstance(content, str):
                out.append({"role": role, "content": content})
            else:
                parts = []
                for part in content if isinstance(content, list) else []:
                    if isinstance(part, dict):
                        pt = part.get("type")
                        if pt in ("text", "input_text"):
                            parts.append({"type": "input_text", "text": part.get("text", "")})
                        elif pt == "output_text":
                            parts.append({"type": "output_text", "text": part.get("text", "")})
                out.append({"role": role, "content": parts or [{"type": "input_text", "text": ""}]})
        elif t == "function_call":
            args = item.get("arguments", {})
            out.append({
                "type": "function_call",
                "call_id": item.get("call_id", ""),
                "name": item.get("name", ""),
                "arguments": json.dumps(args) if isinstance(args, dict) else str(args),
            })
        elif t == "function_call_output":
            out.append({
                "type": "function_call_output",
                "call_id": item.get("call_id", ""),
                "output": item.get("output", ""),
            })
    return out


def _map_tools(tools: list[dict]) -> list[dict]:
    mapped: list[dict] = []
    for t in tools:
        if t.get("type") == "web_search":
            mapped.append({"type": "web_search_preview"})
        else:
            mapped.append(t)
    return mapped


def _normalize_output(output: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for o in output:
        if o.get("type") == "message":
            role = o.get("role", "assistant")
            for part in o.get("content", []):
                if part.get("type") == "output_text":
                    normalized.append({"type": "message", "role": role, "content": part.get("text", "")})
        elif o.get("type") == "function_call":
            args = o.get("arguments")
            normalized.append({
                "type": "function_call",
                "call_id": o.get("call_id", ""),
                "name": o.get("name", ""),
                "arguments": args if isinstance(args, dict) else json.loads(args or "{}"),
            })
    return normalized


class OpenAIProvider:
    """OpenAI Responses API provider (works with OpenAI and OpenRouter)."""

    def __init__(
        self,
        *,
        provider_name: str = "openai",
        api_key: str,
        base_url: str = "https://api.openai.com/v1/responses",
        extra_headers: dict[str, str] | None = None,
        default_max_tokens: int = 8192,
    ):
        self._name = provider_name
        self._api_key = api_key
        self._base_url = base_url
        self._extra_headers = extra_headers or {}
        self._default_max_tokens = default_max_tokens

    @property
    def name(self) -> str:
        return self._name

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            **self._extra_headers,
        }

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        body: dict[str, Any] = {
            "model": request.model,
            "instructions": request.instructions,
            "input": _items_to_input(request.input_items),
            "tools": _map_tools(request.tools),
            "tool_choice": "auto",
            "max_output_tokens": request.max_tokens or self._default_max_tokens,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature

        resp = http_requests.post(
            self._base_url,
            headers=self._headers(),
            json=body,
            timeout=120,
        )
        data = resp.json()
        if not resp.ok or data.get("error"):
            msg = data.get("error", {}).get("message", f"API error {resp.status_code}")
            raise RuntimeError(msg)

        output = _normalize_output(data.get("output", []))
        usage_data = data.get("usage") or {}
        usage = None
        if usage_data:
            usage = TokenUsage(
                input_tokens=usage_data.get("input_tokens", 0),
                output_tokens=usage_data.get("output_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
                cached_tokens=usage_data.get("input_tokens_details", {}).get("cached_tokens", 0),
            )

        return ProviderResponse(output=output, usage=usage)

    def stream(self, request: ProviderRequest) -> Generator[StreamEvent, None, None]:
        body: dict[str, Any] = {
            "model": request.model,
            "instructions": request.instructions,
            "input": _items_to_input(request.input_items),
            "tools": _map_tools(request.tools),
            "tool_choice": "auto",
            "max_output_tokens": request.max_tokens or self._default_max_tokens,
            "stream": True,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature

        resp = http_requests.post(
            self._base_url,
            headers=self._headers(),
            json=body,
            timeout=120,
            stream=True,
        )
        if not resp.ok:
            raise RuntimeError(f"OpenAI streaming error {resp.status_code}")

        fn_call_meta: dict[int, dict[str, str]] = {}

        for line in resp.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8", errors="replace")
            if decoded.startswith("event:"):
                continue
            if not decoded.startswith("data: "):
                continue
            payload = decoded[6:]
            if payload == "[DONE]":
                break
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue

            etype = event.get("type", "")

            if etype == "response.output_item.added":
                item = event.get("item", {})
                idx = event.get("output_index", 0)
                if item.get("type") == "function_call":
                    fn_call_meta[idx] = {
                        "call_id": item.get("call_id", ""),
                        "name": item.get("name", ""),
                    }

            elif etype == "response.output_text.delta":
                yield StreamEvent(type="text_delta", data={"delta": event.get("delta", "")})

            elif etype == "response.output_text.done":
                yield StreamEvent(type="text_done", data={"text": event.get("text", "")})

            elif etype == "response.function_call_arguments.delta":
                idx = event.get("output_index", 0)
                meta = fn_call_meta.get(idx, {})
                yield StreamEvent(type="function_call_delta", data={
                    "call_id": meta.get("call_id", ""),
                    "name": meta.get("name", ""),
                    "arguments_delta": event.get("delta", ""),
                })

            elif etype == "response.function_call_arguments.done":
                idx = event.get("output_index", 0)
                meta = fn_call_meta.get(idx, {})
                args_str = event.get("arguments", "{}")
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = {}
                yield StreamEvent(type="function_call_done", data={
                    "call_id": meta.get("call_id", ""),
                    "name": meta.get("name", ""),
                    "arguments": args,
                })

            elif etype == "response.completed":
                response_data = event.get("response", {})
                output = _normalize_output(response_data.get("output", []))
                usage_data = response_data.get("usage") or {}
                usage = None
                if usage_data:
                    usage = {
                        "input_tokens": usage_data.get("input_tokens", 0),
                        "output_tokens": usage_data.get("output_tokens", 0),
                        "total_tokens": usage_data.get("total_tokens", 0),
                        "cached_tokens": usage_data.get("input_tokens_details", {}).get("cached_tokens", 0),
                    }
                yield StreamEvent(type="done", data={"output": output, "usage": usage})

            elif etype == "response.failed":
                err = event.get("response", {}).get("error", {})
                yield StreamEvent(type="error", data={
                    "message": err.get("message", "Response failed"),
                    "code": err.get("code"),
                })

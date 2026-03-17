"""
Gemini provider adapter — uses Gemini REST API (generateContent).
Implements the Provider protocol for Google Gemini models.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Generator

import requests as http_requests

from domain import TokenUsage
from provider_types import ProviderRequest, ProviderResponse, StreamEvent

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _items_to_gemini_contents(
    items: list[dict], instructions: str
) -> tuple[list[dict], dict | None]:
    """Map internal items to Gemini contents + systemInstruction."""
    contents: list[dict] = []
    system_instruction = {"parts": [{"text": instructions}]} if instructions else None

    for item in items:
        t = item.get("type")
        if t == "message":
            role = item.get("role", "user")
            gemini_role = "model" if role == "assistant" else "user"
            content = item.get("content", "")
            if isinstance(content, str):
                contents.append({"role": gemini_role, "parts": [{"text": content}]})
            else:
                parts = []
                for part in content if isinstance(content, list) else []:
                    if isinstance(part, dict) and part.get("type") in ("text", "input_text", "output_text"):
                        parts.append({"text": part.get("text", "")})
                if parts:
                    contents.append({"role": gemini_role, "parts": parts})

        elif t == "function_call":
            contents.append({
                "role": "model",
                "parts": [{"functionCall": {
                    "name": item.get("name", ""),
                    "args": item.get("arguments", {}),
                }}],
            })

        elif t == "function_call_output":
            fn_name = _find_fn_name(items, item.get("call_id", ""))
            contents.append({
                "role": "user",
                "parts": [{"functionResponse": {
                    "name": fn_name,
                    "response": {"result": item.get("output", "")},
                }}],
            })

    return contents, system_instruction


def _find_fn_name(items: list[dict], call_id: str) -> str:
    """Look up the function name for a given call_id."""
    for it in items:
        if it.get("type") == "function_call" and it.get("call_id") == call_id:
            return it.get("name", "")
    return ""


def _map_tools_to_gemini(tools: list[dict]) -> list[dict] | None:
    function_declarations: list[dict] = []
    has_google_search = False

    for t in tools:
        if t.get("type") == "web_search":
            has_google_search = True
        elif t.get("type") == "function":
            decl: dict[str, Any] = {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
            }
            params = t.get("parameters")
            if params:
                decl["parameters"] = params
            function_declarations.append(decl)

    result: list[dict] = []
    if function_declarations:
        result.append({"functionDeclarations": function_declarations})
    if has_google_search:
        result.append({"googleSearch": {}})
    return result if result else None


def _normalize_gemini_output(response: dict) -> list[dict]:
    normalized: list[dict] = []
    candidates = response.get("candidates", [])
    if not candidates:
        return normalized

    parts = candidates[0].get("content", {}).get("parts", [])
    for part in parts:
        if "text" in part:
            normalized.append({
                "type": "message",
                "role": "assistant",
                "content": part["text"],
            })
        elif "functionCall" in part:
            fc = part["functionCall"]
            normalized.append({
                "type": "function_call",
                "call_id": f"call_{uuid.uuid4().hex[:12]}",
                "name": fc.get("name", ""),
                "arguments": fc.get("args", {}),
            })
    return normalized


class GeminiProvider:
    """Google Gemini API provider."""

    def __init__(
        self,
        *,
        api_key: str,
        default_model: str = "gemini-2.5-flash",
        default_max_tokens: int = 8192,
    ):
        self._api_key = api_key
        self._default_model = default_model
        self._default_max_tokens = default_max_tokens

    @property
    def name(self) -> str:
        return "gemini"

    def _build_body(self, request: ProviderRequest) -> dict[str, Any]:
        contents, system_instruction = _items_to_gemini_contents(
            request.input_items, request.instructions
        )
        tools = _map_tools_to_gemini(request.tools)

        body: dict[str, Any] = {"contents": contents}
        if system_instruction:
            body["systemInstruction"] = system_instruction
        if tools:
            body["tools"] = tools

        gen_config: dict[str, Any] = {
            "maxOutputTokens": request.max_tokens or self._default_max_tokens,
        }
        if request.temperature is not None:
            gen_config["temperature"] = request.temperature
        body["generationConfig"] = gen_config
        return body

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        model = request.model or self._default_model
        body = self._build_body(request)

        url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={self._api_key}"
        resp = http_requests.post(url, json=body, timeout=120)
        data = resp.json()

        if not resp.ok or "error" in data:
            err = data.get("error", {})
            raise RuntimeError(err.get("message", f"Gemini API error {resp.status_code}"))

        output = _normalize_gemini_output(data)
        usage_meta = data.get("usageMetadata", {})
        usage = TokenUsage(
            input_tokens=usage_meta.get("promptTokenCount", 0),
            output_tokens=usage_meta.get("candidatesTokenCount", 0),
            total_tokens=usage_meta.get("totalTokenCount", 0),
        ) if usage_meta else None

        return ProviderResponse(output=output, usage=usage)

    def stream(self, request: ProviderRequest) -> Generator[StreamEvent, None, None]:
        model = request.model or self._default_model
        body = self._build_body(request)

        url = f"{GEMINI_API_BASE}/models/{model}:streamGenerateContent?key={self._api_key}&alt=sse"
        resp = http_requests.post(url, json=body, timeout=120, stream=True)

        if not resp.ok:
            raise RuntimeError(f"Gemini streaming error {resp.status_code}")

        accumulated_text = ""

        for line in resp.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8", errors="replace")
            if not decoded.startswith("data: "):
                continue
            payload = decoded[6:]
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue

            candidates = chunk.get("candidates", [])
            if not candidates:
                continue

            content = candidates[0].get("content", {})
            for part in content.get("parts", []):
                if "text" in part:
                    delta = part["text"]
                    accumulated_text += delta
                    yield StreamEvent(type="text_delta", data={"delta": delta})
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    yield StreamEvent(type="function_call_done", data={
                        "call_id": f"call_{uuid.uuid4().hex[:12]}",
                        "name": fc.get("name", ""),
                        "arguments": fc.get("args", {}),
                    })

            usage_meta = chunk.get("usageMetadata")
            finish_reason = candidates[0].get("finishReason")
            if usage_meta and finish_reason:
                yield StreamEvent(type="done", data={
                    "output": _normalize_gemini_output(chunk),
                    "usage": {
                        "input_tokens": usage_meta.get("promptTokenCount", 0),
                        "output_tokens": usage_meta.get("candidatesTokenCount", 0),
                        "total_tokens": usage_meta.get("totalTokenCount", 0),
                    },
                })

        if accumulated_text:
            yield StreamEvent(type="text_done", data={"text": accumulated_text})

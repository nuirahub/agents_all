"""
OpenAI Responses API client — build input from items, call API, parse output.
"""
from __future__ import annotations

import json
import requests

from config import AI_CONFIG, MAX_OUTPUT_TOKENS
from domain import TokenUsage

# Map our item list to API input format (aligned with 4th-devs/01_05_agent OpenAI adapter).
# - message: { role, content } (no type field); content = string or [{ type: "input_text", text }]
# - function_call: { type: "function_call", call_id, name, arguments } (arguments as JSON string)
# - function_call_output: { type: "function_call_output", call_id, output }
def items_to_input(items: list[dict], instructions: str) -> list[dict]:
    out: list[dict] = []
    for item in items:
        t = item.get("type")
        if t == "message":
            role = item.get("role", "user")
            content = item.get("content", "")
            if isinstance(content, str):
                out.append({"role": role, "content": content})
            else:
                # Content as parts: only input_text / output_text allowed in API
                parts = []
                for part in content if isinstance(content, list) else []:
                    if isinstance(part, dict):
                        pt = part.get("type")
                        if pt == "text" or pt == "input_text":
                            parts.append({"type": "input_text", "text": part.get("text", "")})
                        elif pt == "output_text":
                            parts.append({"type": "output_text", "text": part.get("text", "")})
                out.append({"role": role, "content": parts if parts else [{"type": "input_text", "text": ""}]})
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


def call_provider(
    *,
    model: str,
    instructions: str,
    input_items: list[dict],
    tools: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[list[dict], TokenUsage | None]:
    """
    Call OpenAI Responses API. Returns (output items, usage).
    Output items: message with output_text, or function_call (call_id, name, arguments).
    """
    input_messages = items_to_input(input_items, instructions)
    # Map our internal tools to OpenAI Responses built-ins.
    mapped_tools: list[dict] = []
    for t in tools:
        if t.get("type") == "web_search":
            # Use OpenAI web_search_preview tool
            mapped_tools.append({"type": "web_search_preview"})
        else:
            mapped_tools.append(t)

    body = {
        "model": model,
        "instructions": instructions,
        "input": input_messages,
        "tools": mapped_tools,
        "tool_choice": "auto",
        "max_output_tokens": max_tokens or MAX_OUTPUT_TOKENS,
    }
    if temperature is not None:
        body["temperature"] = temperature
    resp = requests.post(
        AI_CONFIG.responses_api_endpoint,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AI_CONFIG.api_key}",
            **AI_CONFIG.extra_api_headers,
        },
        json=body,
        timeout=120,
    )
    data = resp.json()
    if not resp.ok or data.get("error"):
        msg = data.get("error", {}).get("message", f"API error {resp.status_code}")
        raise RuntimeError(msg)

    output = data.get("output", [])
    usage_data = data.get("usage") or {}
    usage = None
    if usage_data:
        usage = TokenUsage(
            input_tokens=usage_data.get("input_tokens", 0),
            output_tokens=usage_data.get("output_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
            cached_tokens=usage_data.get("input_tokens_details", {}).get("cached_tokens", 0),
        )
    # Normalize output to our item-like format
    normalized: list[dict] = []
    for o in output:
        if o.get("type") == "message":
            role = o.get("role", "assistant")
            for part in o.get("content", []):
                if part.get("type") == "output_text":
                    normalized.append({"type": "message", "role": role, "content": part.get("text", "")})
                elif part.get("type") == "function_call":
                    normalized.append({
                        "type": "function_call",
                        "call_id": part.get("call_id", ""),
                        "name": part.get("name", ""),
                        "arguments": part.get("arguments") if isinstance(part.get("arguments"), dict) else json.loads(part.get("arguments") or "{}"),
                    })
        elif o.get("type") == "function_call":
            normalized.append({
                "type": "function_call",
                "call_id": o.get("call_id", ""),
                "name": o.get("name", ""),
                "arguments": o.get("arguments") if isinstance(o.get("arguments"), dict) else json.loads(o.get("arguments") or "{}"),
            })
    return normalized, usage

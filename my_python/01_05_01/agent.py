"""
Agent loop: chat → tool calls → (optional confirmation) → results.
Supports confirmation callback for sensitive tools (send_email).
"""
from __future__ import annotations

import json
from typing import Any, Callable

import requests

from config import AI_CONFIG, INSTRUCTIONS, MAX_OUTPUT_TOKENS, MODEL
from tools_file import FILE_HANDLERS, FILE_TOOLS
from tools_email import SEND_EMAIL_TOOL, send_email
from logger import log

TOOLS_REQUIRING_CONFIRMATION = frozenset({"send_email"})
MAX_STEPS = 50

ALL_TOOLS = FILE_TOOLS + [SEND_EMAIL_TOOL]
ALL_HANDLERS = {**FILE_HANDLERS, "send_email": lambda a: send_email(**a)}


def _chat(
    *,
    input_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    body = {
        "model": MODEL,
        "input": input_messages,
        "tools": tools,
        "tool_choice": "auto",
        "instructions": INSTRUCTIONS,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
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
    return data


def _extract_tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [o for o in response.get("output", []) if o.get("type") == "function_call"]


def _extract_text(response: dict[str, Any]) -> str | None:
    out = response.get("output_text")
    if isinstance(out, str) and out.strip():
        return out
    for item in response.get("output", []):
        if item.get("type") == "message":
            content = item.get("content") or []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    t = part.get("text")
                    if isinstance(t, str):
                        return t
    return None


def _run_tool(
    tool_name: str,
    args: dict[str, Any],
    confirm_tool: Callable[[str, dict[str, Any]], bool] | None,
) -> str:
    log.tool(tool_name, args)

    if tool_name in TOOLS_REQUIRING_CONFIRMATION and confirm_tool is not None:
        if not confirm_tool(tool_name, args):
            result = json.dumps({"success": False, "error": "User rejected the action", "rejected": True})
            log.tool_result(tool_name, False, "Rejected by user")
            return result

    handler = ALL_HANDLERS.get(tool_name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        out = handler(args)
        result = json.dumps(out)
        log.tool_result(tool_name, True, result)
        return result
    except Exception as e:
        result = json.dumps({"error": str(e)})
        log.tool_result(tool_name, False, str(e))
        return result


def run(
    query: str,
    *,
    conversation_history: list[dict[str, Any]] | None = None,
    confirm_tool: Callable[[str, dict[str, Any]], bool] | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Run agent on query. Returns (response_text, tool_calls_made, new_conversation_history).
    confirm_tool(tool_name, args) -> True to proceed, False to reject.
    """
    messages: list[dict[str, Any]] = list(conversation_history or [])
    messages.append({"role": "user", "content": query})
    tool_call_history: list[dict[str, Any]] = []

    log.query(query)

    for step in range(1, MAX_STEPS + 1):
        log.api(f"Step {step}", len(messages))
        response = _chat(input_messages=messages, tools=ALL_TOOLS)
        usage = response.get("usage")
        if usage:
            log.api_done(usage)

        tool_calls = _extract_tool_calls(response)
        if not tool_calls:
            text = _extract_text(response) or "No response"
            log.response(text)
            # Append assistant output to messages (response.output)
            messages.extend(response.get("output", []))
            return text, tool_call_history, messages

        messages.extend(response.get("output", []))

        for tc in tool_calls:
            tool_call_history.append({
                "name": tc.get("name"),
                "arguments": json.loads(tc.get("arguments") or "{}"),
            })

        for tc in tool_calls:
            name = tc.get("name") or ""
            args = json.loads(tc.get("arguments") or "{}")
            output = _run_tool(name, args, confirm_tool)
            messages.append({
                "type": "function_call_output",
                "call_id": tc.get("call_id"),
                "output": output,
            })

    raise RuntimeError(f"Max steps ({MAX_STEPS}) reached")

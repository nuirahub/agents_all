"""
Chat service: create agents, run them via runner, map to API responses.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from config import DEFAULT_MODEL
from domain import AgentConfig, WaitingFor
from repositories import Repositories
from runner import run_agent, deliver_result as runner_deliver
from tools import get_tool_definitions


def create_agent_for_input(
    repos: Repositories,
    *,
    instructions: str,
    input_text: str,
    model: str | None = None,
) -> str:
    session = repos.sessions.create()
    tools = get_tool_definitions()
    agent = repos.agents.create(
        {
            "session_id": session.id,
            "task": instructions,
            "config": {
                "model": model or DEFAULT_MODEL,
                "tools": tools,
            },
        }
    )
    repos.items.create(
        agent.id,
        {
            "type": "message",
            "role": "user",
            "content": input_text,
        },
    )
    return agent.id


def _waiting_to_dict(waiting: list[WaitingFor]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in waiting:
        out.append(
            {
                "callId": w.call_id,
                "type": w.type,
                "name": w.name,
                "description": w.description,
            }
        )
    return out


def chat_once(
    repos: Repositories,
    *,
    input_text: str,
    instructions: str = "You are a helpful assistant.",
    model: str | None = None,
) -> dict[str, Any]:
    agent_id = create_agent_for_input(
        repos,
        instructions=instructions,
        input_text=input_text,
        model=model,
    )
    result = run_agent(agent_id, repos)
    agent = result["agent"]
    items = result["items"]

    output: list[dict[str, Any]] = []
    for item in items:
        if item.get("type") == "message" and item.get("role") == "assistant":
            content = item.get("content")
            if isinstance(content, str) and content:
                output.append({"type": "text", "text": content})
        elif item.get("type") == "function_call":
            output.append(
                {
                    "type": "function_call",
                    "callId": item.get("call_id", ""),
                    "name": item.get("name", ""),
                    "arguments": item.get("arguments", {}),
                }
            )

    resp: dict[str, Any] = {
        "id": agent.id,
        "sessionId": agent.session_id,
        "status": result["status"],
        "model": agent.config.model,
        "output": output,
    }
    if result["status"] == "waiting":
        resp["waitingFor"] = _waiting_to_dict(result.get("waiting_for", []))
    if agent.usage:
        resp["usage"] = {
            "inputTokens": agent.usage.input_tokens,
            "outputTokens": agent.usage.output_tokens,
            "totalTokens": agent.usage.total_tokens,
        }
    return resp


def deliver_tool_result(
    repos: Repositories,
    *,
    agent_id: str,
    call_id: str,
    output: str,
    is_error: bool,
) -> dict[str, Any]:
    result = runner_deliver(
        agent_id,
        call_id,
        output=output,
        is_error=is_error,
        repos=repos,
    )
    agent = result["agent"]
    items = result["items"]

    output_items: list[dict[str, Any]] = []
    for item in items:
        if item.get("type") == "message" and item.get("role") == "assistant":
            content = item.get("content")
            if isinstance(content, str) and content:
                output_items.append({"type": "text", "text": content})
        elif item.get("type") == "function_call":
            output_items.append(
                {
                    "type": "function_call",
                    "callId": item.get("call_id", ""),
                    "name": item.get("name", ""),
                    "arguments": item.get("arguments", {}),
                }
            )

    resp: dict[str, Any] = {
        "id": agent.id,
        "sessionId": agent.session_id,
        "status": result["status"],
        "model": agent.config.model,
        "output": output_items,
    }
    if result["status"] == "waiting":
        resp["waitingFor"] = _waiting_to_dict(result.get("waiting_for", []))
    if agent.usage:
        resp["usage"] = {
            "inputTokens": agent.usage.input_tokens,
            "outputTokens": agent.usage.output_tokens,
            "totalTokens": agent.usage.total_tokens,
        }
    return resp


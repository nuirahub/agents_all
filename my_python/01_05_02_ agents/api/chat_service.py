"""
Chat service: create agents, run them via runner, map to API responses.
"""
from __future__ import annotations

from typing import Any, Generator

from infra.config import DEFAULT_MODEL, MAX_TURNS
from core.domain import WaitingFor, start_agent, complete_agent
from infra.provider_types import StreamEvent
from infra.repositories import Repositories
from core.runner import run_agent, deliver_result as runner_deliver, _handle_send_message
from tools import get_tool_definitions, get_tool_type, execute_sync_tool


def _get_all_tool_definitions() -> list[dict]:
    """Get built-in tool definitions + MCP tools if available."""
    tools = get_tool_definitions()
    from infra.mcp_client import get_mcp_manager
    mcp = get_mcp_manager()
    if mcp:
        tools.extend(mcp.get_tool_definitions())
    return tools


def create_agent_for_input(
    repos: Repositories,
    *,
    instructions: str,
    input_text: str,
    input_items: list[dict[str, Any]] | None = None,
    model: str | None = None,
    agent_name: str | None = None,
    session_id: str | None = None,
) -> str:
    from agents.agent_templates import get_agent_template

    template = get_agent_template(agent_name) if agent_name else None

    resolved_model = model or (template.model if template else None) or DEFAULT_MODEL
    resolved_instructions = instructions
    if template and instructions == "You are a helpful assistant.":
        resolved_instructions = template.system_prompt

    if template and template.tools:
        tools = get_tool_definitions(template.tools)
        from infra.mcp_client import get_mcp_manager
        mcp = get_mcp_manager()
        if mcp:
            tools.extend(mcp.get_tool_definitions())
    else:
        tools = _get_all_tool_definitions()

    if session_id:
        session = repos.sessions.get_by_id(session_id)
        if not session:
            session = repos.sessions.create()
    else:
        session = repos.sessions.create()

    agent = repos.agents.create(
        {
            "session_id": session.id,
            "task": resolved_instructions,
            "config": {
                "model": resolved_model,
                "tools": tools,
            },
        }
    )

    if input_items:
        for item in input_items:
            repos.items.create(agent.id, item)
    else:
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
    input_items: list[dict[str, Any]] | None = None,
    instructions: str = "You are a helpful assistant.",
    model: str | None = None,
    agent_name: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    agent_id = create_agent_for_input(
        repos,
        instructions=instructions,
        input_text=input_text,
        input_items=input_items,
        model=model,
        agent_name=agent_name,
        session_id=session_id,
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


def chat_stream(
    repos: Repositories,
    *,
    input_text: str,
    input_items: list[dict[str, Any]] | None = None,
    instructions: str = "You are a helpful assistant.",
    model: str | None = None,
    agent_name: str | None = None,
    session_id: str | None = None,
) -> Generator[StreamEvent, None, None]:
    """Stream with full multi-turn tool loop (like runAgentStream in TS)."""
    from infra.provider import stream_provider

    agent_id = create_agent_for_input(
        repos,
        instructions=instructions,
        input_text=input_text,
        input_items=input_items,
        model=model,
        agent_name=agent_name,
        session_id=session_id,
    )
    agent = repos.agents.get_by_id(agent_id)
    agent = start_agent(agent)
    repos.agents.update(agent)

    model_name = agent.config.model or DEFAULT_MODEL
    tools_defs = agent.config.tools or _get_all_tool_definitions()

    for _ in range(MAX_TURNS):
        items = repos.items.list_by_agent(agent.id)

        collected_text = ""
        collected_calls: list[dict[str, Any]] = []
        for event in stream_provider(
            model=model_name,
            instructions=agent.task,
            input_items=items,
            tools=tools_defs,
            temperature=agent.config.temperature,
            max_tokens=agent.config.max_tokens,
        ):
            yield event
            if event.type == "text_delta":
                collected_text += event.data.get("delta", "")
            elif event.type == "done":
                collected_calls = event.data.get("function_calls", [])

        if collected_text:
            repos.items.create(agent.id, {"type": "message", "role": "assistant", "content": collected_text})

        if not collected_calls:
            agent = complete_agent(agent, collected_text or None)
            repos.agents.update(agent)
            return

        had_sync_tools = False
        waiting = False
        for fc in collected_calls:
            call_id = fc.get("call_id", "")
            name = fc.get("name", "")
            args = fc.get("arguments", {})
            repos.items.create(agent.id, {"type": "function_call", "call_id": call_id, "name": name, "arguments": args})

            tool_type = get_tool_type(name) or "tool"
            if tool_type == "sync":
                had_sync_tools = True
                if name == "send_message":
                    ok, result = _handle_send_message(call_id=call_id, args=args, sender=agent, repos=repos)
                else:
                    ok, result = execute_sync_tool(name, args)
                repos.items.create(agent.id, {"type": "function_call_output", "call_id": call_id, "output": result, "is_error": not ok})
                yield StreamEvent(type="tool_result", data={"call_id": call_id, "name": name, "output": result, "is_error": not ok})
            elif tool_type == "human":
                waiting = True
                yield StreamEvent(type="waiting", data={"call_id": call_id, "name": name, "description": str(args.get("question", ""))})
            else:
                from infra.mcp_client import get_mcp_manager
                mcp = get_mcp_manager()
                if mcp and mcp.is_mcp_tool(name):
                    had_sync_tools = True
                    ok, result = mcp.call_tool(name, args)
                    repos.items.create(agent.id, {"type": "function_call_output", "call_id": call_id, "output": result, "is_error": not ok})
                    yield StreamEvent(type="tool_result", data={"call_id": call_id, "name": name, "output": result, "is_error": not ok})
                else:
                    waiting = True
                    yield StreamEvent(type="waiting", data={"call_id": call_id, "name": name})

        if waiting:
            return
        if not had_sync_tools:
            return


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

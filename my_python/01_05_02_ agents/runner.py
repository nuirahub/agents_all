"""
Agent runner: in-memory execution loop with waiting support.
Simplified Python port of 4th-devs/01_05_agent runtime.
"""
from __future__ import annotations

from typing import Any

from config import DEFAULT_MODEL, MAX_TURNS
from domain import (
    Agent,
    WaitingFor,
    add_usage,
    complete_agent,
    deliver_one,
    fail_agent,
    increment_turn,
    start_agent,
)
from provider import call_provider
from repositories import Repositories
from tools import execute_sync_tool, get_tool_definitions, get_tool_type
from agent_templates import get_agent_template


class RunError(RuntimeError):
    pass


def _extract_answer(items: list[dict]) -> str | None:
    """Return last assistant message text, if any."""
    texts: list[str] = []
    for item in items:
        if item.get("type") == "message" and item.get("role") == "assistant":
            content = item.get("content")
            if isinstance(content, str):
                texts.append(content)
    return texts[-1] if texts else None


def run_agent(agent_id: str, repos: Repositories, *, max_turns: int = MAX_TURNS) -> dict[str, Any]:
    """
    Execute an agent until it completes or waits for external input.
    Returns dict with keys:
      - status: 'completed' | 'waiting' | 'failed'
      - agent: Agent
      - items: list[dict]
      - waiting_for: list[WaitingFor] (when status == 'waiting')
    """
    agent = repos.agents.get_by_id(agent_id)
    if not agent:
        raise RunError(f"Agent not found: {agent_id}")

    if agent.status == "pending":
        agent = start_agent(agent)
        repos.agents.update(agent)

    if agent.status == "waiting":
        # Just return current state
        items = repos.items.list_by_agent(agent.id)
        return {"status": "waiting", "agent": agent, "items": items, "waiting_for": list(agent.waiting_for)}

    if agent.status not in {"running", "pending"}:
        items = repos.items.list_by_agent(agent.id)
        return {"status": agent.status, "agent": agent, "items": items, "waiting_for": []}

    for _ in range(max_turns):
        items = repos.items.list_by_agent(agent.id)

        tools = agent.config.tools or get_tool_definitions()
        model = agent.config.model or DEFAULT_MODEL

        output_items, usage = call_provider(
            model=model,
            instructions=agent.task,
            input_items=items,
            tools=tools,
            temperature=agent.config.temperature,
            max_tokens=agent.config.max_tokens,
        )

        # Store provider output as new items
        waiting_for: list[WaitingFor] = []
        had_function_calls = False

        for o in output_items:
            if o.get("type") == "message":
                repos.items.create(
                    agent.id,
                    {
                        "type": "message",
                        "role": o.get("role", "assistant"),
                        "content": o.get("content", ""),
                    },
                )
            elif o.get("type") == "function_call":
                had_function_calls = True
                call_id = o.get("call_id") or ""
                name = o.get("name") or ""
                args = o.get("arguments") or {}

                repos.items.create(
                    agent.id,
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": name,
                        "arguments": args,
                    },
                )

                tool_type = get_tool_type(name) or "tool"

                if tool_type == "sync":
                    ok, result = execute_sync_tool(name, args)
                    repos.items.create(
                        agent.id,
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": result,
                            "is_error": not ok,
                        },
                    )
                elif tool_type == "human":
                    waiting_for.append(
                        WaitingFor(
                            call_id=call_id,
                            type="human",
                            name=name,
                            description=str(args.get("question") or ""),
                        )
                    )
                elif tool_type == "agent":
                    # Delegate to child agent. We try to run the child immediately;
                    # if it ends up waiting (e.g. ask_user), the parent will also wait.
                    child_result = _run_delegate_child(
                        parent=agent,
                        call_id=call_id,
                        delegate_args=args,
                        repos=repos,
                        max_turns=max_turns,
                    )
                    if child_result["mode"] == "inline_result":
                        # Child completed synchronously — function_call_output was
                        # already written to parent, nothing more to do here.
                        pass
                    elif child_result["mode"] == "waiting":
                        waiting_for.append(
                            WaitingFor(
                                call_id=call_id,
                                type="agent",
                                name=str(args.get("agent") or name),
                                description=f"Waiting for delegated agent '{args.get('agent')}'",
                            )
                        )
                    else:
                        # Error — store as failed tool output on parent.
                        repos.items.create(
                            agent.id,
                            {
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": child_result["error"],
                                "is_error": True,
                            },
                        )
                else:
                    waiting_for.append(
                        WaitingFor(
                            call_id=call_id,
                            type="tool",
                            name=name,
                            description="External tool",
                        )
                    )

        # Apply usage & turn
        if usage:
            agent = add_usage(agent, usage)
        agent = increment_turn(agent)
        repos.agents.update(agent)

        if waiting_for:
            agent = fail_agent_if_invalid_wait(agent, waiting_for)
            agent = agent if agent.status != "failed" else agent
            agent = agent  # no-op, just clarity
            from domain import wait_for_many

            agent = wait_for_many(agent, waiting_for)
            repos.agents.update(agent)
            items = repos.items.list_by_agent(agent.id)
            return {"status": "waiting", "agent": agent, "items": items, "waiting_for": list(waiting_for)}

        # This turn had sync tool calls (or delegate inline) — run another turn so model can respond with text
        if had_function_calls:
            continue

        # No function calls and no pending tool calls → completed
        answer = _extract_answer(repos.items.list_by_agent(agent.id))
        agent = complete_agent(agent, answer)
        repos.agents.update(agent)
        items = repos.items.list_by_agent(agent.id)
        return {"status": "completed", "agent": agent, "items": items, "waiting_for": []}

    # Max turns exceeded
    agent = fail_agent(agent, f"Max turns exceeded ({max_turns})")
    repos.agents.update(agent)
    items = repos.items.list_by_agent(agent.id)
    return {"status": "failed", "agent": agent, "items": items, "waiting_for": []}


def fail_agent_if_invalid_wait(agent: Agent, waiting_for: list[WaitingFor]) -> Agent:
    # In this simplified runner we don't add extra validation yet.
    return agent


def deliver_result(
    agent_id: str,
    call_id: str,
    *,
    output: str,
    is_error: bool,
    repos: Repositories,
) -> dict[str, Any]:
    """
    Deliver a tool or human result to a waiting agent, then resume execution.
    """
    agent = repos.agents.get_by_id(agent_id)
    if not agent:
        raise RunError(f"Agent not found: {agent_id}")
    if agent.status != "waiting":
        raise RunError(f"Agent not waiting: {agent.status}")

    # Attach result to this agent
    repos.items.create(
        agent.id,
        {
            "type": "function_call_output",
            "call_id": call_id,
            "output": output,
            "is_error": is_error,
        },
    )

    agent = deliver_one(agent, call_id)
    repos.agents.update(agent)

    # If still waiting (multiple outstanding calls), just return.
    if agent.status == "waiting":
        items = repos.items.list_by_agent(agent.id)
        return {"status": "waiting", "agent": agent, "items": items, "waiting_for": list(agent.waiting_for)}

    # Resume this agent.
    result = run_agent(agent.id, repos)

    # Auto‑propagate child result to parent when delegation completes.
    agent_after = result["agent"]
    if (
        result["status"] == "completed"
        and agent_after.parent_id
        and agent_after.source_call_id
    ):
        # Extract final answer and deliver it to the parent as a successful tool result.
        answer = _extract_answer(result["items"]) or ""
        return deliver_result(
            agent_id=agent_after.parent_id,
            call_id=agent_after.source_call_id,
            output=answer,
            is_error=False,
            repos=repos,
        )

    return result


def _run_delegate_child(
    parent: Agent,
    call_id: str,
    delegate_args: dict[str, Any],
    repos: Repositories,
    max_turns: int,
) -> dict[str, Any]:
    """
    Spawn and run a child agent for delegate tool.
    Returns:
      - {"mode": "inline_result"} when child completed and result was attached to parent
      - {"mode": "waiting"} when child is waiting (parent should also wait)
      - {"mode": "error", "error": "..."} on failure
    """
    agent_name = str(delegate_args.get("agent") or "").strip()
    task = str(delegate_args.get("task") or "").strip()
    if not agent_name or not task:
        return {"mode": "error", "error": 'delegate requires "agent" and "task"'}

    tpl = get_agent_template(agent_name)
    if not tpl:
        return {"mode": "error", "error": f"Agent template not found: {agent_name}"}

    # Tools for child: zgodne z listą z szablonu.
    child_tools = get_tool_definitions(tpl.tools) if tpl.tools else get_tool_definitions()

    # Create child agent in the same session.
    child = repos.agents.create(
        {
            "session_id": parent.session_id,
            "trace_id": parent.trace_id,
            "root_agent_id": parent.root_agent_id or parent.id,
            "parent_id": parent.id,
            "source_call_id": call_id,
            "depth": parent.depth + 1,
            "task": task or tpl.system_prompt,
            "config": {
                "model": parent.config.model or DEFAULT_MODEL,
                "tools": child_tools,
            },
        }
    )

    # Initial user message for child.
    repos.items.create(
        child.id,
        {
            "type": "message",
            "role": "user",
            "content": task,
        },
    )

    child_result = run_agent(child.id, repos, max_turns=max_turns)

    if child_result["status"] == "completed":
        # Attach child's final answer as tool result on parent.
        answer = _extract_answer(child_result["items"]) or ""
        repos.items.create(
            parent.id,
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": answer,
                "is_error": False,
            },
        )
        return {"mode": "inline_result"}

    if child_result["status"] == "waiting":
        return {"mode": "waiting"}

    # Failed or other terminal state.
    return {"mode": "error", "error": f"Delegated agent '{agent_name}' failed with status {child_result['status']}"}


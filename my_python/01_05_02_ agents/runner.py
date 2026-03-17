"""
Agent runner: in-memory execution loop with waiting support.
Simplified Python port of 4th-devs/01_05_agent runtime.
"""
from __future__ import annotations

import time
from typing import Any

from config import DEFAULT_MODEL, MAX_TURNS
from domain import (
    Agent,
    WaitingFor,
    add_usage,
    cancel_agent,
    complete_agent,
    deliver_one,
    fail_agent,
    increment_turn,
    start_agent,
)
from events import create_event_context, event_emitter
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

    ctx = create_event_context(
        trace_id=agent.trace_id or "",
        session_id=agent.session_id,
        agent_id=agent.id,
        root_agent_id=agent.root_agent_id,
        depth=agent.depth,
        parent_agent_id=agent.parent_id,
    )

    if agent.status == "waiting":
        items = repos.items.list_by_agent(agent.id)
        return {"status": "waiting", "agent": agent, "items": items, "waiting_for": list(agent.waiting_for)}

    if agent.status not in {"running", "pending"}:
        items = repos.items.list_by_agent(agent.id)
        return {"status": agent.status, "agent": agent, "items": items, "waiting_for": []}

    agent_start_time = time.time()
    model = agent.config.model or DEFAULT_MODEL
    event_emitter.emit({"type": "agent.started", "ctx": ctx, "model": model, "task": agent.task})

    from model_config import get_model_definition
    from pruning import needs_pruning, prune_conversation

    model_def = get_model_definition(model)

    for _ in range(max_turns):
        agent = repos.agents.get_by_id(agent_id) or agent
        if agent.status == "cancelled":
            event_emitter.emit({"type": "agent.cancelled", "ctx": ctx})
            items = repos.items.list_by_agent(agent.id)
            return {"status": "cancelled", "agent": agent, "items": items, "waiting_for": []}

        items = repos.items.list_by_agent(agent.id)
        tools = agent.config.tools or get_tool_definitions()

        event_emitter.emit({"type": "turn.started", "ctx": ctx, "turn_count": agent.turn_count + 1})

        provider_items = items
        if needs_pruning(items, agent.task, model_def.context_window, model_def.pruning.threshold):
            prune_result = prune_conversation(
                items, agent.task, model_def.context_window, model_def.pruning,
            )
            provider_items = prune_result.items
            event_emitter.emit({
                "type": "context.pruned", "ctx": ctx,
                "dropped_count": prune_result.dropped_count,
                "truncated_count": prune_result.truncated_count,
                "estimated_tokens": prune_result.estimated_tokens,
            })

            if (
                prune_result.dropped_items
                and model_def.pruning.enable_summarization
            ):
                session = repos.sessions.get_by_id(agent.session_id)
                if session:
                    from summarization import generate_summary
                    session.summary = generate_summary(
                        prune_result.dropped_items,
                        previous_summary=session.summary,
                        model=model,
                    )
                    repos.sessions.update(session)
                    provider_items = [
                        {"type": "message", "role": "system",
                         "content": f"[Conversation summary]\n{session.summary}"},
                    ] + provider_items

        gen_start = time.time()

        output_items, usage = call_provider(
            model=model,
            instructions=agent.task,
            input_items=provider_items,
            tools=tools,
            temperature=agent.config.temperature,
            max_tokens=agent.config.max_tokens,
        )

        gen_ms = (time.time() - gen_start) * 1000
        usage_dict = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "cached_tokens": usage.cached_tokens,
        } if usage else None
        event_emitter.emit({
            "type": "generation.completed", "ctx": ctx,
            "model": model, "duration_ms": gen_ms, "usage": usage_dict,
        })

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
                    event_emitter.emit({"type": "tool.called", "ctx": ctx, "call_id": call_id, "name": name, "arguments": args})
                    tool_t0 = time.time()

                    if name == "send_message":
                        ok, result = _handle_send_message(
                            call_id=call_id, args=args,
                            sender=agent, repos=repos,
                        )
                    else:
                        ok, result = execute_sync_tool(name, args)

                    tool_ms = (time.time() - tool_t0) * 1000
                    if ok:
                        event_emitter.emit({"type": "tool.completed", "ctx": ctx, "call_id": call_id, "name": name, "output": result, "duration_ms": tool_ms})
                    else:
                        event_emitter.emit({"type": "tool.failed", "ctx": ctx, "call_id": call_id, "name": name, "error": result, "duration_ms": tool_ms})
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
                    # Check MCP tools before deferring
                    from mcp_client import get_mcp_manager
                    mcp = get_mcp_manager()
                    if mcp and mcp.is_mcp_tool(name):
                        ok, result = mcp.call_tool(name, args)
                        repos.items.create(
                            agent.id,
                            {
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": result,
                                "is_error": not ok,
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

        if usage:
            agent = add_usage(agent, usage)
        agent = increment_turn(agent)
        repos.agents.update(agent)
        event_emitter.emit({"type": "turn.completed", "ctx": ctx, "turn_count": agent.turn_count, "usage": usage_dict})

        if waiting_for:
            agent = fail_agent_if_invalid_wait(agent, waiting_for)
            from domain import wait_for_many

            agent = wait_for_many(agent, waiting_for)
            repos.agents.update(agent)
            wf_dicts = [{"call_id": w.call_id, "type": w.type, "name": w.name} for w in waiting_for]
            event_emitter.emit({"type": "agent.waiting", "ctx": ctx, "waiting_for": wf_dicts})
            items = repos.items.list_by_agent(agent.id)
            return {"status": "waiting", "agent": agent, "items": items, "waiting_for": list(waiting_for)}

        if had_function_calls:
            continue

        answer = _extract_answer(repos.items.list_by_agent(agent.id))
        agent = complete_agent(agent, answer)
        repos.agents.update(agent)
        duration_ms = (time.time() - agent_start_time) * 1000
        a_usage = {
            "input_tokens": agent.usage.input_tokens,
            "output_tokens": agent.usage.output_tokens,
            "total_tokens": agent.usage.total_tokens,
            "cached_tokens": agent.usage.cached_tokens,
        } if agent.usage else None
        event_emitter.emit({"type": "agent.completed", "ctx": ctx, "duration_ms": duration_ms, "usage": a_usage, "result": answer})
        items = repos.items.list_by_agent(agent.id)
        return {"status": "completed", "agent": agent, "items": items, "waiting_for": []}

    agent = fail_agent(agent, f"Max turns exceeded ({max_turns})")
    repos.agents.update(agent)
    event_emitter.emit({"type": "agent.failed", "ctx": ctx, "error": agent.error})
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

    child_model = tpl.model or parent.config.model or DEFAULT_MODEL

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
                "model": child_model,
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


def _handle_send_message(
    *,
    call_id: str,
    args: dict[str, Any],
    sender: Agent,
    repos: Repositories,
) -> tuple[bool, str]:
    """Intercept send_message: write a system message into the target agent's items."""
    to = args.get("to")
    message = args.get("message")
    if not to or not message:
        return False, 'send_message requires "to" and "message"'

    target = repos.agents.get_by_id(str(to))
    if not target:
        return False, f"Target agent not found: {to}"

    repos.items.create(
        target.id,
        {
            "type": "message",
            "role": "system",
            "content": f"[Message from agent {sender.id}]\n\n{message}",
        },
    )
    return True, f"Message delivered to agent {to}"


def cancel_running_agent(agent_id: str, repos: Repositories) -> dict[str, Any]:
    """Cancel a running or waiting agent."""
    agent = repos.agents.get_by_id(agent_id)
    if not agent:
        raise RunError(f"Agent not found: {agent_id}")
    if agent.status not in {"running", "waiting", "pending"}:
        raise RunError(f"Cannot cancel agent in status: {agent.status}")
    agent = cancel_agent(agent)
    repos.agents.update(agent)
    items = repos.items.list_by_agent(agent.id)
    return {"status": "cancelled", "agent": agent, "items": items, "waiting_for": []}


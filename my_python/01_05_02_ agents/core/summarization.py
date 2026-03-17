"""
LLM-based summarization — compress dropped conversation items into a checkpoint.
"""
from __future__ import annotations

import json

_INITIAL_PROMPT = """You are a conversation summarizer. Create a structured checkpoint of the conversation so far.

Format your summary as:

## Goal
What the user is trying to accomplish.

## Progress
- Done: what has been completed
- In Progress: what is currently being worked on
- Blocked: any blockers or issues

## Key Decisions
Important decisions made during the conversation.

## Critical Context
Any facts, file paths, variable names, or technical details that must be preserved.

Be concise but preserve ALL technical details (paths, names, values, errors). Never drop specifics."""

_UPDATE_PROMPT = """You are a conversation summarizer. Update the existing summary with new information.

Rules:
- PRESERVE all existing information from the previous summary
- ADD new progress, decisions, and context from the new conversation
- UPDATE the Progress section (move completed items to Done)
- Keep it structured and concise
- Never drop technical specifics (paths, names, values, errors)"""


def serialize_items(items: list[dict]) -> str:
    lines: list[str] = []
    for item in items:
        t = item.get("type")
        if t == "message":
            content = item.get("content", "")
            role = item.get("role", "")
            if isinstance(content, str):
                lines.append(f"[{role}]: {content}")
            elif isinstance(content, list):
                text = "\n".join(
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
                if text:
                    lines.append(f"[{role}]: {text}")
        elif t == "function_call":
            args_str = json.dumps(item.get("arguments", {}), default=str)[:500]
            lines.append(f"[tool call]: {item.get('name', '')}({args_str})")
        elif t == "function_call_output":
            output = item.get("output", "")
            preview = f"{output[:500]}... [truncated]" if len(output) > 500 else output
            lines.append(f"[tool result]: {preview}")
        elif t == "reasoning":
            summary = item.get("summary")
            if summary:
                lines.append(f"[thinking]: {summary}")
    return "\n".join(lines)


def generate_summary(
    dropped_items: list[dict],
    previous_summary: str | None = None,
    *,
    model: str | None = None,
) -> str:
    """Generate an LLM summary of dropped items. Calls the provider synchronously."""
    from infra.provider import call_provider
    from infra.config import DEFAULT_MODEL

    serialized = serialize_items(dropped_items)
    is_update = bool(previous_summary)
    instructions = _UPDATE_PROMPT if is_update else _INITIAL_PROMPT

    if is_update:
        input_text = (
            f"Previous summary:\n{previous_summary}\n\n"
            f"New conversation to incorporate:\n{serialized}"
        )
    else:
        input_text = serialized

    output_items, _ = call_provider(
        model=model or DEFAULT_MODEL,
        instructions=instructions,
        input_items=[{"type": "message", "role": "user", "content": input_text}],
        tools=[],
        temperature=0.3,
        max_tokens=2000,
    )

    for o in output_items:
        if o.get("type") == "message":
            content = o.get("content", "")
            if isinstance(content, str):
                return content
    return ""

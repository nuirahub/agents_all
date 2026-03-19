"""
Agent runtime: loads agent templates from markdown, runs a chat loop
with tool calling, and handles delegation to sub-agents.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from config import client, resolve_model
from tools import find_tool, tools

MAX_DEPTH = 3
MAX_TURNS = 15
WORKSPACE = Path(__file__).resolve().parent / "workspace"


def _truncate(s: str, max_len: int = 100) -> str:
    return s[:max_len] + "…" if len(s) > max_len else s


@dataclass
class AgentTemplate:
    name: str
    model: str
    tools: list[str]
    system_prompt: str


def load_agent(name: str) -> AgentTemplate:
    file_path = WORKSPACE / "agents" / f"{name}.agent.md"
    raw = file_path.read_text(encoding="utf-8")

    meta, body = _parse_front_matter(raw)
    return AgentTemplate(
        name=meta.get("name", name),
        model=meta.get("model", "openai:gpt-4.1-mini"),
        tools=meta.get("tools", []),
        system_prompt=body.strip(),
    )


def _parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except Exception:
        meta = {}
    return meta, parts[2]


async def run_agent(agent_name: str, task: str, depth: int = 0) -> str:
    try:
        if depth > MAX_DEPTH:
            return "Max agent depth exceeded"

        print(f"[{agent_name}] Starting (depth: {depth})")

        template = load_agent(agent_name)

        raw_model = template.model
        if raw_model.startswith("openai:"):
            raw_model = raw_model[7:]
        model = resolve_model(raw_model)

        agent_tools = [t for t in tools if t.name in template.tools]
        openai_tools = [t.to_openai_schema() for t in agent_tools] if agent_tools else None

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": template.system_prompt},
            {"role": "user", "content": task},
        ]

        for turn in range(MAX_TURNS):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=openai_tools,
            )

            message = response.choices[0].message
            if not message:
                return "Agent error: No response from model"

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": message.content,
            }
            if message.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ]
            messages.append(assistant_msg)

            if not message.tool_calls:
                print(f"[{agent_name}] Completed")
                return message.content or ""

            for tool_call in message.tool_calls:
                if tool_call.type != "function":
                    continue

                name = tool_call.function.name
                try:
                    raw_args = tool_call.function.arguments
                    args = json.loads(raw_args) if raw_args and raw_args.strip() else {}
                except (json.JSONDecodeError, TypeError):
                    args = {}

                args_str = _truncate(json.dumps(args))
                print(f"[{agent_name}] Tool: {name}({args_str})")

                if name == "delegate":
                    delegate_agent = args.get("agent", "")
                    delegate_task = args.get("task", "")
                    print(f"[{agent_name}] Delegating to {delegate_agent}: {_truncate(delegate_task)}")
                    result = await run_agent(delegate_agent, delegate_task, depth + 1)
                else:
                    tool = find_tool(name)
                    if tool:
                        result = await tool.handler(args)
                    else:
                        result = f"Unknown tool: {name}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        return "Agent exceeded maximum turns"

    except Exception as e:
        print(f"[{agent_name}] Error: {e}")
        return f"Agent error: {e}"

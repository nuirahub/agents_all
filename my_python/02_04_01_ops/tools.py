"""
Tool definitions and handlers for agents.
Includes data tools (mail, calendar, tasks, notes), file I/O, and delegate.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Awaitable

WORKSPACE = Path(__file__).resolve().parent / "workspace"


def _is_path_safe(rel_path: str) -> bool:
    full = (WORKSPACE / rel_path).resolve()
    return str(full).startswith(str(WORKSPACE.resolve()))


async def _safe_read_json(file_path: Path) -> str:
    try:
        data = file_path.read_text(encoding="utf-8")
        parsed = json.loads(data)
        return json.dumps(parsed)
    except Exception as e:
        return f"Error: {e}"


ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]


class ToolDefinition:
    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


async def _get_mail(args: dict[str, Any]) -> str:
    return await _safe_read_json(WORKSPACE / "sources" / "mail.json")


async def _get_calendar(args: dict[str, Any]) -> str:
    return await _safe_read_json(WORKSPACE / "sources" / "calendar.json")


async def _get_tasks(args: dict[str, Any]) -> str:
    return await _safe_read_json(WORKSPACE / "sources" / "tasks.json")


async def _get_notes(args: dict[str, Any]) -> str:
    return await _safe_read_json(WORKSPACE / "sources" / "notes.json")


async def _read_file(args: dict[str, Any]) -> str:
    try:
        path = args.get("path")
        if not isinstance(path, str):
            return "Error: path must be a string"
        if not _is_path_safe(path):
            return "Error: Path escapes workspace"
        full_path = WORKSPACE / path
        return full_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error: {e}"


async def _write_file(args: dict[str, Any]) -> str:
    try:
        path = args.get("path")
        content = args.get("content")
        if not isinstance(path, str):
            return "Error: path must be a string"
        if not isinstance(content, str):
            return "Error: content must be a string"
        if not _is_path_safe(path):
            return "Error: Path escapes workspace"
        full_path = WORKSPACE / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return f"Wrote {path}"
    except Exception as e:
        return f"Error: {e}"


async def _delegate_stub(args: dict[str, Any]) -> str:
    return json.dumps(args)


tools: list[ToolDefinition] = [
    ToolDefinition(
        name="get_mail",
        description="Read all emails from the mail inbox. Returns JSON array of emails.",
        parameters={"type": "object", "properties": {}},
        handler=_get_mail,
    ),
    ToolDefinition(
        name="get_calendar",
        description="Read all calendar events. Returns JSON array of events.",
        parameters={"type": "object", "properties": {}},
        handler=_get_calendar,
    ),
    ToolDefinition(
        name="get_tasks",
        description="Read all tasks. Returns JSON array of tasks.",
        parameters={"type": "object", "properties": {}},
        handler=_get_tasks,
    ),
    ToolDefinition(
        name="get_notes",
        description="Read all notes. Returns JSON array of notes.",
        parameters={"type": "object", "properties": {}},
        handler=_get_notes,
    ),
    ToolDefinition(
        name="read_file",
        description="Read a file from the workspace directory. Path is relative to workspace root.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace"},
            },
            "required": ["path"],
        },
        handler=_read_file,
    ),
    ToolDefinition(
        name="write_file",
        description="Write content to a file in the workspace directory. Creates parent directories if needed. Path is relative to workspace root.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
        handler=_write_file,
    ),
    ToolDefinition(
        name="delegate",
        description="Delegate a task to another agent. The runner handles actual delegation; this is a marker tool.",
        parameters={
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Name of the agent to delegate to"},
                "task": {"type": "string", "description": "Task description to delegate"},
            },
            "required": ["agent", "task"],
        },
        handler=_delegate_stub,
    ),
]


def find_tool(name: str) -> ToolDefinition | None:
    return next((t for t in tools if t.name == name), None)

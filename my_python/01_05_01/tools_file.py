"""
Native file tools (replacing MCP file server for standalone Python run).
All paths are relative to workspace directory; sandboxed to it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from config import WORKSPACE_DIR

WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)


def _resolve_path(relative_path: str) -> Path:
    """Resolve path relative to workspace; forbid escape."""
    base = WORKSPACE_DIR.resolve()
    resolved = (base / relative_path).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        raise ValueError(f'Path "{relative_path}" is outside workspace')
    return resolved


def fs_list(path: str) -> dict[str, Any]:
    """List directory contents. path: relative to workspace (e.g. '.' or 'output')."""
    full = _resolve_path(path)
    if not full.exists():
        return {"entries": [], "path": path}
    if not full.is_dir():
        return {"error": f"Not a directory: {path}"}
    entries = []
    for p in sorted(full.iterdir()):
        entries.append({"name": p.name, "type": "directory" if p.is_dir() else "file"})
    return {"entries": entries, "path": path}


def fs_read(path: str) -> dict[str, Any]:
    """Read file contents. path: relative to workspace."""
    full = _resolve_path(path)
    if not full.exists():
        return {"error": f"File not found: {path}"}
    if full.is_dir():
        return {"error": f"Cannot read directory: {path}"}
    try:
        content = full.read_text(encoding="utf-8")
        return {"content": content, "path": path}
    except Exception as e:
        return {"error": str(e)}


def fs_write(path: str, content: str) -> dict[str, Any]:
    """Write content to file (creates or overwrites). path: relative to workspace."""
    full = _resolve_path(path)
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return {"success": True, "path": path}


def fs_search(path: str, pattern: str) -> dict[str, Any]:
    """Search for files matching pattern under path. pattern: glob like '*.md'."""
    full = _resolve_path(path)
    if not full.exists():
        return {"matches": [], "path": path}
    if not full.is_dir():
        return {"error": f"Not a directory: {path}"}
    matches = []
    for p in full.rglob(pattern):
        if p.is_file():
            try:
                rel = p.relative_to(full)
                matches.append(str(rel))
            except ValueError:
                pass
    return {"matches": sorted(matches), "path": path}


# OpenAI-style tool definitions for Responses API
FILE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "fs_list",
        "description": "List directory contents. Use path relative to workspace (e.g. '.' or 'output').",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Relative path"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": False,
    },
    {
        "type": "function",
        "name": "fs_read",
        "description": "Read file contents. Path relative to workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Relative path to file"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": False,
    },
    {
        "type": "function",
        "name": "fs_write",
        "description": "Write content to file (creates or overwrites). Path relative to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to file"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        "strict": False,
    },
    {
        "type": "function",
        "name": "fs_search",
        "description": "Search for files matching a glob pattern under path (e.g. '*.md').",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to directory to search"},
                "pattern": {"type": "string", "description": "Glob pattern (e.g. '*.md')"},
            },
            "required": ["path", "pattern"],
            "additionalProperties": False,
        },
        "strict": False,
    },
]

FILE_HANDLERS: dict[str, Any] = {
    "fs_list": lambda a: fs_list(a["path"]),
    "fs_read": lambda a: fs_read(a["path"]),
    "fs_write": lambda a: fs_write(a["path"], a["content"]),
    "fs_search": lambda a: fs_search(a["path"], a["pattern"]),
}

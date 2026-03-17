"""
Loader szablonów agentów w stylu 4th-devs/01_05_agent/workspace/agents/*.agent.md.

Format pliku:
---
name: alice
tools:
  - calculator
  - delegate
---
<treść promptu markdown>
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parent
AGENTS_DIR = ROOT_DIR / "workspace" / "agents"


@dataclass(frozen=True)
class AgentTemplate:
    name: str
    tools: list[str]
    system_prompt: str
    model: str | None = None


_CACHE: dict[str, AgentTemplate] | None = None


def _parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """
    Prosty parser front-matter:
    ---\n
    yaml...\n
    ---\n
    reszta
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    _, yaml_part, body = parts
    meta = yaml.safe_load(yaml_part) or {}
    return meta, body.lstrip("\n")


def _load_all() -> dict[str, AgentTemplate]:
    cache: dict[str, AgentTemplate] = {}
    if not AGENTS_DIR.exists():
        return cache

    for path in AGENTS_DIR.glob("*.agent.md"):
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_front_matter(text)
        name = str(meta.get("name") or path.stem)
        tools = list(meta.get("tools") or [])
        model = str(meta["model"]) if meta.get("model") else None
        tpl = AgentTemplate(name=name, tools=tools, system_prompt=body.strip(), model=model)
        cache[name] = tpl
    return cache


def _ensure_cache() -> dict[str, AgentTemplate]:
    global _CACHE
    if _CACHE is None:
        _CACHE = _load_all()
    return _CACHE


def get_agent_template(name: str) -> AgentTemplate | None:
    """
    Zwraca szablon agenta o podanej nazwie (np. 'alice'), albo None.
    """
    return _ensure_cache().get(name)


def list_agent_templates() -> list[AgentTemplate]:
    """
    Lista wszystkich załadowanych szablonów.
    """
    return list(_ensure_cache().values())


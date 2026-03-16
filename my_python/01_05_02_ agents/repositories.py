"""
In-memory repositories for sessions, agents, and items.
Port of 4th-devs/01_05_agent repositories/memory.
"""
from __future__ import annotations

import uuid
from typing import Any

from domain import Agent, AgentConfig, Session, WaitingFor
from domain import (
    is_function_call,
    is_function_call_output,
    is_message,
)

UserId = str
SessionId = str
AgentId = str
ItemId = str
CallId = str


def _new_id() -> str:
    return str(uuid.uuid4())


class SessionRepository:
    def __init__(self) -> None:
        self._store: dict[SessionId, Session] = {}

    def create(self, user_id: UserId | None = None, title: str | None = None) -> Session:
        s = Session(id=_new_id(), user_id=user_id, title=title)
        self._store[s.id] = s
        return s

    def get_by_id(self, id: SessionId) -> Session | None:
        return self._store.get(id)

    def update(self, session: Session) -> Session:
        self._store[session.id] = session
        return session


class AgentRepository:
    def __init__(self) -> None:
        self._store: dict[AgentId, Agent] = {}

    def create(self, input: dict[str, Any]) -> Agent:
        agent_id = _new_id()
        config = input.get("config") or {}
        agent = Agent(
            id=agent_id,
            session_id=input["session_id"],
            trace_id=input.get("trace_id"),
            root_agent_id=input.get("root_agent_id") or agent_id,
            parent_id=input.get("parent_id"),
            source_call_id=input.get("source_call_id"),
            depth=input.get("depth", 0),
            task=input.get("task", ""),
            config=AgentConfig(
                model=config.get("model", ""),
                temperature=config.get("temperature"),
                max_tokens=config.get("max_tokens"),
                tools=config.get("tools"),
            ),
        )
        self._store[agent.id] = agent
        return agent

    def get_by_id(self, id: AgentId) -> Agent | None:
        return self._store.get(id)

    def update(self, agent: Agent) -> Agent:
        self._store[agent.id] = agent
        return agent

    def find_waiting_for_call(self, call_id: CallId) -> Agent | None:
        for agent in self._store.values():
            if agent.status == "waiting":
                for w in agent.waiting_for:
                    if w.call_id == call_id:
                        return agent
        return None


class ItemRepository:
    def __init__(self) -> None:
        self._store: dict[ItemId, dict] = {}
        self._by_agent: dict[AgentId, list[dict]] = {}
        self._sequences: dict[AgentId, int] = {}

    def _next_seq(self, agent_id: AgentId) -> int:
        n = self._sequences.get(agent_id, 0) + 1
        self._sequences[agent_id] = n
        return n

    def create(self, agent_id: AgentId, input: dict[str, Any]) -> dict:
        item_id = _new_id()
        seq = self._next_seq(agent_id)
        item = {
            "id": item_id,
            "agent_id": agent_id,
            "sequence": seq,
            "turn_number": input.get("turn_number"),
            "created_at": __import__("datetime").datetime.now(),
            **input,
        }
        self._store[item_id] = item
        self._by_agent.setdefault(agent_id, []).append(item)
        self._by_agent[agent_id].sort(key=lambda x: x["sequence"])
        return item

    def get_by_id(self, id: ItemId) -> dict | None:
        return self._store.get(id)

    def list_by_agent(self, agent_id: AgentId) -> list[dict]:
        return sorted(self._by_agent.get(agent_id, []), key=lambda x: x["sequence"])


class Repositories:
    def __init__(self) -> None:
        self.sessions = SessionRepository()
        self.agents = AgentRepository()
        self.items = ItemRepository()

    async def ping(self) -> bool:
        return True


def create_memory_repositories() -> Repositories:
    return Repositories()

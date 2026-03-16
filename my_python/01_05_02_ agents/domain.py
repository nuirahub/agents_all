"""
Domain types: Agent, Session, Item and state transitions.
Port of 4th-devs/01_05_agent domain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ID types
AgentId = str
SessionId = str
ItemId = str
CallId = str
TraceId = str
UserId = str

AgentStatus = str  # 'pending' | 'running' | 'waiting' | 'completed' | 'failed' | 'cancelled'
MessageRole = str  # 'user' | 'assistant' | 'system'
WaitType = str  # 'tool' | 'agent' | 'human'


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class WaitingFor:
    call_id: CallId
    type: WaitType
    name: str
    description: str | None = None


@dataclass
class AgentConfig:
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None


@dataclass
class Agent:
    id: AgentId
    session_id: SessionId
    trace_id: TraceId | None = None
    root_agent_id: AgentId = ""
    parent_id: AgentId | None = None
    source_call_id: CallId | None = None
    depth: int = 0
    task: str = ""
    config: AgentConfig = field(default_factory=lambda: AgentConfig(model=""))
    status: AgentStatus = "pending"
    waiting_for: list[WaitingFor] = field(default_factory=list)
    result: Any = None
    error: str | None = None
    turn_count: int = 0
    usage: TokenUsage | None = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.root_agent_id:
            self.root_agent_id = self.id


@dataclass
class Session:
    id: SessionId
    user_id: UserId | None = None
    root_agent_id: AgentId | None = None
    title: str | None = None
    summary: str | None = None
    status: str = "active"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime | None = None


# Item types
@dataclass
class MessageItem:
    type: str = "message"
    id: ItemId = ""
    agent_id: AgentId = ""
    sequence: int = 0
    turn_number: int | None = None
    created_at: datetime = field(default_factory=datetime.now)
    role: MessageRole = "user"
    content: str | list[dict[str, Any]] = ""


@dataclass
class FunctionCallItem:
    type: str = "function_call"
    id: ItemId = ""
    agent_id: AgentId = ""
    sequence: int = 0
    turn_number: int | None = None
    created_at: datetime = field(default_factory=datetime.now)
    call_id: CallId = ""
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class FunctionCallOutputItem:
    type: str = "function_call_output"
    id: ItemId = ""
    agent_id: AgentId = ""
    sequence: int = 0
    turn_number: int | None = None
    created_at: datetime = field(default_factory=datetime.now)
    call_id: CallId = ""
    output: str = ""
    is_error: bool = False


def is_message(item: dict) -> bool:
    return item.get("type") == "message"


def is_function_call(item: dict) -> bool:
    return item.get("type") == "function_call"


def is_function_call_output(item: dict) -> bool:
    return item.get("type") == "function_call_output"


# State transitions
def start_agent(agent: Agent, trace_id: TraceId | None = None) -> Agent:
    if agent.status != "pending":
        raise ValueError(f"Cannot start agent in status: {agent.status}")
    agent.status = "running"
    agent.started_at = datetime.now()
    if trace_id:
        agent.trace_id = trace_id
    return agent


def wait_for_many(agent: Agent, waiting: list[WaitingFor]) -> Agent:
    if agent.status != "running":
        raise ValueError(f"Cannot wait agent in status: {agent.status}")
    agent.status = "waiting"
    agent.waiting_for = waiting
    return agent


def deliver_one(agent: Agent, call_id: CallId) -> Agent:
    if agent.status != "waiting":
        raise ValueError(f"Cannot deliver to agent in status: {agent.status}")
    remaining = [w for w in agent.waiting_for if w.call_id != call_id]
    if len(remaining) == len(agent.waiting_for):
        raise ValueError(f"Agent not waiting for callId: {call_id}")
    agent.waiting_for = remaining
    agent.status = "running" if not remaining else "waiting"
    return agent


def complete_agent(agent: Agent, result: Any = None) -> Agent:
    if agent.status != "running":
        raise ValueError(f"Cannot complete agent in status: {agent.status}")
    agent.status = "completed"
    agent.result = result
    agent.completed_at = datetime.now()
    return agent


def fail_agent(agent: Agent, error: str) -> Agent:
    agent.status = "failed"
    agent.error = error
    agent.completed_at = datetime.now()
    return agent


def increment_turn(agent: Agent) -> Agent:
    agent.turn_count += 1
    return agent


def add_usage(agent: Agent, usage: TokenUsage) -> Agent:
    if agent.usage is None:
        agent.usage = TokenUsage()
    agent.usage.input_tokens += usage.input_tokens
    agent.usage.output_tokens += usage.output_tokens
    agent.usage.total_tokens += usage.total_tokens
    agent.usage.cached_tokens += getattr(usage, "cached_tokens", 0) or 0
    return agent

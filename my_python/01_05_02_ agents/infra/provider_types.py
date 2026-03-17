"""Provider abstraction — protocol and shared types for multi-provider support."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generator, Protocol, runtime_checkable

from core.domain import TokenUsage


@dataclass
class ProviderRequest:
    model: str
    instructions: str
    input_items: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass
class ProviderResponse:
    output: list[dict[str, Any]]
    usage: TokenUsage | None = None


@dataclass
class StreamEvent:
    """Unified stream event emitted by providers."""
    type: str
    data: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Provider(Protocol):
    @property
    def name(self) -> str: ...

    def generate(self, request: ProviderRequest) -> ProviderResponse: ...

    def stream(self, request: ProviderRequest) -> Generator[StreamEvent, None, None]: ...

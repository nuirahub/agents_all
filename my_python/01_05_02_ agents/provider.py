"""
Provider facade — backward-compatible call_provider() + stream_provider()
using the provider registry. Supports 'provider:model' syntax.
"""
from __future__ import annotations

from typing import Generator

from domain import TokenUsage
from provider_types import ProviderRequest, StreamEvent
from provider_registry import resolve_provider, get_default_provider


def call_provider(
    *,
    model: str,
    instructions: str,
    input_items: list[dict],
    tools: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[list[dict], TokenUsage | None]:
    """
    Call the appropriate provider based on model string.
    Supports 'provider:model' syntax (e.g. 'gemini:gemini-2.5-flash').
    Falls back to default provider if no ':' prefix.
    """
    provider, actual_model = _resolve(model)

    request = ProviderRequest(
        model=actual_model,
        instructions=instructions,
        input_items=input_items,
        tools=tools,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    response = provider.generate(request)
    return response.output, response.usage


def stream_provider(
    *,
    model: str,
    instructions: str,
    input_items: list[dict],
    tools: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Generator[StreamEvent, None, None]:
    """Stream from the appropriate provider. Yields StreamEvent objects."""
    provider, actual_model = _resolve(model)

    request = ProviderRequest(
        model=actual_model,
        instructions=instructions,
        input_items=input_items,
        tools=tools,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    yield from provider.stream(request)


def _resolve(model: str):
    """Resolve model string to (provider, actual_model)."""
    resolved = resolve_provider(model)
    if resolved:
        return resolved
    provider = get_default_provider()
    if not provider:
        raise RuntimeError("No provider registered. Check config and .env.")
    return provider, model

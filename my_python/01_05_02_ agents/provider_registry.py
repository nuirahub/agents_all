"""
Provider registry — register and resolve providers by name.
Supports 'provider:model' syntax (e.g. 'openai:gpt-4.1', 'gemini:gemini-2.5-flash').
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from provider_types import Provider

_providers: dict[str, Provider] = {}
_default_provider_name: str | None = None


def register_provider(provider: Provider) -> None:
    _providers[provider.name] = provider


def set_default_provider(name: str) -> None:
    global _default_provider_name
    _default_provider_name = name


def get_provider(name: str) -> Provider | None:
    return _providers.get(name)


def get_default_provider() -> Provider | None:
    if _default_provider_name:
        return _providers.get(_default_provider_name)
    if _providers:
        return next(iter(_providers.values()))
    return None


def list_providers() -> list[str]:
    return list(_providers.keys())


def parse_model_string(model_string: str) -> tuple[str, str] | None:
    """Parse 'openai:gpt-4.1' -> ('openai', 'gpt-4.1'). Returns None if no ':' found."""
    idx = model_string.find(":")
    if idx == -1:
        return None
    return model_string[:idx], model_string[idx + 1:]


def resolve_provider(model_string: str) -> tuple[Provider, str] | None:
    """Resolve 'provider:model' to (Provider, model). Returns None if provider not found."""
    parsed = parse_model_string(model_string)
    if not parsed:
        return None
    provider = _providers.get(parsed[0])
    if not provider:
        return None
    return provider, parsed[1]

"""
Model registry — context windows, output limits, and pruning thresholds.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PruningThresholds:
    threshold: float = 0.85
    target_utilization: float = 0.5
    min_recent_turns: int = 3
    max_tool_output_chars: int = 10_000
    enable_summarization: bool = False


@dataclass(frozen=True)
class ModelDefinition:
    id: str
    provider: str
    context_window: int
    max_output_tokens: int
    pruning: PruningThresholds


DEFAULT_PRUNING = PruningThresholds()

_GEMINI_PRUNING = PruningThresholds(
    threshold=0.90,
    target_utilization=0.6,
    min_recent_turns=10,
)

MODELS: dict[str, ModelDefinition] = {
    "gpt-4.1": ModelDefinition(
        id="gpt-4.1", provider="openai",
        context_window=1_000_000, max_output_tokens=32_768,
        pruning=PruningThresholds(min_recent_turns=5),
    ),
    "gpt-4.1-mini": ModelDefinition(
        id="gpt-4.1-mini", provider="openai",
        context_window=1_000_000, max_output_tokens=32_768,
        pruning=DEFAULT_PRUNING,
    ),
    "gpt-4.1-nano": ModelDefinition(
        id="gpt-4.1-nano", provider="openai",
        context_window=1_000_000, max_output_tokens=32_768,
        pruning=DEFAULT_PRUNING,
    ),
    "gpt-4o": ModelDefinition(
        id="gpt-4o", provider="openai",
        context_window=128_000, max_output_tokens=16_384,
        pruning=DEFAULT_PRUNING,
    ),
    "gpt-4o-mini": ModelDefinition(
        id="gpt-4o-mini", provider="openai",
        context_window=128_000, max_output_tokens=16_384,
        pruning=DEFAULT_PRUNING,
    ),
    "gemini-2.5-flash": ModelDefinition(
        id="gemini-2.5-flash", provider="gemini",
        context_window=1_048_576, max_output_tokens=65_536,
        pruning=_GEMINI_PRUNING,
    ),
    "gemini-2.5-pro": ModelDefinition(
        id="gemini-2.5-pro", provider="gemini",
        context_window=1_048_576, max_output_tokens=65_536,
        pruning=_GEMINI_PRUNING,
    ),
}

_FALLBACK = ModelDefinition(
    id="unknown", provider="openai",
    context_window=128_000, max_output_tokens=16_000,
    pruning=DEFAULT_PRUNING,
)


def get_model_definition(model_id: str) -> ModelDefinition:
    """Resolve model definition. Falls back to conservative defaults for unknown models."""
    if model_id in MODELS:
        return MODELS[model_id]
    for key in MODELS:
        if model_id.endswith(key) or key in model_id:
            return MODELS[key]
    return ModelDefinition(
        id=model_id, provider=_FALLBACK.provider,
        context_window=_FALLBACK.context_window,
        max_output_tokens=_FALLBACK.max_output_tokens,
        pruning=_FALLBACK.pruning,
    )

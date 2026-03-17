"""
Context pruning — truncate large outputs, drop old turns, keep recent.

Operates on domain Items in-memory. DB history stays intact (audit trail).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from model_config import PruningThresholds
from tokens import estimate_conversation_tokens


@dataclass
class PruningResult:
    items: list[dict]
    estimated_tokens: int
    dropped_count: int
    truncated_count: int
    dropped_items: list[dict] = field(default_factory=list)


def truncate_tool_output(output: str, max_chars: int) -> str:
    if len(output) <= max_chars:
        return output
    half = max_chars // 2
    dropped = len(output) - max_chars
    return f"{output[:half]}\n\n[... {dropped} characters truncated ...]\n\n{output[-half:]}"


def _truncate_large_outputs(
    items: list[dict], max_chars: int
) -> tuple[list[dict], int]:
    truncated_count = 0
    result: list[dict] = []
    for item in items:
        if item.get("type") != "function_call_output":
            result.append(item)
            continue
        output = item.get("output", "")
        if len(output) <= max_chars:
            result.append(item)
            continue
        truncated_count += 1
        result.append({**item, "output": truncate_tool_output(output, max_chars)})
    return result, truncated_count


def _identify_turns(items: list[dict]) -> list[dict]:
    """Group items into turns. A turn starts with a user message."""
    turns: list[dict] = []
    current_start = 0

    for i, item in enumerate(items):
        if (
            item.get("type") == "message"
            and item.get("role") == "user"
            and i > 0
        ):
            turns.append({
                "start": current_start,
                "end": i - 1,
                "items": items[current_start:i],
            })
            current_start = i

    if current_start < len(items):
        turns.append({
            "start": current_start,
            "end": len(items) - 1,
            "items": items[current_start:],
        })

    return turns


def prune_conversation(
    items: list[dict],
    system_prompt: str | None,
    context_window: int,
    config: PruningThresholds,
) -> PruningResult:
    """
    Prune conversation items to fit within token budget.

    Strategy:
      1. Truncate individual large tool outputs
      2. If still over budget, drop oldest complete turns (keep last N)
      3. Always preserve: first turn + last min_recent_turns
    """
    target_tokens = int(context_window * config.target_utilization)

    truncated, truncated_count = _truncate_large_outputs(
        items, config.max_tool_output_chars
    )

    estimate = estimate_conversation_tokens(truncated, system_prompt)
    if estimate <= target_tokens:
        return PruningResult(
            items=truncated,
            estimated_tokens=estimate,
            dropped_count=0,
            truncated_count=truncated_count,
        )

    turns = _identify_turns(truncated)

    if len(turns) <= config.min_recent_turns:
        return PruningResult(
            items=truncated,
            estimated_tokens=estimate,
            dropped_count=0,
            truncated_count=truncated_count,
        )

    keep_first = turns[0]
    keep_recent = turns[-config.min_recent_turns :]
    droppable = list(turns[1 : -config.min_recent_turns])

    dropped_items: list[dict] = []
    dropped_count = 0

    while droppable:
        dropped_turn = droppable.pop(0)
        dropped_items.extend(dropped_turn["items"])
        dropped_count += len(dropped_turn["items"])

        remaining_items = (
            keep_first["items"]
            + [it for t in droppable for it in t["items"]]
            + [it for t in keep_recent for it in t["items"]]
        )

        estimate = estimate_conversation_tokens(remaining_items, system_prompt)
        if estimate <= target_tokens:
            return PruningResult(
                items=remaining_items,
                estimated_tokens=estimate,
                dropped_count=dropped_count,
                truncated_count=truncated_count,
                dropped_items=dropped_items,
            )

    final_items = keep_first["items"] + [
        it for t in keep_recent for it in t["items"]
    ]
    estimate = estimate_conversation_tokens(final_items, system_prompt)

    return PruningResult(
        items=final_items,
        estimated_tokens=estimate,
        dropped_count=dropped_count,
        truncated_count=truncated_count,
        dropped_items=dropped_items,
    )


def needs_pruning(
    items: list[dict],
    system_prompt: str | None,
    context_window: int,
    threshold: float,
) -> bool:
    estimate = estimate_conversation_tokens(items, system_prompt)
    return estimate > context_window * threshold

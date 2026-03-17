"""
Token estimation — character-based heuristic.

~4 chars per token for English text. We use a conservative multiplier (3.5)
so estimates run slightly high, giving a safety margin before hitting limits.
"""
from __future__ import annotations

CHARS_PER_TOKEN = 3.5


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / CHARS_PER_TOKEN + 0.99))


def _item_text_length(item: dict) -> int:
    t = item.get("type")
    if t == "message":
        content = item.get("content", "")
        if isinstance(content, str):
            return len(content)
        if isinstance(content, list):
            return sum(
                len(p.get("text", ""))
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        return 0
    if t == "function_call":
        import json

        return len(item.get("name", "")) + len(
            json.dumps(item.get("arguments", {}), default=str)
        )
    if t == "function_call_output":
        return len(item.get("output", ""))
    if t == "reasoning":
        return len(item.get("summary", "") or "")
    return 0


def estimate_item_tokens(item: dict) -> int:
    return max(1, int(_item_text_length(item) / CHARS_PER_TOKEN + 0.99))


def estimate_conversation_tokens(items: list[dict], system_prompt: str | None = None) -> int:
    chars = len(system_prompt) if system_prompt else 0
    for item in items:
        chars += _item_text_length(item)
        chars += 20  # overhead per item (role tags, separators, etc.)
    return max(1, int(chars / CHARS_PER_TOKEN + 0.99))

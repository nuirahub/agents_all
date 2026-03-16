from __future__ import annotations

from typing import Any, Dict, List


def extract_response_text(data: Dict[str, Any]) -> str:
    """
    Python odpowiednik `extractResponseText` z helpers.js.

    Szuka:
    1. `output_text` (string na najwyższym poziomie), albo
    2. w `output` szuka wiadomości typu `message` i w nich części `output_text`.
    """
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    messages: List[Dict[str, Any]] = []
    raw_output = data.get("output")
    if isinstance(raw_output, list):
        messages = [item for item in raw_output if isinstance(item, dict) and item.get("type") == "message"]

    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue

        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
            ):
                return part["text"]

    return ""


def to_message(role: str, content: str) -> Dict[str, Any]:
    """
    Python odpowiednik `toMessage` z helpers.js.
    """
    return {"type": "message", "role": role, "content": content}


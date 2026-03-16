from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

# Ensure parent directory (`my_python`) is on sys.path so we can import shared helpers and config
PARENT_DIR = Path(__file__).resolve().parents[1]
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))

from config import CONFIG  # noqa: E402
from helpers import extract_response_text, to_message  # noqa: E402

logger = logging.getLogger(__name__)
MODEL = CONFIG.resolve_model_for_provider("gpt-5.2")


@dataclass
class ChatResult:
    text: str
    reasoning_tokens: int


def chat(input_text: str, history: list[dict[str, Any]] | None = None) -> ChatResult:
    if history is None:
        history = []

    logger.info("Sending chat request")

    body = {
        "model": MODEL,
        "input": [*history, to_message("user", input_text)],
        "reasoning": {"effort": "medium"},
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CONFIG.api_key}",
        **CONFIG.extra_api_headers,
    }

    response = requests.post(
        CONFIG.responses_api_endpoint,
        json=body,
        headers=headers,
        timeout=60,
    )

    try:
        data = response.json()
    except ValueError:
        response.raise_for_status()
        raise

    if (not response.ok) or (isinstance(data, dict) and data.get("error")):
        message = (
            data.get("error", {}).get("message")
            if isinstance(data, dict)
            else f"Request failed with status {response.status_code}"
        )
        logger.error("Chat request failed: %s", message)
        raise RuntimeError(
            message or f"Request failed with status {response.status_code}"
        )

    text = extract_response_text(data)
    if not text:
        logger.error("Missing text output in API response")
        raise RuntimeError("Missing text output in API response")

    usage = data.get("usage") if isinstance(data, dict) else {}
    output_details = (
        usage.get("output_tokens_details") if isinstance(usage, dict) else {}
    )
    reasoning_tokens = (
        output_details.get("reasoning_tokens", 0)
        if isinstance(output_details, dict)
        else 0
    )

    logger.info("Received chat response (reasoning_tokens=%s)", reasoning_tokens)

    return ChatResult(text=text, reasoning_tokens=reasoning_tokens)


def main() -> None:
    logger.info("Starting demo conversation")

    first_question = "What is 25 * 48?"
    first_answer = chat(first_question)

    second_question = "Divide that by 4."
    second_question_context: list[dict[str, Any]] = [
        {
            "type": "message",
            "role": "user",
            "content": first_question,
        },
        {
            "type": "message",
            "role": "assistant",
            "content": first_answer.text,
        },
    ]
    second_answer = chat(second_question, second_question_context)

    print("Q:", first_question)
    print(
        "A:", first_answer.text, f"({first_answer.reasoning_tokens} reasoning tokens)"
    )
    print("Q:", second_question)
    print(
        "A:", second_answer.text, f"({second_answer.reasoning_tokens} reasoning tokens)"
    )

    logger.info("Demo conversation finished")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    try:
        main()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled error in main: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)

# https://story.aidevs.pl/intro

from __future__ import annotations

import json
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
from helpers import extract_response_text  # noqa: E402

logger = logging.getLogger(__name__)
MODEL = CONFIG.resolve_model_for_provider("gpt-5.4")


PERSON_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "name": "person",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": ["string", "null"],
                "description": "Full name of the person. Use null if not mentioned.",
            },
            "age": {
                "type": ["number", "null"],
                "description": "Age in years. Use null if not mentioned or unclear.",
            },
            "occupation": {
                "type": ["string", "null"],
                "description": "Job title or profession. Use null if not mentioned.",
            },
            "skills": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of skills, technologies, or competencies. "
                    "Empty array if none mentioned."
                ),
            },
        },
        "required": ["name", "age", "occupation", "skills"],
        "additionalProperties": False,
    },
}


@dataclass
class Person:
    name: str | None
    age: int | None
    occupation: str | None
    skills: list[str]


def _person_from_dict(data: dict[str, Any]) -> Person:
    return Person(
        name=data.get("name"),
        age=data.get("age"),
        occupation=data.get("occupation"),
        skills=list(data.get("skills") or []),
    )


def extract_person(text: str) -> Person:
    logger.info("Sending structured extraction request")

    body = {
        "model": MODEL,
        "input": f'Extract person information from: "{text}"',
        "text": {"format": PERSON_SCHEMA},
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
        logger.error("Structured extraction request failed: %s", message)
        raise RuntimeError(
            message or f"Request failed with status {response.status_code}"
        )

    output_text = extract_response_text(data)
    if not output_text:
        logger.error("Missing text output in API response")
        raise RuntimeError("Missing text output in API response")

    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:  # noqa: TRY003
        logger.error("Failed to parse JSON from model output: %s", exc)
        raise RuntimeError("Model returned invalid JSON for person schema") from exc

    if not isinstance(parsed, dict):
        logger.error("Parsed JSON is not an object: %r", parsed)
        raise RuntimeError("Model output is not a JSON object for person schema")

    person = _person_from_dict(parsed)
    logger.info("Structured extraction succeeded for name=%r", person.name)
    return person


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting structured output demo")

    text = (
        "John is 30 years old and works as a software engineer. "
        "He is skilled in JavaScript, Python, and React."
    )
    person = extract_person(text)

    print("Name:", person.name or "unknown")
    print("Age:", person.age if person.age is not None else "unknown")
    print("Occupation:", person.occupation or "unknown")
    print("Skills:", ", ".join(person.skills) if person.skills else "none")

    logger.info("Structured output demo finished")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled error in main: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)

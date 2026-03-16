import json
import os
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set in the environment.")


RESPONSES_API_ENDPOINT = "https://api.openai.com/v1/responses"

model = "gpt-4.1-mini"

# `web_search_preview` is the built‑in OpenAI tool for web search.
WEB_SEARCH_TOOL: Dict[str, Any] = {"type": "web_search_preview"}


tools: List[Dict[str, Any]] = [
    {
        "type": "function",
        "name": "get_weather",
        "description": "Get current weather for a given location",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name",
                },
            },
            "required": ["location"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "send_email",
        "description": "Send a short email message to a recipient",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject",
                },
                "body": {
                    "type": "string",
                    "description": "Plain‑text email body",
                },
            },
            "required": ["to", "subject", "body"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'"{field_name}" must be a non-empty string.')
    return value.strip()


def handle_get_weather(args: Dict[str, Any]) -> Dict[str, Any]:
    city = require_text(args.get("location"), "location")
    weather = {
        "Kraków": {"temp": -2, "conditions": "snow"},
        "London": {"temp": 8, "conditions": "rain"},
        "Tokyo": {"temp": 15, "conditions": "cloudy"},
    }
    return weather.get(city, {"temp": None, "conditions": "unknown"})


def handle_send_email(args: Dict[str, Any]) -> Dict[str, Any]:
    recipient = require_text(args.get("to"), "to")
    email_subject = require_text(args.get("subject"), "subject")
    email_body = require_text(args.get("body"), "body")

    return {
        "success": True,
        "status": "sent",
        "to": recipient,
        "subject": email_subject,
        "body": email_body,
    }


handlers = {
    "get_weather": handle_get_weather,
    "send_email": handle_send_email,
}


def get_tool_calls(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        item
        for item in response.get("output", [])
        if item.get("type") == "function_call"
    ]


def get_final_text(response: Dict[str, Any]) -> str:
    if response.get("output_text") is not None:
        return str(response["output_text"])

    for item in response.get("output", []):
        if item.get("type") == "message":
            content = item.get("content") or []
            if content and isinstance(content[0], dict) and "text" in content[0]:
                return str(content[0]["text"])

    return "No response"


def log(label: str, text: str) -> None:
    print(f"[{label}] {text}")


def log_json(label: str, value: Any) -> None:
    print(f"[{label}] {json.dumps(value, indent=2, ensure_ascii=False)}")


def execute_tool_call(call: Dict[str, Any]) -> Dict[str, Any]:
    args = json.loads(call.get("arguments") or "{}")
    name = call.get("name")
    handler = handlers.get(name)
    if handler is None:
        raise RuntimeError(f"Unknown tool: {name}")

    log("TOOL", name or "")
    log_json("ARGS", args)
    result = handler(args)
    log_json("RESULT", result)

    return {
        "type": "function_call_output",
        "call_id": call.get("call_id"),
        "output": json.dumps(result, ensure_ascii=False),
    }


def build_next_conversation(
    conversation: List[Dict[str, Any]],
    tool_calls: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    tool_results = [execute_tool_call(call) for call in tool_calls]
    return [*conversation, *tool_calls, *tool_results]


def request_response(conversation: List[Dict[str, Any]]) -> Dict[str, Any]:
    body = {
        "model": model,
        "input": conversation,
        "tools": [WEB_SEARCH_TOOL, *tools],
    }

    response = requests.post(
        RESPONSES_API_ENDPOINT,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        data=json.dumps(body),
        timeout=60,
    )

    data = response.json()
    if not response.ok:
        message = (
            data.get("error", {}).get("message") if isinstance(data, dict) else None
        )
        raise RuntimeError(message or f"Request failed ({response.status_code})")
    return data


MAX_TOOL_STEPS = 5


def chat(conversation: List[Dict[str, Any]]) -> str:
    current_conversation = conversation
    steps_remaining = MAX_TOOL_STEPS

    while steps_remaining > 0:
        steps_remaining -= 1
        resp = request_response(current_conversation)
        tool_calls = get_tool_calls(resp)

        if not tool_calls:
            return get_final_text(resp)

        current_conversation = build_next_conversation(current_conversation, tool_calls)

    raise RuntimeError(f"Tool calling did not finish within {MAX_TOOL_STEPS} steps.")


def main() -> None:
    query = (
        "Use web search to check the current weather in Kraków. "
        "Then send a short email with the answer to student@example.com."
    )
    log("USER", query)
    answer = chat([{"role": "user", "content": query}])
    log("ASSISTANT", answer)


if __name__ == "__main__":
    main()

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set in the environment.")


RESPONSES_API_ENDPOINT = "https://api.openai.com/v1/responses"


@dataclass
class ApiConfig:
    model: str
    instructions: str


@dataclass
class SandboxConfig:
    root: Path


ROOT_DIR = Path(__file__).resolve().parent
SANDBOX = SandboxConfig(root=ROOT_DIR / "sandbox")


def ensure_sandbox() -> None:
    if SANDBOX.root.exists():
        # Clean sandbox directory
        for path in SANDBOX.root.rglob("*"):
            if path.is_file():
                path.unlink()
        for path in sorted(SANDBOX.root.glob("**/*"), reverse=True):
            if path.is_dir():
                path.rmdir()
    SANDBOX.root.mkdir(parents=True, exist_ok=True)


def resolve_sandbox_path(relative_path: str) -> Path:
    base = SANDBOX.root
    resolved = (base / relative_path).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        raise ValueError(f'Access denied: path "{relative_path}" is outside sandbox')
    return resolved


API = ApiConfig(
    model="gpt-4.1",
    instructions=(
        "You are a helpful assistant with access to a sandboxed filesystem. "
        "You can list, read, write, and delete files within the sandbox. "
        "Always use the available tools to interact with files. "
        "Be concise in your responses."
    ),
)


# Tool definitions (JSON Schema format, like in JS version)
TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "name": "list_files",
        "description": "List files and directories at a given path within the sandbox",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within sandbox. Use '.' for root directory.",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "read_file",
        "description": "Read the contents of a file",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file within sandbox",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "write_file",
        "description": "Write content to a file (creates or overwrites)",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file within sandbox",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "delete_file",
        "description": "Delete a file",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file to delete",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "create_directory",
        "description": "Create a directory (and parent directories if needed)",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path for the new directory",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "file_info",
        "description": "Get metadata about a file or directory",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file or directory",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


# Tool handlers (Python equivalents)
def list_files(path: str) -> List[Dict[str, Any]]:
    full_path = resolve_sandbox_path(path)
    if not full_path.exists():
        return []
    entries = []
    for entry in full_path.iterdir():
        entries.append(
            {
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
            }
        )
    return entries


def read_file(path: str) -> Dict[str, Any]:
    full_path = resolve_sandbox_path(path)
    content = full_path.read_text(encoding="utf-8")
    return {"content": content}


def write_file(path: str, content: str) -> Dict[str, Any]:
    full_path = resolve_sandbox_path(path)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")
    return {"success": True, "message": f"File written: {path}"}


def delete_file(path: str) -> Dict[str, Any]:
    full_path = resolve_sandbox_path(path)
    if full_path.exists():
        full_path.unlink()
    return {"success": True, "message": f"File deleted: {path}"}


def create_directory(path: str) -> Dict[str, Any]:
    full_path = resolve_sandbox_path(path)
    full_path.mkdir(parents=True, exist_ok=True)
    return {"success": True, "message": f"Directory created: {path}"}


def file_info(path: str) -> Dict[str, Any]:
    full_path = resolve_sandbox_path(path)
    stats = full_path.stat()
    return {
        "size": stats.st_size,
        "isDirectory": full_path.is_dir(),
        "created": stats.st_ctime,
        "modified": stats.st_mtime,
    }


HandlerFunc = Callable[[Dict[str, Any]], Any]

HANDLERS: Dict[str, HandlerFunc] = {
    "list_files": lambda args: list_files(args["path"]),
    "read_file": lambda args: read_file(args["path"]),
    "write_file": lambda args: write_file(args["path"], args["content"]),
    "delete_file": lambda args: delete_file(args["path"]),
    "create_directory": lambda args: create_directory(args["path"]),
    "file_info": lambda args: file_info(args["path"]),
}


def chat(
    *,
    model: str,
    input: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: str = "auto",
    instructions: Optional[str] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"model": model, "input": input}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = tool_choice
    if instructions:
        body["instructions"] = instructions

    response = requests.post(
        RESPONSES_API_ENDPOINT,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        data=json.dumps(body),
        timeout=120,
    )

    data = response.json()
    if not response.ok or data.get("error"):
        message = (
            data.get("error", {}).get("message")
            or f"Request failed with status {response.status_code}"
        )
        raise RuntimeError(message)
    return data


def extract_tool_calls(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        item
        for item in response.get("output", [])
        if item.get("type") == "function_call"
    ]


def extract_text(response: Dict[str, Any]) -> Optional[str]:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    for item in response.get("output", []):
        if item.get("type") == "message":
            content = item.get("content") or []
            if content and isinstance(content[0], dict):
                text = content[0].get("text")
                if isinstance(text, str):
                    return text
    return None


def execute_tool_calls(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    print(f"\nTool calls: {len(tool_calls)}")
    results: List[Dict[str, Any]] = []
    for call in tool_calls:
        args = json.loads(call.get("arguments") or "{}")
        name = call.get("name")
        print(f"  → {name}({json.dumps(args)})")
        try:
            handler = HANDLERS.get(name or "")
            if handler is None:
                raise RuntimeError(f"Unknown tool: {name}")
            result = handler(args)
            print("    ✓ Success")
            results.append(
                {
                    "type": "function_call_output",
                    "call_id": call.get("call_id"),
                    "output": json.dumps(result),
                }
            )
        except Exception as exc:
            print(f"    ✗ Error: {exc}")
            results.append(
                {
                    "type": "function_call_output",
                    "call_id": call.get("call_id"),
                    "output": json.dumps({"error": str(exc)}),
                }
            )
    return results


MAX_TOOL_ROUNDS = 10


def process_query(query: str) -> str:
    chat_config = {"model": API.model, "tools": TOOLS, "instructions": API.instructions}
    print("\n" + "=" * 60)
    print(f"Query: {query}")
    print("=" * 60)

    conversation: List[Dict[str, Any]] = [{"role": "user", "content": query}]

    for _ in range(MAX_TOOL_ROUNDS):
        response = chat(**chat_config, input=conversation)
        tool_calls = extract_tool_calls(response)
        if not tool_calls:
            text = extract_text(response) or "No response"
            print(f"\nA: {text}")
            return text

        tool_results = execute_tool_calls(tool_calls)
        conversation = [*conversation, *tool_calls, *tool_results]

    print("\nA: Max tool rounds reached")
    return "Max tool rounds reached"


def main() -> None:
    ensure_sandbox()
    print(f"Sandbox prepared at: {SANDBOX.root}\n")

    queries = [
        "What files are in the sandbox?",
        "Create a file called hello.txt with content: 'Hello, World!'",
        "Read the hello.txt file",
        "Get info about hello.txt",
        "Create a directory called 'docs'",
        "Create a file docs/readme.txt with content: 'Documentation folder'",
        "List files in the docs directory",
        "Delete the hello.txt file",
        "Try to read ../config.js",
    ]

    for q in queries:
        process_query(q)


if __name__ == "__main__":
    main()

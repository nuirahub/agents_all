"""
MCP (Model Context Protocol) client — connects to MCP servers via stdio
and bridges their tools into the agent runtime.

Config is loaded from `.mcp.json` in the workspace directory.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SEPARATOR = "__"


@dataclass
class McpToolInfo:
    server: str
    original_name: str
    prefixed_name: str
    description: str
    input_schema: dict[str, Any]


class McpStdioConnection:
    """JSON-RPC 2.0 over stdio connection to an MCP server process."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ):
        self._command = command
        self._args = args or []
        self._env = {**os.environ, **(env or {})}
        self._cwd = cwd
        self._process: subprocess.Popen | None = None
        self._request_id = 0
        self._lock = threading.Lock()

    def connect(self) -> bool:
        try:
            self._process = subprocess.Popen(
                [self._command, *self._args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._env,
                cwd=self._cwd,
            )
            resp = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agent-mcp-client", "version": "1.0.0"},
            })
            if resp and "result" in resp:
                self._send_notification("notifications/initialized", {})
                return True
            return False
        except Exception as e:
            log.error("MCP connect failed: %s", e)
            return False

    def _send_request(self, method: str, params: dict) -> dict | None:
        with self._lock:
            self._request_id += 1
            msg = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params,
            }
            self._write(msg)
            return self._read_response(self._request_id)

    def _send_notification(self, method: str, params: dict) -> None:
        with self._lock:
            msg = {"jsonrpc": "2.0", "method": method, "params": params}
            self._write(msg)

    def _write(self, msg: dict) -> None:
        if not self._process or not self._process.stdin:
            return
        content = json.dumps(msg)
        content_bytes = content.encode("utf-8")
        header = f"Content-Length: {len(content_bytes)}\r\n\r\n"
        self._process.stdin.write(header.encode("utf-8") + content_bytes)
        self._process.stdin.flush()

    def _read_response(self, expected_id: int) -> dict | None:
        for _ in range(50):
            msg = self._read_message()
            if msg is None:
                return None
            if msg.get("id") == expected_id:
                return msg
        return None

    def _read_message(self) -> dict | None:
        if not self._process or not self._process.stdout:
            return None
        try:
            content_length = 0
            while True:
                line = self._process.stdout.readline()
                if not line:
                    return None
                line_str = line.decode("utf-8").strip()
                if not line_str:
                    break
                if line_str.lower().startswith("content-length:"):
                    content_length = int(line_str.split(":", 1)[1].strip())
            if content_length == 0:
                return None
            content = self._process.stdout.read(content_length)
            return json.loads(content.decode("utf-8"))
        except Exception as e:
            log.error("MCP read error: %s", e)
            return None

    def list_tools(self) -> list[dict]:
        resp = self._send_request("tools/list", {})
        if resp and "result" in resp:
            return resp["result"].get("tools", [])
        return []

    def call_tool(self, name: str, arguments: dict) -> dict:
        resp = self._send_request("tools/call", {"name": name, "arguments": arguments})
        if resp and "result" in resp:
            return resp["result"]
        if resp and "error" in resp:
            return {
                "isError": True,
                "content": [{"type": "text", "text": resp["error"].get("message", "MCP error")}],
            }
        return {"isError": True, "content": [{"type": "text", "text": "No response from MCP server"}]}

    def close(self) -> None:
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass


class McpManager:
    """Manages connections to MCP servers and provides a unified tool interface."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._connections: dict[str, McpStdioConnection] = {}
        self._tools_cache: list[McpToolInfo] | None = None
        self._config = (config or {}).get("mcpServers", {})

    def connect_all(self) -> None:
        for name, server_config in self._config.items():
            transport = server_config.get("transport", "stdio")
            if transport != "stdio":
                log.warning("MCP server '%s' uses unsupported transport '%s', skipping", name, transport)
                continue
            command = server_config.get("command", "")
            if not command:
                log.warning("MCP server '%s' has no command, skipping", name)
                continue
            conn = McpStdioConnection(
                command=command,
                args=server_config.get("args"),
                env=server_config.get("env"),
                cwd=server_config.get("cwd"),
            )
            if conn.connect():
                self._connections[name] = conn
                log.info("MCP server '%s' connected", name)
            else:
                log.warning("MCP server '%s' failed to connect", name)

    def list_tools(self) -> list[McpToolInfo]:
        if self._tools_cache is not None:
            return self._tools_cache
        tools: list[McpToolInfo] = []
        for server_name, conn in self._connections.items():
            for t in conn.list_tools():
                tools.append(McpToolInfo(
                    server=server_name,
                    original_name=t.get("name", ""),
                    prefixed_name=f"{server_name}{SEPARATOR}{t['name']}",
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                ))
        self._tools_cache = tools
        return tools

    def get_tool_definitions(self) -> list[dict]:
        """Return MCP tool definitions in OpenAI function format."""
        return [
            {
                "type": "function",
                "name": tool.prefixed_name,
                "description": tool.description,
                "parameters": tool.input_schema,
            }
            for tool in self.list_tools()
        ]

    def is_mcp_tool(self, name: str) -> bool:
        return SEPARATOR in name and name.split(SEPARATOR, 1)[0] in self._connections

    def call_tool(self, prefixed_name: str, arguments: dict) -> tuple[bool, str]:
        parts = prefixed_name.split(SEPARATOR, 1)
        if len(parts) != 2:
            return False, f"Invalid MCP tool name: {prefixed_name}"
        server_name, tool_name = parts
        conn = self._connections.get(server_name)
        if not conn:
            return False, f"MCP server not connected: {server_name}"

        result = conn.call_tool(tool_name, arguments)
        is_error = result.get("isError", False)
        content = result.get("content", [])
        text = "\n".join(
            c.get("text", "") for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        )
        return not is_error, text or json.dumps(content)

    def servers(self) -> list[str]:
        return list(self._connections.keys())

    def close_all(self) -> None:
        for conn in self._connections.values():
            conn.close()
        self._connections.clear()
        self._tools_cache = None


_mcp_manager: McpManager | None = None


def load_mcp_config(root_dir: str | Path) -> dict[str, Any]:
    config_path = Path(root_dir) / ".mcp.json"
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text("utf-8"))
    except Exception as e:
        log.error("Failed to parse .mcp.json: %s", e)
        return {}


def initialize_mcp(root_dir: str | Path | None = None) -> McpManager:
    global _mcp_manager
    if root_dir is None:
        root_dir = Path(__file__).resolve().parent
    config = load_mcp_config(root_dir)
    _mcp_manager = McpManager(config)
    if config.get("mcpServers"):
        _mcp_manager.connect_all()
    return _mcp_manager


def get_mcp_manager() -> McpManager | None:
    return _mcp_manager


def shutdown_mcp() -> None:
    global _mcp_manager
    if _mcp_manager:
        _mcp_manager.close_all()
        _mcp_manager = None

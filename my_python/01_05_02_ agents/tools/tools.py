"""
Tool definitions and registry for the agent (calculator, ask_user, delegate, send_message, send_email).
Port of 4th-devs/01_05_agent tools.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable

logger = logging.getLogger(__name__)

# OpenAI-style function declaration (for API)
CALCULATOR_DEF = {
    "type": "function",
    "name": "calculator",
    "description": "Perform basic math operations: add, subtract, multiply, divide",
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["add", "subtract", "multiply", "divide"],
                "description": "The math operation to perform",
            },
            "a": {"type": "number", "description": "First operand"},
            "b": {"type": "number", "description": "Second operand"},
        },
        "required": ["operation", "a", "b"],
    },
}

ASK_USER_DEF = {
    "type": "function",
    "name": "ask_user",
    "description": (
        "Ask the user a question and wait for their response. "
        "Use this when you need clarification, confirmation, or additional "
        "information that only the user can provide. The agent will pause until the user responds."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask the user",
            },
        },
        "required": ["question"],
    },
}

DELEGATE_DEF = {
    "type": "function",
    "name": "delegate",
    "description": (
        "Delegate a task to another agent and wait for the result. "
        "Use this when a specialised agent can handle part of the work (e.g. web research, file operations)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "description": "Name of the agent template to run (e.g. 'bob')",
            },
            "task": {
                "type": "string",
                "description": "A clear description of what the child agent should accomplish",
            },
        },
        "required": ["agent", "task"],
    },
}

SEND_MESSAGE_DEF = {
    "type": "function",
    "name": "send_message",
    "description": (
        "Send a non-blocking message to another running agent. "
        "The message appears in the target agent's context on their next turn. "
        "Use this to share information without waiting for a response."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "The agent ID to send the message to",
            },
            "message": {
                "type": "string",
                "description": "The message content to deliver",
            },
        },
        "required": ["to", "message"],
    },
}

SEND_EMAIL_DEF = {
    "type": "function",
    "name": "send_email",
    "description": (
        "Send an email to a recipient via SMTP. "
        "Use this when the user asks you to send an email. "
        "Provide the recipient address, subject line, and body text."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient email address",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line",
            },
            "body": {
                "type": "string",
                "description": "Email body text (plain text or HTML)",
            },
        },
        "required": ["to", "subject", "body"],
    },
}

# Built-in web search tool (handled by OpenAI Responses API, no local handler)
WEB_SEARCH_DEF = {
    "type": "web_search",
}


def run_calculator(args: dict[str, Any]) -> tuple[bool, str]:
    op = (args.get("operation") or "").lower()
    a = args.get("a")
    b = args.get("b")
    if a is None or b is None:
        return False, "Missing a or b"
    if op == "add":
        return True, str(a + b)
    if op == "subtract":
        return True, str(a - b)
    if op == "multiply":
        return True, str(a * b)
    if op == "divide":
        if b == 0:
            return False, "Division by zero"
        return True, str(a / b)
    return False, f"Unknown operation: {op}"


def run_ask_user(args: dict[str, Any]) -> tuple[bool, str]:
    question = args.get("question")
    if not question:
        return False, '"question" is required'
    return True, str(question)


def run_delegate(args: dict[str, Any]) -> tuple[bool, str]:
    agent = args.get("agent")
    task = args.get("task")
    if not agent or not task:
        return False, 'Both "agent" and "task" are required'
    return True, str(task)  # Actual delegation is done in runner


def run_send_message(args: dict[str, Any]) -> tuple[bool, str]:
    to = args.get("to")
    message = args.get("message")
    if not to or not message:
        return False, 'Both "to" and "message" are required'
    return True, f"Message delivered to agent {to}"


def run_send_email(args: dict[str, Any]) -> tuple[bool, str]:
    to_addr = (args.get("to") or "").strip()
    subject = (args.get("subject") or "").strip()
    body = (args.get("body") or "").strip()

    if not to_addr:
        return False, '"to" (recipient address) is required'
    if not subject:
        return False, '"subject" is required'
    if not body:
        return False, '"body" is required'

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASS", "").strip()
    smtp_from = os.getenv("SMTP_FROM", smtp_user).strip()

    if not smtp_host or not smtp_user or not smtp_pass:
        return False, (
            "SMTP not configured. Set SMTP_HOST, SMTP_USER, and SMTP_PASS in .env"
        )

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp_from
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html" if "<" in body else "plain", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, [to_addr], msg.as_string())
        logger.info("Email sent to %s (subject: %s)", to_addr, subject)
        return True, f"Email successfully sent to {to_addr}"
    except smtplib.SMTPException as exc:
        logger.error("Failed to send email to %s: %s", to_addr, exc)
        return False, f"SMTP error: {exc}"


# Tool type: "sync" | "human" | "agent"
TOOL_META: dict[str, tuple[str, dict, Callable[[dict], tuple[bool, str]]]] = {
    "calculator": ("sync", CALCULATOR_DEF, run_calculator),
    "ask_user": ("human", ASK_USER_DEF, run_ask_user),
    "delegate": ("agent", DELEGATE_DEF, run_delegate),
    "send_message": ("sync", SEND_MESSAGE_DEF, run_send_message),
    "send_email": ("sync", SEND_EMAIL_DEF, run_send_email),
}


def get_tool_definitions(names: list[str] | None = None) -> list[dict]:
    """Return OpenAI-format tool list. If names is None, return all."""
    tools: list[dict] = []
    if names is None:
        tools = [m[1] for m in TOOL_META.values()]
    else:
        tools = [TOOL_META[n][1] for n in names if n in TOOL_META]
    tools.append(WEB_SEARCH_DEF)
    return tools


def get_tool_type(name: str) -> str | None:
    """Return 'sync', 'human', or 'agent' for registered tools."""
    if name in TOOL_META:
        return TOOL_META[name][0]
    return None


def execute_sync_tool(name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
    """Execute a sync tool and return (ok, output)."""
    if name not in TOOL_META:
        return False, f"Unknown tool: {name}"
    kind, _, handler = TOOL_META[name]
    if kind != "sync":
        return False, f"Tool {name} is not sync"
    return handler(arguments)

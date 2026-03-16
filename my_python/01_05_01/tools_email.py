"""
Native email tool: send_email via Resend API with whitelist enforcement.
"""
from __future__ import annotations

import json
import re
from typing import Any

import requests

from config import RESEND_API_KEY, RESEND_FROM, WHITELIST_PATH

RESEND_API_BASE = "https://api.resend.com"


def _load_whitelist() -> list[str]:
    try:
        content = WHITELIST_PATH.read_text(encoding="utf-8")
        data = json.loads(content)
        return data.get("allowed_recipients") or []
    except Exception:
        return []


def _is_email_allowed(email: str, whitelist: list[str]) -> bool:
    normalized = email.lower().strip()
    domain = normalized.split("@")[-1] if "@" in normalized else ""
    for pattern in whitelist:
        p = pattern.lower().strip()
        if p.startswith("@"):
            if domain == p[1:]:
                return True
        else:
            if normalized == p:
                return True
    return False


def _validate_recipients(recipients: list[str], whitelist: list[str]) -> tuple[bool, list[str]]:
    blocked = [r for r in recipients if not _is_email_allowed(r, whitelist)]
    return (len(blocked) == 0, blocked)


def _text_to_html(text: str) -> str:
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>\n")
    )
    return f'<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; line-height: 1.6; color: #333;">{escaped}</div>'


def send_email(
    *,
    to: list[str] | str,
    subject: str,
    body: str,
    format: str = "text",
    reply_to: str | None = None,
) -> dict[str, Any]:
    """
    Send email via Resend. Recipients must be in workspace/whitelist.json.
    """
    recipients = [to] if isinstance(to, str) else list(to)

    if not RESEND_API_KEY or not RESEND_FROM:
        return {
            "success": False,
            "error": "RESEND_API_KEY / RESEND_FROM not configured. Add them to .env to enable email sending.",
        }

    whitelist = _load_whitelist()
    if not whitelist:
        return {
            "success": False,
            "error": "Whitelist is empty or not configured. Add allowed recipients to workspace/whitelist.json",
        }

    valid, blocked = _validate_recipients(recipients, whitelist)
    if not valid:
        return {
            "success": False,
            "error": f"Recipients not in whitelist: {', '.join(blocked)}. Update workspace/whitelist.json to allow them.",
        }

    is_html = format == "html"
    html = body if is_html else _text_to_html(body)
    text = body if not is_html else re.sub(r"<[^>]*>", "", body)

    payload = {
        "from": RESEND_FROM,
        "to": recipients,
        "subject": subject,
        "html": html,
        "text": text,
    }
    if reply_to:
        payload["reply_to"] = reply_to

    resp = requests.post(
        f"{RESEND_API_BASE}/emails",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {RESEND_API_KEY}",
        },
        json=payload,
        timeout=30,
    )
    data = resp.json()

    if not resp.ok:
        return {"success": False, "error": data.get("message", f"Resend API error: {resp.status_code}")}

    return {
        "success": True,
        "id": data.get("id"),
        "to": recipients,
        "subject": subject,
    }


# Tool definition for Responses API
SEND_EMAIL_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "send_email",
    "description": "Send an email to one or more recipients. Recipients must be in the whitelist (workspace/whitelist.json). Supports plain text or HTML content.",
    "parameters": {
        "type": "object",
        "properties": {
            "to": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Recipient email address(es). Must be in the whitelist.",
            },
            "subject": {"type": "string", "description": "Email subject line."},
            "body": {"type": "string", "description": "Email content. Plain text or HTML."},
            "format": {
                "type": "string",
                "enum": ["text", "html"],
                "description": "Content format: 'text' or 'html'. Default: text",
            },
            "reply_to": {"type": "string", "description": "Optional reply-to email address."},
        },
        "required": ["to", "subject", "body"],
        "additionalProperties": False,
    },
    "strict": False,
}

"""
Event system for agent observability.
Port of 4th-devs/01_05_agent events/ (emitter + types + event-logger).

Events are plain dicts with a 'type' key and a 'ctx' dict carrying trace ids.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from logger import logger

EventHandler = Callable[[dict[str, Any]], None]


class EventEmitter:
    """Simple event emitter with type-specific and catch-all subscriptions."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._any_handlers: list[EventHandler] = []

    def emit(self, event: dict[str, Any]) -> None:
        etype = event.get("type", "")
        for h in self._handlers.get(etype, []):
            try:
                h(event)
            except Exception as e:
                logger.error(f"Event handler error ({etype}): {e}")
        for h in self._any_handlers:
            try:
                h(event)
            except Exception as e:
                logger.error(f"Event handler error (any/{etype}): {e}")

    def on(self, event_type: str, handler: EventHandler) -> Callable[[], None]:
        self._handlers.setdefault(event_type, []).append(handler)
        def _off():
            self._handlers[event_type].remove(handler)
        return _off

    def on_any(self, handler: EventHandler) -> Callable[[], None]:
        self._any_handlers.append(handler)
        def _off():
            self._any_handlers.remove(handler)
        return _off


# ── Helpers ───────────────────────────────────────────────────────────────────

def create_event_context(
    *,
    trace_id: str,
    session_id: str,
    agent_id: str,
    root_agent_id: str,
    depth: int,
    parent_agent_id: str | None = None,
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "timestamp": time.time(),
        "session_id": session_id,
        "agent_id": agent_id,
        "root_agent_id": root_agent_id,
        "depth": depth,
        "parent_agent_id": parent_agent_id,
    }


def _fmt_tokens(usage: dict | None) -> str:
    if not usage:
        return ""
    cached = f" ({usage.get('cached_tokens', 0)} cached)" if usage.get("cached_tokens") else ""
    return f"{usage.get('input_tokens', 0)} in, {usage.get('output_tokens', 0)} out{cached}"


def _trunc(s: str, n: int = 120) -> str:
    return s[:n] + "…" if len(s) > n else s


# ── Event logger subscriber ──────────────────────────────────────────────────

def subscribe_event_logger(emitter: EventEmitter) -> Callable[[], None]:
    """Subscribe a logger that prints human-readable lifecycle messages."""
    log = logger.child(name="lifecycle")

    def _handler(event: dict[str, Any]) -> None:
        ctx = event.get("ctx", {})
        base = {
            "trace_id": ctx.get("trace_id"),
            "agent_id": ctx.get("agent_id"),
            "depth": ctx.get("depth"),
        }
        etype = event.get("type", "")

        if etype == "agent.started":
            log.info(
                f"started — {event.get('agent_name', 'agent')} ({event.get('model', '')})",
                extra=base,
            )
        elif etype == "agent.completed":
            secs = f"{event.get('duration_ms', 0) / 1000:.1f}"
            log.info(f"completed — {secs}s, {_fmt_tokens(event.get('usage'))}", extra=base)
        elif etype == "agent.failed":
            log.error(f"failed — {event.get('error', '')}", extra=base)
        elif etype == "agent.waiting":
            wf = event.get("waiting_for", [])
            log.info(f"waiting for {len(wf)} tool(s)", extra=base)
        elif etype == "agent.resumed":
            log.info(f"resumed — {event.get('remaining', 0)} remaining", extra=base)
        elif etype == "turn.started":
            log.info(f"turn {event.get('turn_count', 0)}", extra=base)
        elif etype == "turn.completed":
            tok = _fmt_tokens(event.get("usage"))
            log.info(f"turn {event.get('turn_count', 0)} done{f' — {tok}' if tok else ''}", extra=base)
        elif etype == "generation.completed":
            secs = f"{event.get('duration_ms', 0) / 1000:.1f}"
            tok = _fmt_tokens(event.get("usage"))
            log.info(f"generation {event.get('model', '')} — {secs}s{f', {tok}' if tok else ''}", extra=base)
        elif etype == "tool.called":
            log.info(f"{event.get('name', '')} called", extra={**base, "call_id": event.get("call_id")})
        elif etype == "tool.completed":
            secs = f"{event.get('duration_ms', 0) / 1000:.1f}"
            log.info(
                f"{event.get('name', '')} ok — {secs}s",
                extra={**base, "call_id": event.get("call_id"), "output": _trunc(event.get("output", ""))},
            )
        elif etype == "tool.failed":
            log.warning(
                f"{event.get('name', '')} failed — {event.get('error', '')}",
                extra={**base, "call_id": event.get("call_id")},
            )
        else:
            log.info(etype, extra=base)

    return emitter.on_any(_handler)


# ── Module-level singleton ────────────────────────────────────────────────────

event_emitter = EventEmitter()
subscribe_event_logger(event_emitter)

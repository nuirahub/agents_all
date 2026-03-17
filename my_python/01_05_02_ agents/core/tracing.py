"""
Langfuse / OpenTelemetry tracing subscriber.
Port of 4th-devs/01_05_agent events/langfuse-subscriber.ts.

Activation: set LANGFUSE_SECRET_KEY + LANGFUSE_PUBLIC_KEY in env.
Falls back to no-op if the `langfuse` package is not installed.
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable

from core.events import EventEmitter
from infra.logger import logger

_langfuse_available = False
try:
    from langfuse import Langfuse  # type: ignore[import-untyped]

    _langfuse_available = True
except ImportError:
    pass


class _NoopTrace:
    """Drop-in stub when Langfuse is unavailable."""

    def generation(self, **kw: Any) -> "_NoopTrace":
        return self

    def span(self, **kw: Any) -> "_NoopTrace":
        return self

    def end(self, **kw: Any) -> None:
        pass

    def update(self, **kw: Any) -> None:
        pass


class LangfuseSubscriber:
    """Subscribe to agent events and push traces to Langfuse."""

    def __init__(self, emitter: EventEmitter) -> None:
        self._client: Any = None
        self._traces: dict[str, Any] = {}
        self._spans: dict[str, Any] = {}
        self._generations: dict[str, Any] = {}
        self._emitter = emitter
        self._unsubscribe: Callable[[], None] | None = None

    @property
    def active(self) -> bool:
        return self._client is not None

    def start(self) -> None:
        secret = os.getenv("LANGFUSE_SECRET_KEY", "")
        public = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        if not secret or not public:
            logger.info("Langfuse tracing disabled (keys not set)")
            return
        if not _langfuse_available:
            logger.warning("langfuse package not installed — tracing disabled (pip install langfuse)")
            return
        self._client = Langfuse(secret_key=secret, public_key=public, host=host)
        self._unsubscribe = self._emitter.on_any(self._handle)
        logger.info("Langfuse tracing enabled")

    def shutdown(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
        if self._client:
            try:
                self._client.flush()
            except Exception:
                pass

    def _trace_for(self, ctx: dict[str, Any]) -> Any:
        tid = ctx.get("trace_id", "")
        if tid in self._traces:
            return self._traces[tid]
        if not self._client:
            return _NoopTrace()
        trace = self._client.trace(
            id=tid,
            session_id=ctx.get("session_id"),
            metadata={"agent_id": ctx.get("agent_id"), "depth": ctx.get("depth")},
        )
        self._traces[tid] = trace
        return trace

    def _handle(self, event: dict[str, Any]) -> None:
        ctx = event.get("ctx", {})
        etype = event.get("type", "")
        trace = self._trace_for(ctx)
        agent_id = ctx.get("agent_id", "")

        if etype == "agent.started":
            span = trace.span(name=f"agent:{agent_id}", metadata={"model": event.get("model"), "task": event.get("task")})
            self._spans[agent_id] = span

        elif etype == "generation.completed":
            gen_key = f"{agent_id}:gen:{event.get('turn_count', time.time())}"
            usage = event.get("usage") or {}
            parent = self._spans.get(agent_id) or trace
            gen = parent.generation(
                name=event.get("model", ""),
                model=event.get("model"),
                usage={
                    "input": usage.get("input_tokens", 0),
                    "output": usage.get("output_tokens", 0),
                    "total": usage.get("total_tokens", 0),
                },
                metadata={"duration_ms": event.get("duration_ms")},
            )
            gen.end()
            self._generations[gen_key] = gen

        elif etype == "tool.called":
            call_id = event.get("call_id", "")
            parent = self._spans.get(agent_id) or trace
            span = parent.span(name=f"tool:{event.get('name', '')}", metadata={"call_id": call_id, "arguments": event.get("arguments")})
            self._spans[f"tool:{call_id}"] = span

        elif etype in {"tool.completed", "tool.failed"}:
            call_id = event.get("call_id", "")
            span = self._spans.pop(f"tool:{call_id}", None)
            if span:
                meta: dict[str, Any] = {"duration_ms": event.get("duration_ms")}
                if etype == "tool.failed":
                    meta["error"] = event.get("error")
                else:
                    out = event.get("output", "")
                    meta["output"] = out[:500] if len(out) > 500 else out
                span.update(metadata=meta)
                span.end()

        elif etype in {"agent.completed", "agent.failed", "agent.cancelled"}:
            span = self._spans.pop(agent_id, None)
            if span:
                span.update(
                    metadata={
                        "status": etype.split(".")[-1],
                        "duration_ms": event.get("duration_ms"),
                        "error": event.get("error"),
                    }
                )
                span.end()
            self._traces.pop(ctx.get("trace_id", ""), None)


_subscriber: LangfuseSubscriber | None = None


def init_tracing(emitter: EventEmitter) -> LangfuseSubscriber:
    """Initialize Langfuse subscriber (idempotent)."""
    global _subscriber
    if _subscriber is None:
        _subscriber = LangfuseSubscriber(emitter)
        _subscriber.start()
    return _subscriber


def shutdown_tracing() -> None:
    global _subscriber
    if _subscriber:
        _subscriber.shutdown()
        _subscriber = None

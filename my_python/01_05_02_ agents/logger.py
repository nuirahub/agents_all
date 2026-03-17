"""
Structured logging — JSON in production, pretty in development.
Dual output: stdout (pretty/JSON) + agent.log (JSON).
Port of 4th-devs/01_05_agent lib/logger.ts (pino).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REDACT_KEYS = frozenset({
    "api_key", "api_key_hash", "authorization",
    "apikey", "apikeyhash", "password", "secret",
})


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "level": record.levelname.lower(),
            "time": datetime.fromtimestamp(record.created).isoformat(),
            "name": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "ctx", None)
        if isinstance(extra, dict):
            for k, v in extra.items():
                data[k] = "[REDACTED]" if k.lower() in REDACT_KEYS else v
        if record.exc_info and record.exc_info[1]:
            data["error"] = str(record.exc_info[1])
        return json.dumps(data, default=str)


class _PrettyFormatter(logging.Formatter):
    _COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        c = self._COLORS.get(record.levelname, "")
        r = self._RESET
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.") + f"{int(record.msecs):03d}"
        name = record.name.removeprefix("agent.")
        line = f"{c}{ts}{r} {c}{record.levelname:<7}{r} [{name}] {record.getMessage()}"
        extra = getattr(record, "ctx", None)
        if isinstance(extra, dict):
            brief = {k: v for k, v in extra.items() if v is not None}
            if brief:
                line += f"  {brief}"
        if record.exc_info and record.exc_info[1]:
            line += f"\n  ERROR: {record.exc_info[1]}"
        return line


class ContextLogger:
    """Logger with attached context data (child-logger pattern)."""

    def __init__(self, base: logging.Logger, context: dict[str, Any] | None = None):
        self._base = base
        self._context = context or {}

    def child(self, **kwargs: Any) -> ContextLogger:
        return ContextLogger(self._base, {**self._context, **kwargs})

    def _emit(self, level: int, msg: str, extra: dict[str, Any] | None = None, **kw: Any) -> None:
        merged = {**self._context, **(extra or {}), **kw}
        record = self._base.makeRecord(
            self._base.name, level, "(agent)", 0, msg, (), None,
        )
        record.ctx = merged  # type: ignore[attr-defined]
        self._base.handle(record)

    def debug(self, msg: str, extra: dict[str, Any] | None = None, **kw: Any) -> None:
        self._emit(logging.DEBUG, msg, extra, **kw)

    def info(self, msg: str, extra: dict[str, Any] | None = None, **kw: Any) -> None:
        self._emit(logging.INFO, msg, extra, **kw)

    def warning(self, msg: str, extra: dict[str, Any] | None = None, **kw: Any) -> None:
        self._emit(logging.WARNING, msg, extra, **kw)

    def error(self, msg: str, extra: dict[str, Any] | None = None, **kw: Any) -> None:
        self._emit(logging.ERROR, msg, extra, **kw)


def _setup() -> ContextLogger:
    is_prod = os.getenv("ENV", "").lower() == "production"
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger("agent")
    root.setLevel(level)
    root.handlers.clear()
    root.propagate = False

    # stdout
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(_JsonFormatter() if is_prod else _PrettyFormatter())
    root.addHandler(stdout)

    # agent.log (JSON)
    log_file = Path(__file__).resolve().parent / "agent.log"
    try:
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setFormatter(_JsonFormatter())
        root.addHandler(fh)
    except OSError:
        pass

    return ContextLogger(root)


logger = _setup()

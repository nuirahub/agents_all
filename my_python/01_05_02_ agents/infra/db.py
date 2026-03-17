"""
SQLite repository implementation using stdlib sqlite3.

Drop-in replacement for in-memory repositories. All domain objects
(User, Session, Agent, Item) are persisted with the same interface.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from core.domain import Agent, AgentConfig, Session, TokenUsage, User, WaitingFor
from infra.repositories import Repositories

# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id             TEXT PRIMARY KEY,
    email          TEXT NOT NULL,
    api_key_hash   TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_api_key_hash ON users(api_key_hash);

CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,
    user_id        TEXT,
    root_agent_id  TEXT,
    title          TEXT,
    summary        TEXT,
    status         TEXT NOT NULL DEFAULT 'active',
    created_at     TEXT NOT NULL,
    updated_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS agents (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    trace_id        TEXT,
    root_agent_id   TEXT NOT NULL,
    parent_id       TEXT,
    source_call_id  TEXT,
    depth           INTEGER NOT NULL DEFAULT 0,
    task            TEXT NOT NULL,
    config          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    waiting_for     TEXT NOT NULL DEFAULT '[]',
    result          TEXT,
    error           TEXT,
    turn_count      INTEGER NOT NULL DEFAULT 0,
    usage           TEXT,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    completed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_agents_session ON agents(session_id);
CREATE INDEX IF NOT EXISTS idx_agents_parent ON agents(parent_id);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

CREATE TABLE IF NOT EXISTS items (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL REFERENCES agents(id),
    sequence    INTEGER NOT NULL,
    type        TEXT NOT NULL,
    role        TEXT,
    content     TEXT,
    call_id     TEXT,
    name        TEXT,
    arguments   TEXT,
    output      TEXT,
    is_error    INTEGER,
    summary     TEXT,
    turn_number INTEGER,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_agent_seq ON items(agent_id, sequence);
CREATE INDEX IF NOT EXISTS idx_items_call_id ON items(call_id);
"""

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now().isoformat()


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    return datetime.fromisoformat(val)


def _new_id() -> str:
    return str(uuid.uuid4())


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _json_loads(text: str | None) -> Any:
    if not text:
        return None
    return json.loads(text)


# ─────────────────────────────────────────────────────────────────────────────
# Mappers
# ─────────────────────────────────────────────────────────────────────────────


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        api_key_hash=row["api_key_hash"],
        created_at=_parse_dt(row["created_at"]) or datetime.now(),
    )


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        user_id=row["user_id"],
        root_agent_id=row["root_agent_id"],
        title=row["title"],
        summary=row["summary"],
        status=row["status"],
        created_at=_parse_dt(row["created_at"]) or datetime.now(),
        updated_at=_parse_dt(row["updated_at"]),
    )


def _row_to_agent(row: sqlite3.Row) -> Agent:
    config_raw = _json_loads(row["config"]) or {}
    usage_raw = _json_loads(row["usage"])
    wf_raw = _json_loads(row["waiting_for"]) or []

    return Agent(
        id=row["id"],
        session_id=row["session_id"],
        trace_id=row["trace_id"],
        root_agent_id=row["root_agent_id"],
        parent_id=row["parent_id"],
        source_call_id=row["source_call_id"],
        depth=row["depth"],
        task=row["task"],
        config=AgentConfig(
            model=config_raw.get("model", ""),
            temperature=config_raw.get("temperature"),
            max_tokens=config_raw.get("max_tokens"),
            tools=config_raw.get("tools"),
        ),
        status=row["status"],
        waiting_for=[
            WaitingFor(
                call_id=w.get("call_id", ""),
                type=w.get("type", "tool"),
                name=w.get("name", ""),
                description=w.get("description"),
            )
            for w in wf_raw
        ],
        result=_json_loads(row["result"]),
        error=row["error"],
        turn_count=row["turn_count"],
        usage=TokenUsage(
            input_tokens=usage_raw.get("input_tokens", 0),
            output_tokens=usage_raw.get("output_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
            cached_tokens=usage_raw.get("cached_tokens", 0),
        ) if usage_raw else None,
        created_at=_parse_dt(row["created_at"]) or datetime.now(),
        started_at=_parse_dt(row["started_at"]),
        completed_at=_parse_dt(row["completed_at"]),
    )


def _row_to_item(row: sqlite3.Row) -> dict:
    base: dict[str, Any] = {
        "id": row["id"],
        "agent_id": row["agent_id"],
        "sequence": row["sequence"],
        "type": row["type"],
        "turn_number": row["turn_number"],
        "created_at": _parse_dt(row["created_at"]),
    }
    t = row["type"]
    if t == "message":
        content_raw = row["content"]
        try:
            content = json.loads(content_raw) if content_raw else ""
        except (json.JSONDecodeError, TypeError):
            content = content_raw or ""
        base["role"] = row["role"]
        base["content"] = content
    elif t == "function_call":
        base["call_id"] = row["call_id"]
        base["name"] = row["name"]
        base["arguments"] = _json_loads(row["arguments"]) or {}
    elif t == "function_call_output":
        base["call_id"] = row["call_id"]
        base["output"] = row["output"] or ""
        base["is_error"] = bool(row["is_error"])
    elif t == "reasoning":
        base["summary"] = row["summary"]
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Repository implementations
# ─────────────────────────────────────────────────────────────────────────────


class SqliteUserRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._db = conn

    def create(self, input: dict[str, Any]) -> User:
        uid = _new_id()
        now = _now_iso()
        user = User(
            id=uid,
            email=input.get("email", ""),
            api_key_hash=input.get("api_key_hash", ""),
            created_at=_parse_dt(now) or datetime.now(),
        )
        self._db.execute(
            "INSERT INTO users (id, email, api_key_hash, created_at) VALUES (?, ?, ?, ?)",
            (uid, user.email, user.api_key_hash, now),
        )
        self._db.commit()
        return user

    def get_by_id(self, id: str) -> User | None:
        cur = self._db.execute("SELECT * FROM users WHERE id = ?", (id,))
        row = cur.fetchone()
        return _row_to_user(row) if row else None

    def get_by_email(self, email: str) -> User | None:
        cur = self._db.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        return _row_to_user(row) if row else None

    def get_by_api_key_hash(self, key_hash: str) -> User | None:
        cur = self._db.execute(
            "SELECT * FROM users WHERE api_key_hash = ?", (key_hash,)
        )
        row = cur.fetchone()
        return _row_to_user(row) if row else None


class SqliteSessionRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._db = conn

    def create(
        self, user_id: str | None = None, title: str | None = None
    ) -> Session:
        sid = _new_id()
        now = _now_iso()
        session = Session(
            id=sid,
            user_id=user_id,
            title=title,
            created_at=_parse_dt(now) or datetime.now(),
        )
        self._db.execute(
            "INSERT INTO sessions (id, user_id, title, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (sid, user_id, title, "active", now),
        )
        self._db.commit()
        return session

    def get_by_id(self, id: str) -> Session | None:
        cur = self._db.execute("SELECT * FROM sessions WHERE id = ?", (id,))
        row = cur.fetchone()
        return _row_to_session(row) if row else None

    def list_by_user(self, user_id: str) -> list[Session]:
        cur = self._db.execute(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        )
        return [_row_to_session(row) for row in cur.fetchall()]

    def update(self, session: Session) -> Session:
        session.updated_at = datetime.now()
        self._db.execute(
            """UPDATE sessions SET
                root_agent_id = ?, title = ?, summary = ?,
                status = ?, updated_at = ?
            WHERE id = ?""",
            (
                session.root_agent_id,
                session.title,
                session.summary,
                session.status,
                session.updated_at.isoformat() if session.updated_at else None,
                session.id,
            ),
        )
        self._db.commit()
        return session


class SqliteAgentRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._db = conn

    def create(self, input: dict[str, Any]) -> Agent:
        agent_id = _new_id()
        now = _now_iso()
        config = input.get("config") or {}
        agent = Agent(
            id=agent_id,
            session_id=input["session_id"],
            trace_id=input.get("trace_id"),
            root_agent_id=input.get("root_agent_id") or agent_id,
            parent_id=input.get("parent_id"),
            source_call_id=input.get("source_call_id"),
            depth=input.get("depth", 0),
            task=input.get("task", ""),
            config=AgentConfig(
                model=config.get("model", ""),
                temperature=config.get("temperature"),
                max_tokens=config.get("max_tokens"),
                tools=config.get("tools"),
            ),
            created_at=_parse_dt(now) or datetime.now(),
        )
        self._db.execute(
            """INSERT INTO agents
                (id, session_id, trace_id, root_agent_id, parent_id,
                 source_call_id, depth, task, config, status,
                 waiting_for, turn_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent.id,
                agent.session_id,
                agent.trace_id,
                agent.root_agent_id,
                agent.parent_id,
                agent.source_call_id,
                agent.depth,
                agent.task,
                _json_dumps({
                    "model": agent.config.model,
                    "temperature": agent.config.temperature,
                    "max_tokens": agent.config.max_tokens,
                    "tools": agent.config.tools,
                }),
                agent.status,
                "[]",
                0,
                now,
            ),
        )
        self._db.commit()
        return agent

    def get_by_id(self, id: str) -> Agent | None:
        cur = self._db.execute("SELECT * FROM agents WHERE id = ?", (id,))
        row = cur.fetchone()
        return _row_to_agent(row) if row else None

    def update(self, agent: Agent) -> Agent:
        wf = [
            {
                "call_id": w.call_id,
                "type": w.type,
                "name": w.name,
                "description": w.description,
            }
            for w in agent.waiting_for
        ]
        usage_json = _json_dumps({
            "input_tokens": agent.usage.input_tokens,
            "output_tokens": agent.usage.output_tokens,
            "total_tokens": agent.usage.total_tokens,
            "cached_tokens": agent.usage.cached_tokens,
        }) if agent.usage else None

        self._db.execute(
            """UPDATE agents SET
                status = ?, waiting_for = ?, result = ?,
                error = ?, turn_count = ?, usage = ?,
                started_at = ?, completed_at = ?
            WHERE id = ?""",
            (
                agent.status,
                _json_dumps(wf),
                _json_dumps(agent.result) if agent.result is not None else None,
                agent.error,
                agent.turn_count,
                usage_json,
                agent.started_at.isoformat() if agent.started_at else None,
                agent.completed_at.isoformat() if agent.completed_at else None,
                agent.id,
            ),
        )
        self._db.commit()
        return agent

    def list_by_session(self, session_id: str) -> list[Agent]:
        cur = self._db.execute(
            "SELECT * FROM agents WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        )
        return [_row_to_agent(row) for row in cur.fetchall()]

    def list_by_parent(self, parent_id: str) -> list[Agent]:
        cur = self._db.execute(
            "SELECT * FROM agents WHERE parent_id = ? ORDER BY created_at",
            (parent_id,),
        )
        return [_row_to_agent(row) for row in cur.fetchall()]

    def find_waiting_for_call(self, call_id: str) -> Agent | None:
        cur = self._db.execute(
            """SELECT * FROM agents
            WHERE status = 'waiting'
            AND EXISTS (
                SELECT 1 FROM json_each(waiting_for)
                WHERE json_extract(value, '$.call_id') = ?
            )
            LIMIT 1""",
            (call_id,),
        )
        row = cur.fetchone()
        return _row_to_agent(row) if row else None


class SqliteItemRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._db = conn

    def create(self, agent_id: str, input: dict[str, Any]) -> dict:
        item_id = _new_id()
        now = _now_iso()

        cur = self._db.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM items WHERE agent_id = ?",
            (agent_id,),
        )
        seq = (cur.fetchone()[0] or 0) + 1

        t = input.get("type", "")

        role = input.get("role") if t == "message" else None
        content: str | None = None
        if t == "message":
            c = input.get("content", "")
            content = c if isinstance(c, str) else _json_dumps(c)

        call_id = input.get("call_id") if t in ("function_call", "function_call_output") else None
        name = input.get("name") if t == "function_call" else None
        arguments = _json_dumps(input.get("arguments", {})) if t == "function_call" else None
        output = input.get("output") if t == "function_call_output" else None
        is_error = int(bool(input.get("is_error"))) if t == "function_call_output" else None
        summary = input.get("summary") if t == "reasoning" else None

        self._db.execute(
            """INSERT INTO items
                (id, agent_id, sequence, type, role, content,
                 call_id, name, arguments, output, is_error,
                 summary, turn_number, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item_id, agent_id, seq, t, role, content,
                call_id, name, arguments, output, is_error,
                summary, input.get("turn_number"), now,
            ),
        )
        self._db.commit()

        item: dict[str, Any] = {
            "id": item_id,
            "agent_id": agent_id,
            "sequence": seq,
            "turn_number": input.get("turn_number"),
            "created_at": _parse_dt(now),
            **input,
        }
        return item

    def get_by_id(self, id: str) -> dict | None:
        cur = self._db.execute("SELECT * FROM items WHERE id = ?", (id,))
        row = cur.fetchone()
        return _row_to_item(row) if row else None

    def list_by_agent(self, agent_id: str) -> list[dict]:
        cur = self._db.execute(
            "SELECT * FROM items WHERE agent_id = ? ORDER BY sequence",
            (agent_id,),
        )
        return [_row_to_item(row) for row in cur.fetchall()]

    def get_output_by_call_id(self, call_id: str) -> dict | None:
        cur = self._db.execute(
            "SELECT * FROM items WHERE call_id = ? AND type = 'function_call_output' LIMIT 1",
            (call_id,),
        )
        row = cur.fetchone()
        return _row_to_item(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────


def _connect(db_path: str) -> sqlite3.Connection:
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
    return conn


def create_sqlite_repositories(db_path: str) -> Repositories:
    """Create Repositories backed by SQLite. Tables are auto-created."""
    conn = _connect(db_path)
    repos = Repositories.__new__(Repositories)
    repos.users = SqliteUserRepo(conn)
    repos.sessions = SqliteSessionRepo(conn)
    repos.agents = SqliteAgentRepo(conn)
    repos.items = SqliteItemRepo(conn)
    repos._conn = conn  # type: ignore[attr-defined]
    return repos

"""
FastAPI HTTP API for the 01_05_02 agent runtime.
Full-ish port of 4th-devs/01_05_agent chat endpoints.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Union

from auth import require_auth, seed_default_user
from chat_service import chat_once, chat_stream, deliver_tool_result
from errors import NotFoundError, register_error_handlers
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from logger import logger
from pydantic import BaseModel
from repositories import create_memory_repositories
from starlette.responses import StreamingResponse


def _create_repos():
    from config import DATABASE_URL

    if DATABASE_URL:
        from db import create_sqlite_repositories

        return create_sqlite_repositories(DATABASE_URL)
    return create_memory_repositories()


repos = _create_repos()


def _print_startup_examples() -> None:
    port = os.getenv("PORT", "8000")
    base = f"http://localhost:{port}"
    lines = [
        "",
        "┌─ Example requests ─────────────────────────────────────────────┐",
        "│                                                                │",
        "│  Health check:                                                 │",
        f"│    curl {base}/health                              │",
        "│                                                                │",
        "│  Chat (simple):                                                │",
        f"│    curl -X POST {base}/api/chat/completions \\     │",
        '│      -H "Content-Type: application/json" \\                     │',
        '│      -d \'{"input":"Hello!"}\'                                    │',
        "│                                                                │",
        "│  Chat (streaming):                                             │",
        f"│    curl -N -X POST {base}/api/chat/completions \\ │",
        '│      -H "Content-Type: application/json" \\                     │',
        '│      -d \'{"input":"Hello!","stream":true}\'                     │',
        "│                                                                │",
        "│  Cancel agent:                                                 │",
        f"│    curl -X POST {base}/api/chat/agents/ID/cancel │",
        "│                                                                │",
        "│  List providers:                                               │",
        f"│    curl {base}/api/providers                       │",
        "│                                                                │",
        "└────────────────────────────────────────────────────────────────┘",
        "",
    ]
    for line in lines:
        logger.info(line)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from config import ROOT_DIR
    from mcp_client import initialize_mcp, shutdown_mcp

    app.state.repos = repos
    app.state.auth_enabled = os.getenv("AUTH_ENABLED", "").lower() == "true"

    seed_default_user(repos)
    initialize_mcp(ROOT_DIR)

    from events import event_emitter
    from tracing import init_tracing

    init_tracing(event_emitter)

    from config import DATABASE_URL

    if DATABASE_URL:
        logger.info(f"Storage: SQLite ({DATABASE_URL})")
    else:
        logger.info("Storage: in-memory (set DATABASE_URL for persistence)")

    if app.state.auth_enabled:
        logger.info("Auth ENABLED — bearer token required on protected endpoints")
    else:
        logger.info(
            "Auth disabled — all endpoints are open (set AUTH_ENABLED=true to enable)"
        )

    _print_startup_examples()

    yield

    from tracing import shutdown_tracing

    shutdown_tracing()
    shutdown_mcp()


class InputItem(BaseModel):
    type: str
    role: str | None = None
    content: str | list[dict] | None = None
    callId: str | None = None
    name: str | None = None
    output: str | None = None


class ChatRequest(BaseModel):
    input: Union[str, list[InputItem]]
    instructions: str | None = None
    model: str | None = None
    agent: str | None = None
    sessionId: str | None = None
    stream: bool = False


class ChatResponse(BaseModel):
    id: str
    sessionId: str
    status: str
    model: str
    output: list[dict]
    waitingFor: list[dict] | None = None
    usage: dict | None = None


class DeliverRequest(BaseModel):
    callId: str
    output: str
    isError: bool = False


class DeliverResponse(ChatResponse):
    pass


app = FastAPI(title="01_05_02 Agent API", version="1.0.0", lifespan=lifespan)
register_error_handlers(app)

cors_origin = os.getenv("CORS_ORIGIN", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origin.split(",") if cors_origin != "*" else ["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=86400,
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    start = time.time()
    response = await call_next(request)
    ms = (time.time() - start) * 1000
    method = request.method
    path = request.url.path
    status = response.status_code
    response.headers["x-request-id"] = request_id
    response.headers["x-response-time"] = f"{ms:.0f}ms"
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    log_fn = (
        logger.error
        if status >= 500
        else (logger.warning if status >= 400 else logger.info)
    )
    log_fn(f"{method} {path} → {status} ({ms:.0f}ms) [{request_id[:8]}]")
    return response


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    checks: dict[str, bool] = {"runtime": True}
    try:
        conn = getattr(repos, "_conn", None)
        if conn:
            conn.execute("SELECT 1")
            checks["db"] = True
        else:
            checks["db"] = True
    except Exception:
        checks["db"] = False
    healthy = all(checks.values())
    return {"status": "ok" if healthy else "degraded", "checks": checks}


# ── Chat completions ─────────────────────────────────────────────────────────


@app.post("/api/chat/completions")
async def create_completion(body: ChatRequest, user=Depends(require_auth)):
    input_text, input_items = _parse_input(body.input)

    if body.stream:

        def event_generator():
            for event in chat_stream(
                repos,
                input_text=input_text,
                input_items=input_items,
                instructions=body.instructions or "You are a helpful assistant.",
                model=body.model,
                agent_name=body.agent,
                session_id=body.sessionId,
            ):
                yield f"event: {event.type}\ndata: {json.dumps(event.data, default=str)}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    resp = chat_once(
        repos,
        input_text=input_text,
        input_items=input_items,
        instructions=body.instructions or "You are a helpful assistant.",
        model=body.model,
        agent_name=body.agent,
        session_id=body.sessionId,
    )
    status_code = 202 if resp.get("status") == "waiting" else 200
    return JSONResponse(
        content=ChatResponse(**resp).model_dump(), status_code=status_code
    )


def _parse_input(raw: str | list) -> tuple[str, list[dict[str, Any]] | None]:
    """Parse ChatRequest.input: string → (text, None), array → (first_text, items)."""
    if isinstance(raw, str):
        return raw, None
    items: list[dict[str, Any]] = []
    first_text = ""
    for item in raw:
        d = (
            item.model_dump(exclude_none=True)
            if hasattr(item, "model_dump")
            else dict(item)
        )
        items.append(d)
        if not first_text and d.get("type") == "message" and d.get("role") == "user":
            c = d.get("content", "")
            if isinstance(c, str):
                first_text = c
    return first_text or "(structured input)", items


# ── Agent status (polling) ───────────────────────────────────────────────────


@app.get("/api/chat/agents/{agent_id}")
async def get_agent_status(agent_id: str, user=Depends(require_auth)):
    agent = repos.agents.get_by_id(agent_id)
    if not agent:
        raise NotFoundError("Agent not found")
    return {
        "data": {
            "id": agent.id,
            "sessionId": agent.session_id,
            "status": agent.status,
            "waitingFor": [
                {
                    "callId": w.call_id,
                    "type": w.type,
                    "name": w.name,
                    "description": w.description,
                }
                for w in agent.waiting_for
            ],
            "turnCount": agent.turn_count,
            "depth": agent.depth,
            "parentId": agent.parent_id,
            "rootAgentId": agent.root_agent_id,
        },
        "error": None,
    }


# ── Deliver result to waiting agent ──────────────────────────────────────────


@app.post("/api/chat/agents/{agent_id}/deliver")
async def deliver(agent_id: str, body: DeliverRequest, user=Depends(require_auth)):
    resp = deliver_tool_result(
        repos,
        agent_id=agent_id,
        call_id=body.callId,
        output=body.output,
        is_error=body.isError,
    )
    status_code = 202 if resp.get("status") == "waiting" else 200
    return JSONResponse(
        content=DeliverResponse(**resp).model_dump(), status_code=status_code
    )


# ── Cancel agent ──────────────────────────────────────────────────────────────


@app.post("/api/chat/agents/{agent_id}/cancel")
async def cancel_agent_endpoint(agent_id: str, user=Depends(require_auth)):
    from runner import cancel_running_agent

    cancel_running_agent(agent_id, repos)
    return {"data": {"id": agent_id, "status": "cancelled"}, "error": None}


# ── MCP endpoints ────────────────────────────────────────────────────────────


@app.get("/api/mcp/servers")
async def list_mcp_servers():
    from mcp_client import get_mcp_manager

    mcp = get_mcp_manager()
    if not mcp:
        return {"data": [], "error": None}
    return {"data": mcp.servers(), "error": None}


@app.get("/api/mcp/tools")
async def list_mcp_tools():
    from mcp_client import get_mcp_manager

    mcp = get_mcp_manager()
    if not mcp:
        return {"data": [], "error": None}
    tools = [
        {
            "server": t.server,
            "name": t.prefixed_name,
            "originalName": t.original_name,
            "description": t.description,
        }
        for t in mcp.list_tools()
    ]
    return {"data": tools, "error": None}


# ── Provider info ────────────────────────────────────────────────────────────


@app.get("/api/providers")
async def list_providers_endpoint():
    from provider_registry import list_providers

    return {"data": list_providers(), "error": None}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

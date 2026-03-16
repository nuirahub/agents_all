"""
FastAPI HTTP API for the 01_05_02 agent runtime.
Full-ish port of 4th-devs/01_05_agent chat endpoints.
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from chat_service import chat_once, deliver_tool_result
from repositories import create_memory_repositories

repos = create_memory_repositories()


class ChatRequest(BaseModel):
    input: str
    instructions: str | None = None
    model: str | None = None


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


app = FastAPI(title="01_05_02 Agent API", version="1.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/chat/completions", response_model=ChatResponse)
async def create_completion(body: ChatRequest) -> ChatResponse:
    resp = chat_once(
        repos,
        input_text=body.input,
        instructions=body.instructions or "You are a helpful assistant.",
        model=body.model,
    )
    return ChatResponse(**resp)


@app.post("/api/chat/agents/{agent_id}/deliver", response_model=DeliverResponse)
async def deliver(agent_id: str, body: DeliverRequest) -> DeliverResponse:
    resp = deliver_tool_result(
        repos,
        agent_id=agent_id,
        call_id=body.callId,
        output=body.output,
        is_error=body.isError,
    )
    return DeliverResponse(**resp)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("01_05_02.app:app", host="0.0.0.0", port=8000, reload=True)


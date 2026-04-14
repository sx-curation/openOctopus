"""
GitHub Copilot Extension webhook handler for OpenOctopus.

When a user types "@openoctopus AAPL" in GitHub Copilot Chat, GitHub sends
a POST to this endpoint with an OpenAI-compatible chat messages payload.

The handler:
  1. Validates the GitHub token (X-GitHub-Token header)
  2. Extracts the user's message
  3. Runs the equity analysis (in an executor thread, since it's blocking)
  4. Streams the response as OpenAI chat.completion.chunk SSE events

Responses MUST use the OpenAI streaming format — Copilot Chat renders
delta.content as markdown; any other format shows raw JSON.

Deploy alongside the REST API (Target 1) in the same Container Apps environment,
using copilot/Dockerfile on port 8080.
"""
import asyncio
import json
import logging
import os
import uuid
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent.loop import run_analysis

app = FastAPI(title="OpenOctopus Copilot Extension")
logger = logging.getLogger(__name__)


async def _verify_github_token(token: str) -> bool:
    """Verify the GitHub token is valid by calling the GitHub user API."""
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            return r.status_code == 200
    except Exception:
        return False


async def _stream_analysis(query: str) -> AsyncGenerator[str, None]:
    """
    Run analysis and yield OpenAI chat.completion.chunk SSE events.
    Sends an immediate 'Analyzing...' chunk so Copilot Chat shows activity
    rather than a silent wait during the 30-45 second analysis.
    """
    _id = str(uuid.uuid4())

    def _chunk(content: str, finish: str | None = None) -> str:
        payload = {
            "id": _id,
            "object": "chat.completion.chunk",
            "choices": [
                {"delta": {"content": content}, "finish_reason": finish, "index": 0}
            ],
        }
        return f"data: {json.dumps(payload)}\n\n"

    # Immediate acknowledgement
    yield _chunk(f"Analyzing **{query}**...\n\n")

    try:
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(None, run_analysis, query)

        # Stream in 500-char chunks so Copilot renders progressively
        chunk_size = 500
        for i in range(0, len(report), chunk_size):
            yield _chunk(report[i : i + chunk_size])

    except Exception as exc:
        logger.exception("Analysis failed for query: %s", query)
        yield _chunk(f"\n\n**Error:** {exc}")

    # Final stop event
    payload_stop = {
        "id": _id,
        "object": "chat.completion.chunk",
        "choices": [{"delta": {}, "finish_reason": "stop", "index": 0}],
    }
    yield f"data: {json.dumps(payload_stop)}\n\n"
    yield "data: [DONE]\n\n"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/copilot")
async def copilot_webhook(request: Request):
    """
    GitHub Copilot Extension entry point.

    GitHub sends the conversation as an OpenAI-compatible messages array.
    We extract the latest user message and stream back the analysis.
    """
    # Validate GitHub token
    token = request.headers.get("X-GitHub-Token", "")
    if os.environ.get("VERIFY_GITHUB_TOKEN", "true").lower() != "false":
        if not await _verify_github_token(token):
            raise HTTPException(status_code=401, detail="Invalid GitHub token")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages", [])
    user_msg = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"),
        "",
    )

    if not user_msg.strip():
        raise HTTPException(status_code=400, detail="No user message found")

    return StreamingResponse(
        _stream_analysis(user_msg.strip()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

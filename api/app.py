"""
FastAPI REST wrapper for the OpenOctopus equity research agent.

Endpoints:
  GET  /health    — liveness probe for Azure Container Apps
  POST /analyze   — run a full equity analysis, returns markdown report

run_analysis() is blocking (uses ThreadPoolExecutor internally), so it is
pushed to an executor thread to avoid blocking the uvicorn event loop.
"""
import asyncio
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent.loop import run_analysis

app = FastAPI(title="OpenOctopus Equity Research API", version="1.0.0")
logger = logging.getLogger(__name__)


class AnalysisRequest(BaseModel):
    query: str          # ticker ("AAPL") or natural-language question
    request_id: str = ""


class AnalysisResponse(BaseModel):
    report: str
    request_id: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(req: AnalysisRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")
    try:
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(None, run_analysis, req.query)
        return AnalysisResponse(report=report, request_id=req.request_id)
    except Exception as exc:
        logger.exception("Analysis failed for query: %s", req.query)
        raise HTTPException(status_code=500, detail=str(exc))

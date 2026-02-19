from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.supervisor import SupervisorAgent

app = FastAPI(title="Autonomous CI/CD Healing Agent")
supervisor = SupervisorAgent()
settings = get_settings()
RESULTS_FILE = Path(__file__).with_name("results.json")


class RunRequest(BaseModel):
    repo_url: str
    team_name: str
    leader_name: str
    retry_limit: int | None = Field(default=None, ge=1, le=50)


@app.post("/run")
@app.post("/execute")
async def run_workflow(payload: RunRequest) -> dict:
    retry_limit = payload.retry_limit or settings.max_retries
    result = await supervisor.execute(
        repo_url=payload.repo_url,
        team_name=payload.team_name,
        leader_name=payload.leader_name,
        retry_limit=min(retry_limit, settings.max_retries),
    )
    RESULTS_FILE.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


@app.get("/results")
async def get_results() -> dict:
    if not RESULTS_FILE.exists():
        raise HTTPException(status_code=404, detail="results.json not found")
    return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

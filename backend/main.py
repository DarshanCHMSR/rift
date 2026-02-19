from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Load .env before any settings are read so os.getenv() picks up the values.
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=_env_path, override=False)
except ImportError:
    pass  # python-dotenv not installed — rely on real env vars

from backend.config import get_settings
from backend.supervisor import SupervisorAgent
from backend.logging_config import setup_logging

setup_logging()

app = FastAPI(
    title="RIFT — Autonomous CI/CD Healing Agent",
    description="Multi-agent system that diagnoses failing tests, generates fixes, and verifies them in Docker sandboxes.",
    version="2.0.0",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

supervisor = SupervisorAgent()
settings = get_settings()
RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)
RESULTS_FILE = Path(__file__).with_name("results.json")

# Serve the pre-built React SPA when running outside Docker (optional).
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/ui", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")


# ── Rate limiting (simple in-memory per-IP) ──────────────────────────────────
_rate_store: dict[str, list[float]] = {}
_RATE_LIMIT = 5       # max runs per window
_RATE_WINDOW = 3600   # 1 hour in seconds


def _check_rate(ip: str) -> bool:
    import time
    now = time.time()
    hits = _rate_store.get(ip, [])
    hits = [t for t in hits if now - t < _RATE_WINDOW]
    if len(hits) >= _RATE_LIMIT:
        return False
    hits.append(now)
    _rate_store[ip] = hits
    return True


# ── API key middleware ────────────────────────────────────────────────────────
@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    rift_key = settings.rift_api_key
    if rift_key:
        exempt = ("/health", "/docs", "/openapi.json", "/ui")
        if not any(request.url.path.startswith(p) for p in exempt):
            provided = request.headers.get("X-RIFT-KEY", "")
            if provided != rift_key:
                return _json_response(403, "Invalid or missing X-RIFT-KEY header")
    return await call_next(request)


def _json_response(status: int, detail: str):
    from starlette.responses import JSONResponse
    return JSONResponse(status_code=status, content={"detail": detail})


class RunRequest(BaseModel):
    repo_url: str
    team_name: str
    leader_name: str
    retry_limit: int | None = Field(default=None, ge=1, le=50)


@app.post("/run")
@app.post("/execute")
async def run_workflow(payload: RunRequest, request: Request) -> dict:
    # Rate limit
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded (5 runs/hr)")

    retry_limit = payload.retry_limit or settings.max_retries
    result = await supervisor.execute(
        repo_url=payload.repo_url,
        team_name=payload.team_name,
        leader_name=payload.leader_name,
        retry_limit=min(retry_limit, settings.max_retries),
    )

    # Save to results/ directory with timestamp
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_file = RESULTS_DIR / f"run_{run_ts}.json"
    run_json = json.dumps(result, indent=2)
    run_file.write_text(run_json, encoding="utf-8")

    # latest.json symlink / copy
    latest = RESULTS_DIR / "latest.json"
    latest.write_text(run_json, encoding="utf-8")

    # Legacy results.json
    RESULTS_FILE.write_text(run_json, encoding="utf-8")

    return result


@app.get("/results")
async def get_results() -> dict:
    latest = RESULTS_DIR / "latest.json"
    if latest.exists():
        return json.loads(latest.read_text(encoding="utf-8"))
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="No results found")


@app.get("/runs")
async def list_runs() -> list[dict]:
    """Return a list of all historical runs (newest first)."""
    runs = []
    for f in sorted(RESULTS_DIR.glob("run_*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            runs.append({
                "id": f.stem,
                "file": f.name,
                "team_name": data.get("team_name", ""),
                "final_status": data.get("final_status", ""),
                "score": data.get("score", 0),
                "time_taken": data.get("time_taken", 0),
            })
        except Exception:
            continue
    return runs


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    """Return a specific historical run by ID."""
    run_file = RESULTS_DIR / f"{run_id}.json"
    if not run_file.exists():
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return json.loads(run_file.read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> dict:
    from backend.services.gemini_service import build_gemini_service
    gemini = build_gemini_service()
    return {
        "status": "ok",
        "gemini": "available" if gemini.available else "unavailable (GEMINI_API_KEY not set)",
        "github_token": "set" if settings.github_token else "missing",
        "api_key_required": bool(settings.rift_api_key),
    }


# ── Dev entrypoint ────────────────────────────────────────────────────────────
# Run with:  python -m backend.main  OR  python backend/main.py
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)

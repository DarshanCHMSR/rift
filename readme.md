# RIFT — Autonomous CI/CD Healing Agent

> **RIFT** (**R**epair, **I**terate, **F**ix, **T**est) is a production-grade multi-agent system that automatically diagnoses failing test suites, generates code fixes using a **hybrid rule-engine + Gemini LLM** pipeline, commits them to an isolated branch, and verifies the result inside a Docker sandbox — without ever touching `main`.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Multi-Agent Pipeline](#multi-agent-pipeline)
3. [Key Features](#key-features)
4. [Tech Stack](#tech-stack)
5. [Supported Bug Types](#supported-bug-types)
6. [Environment Variables](#environment-variables)
7. [Local Setup](#local-setup)
8. [Docker / Production Deployment](#docker--production-deployment)
9. [API Reference](#api-reference)
10. [Scoring System](#scoring-system)
11. [Security](#security)
12. [Testing](#testing)
13. [Observability](#observability)
14. [Branch & Commit Safety](#branch--commit-safety)
15. [Known Limitations](#known-limitations)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        RIFT System v2                               │
│                                                                     │
│  ┌──────────┐   REST    ┌─────────────────────────────────────────┐ │
│  │ React    │ ◄───────► │  FastAPI  (backend/main.py)             │ │
│  │ Frontend │  /run     │  + API key auth + rate limiting         │ │
│  │ (Vite +  │  /results │  ┌──────────────────────────────────┐  │ │
│  │ Zustand) │  /health  │  │        SupervisorAgent           │  │ │
│  └──────────┘           │  │  (LangChain RunnableLambda chain) │  │ │
│                         │  └──────┬──────────────────────┬─────┘  │ │
│                         │         │                      │        │ │
│                         │  ┌──────▼──────┐   ┌──────────▼──────┐ │ │
│                         │  │ RepoAnalyzer│   │  CICDMonitor    │ │ │
│                         │  │   Agent     │   │  (timeline log) │ │ │
│                         │  └──────┬──────┘   └─────────────────┘ │ │
│                         │         │                               │ │
│                         │  ┌──────▼──────┐                       │ │
│                         │  │ TestRunner  │◄──── Docker SDK ────┐  │ │
│                         │  │   Agent     │                     │  │ │
│                         │  └──────┬──────┘   ┌────────────────┐│  │ │
│                         │         │           │ Isolated       ││  │ │
│                         │  ┌──────▼──────┐   │ Container      ││  │ │
│                         │  │ ErrorParser │   │ (python/node)  ││  │ │
│                         │  │   Agent     │   │ Clone→Test→Die ││  │ │
│                         │  └──────┬──────┘   └────────────────┘│  │ │
│                         │         │                             │  │ │
│                         │  ┌──────▼──────┐                     │  │ │
│                         │  │ FixGenerator│  (rule-based +      │  │ │
│                         │  │   Agent     │   pattern matching)  │  │ │
│                         │  └──────┬──────┘                     │  │ │
│                         │         │                             │  │ │
│                         │  ┌──────▼──────┐                     │  │ │
│                         │  │   Commit    │ ──► [AI-AGENT] msg  │  │ │
│                         │  │   Agent     │     ↕ GitPython      │  │ │
│                         │  └──────┬──────┘   *_AI_Fix branch   │  │ │
│                         │         │                             │  │ │
│                         │  ┌──────▼──────┐                     │  │ │
│                         │  │  GitService │ push → GitHub ──────┘  │ │
│                         │  └─────────────┘  (sandbox verify)      │ │
│                         └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

**Data flow (one run):**

```
GitHub Repo URL
      │
      ▼
  [Clone + Branch]
      │
      ▼
  ┌─────────────────────────────────────────────┐
  │  Retry Loop  (up to MAX_RETRIES, 10m cap)   │
  │                                              │
  │  Test (Docker sandbox) ───PASS──► push ──► sandbox verify
  │          │                                   │
  │         FAIL                                 │
  │          │                                   │
  │  Parse errors (Python/JS/TS/Assertion)       │
  │          │                                   │
  │  ┌──────┴──────────┐                        │
  │  │ Rule-based fix  │  (parallel strategy)    │
  │  │ + LLM fix agent │  (Gemini structured)    │
  │  └──────┬──────────┘                        │
  │         │                                    │
  │  Commit [AI-AGENT] + interim push            │
  │          │                                   │
  │  ────────┘  (next attempt)                   │
  └─────────────────────────────────────────────┘
      │
      ▼
  Score  →  Workspace cleanup  →  Save to results/
```

---

## Multi-Agent Pipeline

| Agent | Role | Key Logic |
|---|---|---|
| **SupervisorAgent** | StateGraph orchestrator — coordinates all sub-agents | LangChain `RunnableLambda` nodes; 10-min timeout; workspace cleanup |
| **RepoAnalyzerAgent** | Clones the repo, creates the AI_Fix branch, detects test framework | Checks `package.json`, `pytest.ini`, `pyproject.toml`, `requirements.txt` |
| **TestRunnerAgent** | Executes tests inside isolated Docker containers | Volume-mount (fast local) + URL-clone (true sandbox verification) |
| **ErrorParserAgent** | Parses test output into structured issues with confidence scores | Python tracebacks, pytest, JS stack traces, TS compiler, assertions |
| **FixGeneratorAgent** | Applies deterministic code fixes to source files | Indentation, syntax, import, linting — falls back to Gemini LLM |
| **LLMFixAgent** | Structured Gemini patches with retry validation | Returns `{file, line, replacement, explanation}` JSON; auto-reverts bad patches |
| **CommitAgent** | Commits changes with `[AI-AGENT]` prefix; guards branch names | Uses GitPython; single commit per iteration (batched fixes) |
| **CICDMonitorAgent** | Appends timestamped events to the run timeline | Audit trail powering the frontend timeline and event log |

---

## Key Features

- **Hybrid Fix Engine** — rule-based heuristics handle common bugs instantly; Gemini LLM repairs complex TYPE_ERROR / LOGIC / ASSERTION errors with structured JSON patches
- **Parallel Fix Strategy** — rule engine and LLM agent run in parallel per iteration; single commit per retry batch
- **Sandbox Verification** — post-push Docker container clones directly from GitHub (no host FS access) to confirm the fix branch is truly green
- **Run History** — every run saved to `backend/results/run_<timestamp>.json`; browse past runs from the frontend dropdown or `GET /runs`
- **API Security** — optional `RIFT_API_KEY` header authentication; per-IP rate limiting (5 runs/hr)
- **10-Minute Timeout** — supervisor hard-caps each run to prevent runaway processes
- **Workspace Cleanup** — work directories are automatically deleted after each run completes
- **Enhanced Scoring** — base 100 + speed bonus + zero-fix bonus − commit penalty − sandbox penalty; capped 0–120
- **Structured Logging** — JSON log output with run ID correlation; per-run log files in `backend/logs/`
- **Progress Tracker** — animated pipeline stage indicator (Cloning → Testing → Fixing → Pushing → Verifying → Done)

---

## Tech Stack

| Layer | Technology |
|---|---|
| **API** | FastAPI 0.115 + Uvicorn |
| **Agent Orchestration** | LangChain Core (`RunnableLambda` StateGraph pattern) |
| **LLM** | Google Gemini 1.5 Flash (structured JSON patches) |
| **Container Isolation** | Docker SDK for Python 7.1 |
| **Git Operations** | GitPython 3.1 |
| **Frontend** | React 18 + Vite 6 + Zustand 5 + Recharts + Tailwind CSS |
| **Containerisation** | Docker + Docker Compose v3.9 |
| **Python** | 3.11 |
| **Node** | 20 (sandbox containers) |

---

## Supported Bug Types

| Type | Detection | Fix Strategy |
|---|---|---|
| `INDENTATION` | `IndentationError`, `TabError` | Replace tabs with spaces |
| `SYNTAX` | `SyntaxError`, `expected ':'` | Add missing colons |
| `IMPORT` | `ImportError`, `ModuleNotFoundError` | Disable import or create stub module |
| `LINTING` | Flake8 `F401`, `E302`, trailing whitespace | Remove unused imports; strip whitespace |
| `TYPE_ERROR` | `TypeError` in traceback | Gemini LLM structured repair |
| `LOGIC` | All other tracebacks | Gemini LLM structured repair |
| `ASSERTION` | `AssertionError`, `assert` failures | Gemini LLM structured repair |
| `REFERENCE` | `ReferenceError`, `is not defined` (JS) | Gemini LLM structured repair |

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_TOKEN` | ✅ | — | PAT with `repo` + `workflow` scopes |
| `GEMINI_API_KEY` | ✅ | — | Google Gemini key — powers LLM repair |
| `MAX_RETRIES` | ❌ | `5` | Fix-retry attempts per run (1–50) |
| `RIFT_API_KEY` | ❌ | — | When set, all non-health endpoints require `X-RIFT-KEY` header |

Copy `.env.example` → `.env` and fill in your values.

---

## Local Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker Desktop running locally

### 1 — Backend

```bash
cd backend
python -m venv myenv
myenv\Scripts\activate          # Windows
# source myenv/bin/activate     # macOS/Linux

pip install -r requirements.txt

# Set secrets
cp ..\.env.example ..\.env
# Edit .env → add GITHUB_TOKEN + GEMINI_API_KEY

# Start the API (from repo root)
cd ..
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 2 — Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

### 3 — Trigger a run

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/your-org/your-repo",
    "team_name": "AlphaTeam",
    "leader_name": "Alice"
  }'
```

---

## Docker / Production Deployment

```bash
cp .env.example .env          # configure secrets
docker compose up --build     # Backend → :8000 / Frontend → :3000
```

| Service | Port | Description |
|---|---|---|
| `rift_backend` | 8000 | FastAPI agent orchestrator |
| `rift_frontend` | 3000 | React SPA (nginx) |

```bash
docker compose down            # stop containers
docker compose down -v         # also remove workspace volume
```

---

## API Reference

### `POST /run` · `POST /execute`

Trigger a full healing run.

```json
{
  "repo_url":     "https://github.com/org/repo",
  "team_name":    "AlphaTeam",
  "leader_name":  "Alice",
  "retry_limit":  5
}
```

**Response:**

```json
{
  "repo_url":            "…",
  "branch_name":         "ALPHATEAM_ALICE_AI_Fix",
  "total_failures":      2,
  "total_fixes":         3,
  "final_status":        "PASSED",
  "time_taken":          47.3,
  "score":               110,
  "score_breakdown":     { "base": 100, "speed_bonus": 10, … },
  "fixes":               ["LINTING error in src/utils.py line 12 → Fix: removed unused import"],
  "sandbox_verification": { "exit_code": 0, "passed": true },
  "cicd timeline":       [{ "timestamp": "…", "stage": "…", "status": "…" }]
}
```

### `GET /results` — Latest run result

### `GET /runs` — List all historical runs (newest first)

### `GET /runs/{run_id}` — Fetch a specific past run

### `GET /health` — Health check (Gemini status, token status, API key requirement)

---

## Scoring System

| Component | Points | Condition |
|---|---|---|
| Base score | 100 | Always |
| Speed bonus | +10 | Total time < 300s |
| Zero-fix bonus | +5 | No fixes needed & sandbox didn't fail |
| Commit penalty | −2 × (commits − 20) | If > 20 commits |
| Sandbox penalty | −20 | Sandbox verification failed |
| **Cap** | **0 – 120** | Floor at 0, ceiling at 120 |

---

## Security

- **API Key** — set `RIFT_API_KEY` env var; all non-health endpoints require `X-RIFT-KEY` header
- **Rate Limiting** — 5 runs per hour per IP address (in-memory)
- **10-Min Timeout** — supervisor kills the pipeline if it exceeds 600 seconds
- **Branch Guards** — never pushes to `main`/`master`; branch must match `[A-Z0-9_]+_AI_Fix`
- **Docker Sandbox** — `cap_drop=ALL`, `no-new-privileges`, 1 GB RAM, 1 vCPU, auto-destroy

---

## Testing

```bash
# From repo root
pip install pytest
pytest tests/ -v
```

Test suite covers:
- `test_error_parser.py` — Python/JS/TS parsing, classification, confidence scores
- `test_scoring_service.py` — Base, bonuses, penalties, cap enforcement
- `test_git_service.py` — Branch validation, protected branch blocks, URL auth injection

---

## Observability

- **Structured JSON logs** — every log line is JSON with `ts`, `level`, `logger`, `msg`, optional `run_id`
- **Per-run log files** — saved to `backend/logs/<run_id>.log`
- **Timeline events** — full audit trail in response `"cicd timeline"` array
- **Event log modal** — click "View Event Log" in the frontend to inspect all pipeline events

---

## Branch & Commit Safety

| Rule | Enforcement |
|---|---|
| Never push to `main` or `master` | `GitService.push_branch` hard-blocks protected names |
| Branch must end with `_AI_Fix` | Validated by regex before every push |
| Branch format | `{TEAM}_{LEADER}_AI_Fix` — uppercase alphanumeric + underscores |
| All commits prefixed `[AI-AGENT]` | `GitService.commit_all` prepends if absent |
| Sandbox isolation | `cap_drop=ALL`, `no-new-privileges`, 1 GB RAM, 1 vCPU |

---

## Known Limitations

| Area | Limitation |
|---|---|
| **Fix quality** | Complex algorithmic bugs may require manual review even with Gemini |
| **Test frameworks** | `pytest`, `unittest`, `npm test` only. Maven/Go/Rust not yet supported |
| **Docker-in-Docker** | Docker socket sharing required. In Kubernetes, use Kaniko or remote daemon |
| **Rate limiting** | In-memory only — resets on restart. Use Redis for multi-instance deployments |
| **Concurrent runs** | Each run creates a unique workspace directory; no distributed locking. Running many concurrent jobs may exhaust disk space or Docker resources. |
| **LLM dependency** | `GEMINI_API_KEY` is required for TYPE_ERROR and LOGIC bug fixes. Rule-based fixes (LINTING, SYNTAX, INDENTATION, IMPORT) work without it. |
| **Private repos** | Only GitHub HTTPS URLs with a PAT are supported. SSH URLs and GitLab/Bitbucket require minor changes to `GitService._auth_repo_url`. |
| **Windows host** | Volume mounts in `docker_service.py` use POSIX paths. On Windows, Docker Desktop translates paths automatically; WSL2 backend is recommended. |

# RIFT — Autonomous CI/CD Healing Agent

> **RIFT** (**R**epair, **I**terate, **F**ix, **T**est) is a multi-agent system that automatically diagnoses failing test suites, generates code fixes, commits them to an isolated branch, and verifies the result inside a Docker sandbox — without ever touching `main`.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Multi-Agent Pipeline](#multi-agent-pipeline)
3. [Tech Stack](#tech-stack)
4. [Supported Bug Types](#supported-bug-types)
5. [Environment Variables](#environment-variables)
6. [Local Setup](#local-setup)
7. [Docker / Production Deployment](#docker--production-deployment)
8. [API Reference](#api-reference)
9. [Branch & Commit Safety](#branch--commit-safety)
10. [Known Limitations](#known-limitations)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        RIFT System                                  │
│                                                                     │
│  ┌──────────┐   REST    ┌─────────────────────────────────────────┐ │
│  │ React    │ ◄───────► │  FastAPI  (backend/main.py)             │ │
│  │ Frontend │  /run     │                                         │ │
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
  ┌─────────────────────────────────────┐
  │  Retry Loop  (up to MAX_RETRIES)    │
  │                                     │
  │  Test (Docker container) ──PASS──► push branch ──► sandbox verify
  │          │                          │
  │         FAIL                        │
  │          │                          │
  │  Parse errors                       │
  │          │                          │
  │  Generate fixes                     │
  │          │                          │
  │  Commit [AI-AGENT] + push           │
  │          │                          │
  │  ────────┘  (next attempt)          │
  └─────────────────────────────────────┘
```

---

## Multi-Agent Pipeline

| Agent | Role | Key Logic |
|---|---|---|
| **SupervisorAgent** | Orchestrates the full pipeline via a LangChain `RunnableLambda` chain | Coordinates all sub-agents; owns the retry loop |
| **RepoAnalyzerAgent** | Clones the repo, creates the AI_Fix branch, detects test framework | Checks for `package.json`, `pytest.ini`, `pyproject.toml`, `requirements.txt` |
| **TestRunnerAgent** | Executes tests inside isolated Docker containers | Volume-mount mode (fast local); URL-clone mode (post-push sandbox verification) |
| **ErrorParserAgent** | Parses raw test output into structured issue records | Regex on Python tracebacks, pytest output, flake8 codes |
| **FixGeneratorAgent** | Applies deterministic code fixes to source files | Rule-based: indentation, syntax, import resolution, linting whitespace |
| **CommitAgent** | Commits changes with `[AI-AGENT]` prefix; guards branch names | Uses GitPython; calls `git_service.commit_all` |
| **CICDMonitorAgent** | Appends timestamped events to the run timeline | Provides audit trail for the frontend timeline view |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **API** | FastAPI 0.115 + Uvicorn |
| **Agent Orchestration** | LangChain Core (`RunnableLambda` supervisor pattern) |
| **Container Isolation** | Docker SDK for Python 7.1 |
| **Git Operations** | GitPython 3.1 |
| **Frontend** | React 18 + Vite 6 + Zustand + Recharts + Tailwind CSS |
| **Containerisation** | Docker + Docker Compose v3.9 |
| **Python** | 3.11 |
| **Node** | 20 (sandbox containers) |

---

## Supported Bug Types

| Type | Detection | Fix Strategy |
|---|---|---|
| `INDENTATION` | `IndentationError`, `TabError` | Re-indent file with `autopep8`-style rules |
| `SYNTAX` | `SyntaxError`, `expected ':'` | Remove stray characters; fix missing colons |
| `IMPORT` | `ImportError`, `ModuleNotFoundError` | Add missing `pip install` to `requirements.txt`; stub missing local module |
| `LINTING` | Flake8 `F401`, `E302`, trailing whitespace | Remove unused imports; add blank lines; strip trailing spaces |
| `TYPE_ERROR` | `TypeError` in traceback | Detected; fix generation currently rule-limited (LLM extension point) |
| `LOGIC` | All other tracebacks | Recorded in timeline; manual review recommended |

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_TOKEN` | ✅ | — | PAT with `repo` + `workflow` scopes |
| `OPENAI_API_KEY` | ✅ | — | OpenAI key (used by FixGeneratorAgent LLM path) |
| `MAX_RETRIES` | ❌ | `5` | Fix-retry attempts per run (clamped 1–50) |

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

# Windows
myenv\Scripts\activate

# macOS/Linux
source myenv/bin/activate

pip install -r requirements.txt

# Set secrets
cp ..\\.env.example ..\\.env
# Edit .env and add GITHUB_TOKEN + OPENAI_API_KEY

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

Results are persisted to `backend/results.json` and served at `GET /results`.

---

## Docker / Production Deployment

### Quick start (recommended)

```bash
# 1. Clone the repository
git clone https://github.com/your-org/rift.git
cd rift

# 2. Configure secrets
cp .env.example .env
# Open .env in your editor and set GITHUB_TOKEN and OPENAI_API_KEY

# 3. Build and start all services
docker compose up --build

# Backend → http://localhost:8000
# Frontend → http://localhost:3000
```

### Services

| Service | Port | Description |
|---|---|---|
| `rift_backend` | 8000 | FastAPI agent orchestrator |
| `rift_frontend` | 3000 | React SPA (nginx) |

### Stopping

```bash
docker compose down          # stop and remove containers
docker compose down -v       # also remove the workspace volume
```

### Scaling workers

```bash
docker compose up --build --scale backend=2
```

### Environment secrets in CI/CD

Set `GITHUB_TOKEN`, `OPENAI_API_KEY`, and optionally `MAX_RETRIES` as repository secrets (GitHub Actions, GitLab CI, etc.) and pass them to `docker compose` via `--env-file` or `-e` flags. **Never hard-code them in the image.**

### Production notes

- The backend container mounts `/var/run/docker.sock` so it can spawn sandbox child containers. Restrict access accordingly in production.
- All sandbox containers are automatically destroyed after each test run.
- The `workspace_data` Docker volume persists run workspaces across restarts; prune it periodically with `docker volume prune`.

---

## API Reference

### `POST /run` · `POST /execute`

Trigger a full agent run.

**Request body:**

```json
{
  "repo_url":     "https://github.com/org/repo",
  "team_name":    "AlphaTeam",
  "leader_name":  "Alice",
  "retry_limit":  5
}
```

**Response (200):**

```json
{
  "repo_url":          "https://github.com/org/repo",
  "team_name":         "AlphaTeam",
  "leader_name":       "Alice",
  "branch_name":       "ALPHATEAM_ALICE_AI_Fix",
  "total_failures":    2,
  "total_fixes":       3,
  "final_status":      "PASSED",
  "time_taken":        47.3,
  "score":             110,
  "fixes":             ["LINTING error in src/utils.py line 12 -> Fix: removed unused import"],
  "sandbox_verification": {
    "exit_code": 0,
    "duration":  12.1,
    "passed":    true,
    "branch":    "ALPHATEAM_ALICE_AI_Fix"
  },
  "cicd timeline":     [...]
}
```

### `GET /results`

Returns the most recent run result from `results.json`.

### `GET /health`

Returns `{"status": "ok"}`. Used by Docker health checks.

---

## Branch & Commit Safety

| Rule | Enforcement |
|---|---|
| Never push to `main` or `master` | `GitService.push_branch` hard-blocks pushes to protected names |
| Branch must end with `_AI_Fix` | Validated by regex before every push |
| Branch name format | `{TEAM}_{LEADER}_AI_Fix` — uppercase alphanumeric + underscores only |
| All commits prefixed `[AI-AGENT]` | `GitService.commit_all` prepends the prefix if absent |
| Sandbox containers | `cap_drop=ALL`, `security_opt=no-new-privileges`, 1 GB RAM, 1 vCPU |

---

## Known Limitations

| Area | Limitation |
|---|---|
| **Fix quality** | FixGeneratorAgent is currently rule-based. Complex logic bugs (off-by-one, algorithmic errors) are detected but not fixed. An LLM-assisted fix path is stubbed and ready for extension. |
| **Test frameworks** | Supports `pytest`, `unittest` (Python), and `npm test` (Node). Maven, Gradle, Go, Rust are not yet supported. |
| **Docker-in-Docker** | Production deployment requires the Docker socket to be shared. In hardened environments (Kubernetes), replace with Kaniko or a remote Docker daemon. |
| **Concurrent runs** | Each run creates a unique workspace directory; no distributed locking. Running many concurrent jobs may exhaust disk space or Docker resources. |
| **LLM dependency** | `OPENAI_API_KEY` is required even when the rule-based fixer handles all errors. The LLM call path can be disabled by removing the import without breaking core functionality. |
| **Private repos** | Only GitHub HTTPS URLs with a PAT are supported. SSH URLs and GitLab/Bitbucket require minor changes to `GitService._auth_repo_url`. |
| **Windows host** | Volume mounts in `docker_service.py` use POSIX paths. On Windows, Docker Desktop translates paths automatically; WSL2 backend is recommended. |

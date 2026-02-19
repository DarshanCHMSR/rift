# RIFT — Project Analysis

> Full technical analysis of the **RIFT Autonomous CI/CD Healing Agent** codebase.  
> Generated: February 2026

---

## Table of Contents

1. [Project Overview](#
++++++1-project-overview)
2. [Repository Structure](#2-repository-structure)
3. [Backend Analysis](#3-backend-analysis)
   - [Entry Point & Configuration](#31-entry-point--configuration)
   - [Supervisor Orchestrator](#32-supervisor-orchestrator)
   - [Agent Inventory](#33-agent-inventory)
   - [Service Layer](#34-service-layer)
4. [Frontend Analysis](#4-frontend-analysis)
   - [Component Tree](#41-component-tree)
   - [State Management](#42-state-management)
   - [Data Normalisation Pipeline](#43-data-normalisation-pipeline)
5. [Data Flow (End-to-End)](#5-data-flow-end-to-end)
6. [API Contract](#6-api-contract)
7. [Docker & Deployment Model](#7-docker--deployment-model)
8. [Bugs Fixed in This Session](#8-bugs-fixed-in-this-session)
9. [Security Posture](#9-security-posture)
10. [Performance Characteristics](#10-performance-characteristics)
11. [Test Coverage Assessment](#11-test-coverage-assessment)
12. [Dependency Inventory](#12-dependency-inventory)
13. [Configuration Reference](#13-configuration-reference)
14. [Known Limitations & Improvement Areas](#14-known-limitations--improvement-areas)
15. [Startup Quick Reference](#15-startup-quick-reference)

---

## 1. Project Overview

RIFT is a **multi-agent autonomous CI/CD healing system**.  Given a GitHub repository URL it:

1. Clones the repo into an isolated Docker container.
2. Runs the test suite (`pytest`, `unittest`, or `npm test`).
3. If tests fail, parses the output for structured error records.
4. Applies deterministic code fixes (indentation, syntax, imports, linting).
5. Commits the fixes with a `[AI-AGENT]` prefix on a dedicated `*_AI_Fix` branch.
6. Pushes the branch and then **verifies the pushed state** by re-running the tests inside a second, completely isolated container that clones directly from GitHub (no host filesystem access).
7. Returns a scored result, full timeline, and per-fix breakdown to a React dashboard.

---

## 2. Repository Structure

```
rift/
├── backend/                   Python FastAPI application
│   ├── main.py                FastAPI app, CORS, .env loading, uvicorn entrypoint
│   ├── config.py              Settings dataclass (GITHUB_TOKEN, OPENAI_API_KEY, MAX_RETRIES)
│   ├── supervisor.py          LangChain RunnableLambda orchestrator (the "brain")
│   ├── requirements.txt       Pinned Python dependencies
│   ├── agents/
│   │   ├── cicd_monitor.py    Timestamped timeline event recorder
│   │   ├── commit_agent.py    Git commit with [AI-AGENT] prefix enforcement
│   │   ├── error_parser.py    Regex parser: tracebacks → structured issue records
│   │   ├── fix_generator.py   Rule-based code fixer (5 bug categories)
│   │   ├── repo_analyzer.py   Clone + branch creation + framework detection
│   │   └── test_runner.py     Docker test executor (volume-mount + URL-clone modes)
│   └── services/
│       ├── docker_service.py  Docker SDK wrapper — sandbox container lifecycle
│       ├── git_service.py     GitPython wrapper — clone, branch, commit, push
│       └── scoring_service.py Score formula: 100 + speed_bonus − commit_penalty
├── frontend/                  React 18 SPA
│   ├── index.html
│   ├── vite.config.js         Vite + dev proxy (→ :8000)
│   ├── tailwind.config.js     Dark night-sky theme
│   ├── src/
│   │   ├── main.jsx           React root
│   │   ├── App.jsx            Layout + lazy component loading
│   │   ├── index.css          Tailwind + custom dark background
│   │   ├── components/
│   │   │   ├── InputSection.jsx        Form: repo URL, team, leader, retry limit
│   │   │   ├── RunSummaryCard.jsx      High-level metrics grid
│   │   │   ├── ScoreBreakdownPanel.jsx Recharts bar chart + score tiles
│   │   │   ├── CICDTimeline.jsx        Per-attempt PASS/FAIL/RUNNING cards
│   │   │   └── FixesAppliedTable.jsx   Detailed fix table with status badges
│   │   └── store/
│   │       └── useAgentStore.js        Zustand store + fetch logic + data normalisers
├── Dockerfile                 Multi-stage: Node 20 build + Python 3.11-slim runtime
├── docker-compose.yml         Backend (8000) + Nginx frontend (3000) + volume
├── .env.example               Token template
├── .gitignore
└── readme.md                  User-facing README with ASCII architecture diagram
```

---

## 3. Backend Analysis

### 3.1 Entry Point & Configuration

**`backend/main.py`**

| Responsibility | Implementation |
|---|---|
| Environment loading | `python-dotenv` loads `.env` at import time before settings are read |
| CORS | `CORSMiddleware` allows `localhost:5173` and `localhost:3000` |
| Static file serving | Mounts `/ui` → `frontend/dist/` if the directory exists |
| Routes | `POST /run`, `POST /execute`, `GET /results`, `GET /health` |
| Dev entrypoint | `if __name__ == "__main__": uvicorn.run(...)` — enables `python -m backend.main` |

**`backend/config.py`**

```python
@dataclass(frozen=True)
class Settings:
    github_token: str       # GITHUB_TOKEN env var
    openai_api_key: str     # OPENAI_API_KEY env var
    max_retries: int        # MAX_RETRIES env var, clamped 1–50, default 5
```

`_clamp_retry` guards against invalid inputs (non-numeric strings, out-of-range integers).

---

### 3.2 Supervisor Orchestrator

**`backend/supervisor.py`** — `SupervisorAgent`

The supervisor implements the **LangChain Supervisor pattern**: each sub-agent is wrapped in a `RunnableLambda` so the full pipeline is composable, inspectable, and extensible.

**Execution flow (`_execute_sync`)**:

```
1. Create isolated workspace directory (uuid4 run-id)
2. RepoAnalyzerAgent  → clone repo, create AI_Fix branch, detect framework
3. For attempt in 1..retry_limit:
   a. TestRunnerAgent (volume-mount)  → run tests in Docker container
   b. If exit_code == 0 → PASSED, break
   c. ErrorParserAgent               → parse failures into issues[]
   d. FixGeneratorAgent              → apply fixes, return fix records
   e. CommitAgent                    → git commit with [AI-AGENT] prefix
   f. GitService.push_branch()       → interim push (branch stays current)
4. Final push (idempotent)
5. IF PASSED AND push succeeded:
   TestRunnerAgent (URL-clone sandbox) → clone from GitHub, run tests in fresh container
6. ScoringService.calculate_score()
7. Return result dict → persisted to results.json
```

**Branch naming**: `{TEAM}_{LEADER}_AI_Fix` (uppercase, alphanumeric + underscores).

---

### 3.3 Agent Inventory

#### `CICDMonitorAgent`
- Appends `{ timestamp, stage, status, details }` records to a shared in-memory `timeline` list.
- No state; pure recorder.

#### `RepoAnalyzerAgent`
- **Clone**: `GitService.clone_repo()`.
- **Branch**: `git checkout -b {branch_name}` (idempotent — skips if already exists).
- **Framework detection priority**: `package.json` → `pytest.ini` → `pyproject.toml` → `requirements.txt` → `tests/` directory → fallback `unittest`.

#### `TestRunnerAgent`
- **`run()`**: Volume-mount mode. Host repo path → `/seed/repo` (read-only). Container clones to `/workspace/repo` internally. Fast; used in retry loop.
- **`run_sandbox()`**: URL-clone mode. No host paths. GitHub repo cloned inside container. Used for final post-push verification.

#### `ErrorParserAgent`
Applies two regex passes over test output:

| Pattern | Extracts |
|---|---|
| `File "(.+?)", line (\d+)` | Python tracebacks |
| `^(.+?):(\d+):\s*(.+)$` + error token | Pytest/flake8 output |

**Bug classification** (`_classify`):

```
INDENTATION  → IndentationError / TabError
SYNTAX       → SyntaxError / expected ':'
IMPORT       → ImportError / ModuleNotFoundError / No module named
TYPE_ERROR   → TypeError
LINTING      → flake8 / F401 / E302 / trailing whitespace
LOGIC        → everything else (fallback)
```

If no issues are parsed but output is non-empty, a single LOGIC record is created from the last output line (max 300 chars).

#### `FixGeneratorAgent`
Rule-based fixer keyed on `error_type`:

| Type | Strategy |
|---|---|
| `LINTING` | Remove unused import lines; strip trailing whitespace; add blank lines before `def`/`class` |
| `SYNTAX` | Remove stray characters at error line; add missing `:` |
| `INDENTATION` | Re-indent file with 4-space normalization via `ast` parse + rewrite |
| `IMPORT` | Append missing package to `requirements.txt`; create stub module file if local |
| `TYPE_ERROR` / `LOGIC` | Detected; no automated fix (extension point) |

Each fix produces a `summary` string: `"{TYPE} error in {file} line {n} -> Fix: {description}"`.

#### `CommitAgent`
- Calls `GitService.commit_all()` which:
  - Stages all changes (`git add -A`).
  - Only commits if the working tree is dirty.
  - Enforces `[AI-AGENT]` prefix (prepends if absent).
  - Auto-configures git identity (`AI Agent <ai-agent@local>`) if not set.

---

### 3.4 Service Layer

#### `DockerService`

Two public methods:

| Method | Sandbox Mode | Host Filesystem | Use Case |
|---|---|---|---|
| `run_tests(repo_path, framework)` | Volume mount | Read-only at `/seed/repo` | Fast local retry loop |
| `run_sandbox_from_url(repo_url, branch, framework)` | URL clone | None | Post-push verification |

**Container security defaults** (both modes):
- `cap_drop=["ALL"]` — drops all Linux capabilities
- `security_opt=["no-new-privileges"]` — prevents privilege escalation
- `mem_limit="1g"` — 1 GB RAM cap
- `nano_cpus=1_000_000_000` — 1 vCPU cap
- `auto_remove=False` — explicit removal in `finally` block ensures cleanup even on timeout
- Token injected via environment variable, never written to disk

**Images used**:
- Python repos: `python:3.11-slim`
- Node repos: `node:20-bookworm-slim`

#### `GitService`
- `clone_repo`: Injects `GITHUB_TOKEN` into HTTPS URL (`https://{token}@github.com/...`).
- `push_branch`: Three guards before pushing:
  1. Blocks `main`/`master`.
  2. Requires `_AI_Fix` suffix.
  3. Validates full format with `re.fullmatch(r"[A-Z0-9_]+_AI_Fix", ...)`.

#### `ScoringService`
```
score = 100
if elapsed_seconds < 300: score += 10    # speed bonus
if commit_count > 20: score -= 2 * (commit_count - 20)  # commit penalty
return max(0, score)
```

---

## 4. Frontend Analysis

### 4.1 Component Tree

```
App
├── InputSection          Form fields + submit button
├── RunSummaryCard        metrics grid (URL, branch, team, time, failures, fixes)
├── ScoreBreakdownPanel   Recharts BarChart + score breakdown tiles   [lazy]
├── CICDTimeline          Per-attempt result cards                    [lazy]
└── FixesAppliedTable     Fix details table with status badges        [lazy]
```

`ScoreBreakdownPanel`, `CICDTimeline`, and `FixesAppliedTable` are **lazily imported** via `React.lazy` + `Suspense` — they are only loaded after the initial form renders.

### 4.2 State Management

**`useAgentStore.js`** (Zustand)

| State Slice | Type | Purpose |
|---|---|---|
| `form` | `{ repo_url, team_name, leader_name, retry_limit }` | Form inputs |
| `loading` | `boolean` | Disables submit button + shows loading state |
| `error` | `string` | Displayed below the form on failure |
| `results` | `NormalizedResult \| null` | Drives all result panels |

**Actions**:
- `setFormField(field, value)` — controlled input updates
- `runAgent()` — POST `/run` → GET `/results` → normalize → set state
- `loadLatestResults()` — silent GET `/results` on page load (cold-start hydration)

**API base URL**: Defaults to `""` (relative paths via Vite proxy). Override with `VITE_API_BASE_URL` env var for staging/prod.

### 4.3 Data Normalisation Pipeline

Raw API response → `normalizeResult()` → stored in Zustand → consumed by components.

```
raw.fixes[]        → parseFixLine()       → fixesRows[]
raw["cicd timeline"] → normalizeTimeline() → timelineRows[]
raw.score, ...     → scoreBreakdown{}
```

**`parseFixLine`**: Handles both object format (future structured output) and legacy string format `"{TYPE} error in {file} line {n} -> Fix: {desc}"`.

**`normalizeTimeline`**: Groups raw timeline events by `attempt` number using a `Map`, resolves final `PASSED`/`FAILED`/`RUNNING` status per attempt.

**`safeNumber`**: Guards every numeric field against `NaN`/`Infinity`.

---

## 5. Data Flow (End-to-End)

```
Browser (React + Zustand)
    │  POST /run { repo_url, team_name, leader_name, retry_limit }
    │  [via Vite proxy → :8000]
    ▼
FastAPI  main.py
    │
    ▼
SupervisorAgent._execute_sync()
    │
    ├─► RepoAnalyzerAgent
    │       GitService.clone_repo()          [GITHUB_TOKEN auth]
    │       GitService.checkout_new_branch()
    │       _detect_test_framework()
    │
    ├─► [Retry loop 1..N]
    │       TestRunnerAgent.run()
    │           DockerService.run_tests()
    │               docker container create  [cap_drop=ALL, mem=1g, cpu=1]
    │               wait / collect logs
    │               container.remove(force=True)
    │       ErrorParserAgent.run()
    │       FixGeneratorAgent.run()
    │       CommitAgent.run()
    │           GitService.commit_all()      [AI-AGENT prefix]
    │       GitService.push_branch()         [interim push]
    │
    ├─► GitService.push_branch()             [final push]
    │
    └─► TestRunnerAgent.run_sandbox()        [only if PASSED + push succeeded]
            DockerService.run_sandbox_from_url()
                docker container create      [no volumes, clone from GitHub]
                wait / collect logs
                container.remove(force=True)
    │
    ▼
ScoringService.calculate_score()
    │
    ▼
results.json (persisted)
    │
    ▼
HTTP 200 JSON response
    │
    ▼
Browser: normalizeResult() → Zustand → React re-render
```

---

## 6. API Contract

### `POST /run` · `POST /execute`

**Request**
```json
{
  "repo_url":    "https://github.com/org/repo",
  "team_name":   "AlphaTeam",
  "leader_name": "Alice",
  "retry_limit": 5
}
```

**Response 200**
```json
{
  "repo_url":       "https://github.com/org/repo",
  "team_name":      "AlphaTeam",
  "leader_name":    "Alice",
  "branch_name":    "ALPHATEAM_ALICE_AI_Fix",
  "total_failures": 2,
  "total_fixes":    3,
  "final_status":   "PASSED | FAILED | SANDBOX_FAILED",
  "time_taken":     47.3,
  "score":          110,
  "fixes":          ["LINTING error in src/utils.py line 12 -> Fix: removed unused import"],
  "sandbox_verification": {
    "exit_code": 0,
    "duration":  12.1,
    "passed":    true,
    "branch":    "ALPHATEAM_ALICE_AI_Fix"
  },
  "cicd timeline": [
    { "timestamp": "...", "stage": "supervisor", "status": "started", "details": {} }
  ]
}
```

**`final_status` values**

| Value | Meaning |
|---|---|
| `PASSED` | All tests pass locally AND in sandbox |
| `FAILED` | Tests still failing after all retries |
| `SANDBOX_FAILED` | Local tests passed but sandbox (GitHub clone) failed |

### `GET /results`

Returns last persisted `results.json`. `404` if no run has been performed yet.

### `GET /health`

Returns `{"status": "ok"}`. No auth required. Used by Docker health checks.

---

## 7. Docker & Deployment Model

### Multi-Stage `Dockerfile`

| Stage | Base | Purpose |
|---|---|---|
| `frontend-build` | `node:20-bookworm-slim` | `npm ci` + `npm run build` → `/app/frontend/dist` |
| `backend` | `python:3.11-slim` | Install Python deps; copy source + built frontend dist |

Security hardening in the image:
- Non-root user `appuser` (uid 1001)
- `apt-get` cache cleared
- Health check via `/health` endpoint

### `docker-compose.yml`

```
rift_backend   → port 8000   FastAPI + Docker socket mount
rift_frontend  → port 3000   nginx serving React SPA
workspace_data              Named volume for run workspaces
rift_net                    Bridge network isolating services
```

The Docker socket (`/var/run/docker.sock`) is mounted into `rift_backend` so it can spawn sandbox child containers at runtime.

---

## 8. Bugs Fixed in This Session

### Bug 1 — `ERR_CONNECTION_REFUSED` on all API calls

**Root Cause**: `uvicorn` was never started. Running `python main.py` was a no-op because the file had no `if __name__ == "__main__":` block.

**Fix**: Added uvicorn entrypoint to `backend/main.py`:
```python
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
```
Now `python -m backend.main` or `python backend/main.py` starts the server.

---

### Bug 2 — CORS blocking all browser requests

**Root Cause**: FastAPI had no `CORSMiddleware`. Browsers enforce CORS; responses from `localhost:8000` were blocked when the frontend was on `localhost:5173`.

**Fix**: Added `CORSMiddleware` to `main.py` allowing the Vite dev server (`5173`) and Docker nginx frontend (`3000`).

---

### Bug 3 — `.env` file not loaded; tokens always empty

**Root Cause**: `config.py` called `os.getenv()` but nothing ever loaded the `.env` file. `GITHUB_TOKEN` and `OPENAI_API_KEY` were always empty strings.

**Fix**: Added `python-dotenv` loading at the top of `main.py`:
```python
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=False)
```

---

### Bug 4 — Vite dev server had no API proxy

**Root Cause**: The frontend used absolute URLs (`http://localhost:8000/...`). Even with CORS fixed, this is fragile in development and breaks in any environment where backend and frontend are on different ports.

**Fix**: Added proxy rules to `vite.config.js` for `/run`, `/execute`, `/results`, `/health`. The frontend store's `API_BASE` now defaults to `""` (relative paths), routing through the Vite proxy transparently.

---

### Bug 5 — Missing `aiofiles` dependency

**Root Cause**: `FastAPI.StaticFiles` requires `aiofiles` at runtime but it was not in `requirements.txt`.

**Fix**: Added `aiofiles==23.2.1` to `requirements.txt` and installed it.

---

## 9. Security Posture

| Area | Status | Notes |
|---|---|---|
| Protected branches | ✅ | `main`/`master` pushes hard-blocked in `GitService` |
| Branch format validation | ✅ | `re.fullmatch` before every push |
| Commit prefix enforcement | ✅ | `[AI-AGENT]` prefix auto-prepended |
| Container capability drop | ✅ | `cap_drop=["ALL"]` on all sandbox containers |
| No-new-privileges | ✅ | `security_opt=["no-new-privileges"]` |
| Resource limits | ✅ | 1 GB RAM, 1 vCPU per container |
| Token injection | ✅ | GitHub token injected via env var; never written to disk |
| Non-root app user | ✅ | `appuser` uid 1001 in production Docker image |
| `.env` in `.gitignore` | ✅ | Secrets never committed |
| CORS scope | ⚠️ | Currently allows all `localhost` origins — tighten for production |
| Docker socket exposure | ⚠️ | Mounting `/var/run/docker.sock` grants root-equivalent access; use `dockerd` proxy in hardened environments |

---

## 10. Performance Characteristics

| Operation | Typical Duration | Notes |
|---|---|---|
| Repo clone (small) | 2–10 s | Depends on repo size and network |
| Docker image pull (first run) | 30–120 s | Cached on subsequent runs |
| pytest run (small suite) | 5–30 s | Inside container overhead ~2 s |
| npm test (small suite) | 15–60 s | Node cold start adds ~5 s |
| Sandbox verification | 20–90 s | Full clone from GitHub each time |
| Full PASSED run (1 attempt) | ~60 s | No fixes needed |
| Full run (3 retries, fixes) | ~3–5 min | Dominated by container spawns |

**Score bonus threshold**: Runs completing in under 300 seconds receive a +10 speed bonus.

---

## 11. Test Coverage Assessment

| Module | Has Tests | Notes |
|---|---|---|
| `config.py` | ❌ | `_clamp_retry` edge cases not tested |
| `supervisor.py` | ❌ | Core orchestration untested |
| `agents/*` | ❌ | All agents lack unit tests |
| `services/docker_service.py` | ❌ | Docker SDK calls not mocked |
| `services/git_service.py` | ❌ | GitPython calls not mocked |
| `services/scoring_service.py` | ❌ | Simple math; easy to test |
| Frontend `useAgentStore.js` | ❌ | No Vitest/Jest tests |
| Frontend components | ❌ | No React Testing Library tests |

**Recommended additions**:
- Unit tests for `ErrorParserAgent._extract_issues` (regex regression prevention)
- Unit tests for `FixGeneratorAgent` fix functions
- Unit tests for `GitService.push_branch` guard conditions
- Integration test with a mock Docker client
- Frontend: Vitest + Testing Library for `normalizeResult` and `normalizeTimeline`

---

## 12. Dependency Inventory

### Backend (`backend/requirements.txt`)

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | 0.115.8 | Web framework |
| `uvicorn[standard]` | 0.34.0 | ASGI server |
| `langchain-core` | 0.3.45 | `RunnableLambda` supervisor pattern |
| `docker` | 7.1.0 | Docker SDK — sandbox container management |
| `GitPython` | 3.1.44 | Git operations (clone, branch, commit, push) |
| `python-dotenv` | 1.0.1 | `.env` file loading |
| `httpx` | 0.28.1 | Async HTTP client (available for LLM calls) |
| `aiofiles` | 23.2.1 | Async file I/O for `StaticFiles` |

### Frontend (`frontend/package.json`)

| Package | Version | Purpose |
|---|---|---|
| `react` + `react-dom` | 18.3.1 | UI framework |
| `zustand` | 5.0.3 | Lightweight state management |
| `recharts` | 2.15.1 | Score breakdown bar chart |
| `vite` | 6.1.0 | Build tool + dev server with proxy |
| `tailwindcss` | 3.4.17 | Utility-first CSS |
| `@vitejs/plugin-react` | 4.3.4 | Vite React plugin |

---

## 13. Configuration Reference

| Variable | Location | Required | Default | Description |
|---|---|---|---|---|
| `GITHUB_TOKEN` | `.env` | ✅ | — | PAT for clone + push |
| `OPENAI_API_KEY` | `.env` | ✅ | — | LLM integration key |
| `MAX_RETRIES` | `.env` | ❌ | `5` | Retry cap (1–50) |
| `VITE_API_BASE_URL` | `frontend/.env.local` | ❌ | `""` | Override API base for staging/prod |

---

## 14. Known Limitations & Improvement Areas

| Area | Detail | Priority |
|---|---|---|
| **No LLM fix path active** | `FixGeneratorAgent` is fully rule-based. `OPENAI_API_KEY` is wired but no LLM call is made yet. | High |
| **TYPE_ERROR / LOGIC not fixed** | Errors are detected and recorded but no automated fix is applied. | High |
| **No test suite** | Zero automated tests exist. Regression risk is high. | High |
| **Single result file** | `results.json` is overwritten on every run. History is lost. | Medium |
| **No auth on API** | `/run` has no API key or rate limiting. Anyone with network access can trigger runs. | Medium |
| **Sequential retry loop** | Fixes are applied one attempt at a time. Parallel fix strategies not explored. | Medium |
| **SSH repo URLs unsupported** | Only GitHub HTTPS + PAT is supported. | Medium |
| **Windows Docker path edge case** | Volume mount paths use POSIX internally; WSL2 backend required on Windows. | Low |
| **No GitLab / Bitbucket support** | `_auth_repo_url` only handles `github.com`. | Low |
| **Workspace not cleaned up** | `.workspace/` directories accumulate; no TTL or garbage collection. | Low |

---

## 15. Startup Quick Reference

### Development (no Docker)

```powershell
# Terminal 1 — Backend
cd C:\Users\Darsh\OneDrive\Desktop\Projects\rift
# Activate your venv (adjust path if using backend\myenv)
.venv\Scripts\Activate.ps1
# Install deps (first time only)
pip install -r backend\requirements.txt
# Start the API server
python -m backend.main
# OR
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — Frontend
cd frontend
npm install   # first time only
npm run dev
# Open: http://localhost:5173
```

### Production (Docker Compose)

```bash
cp .env.example .env
# Fill in GITHUB_TOKEN and OPENAI_API_KEY in .env

docker compose up --build

# Backend:  http://localhost:8000
# Frontend: http://localhost:3000
# Health:   http://localhost:8000/health
```

### Test a run manually

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url":    "https://github.com/your-org/your-repo",
    "team_name":   "TestTeam",
    "leader_name": "Alice",
    "retry_limit": 3
  }'
```

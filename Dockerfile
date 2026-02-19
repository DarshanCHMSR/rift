# ── Stage 1: build frontend ──────────────────────────────────────────────────
FROM node:20-bookworm-slim AS frontend-build

WORKDIR /app/frontend

# Install JS dependencies first (layer caching)
COPY frontend/package*.json ./
RUN npm ci --silent

# Copy source and build
COPY frontend/ ./
RUN npm run build            # outputs to /app/frontend/dist


# ── Stage 2: backend runtime ─────────────────────────────────────────────────
FROM python:3.11-slim AS backend

# Non-root user for security
RUN groupadd --gid 1001 appgroup \
 && useradd  --uid 1001 --gid 1001 --no-create-home appuser

WORKDIR /app

# System deps: git (for GitPython + container clone operations) + clean up
RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# Python deps — separate layer so edits to source don't bust the cache
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend into a location the FastAPI app can serve statically
COPY --from=frontend-build /app/frontend/dist ./frontend_dist/

# Make workspace writable by the app user
RUN mkdir -p /app/backend/.workspace \
 && chown -R appuser:appgroup /app

# Mount the Docker socket at runtime (docker-compose handles this).
# We do NOT embed the socket into the image.
VOLUME ["/var/run"]

USER appuser

# Expose the API port
EXPOSE 8000

# Health-check: the /health endpoint returns {"status":"ok"}
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Production startup: single worker for now; scale via docker-compose replicas
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--log-level", "info"]

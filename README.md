# Web Intelligence Agent

AI Website Audit + Outreach Automation Platform — production foundation scaffold.

## Overview

This platform crawls a business website, analyzes it with AI agents orchestrated by LangGraph, identifies pain points, scores opportunities, generates recommendations, and drafts a personalized outreach email for **human review and manual send**.

**No automatic email sending** is implemented.

## Architecture

Modular monolith with clean layer separation:

- **API** (`app/api/`) — FastAPI routes and schemas
- **Application** (`app/services/`, `app/workflows/`) — use cases and job orchestration
- **Domain** (`app/database/models/`, `app/agents/state.py`) — entities and workflow state
- **Infrastructure** (`app/ai/`, `app/crawler/`, `app/vector/`, `app/tasks/`) — external integrations

### Agent Pipeline (LangGraph)

```
START → Crawler → BusinessAnalysis → PainPoints → ImpactScoring
      → Recommendations → EmailWriter → HumanReview → END
```

## Tech Stack

- Python 3.12, FastAPI, Pydantic v2, Motor/PyMongo
- MongoDB, Redis, Celery
- LangGraph (agent orchestration)
- Ollama (`llama3.2:3b`) — external Docker instance
- Qdrant (vector storage)

## Prerequisites

- [uv](https://docs.astral.sh/uv/) package manager
- Python 3.12
- Docker & Docker Compose
- Ollama running with `llama3.2:3b` pulled

## Quick Start

### 1. Clone and configure

```bash
cp .env.example .env
```

### 2. Install dependencies

```bash
uv sync --all-extras
```

### 3. Start infrastructure

Start the existing Ollama container (from `voice-calling-agent-noor`, already has models):

```bash
docker start voice-calling-agent-noor-ollama-1
# or: make ollama-up
```

If you instead start a **fresh** compose-managed Ollama container (`make ollama-up` on a machine that has never run it before), it ships with **no models**. Pull them once — otherwise every LLM-dependent agent (crawler analysis, business profile, pain points, recommendations, email draft) will fail with `model '...' not found` and silently fall back to degraded rule-based/template output:

```bash
make ollama-pull
# or manually:
docker exec web-intelligence-ollama ollama pull llama3.2:3b
docker exec web-intelligence-ollama ollama pull nomic-embed-text

# verify:
docker exec web-intelligence-ollama ollama list
```

Start MongoDB, Redis, Qdrant, API, and worker:

```bash
make up
# or: docker compose up -d
```

**Where data is stored:** All application data goes to **one MongoDB** database `web_intelligence` on your host (`MONGODB_URI` in `.env`, default `mongodb://localhost:27017/web_intelligence`). Compose does not start a separate Mongo service.

- Host CLI (`uv run python scripts/process_queue.py …`) uses `.env` as-is (`localhost:27017`).
- Docker `api` / `worker` also load Mongo from `.env`. With `IN_DOCKER=1`, `localhost` / `127.0.0.1` in `MONGODB_URI` is rewritten to `host.docker.internal` so containers reach the **same** host mongod (port and database name unchanged).
- **`website_url` is unique** on `website_audits`: re-running an audit or `process_queue.py` for the same URL **upserts** the existing document (same `_id`), resets scrape-derived fields, and appends a new `audit_run`. It does not create duplicate audits. After pulling code that adds the unique index, run `make ensure-db`. If index creation fails, remove duplicate `website_audits` rows for the same URL first.

In Compass/mongosh, open database **`web_intelligence`** and check:

- `audit_queue_batches` / `audit_queue_jobs` — created on enqueue (`process_queue.py --file …`)
- `website_audits` — created when workers process jobs (empty until then)

API and worker connect to that Ollama via the shared Docker network (`http://ollama:11434`).
Host-side scripts use `http://localhost:11434` from `.env`.

For GPU-backed speed, set **`OLLAMA_USE_REMOTE=true`** and point `OLLAMA_REMOTE_URL` at a live remote Ollama (ngrok or similar). The client tries `/api/generate` then `/api/chat`, does not retry HTTP 404, and surfaces a clear error when the tunnel returns an HTML 404 page. Keep the tunnel up while running `process_queue`. Prefer a strong GPU host for agent wall time; crawl uses Colly with `CRAWLER_CONCURRENCY` (default `3`) and fail-fast infrastructure retries. Keep Colly healthy: `docker compose up -d colly-sidecar`.

#### CPU-only Ollama + `QUEUE_WORKERS` > 1: cap `OLLAMA_NUM_PARALLEL=1`

A **local CPU** Ollama container has one fixed pool of cores. If `OLLAMA_NUM_PARALLEL` is left unset, Ollama happily accepts a generate request from every concurrent worker and time-slices the CPU between them — each request's tokens/sec collapses (observed dropping to ~2-3 tok/s with `QUEUE_WORKERS=5`, versus ~15-25 tok/s with one request at a time), so a batch that should take minutes looks "stuck" for 30+ minutes with no error, just extremely slow LLM decoding.

`OLLAMA_NUM_PARALLEL=1` (set in `.env`, applied via `docker-compose.yml`) forces Ollama to **queue** concurrent requests and run them one at a time at full CPU speed — net throughput is *higher* even though requests wait their turn. This is independent of `QUEUE_WORKERS`: keep workers >1 so crawling (I/O-bound) for other jobs still overlaps while one job's LLM call runs. Apply a changed value with:

```bash
docker compose up -d ollama   # recreates the container with new env vars
docker exec web-intelligence-ollama ollama ps   # confirm; PROCESSOR should show one active slot
```

If you're using a remote/GPU Ollama (`OLLAMA_USE_REMOTE=true`), this generally isn't needed — a GPU has much more headroom for parallel decoding.

### 4. Ensure database indexes

Indexes and the default user are created automatically on API startup. To run manually:

```bash
make ensure-db
```

### 5. Create an audit

```bash
curl -X POST http://localhost:8000/audits \
  -H "Content-Type: application/json" \
  -d '{"website_url": "https://example.com"}'
```

Response:

```json
{"audit_id": "...", "status": "pending"}
```

### 6. Poll for results

```bash
curl http://localhost:8000/audits/{audit_id}
```

### 7. Get email draft

```bash
curl http://localhost:8000/audits/{audit_id}/email
```

### 8. Approve for manual send

```bash
curl -X POST http://localhost:8000/audits/{audit_id}/approve
```

This marks the email as approved — **it does not send the email**.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check |
| GET | `/ready` | Readiness (DB connectivity) |
| POST | `/audits` | Create audit (async) |
| GET | `/audits/{id}` | Full audit report |
| GET | `/audits/{id}/email` | Generated email draft |
| POST | `/audits/{id}/approve` | Approve email for manual send |

## Development

```bash
# Run API locally
make dev

# Run tests (no real Ollama required)
make test

# Lint
make lint
```

## Environment Variables

See [`.env.example`](.env.example) for all configuration options.

Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGODB_URI` | `mongodb://localhost:27017/web_intelligence` | Single MongoDB URI from `.env` (host mongod on **27017**) |
| `MONGODB_DB_NAME` | `web_intelligence` | Database name fallback if URI has no path |
| `IN_DOCKER` | `false` | Set by Compose on `api`/`worker`; rewrites `localhost` Mongo host to `host.docker.internal` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Existing `voice-calling-agent-noor` Ollama |
| `OLLAMA_USE_REMOTE` | `false` | Prefer local Ollama for queue/agent speed; set `true` to use `OLLAMA_REMOTE_URL` |
| `OLLAMA_MODEL` | `llama3.2:3b` | LLM model |
| `EMBEDDING_PROVIDER` | `ollama` | Embedding backend |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model |
| `QDRANT_URL` | `http://localhost:6335` | Vector DB |
| `CRAWLER_CONCURRENCY` | `3` | Parallel in-site page fetches per crawl |

## Where to Add Features

| Feature | Location |
|---------|----------|
| Deeper crawling | `app/crawler/crawler_service.py` |
| New AI agent | `app/agents/nodes/` + register in `app/agents/graph.py` |
| New prompt | `app/ai/prompts/` |
| RAG retrieval | `app/vector/retriever.py` |
| Auth (JWT) | `app/core/security.py` + `app/api/routes/auth.py` |
| Email sending | **Not in scope** — would be separate infra behind feature flag |

## Adding a New Agent

1. Create prompt in `app/ai/prompts/`
2. Add output schema in `app/ai/schemas.py`
3. Create node handler in `app/agents/nodes/`
4. Register node and edges in `app/agents/graph.py`
5. Add tests in `tests/agents/`

Agents communicate **only via graph state** — never call each other directly.

## Scaling

- **Workers**: scale `worker` service replicas
- **API**: scale `api` replicas (stateless)
- **DB**: scale MongoDB replica set; connection via `app/database/session.py`
- **LLM**: swap `OllamaClient` implementation without changing agents

## Project Structure

```
app/
├── api/           # HTTP layer
├── core/          # Config, logging, constants
├── database/      # Models, repos, indexes
├── agents/        # LangGraph workflow
├── ai/            # Ollama, prompts, embeddings
├── crawler/       # Website crawling
├── vector/        # Qdrant integration
├── workflows/     # Audit orchestration
├── services/      # Application services
└── tasks/         # Celery jobs
tests/
├── agents/
├── services/
├── workflows/
└── api/
```

## License

Proprietary — Techverseo Agentic AI

.PHONY: install lock dev up down ensure-db test lint ollama-up ollama-pull \
	osm-ensure-schema osm-bootstrap osm-update osm-status osm-test

install:
	uv sync --all-extras

lock:
	uv lock

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

up:
	docker compose up -d

ollama-up:
	docker compose --profile local-ollama up -d ollama

ollama-pull:
	docker exec web-intelligence-ollama ollama pull llama3.2:3b
	docker exec web-intelligence-ollama ollama pull nomic-embed-text

down:
	docker compose down

ensure-db:
	uv run python -c "from app.database.indexes import ensure_indexes_sync; ensure_indexes_sync(); print('MongoDB indexes ensured')"

test:
	uv run pytest -v

test-audit:
	uv run python scripts/test_audit.py https://example.com

process-queue:
	uv run python scripts/process_queue.py --file urls.txt

lint:
	uv run ruff check app tests
	uv run ruff format --check app tests

# --- OSM business ingest (Planet PBF → PostGIS) ---

osm-ensure-schema:
	uv run python -c "from osm_ingest.persist.db import ensure_schema; from osm_ingest.config.settings import get_settings; ensure_schema(get_settings().postgis_dsn); print('PostGIS schema ensured')"

osm-bootstrap:
	uv run python -m osm_ingest bootstrap

osm-update:
	uv run python -m osm_ingest update

osm-status:
	uv run python -m osm_ingest status

osm-test:
	uv run pytest osm_ingest/tests -v

# Worldwide OSM Business Ingest

Production pipeline that indexes **every OSM-tagged business on Earth** into PostGIS.

**Strategy:** Planet PBF (not Overpass) → `osmium tags-filter` → pyosmium stream → batch upsert → hourly replication diffs.

Overpass API is unsuitable for worldwide extraction (timeouts, RAM caps, rate limits). See analysis in the project plan.

## Requirements

| Resource | Guidance |
|----------|----------|
| Disk | ≥ 200 GB free (planet ~85 GB + filtered PBF + DB) |
| RAM | 16 GB+ recommended; use `OSM_LOCATION_STORE=dense_file_array` for planet-scale ways |
| Tools | [osmium-tool](https://osmcode.org/osmium-tool/) on `PATH`, Python 3.12+, Docker for PostGIS |
| License | Data © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright) |

## Quick start

```bash
# 1. Dependencies
uv sync --extra osm --all-extras

# 2. PostGIS
docker compose up -d postgis
# wait until healthy, then:
make osm-ensure-schema

# 3. Bootstrap (downloads ~85 GB planet — resumes on interrupt)
make osm-bootstrap
# or:
uv run osm-ingest bootstrap

# 4. Incremental updates (cron / scheduled)
make osm-update
```

Useful flags:

```bash
uv run osm-ingest bootstrap --skip-download   # planet already on disk
uv run osm-ingest bootstrap --skip-filter     # filtered PBF already built
uv run osm-ingest bootstrap --no-verify-md5
uv run osm-ingest status
```

## Architecture

```
planet-latest.osm.pbf
        │
        ▼
 osmium tags-filter  (business tag expressions)
        │
        ▼
 businesses.osm.pbf
        │
        ▼
 pyosmium FileProcessor  (stream, locations + areas)
        │
        ▼
 PostGIS osm_businesses  (PK: osm_type + osm_id)
        ▲
        │
 hourly OSC replication diffs (soft-delete + upsert)
```

No latitude, longitude, country, or bbox input is required. The planet file *is* worldwide coverage.

## Configuration

Environment variables (see root `.env.example`):

| Variable | Purpose |
|----------|---------|
| `POSTGIS_DSN` | PostgreSQL/PostGIS connection string |
| `OSM_DATA_DIR` | Local data root (`./data/osm`) |
| `OSM_PLANET_URL` | Planet PBF URL |
| `OSM_REPLICATION_BASE_URL` | Hourly replication base |
| `OSM_BATCH_SIZE` | Upsert batch size |
| `OSM_TAGS_CONFIG` | Path to `business_tags.yaml` |
| `OSM_OSMIUM_BIN` | osmium binary name/path |

Business detection rules live in [`config/business_tags.yaml`](config/business_tags.yaml) (include keys, amenity/tourism deny-lists, leisure allow-list, osmium expressions).

## Resume / checkpointing

Job state is stored in `ingest_checkpoints`:

- Phases: `downloading` → `downloaded` → `filtering` → `filtered` → `extracting` → `ready`
- `replication_seq` drives incremental updates
- Planet download uses HTTP `Range` resume via `.partial` files

## Uniqueness

Primary key `(osm_type, osm_id)`. Upserts apply only when `EXCLUDED.version >=` stored version. OSC deletes (and tag changes that leave the business set) set `is_deleted = true`.

## Tests

```bash
uv sync --extra osm --all-extras
uv run pytest osm_ingest/tests -v
# Upsert tests need PostGIS:
docker compose up -d postgis
uv run pytest osm_ingest/tests/test_upsert_idempotent.py -v
```

## Package layout

```
osm_ingest/
  cli.py                 # osm-ingest entrypoint
  pipeline.py            # bootstrap / update / status
  config/                # settings + business_tags.yaml
  download/              # resume planet fetch + MD5
  filter/                # osmium tags-filter wrapper
  classify/              # tag taxonomy
  extract/               # pyosmium streaming
  persist/               # PostGIS schema helpers + upsert
  replicate/             # OSC download + apply
  checkpoint/            # job state
  tests/
```

## Why not Overpass?

Public Overpass instances enforce query timeouts, memory limits, and per-IP slots. Recursive bbox/S2 splitting for the whole planet creates millions of fragile requests and still cannot guarantee completeness. Companies that ingest all OSM data use **planet dumps + osmium/pyosmium + replication**, which this package implements.

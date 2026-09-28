-- OSM business ingest schema (PostGIS)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS osm_businesses (
  osm_type         CHAR(1) NOT NULL CHECK (osm_type IN ('n', 'w', 'r')),
  osm_id           BIGINT NOT NULL,
  version          INTEGER NOT NULL,
  changeset_id     BIGINT,
  osm_timestamp    TIMESTAMPTZ,
  name             TEXT,
  brand            TEXT,
  operator         TEXT,
  business_key     TEXT NOT NULL,
  business_value   TEXT NOT NULL,
  phone            TEXT,
  website          TEXT,
  email            TEXT,
  addr_housenumber TEXT,
  addr_street      TEXT,
  addr_city        TEXT,
  addr_postcode    TEXT,
  addr_country     TEXT,
  tags             JSONB NOT NULL DEFAULT '{}'::jsonb,
  geom             geometry(Geometry, 4326) NOT NULL,
  centroid         geography(Point, 4326) NOT NULL,
  is_deleted       BOOLEAN NOT NULL DEFAULT FALSE,
  first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (osm_type, osm_id)
);

CREATE INDEX IF NOT EXISTS osm_biz_centroid_gix
  ON osm_businesses USING GIST (centroid);
CREATE INDEX IF NOT EXISTS osm_biz_geom_gix
  ON osm_businesses USING GIST (geom);
CREATE INDEX IF NOT EXISTS osm_biz_class_idx
  ON osm_businesses (business_key, business_value)
  WHERE NOT is_deleted;
CREATE INDEX IF NOT EXISTS osm_biz_tags_gin
  ON osm_businesses USING GIN (tags);
CREATE INDEX IF NOT EXISTS osm_biz_website_idx
  ON osm_businesses (website)
  WHERE website IS NOT NULL AND NOT is_deleted;
CREATE INDEX IF NOT EXISTS osm_biz_name_trgm
  ON osm_businesses USING GIN (name gin_trgm_ops);

CREATE TABLE IF NOT EXISTS ingest_checkpoints (
  job_name         TEXT PRIMARY KEY,
  phase            TEXT NOT NULL,
  replication_seq  BIGINT,
  replication_ts   TIMESTAMPTZ,
  planet_url       TEXT,
  planet_md5       TEXT,
  extra            JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

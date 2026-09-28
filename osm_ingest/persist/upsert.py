"""Batch upsert / soft-delete for osm_businesses."""

from __future__ import annotations

import logging
from collections.abc import Sequence

import psycopg
from psycopg.types.json import Jsonb

from osm_ingest.models import BusinessEntity

logger = logging.getLogger(__name__)

_UPSERT_SQL = """
INSERT INTO osm_businesses (
  osm_type, osm_id, version, changeset_id, osm_timestamp,
  name, brand, operator, business_key, business_value,
  phone, website, email,
  addr_housenumber, addr_street, addr_city, addr_postcode, addr_country,
  tags, geom, centroid, is_deleted, first_seen_at, last_seen_at, updated_at
) VALUES (
  %(osm_type)s, %(osm_id)s, %(version)s, %(changeset_id)s, %(osm_timestamp)s,
  %(name)s, %(brand)s, %(operator)s, %(business_key)s, %(business_value)s,
  %(phone)s, %(website)s, %(email)s,
  %(addr_housenumber)s, %(addr_street)s, %(addr_city)s, %(addr_postcode)s, %(addr_country)s,
  %(tags)s,
  ST_SetSRID(ST_GeomFromText(%(geom_wkt)s), 4326),
  ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography,
  FALSE,
  now(), now(), now()
)
ON CONFLICT (osm_type, osm_id) DO UPDATE SET
  version = EXCLUDED.version,
  changeset_id = EXCLUDED.changeset_id,
  osm_timestamp = EXCLUDED.osm_timestamp,
  name = EXCLUDED.name,
  brand = EXCLUDED.brand,
  operator = EXCLUDED.operator,
  business_key = EXCLUDED.business_key,
  business_value = EXCLUDED.business_value,
  phone = EXCLUDED.phone,
  website = EXCLUDED.website,
  email = EXCLUDED.email,
  addr_housenumber = EXCLUDED.addr_housenumber,
  addr_street = EXCLUDED.addr_street,
  addr_city = EXCLUDED.addr_city,
  addr_postcode = EXCLUDED.addr_postcode,
  addr_country = EXCLUDED.addr_country,
  tags = EXCLUDED.tags,
  geom = EXCLUDED.geom,
  centroid = EXCLUDED.centroid,
  is_deleted = FALSE,
  last_seen_at = now(),
  updated_at = now()
WHERE osm_businesses.version <= EXCLUDED.version
"""

_SOFT_DELETE_SQL = """
UPDATE osm_businesses
SET is_deleted = TRUE, updated_at = now(), last_seen_at = now()
WHERE osm_type = %(osm_type)s AND osm_id = %(osm_id)s AND NOT is_deleted
"""


def _entity_params(entity: BusinessEntity) -> dict:
    return {
        "osm_type": entity.osm_type,
        "osm_id": entity.osm_id,
        "version": entity.version,
        "changeset_id": entity.changeset_id,
        "osm_timestamp": entity.osm_timestamp,
        "name": entity.name,
        "brand": entity.brand,
        "operator": entity.operator,
        "business_key": entity.business_key,
        "business_value": entity.business_value,
        "phone": entity.phone,
        "website": entity.website,
        "email": entity.email,
        "addr_housenumber": entity.addr_housenumber,
        "addr_street": entity.addr_street,
        "addr_city": entity.addr_city,
        "addr_postcode": entity.addr_postcode,
        "addr_country": entity.addr_country,
        "tags": Jsonb(entity.tags),
        "geom_wkt": entity.geom_wkt,
        "lon": entity.lon,
        "lat": entity.lat,
    }


def upsert_batch(conn: psycopg.Connection, entities: Sequence[BusinessEntity]) -> int:
    if not entities:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, [_entity_params(e) for e in entities])
    logger.debug("Upserted %s businesses", len(entities))
    return len(entities)


def soft_delete_batch(
    conn: psycopg.Connection,
    keys: Sequence[tuple[str, int]],
) -> int:
    if not keys:
        return 0
    params = [{"osm_type": t, "osm_id": i} for t, i in keys]
    with conn.cursor() as cur:
        cur.executemany(_SOFT_DELETE_SQL, params)
    return len(keys)


def count_businesses(conn: psycopg.Connection, *, include_deleted: bool = False) -> int:
    sql = "SELECT COUNT(*) AS n FROM osm_businesses"
    if not include_deleted:
        sql += " WHERE NOT is_deleted"
    row = conn.execute(sql).fetchone()
    return int(row["n"]) if row else 0

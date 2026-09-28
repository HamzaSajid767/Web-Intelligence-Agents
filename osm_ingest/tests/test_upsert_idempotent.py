"""Idempotent upsert / soft-delete tests (requires PostGIS)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from osm_ingest.models import BusinessEntity
from osm_ingest.persist.db import connection, ensure_schema
from osm_ingest.persist.upsert import count_businesses, soft_delete_batch, upsert_batch

DSN = os.environ.get("POSTGIS_DSN", "postgresql://osm:osm@localhost:5433/osm_businesses")


def _entity(osm_id: int = 1, version: int = 1, name: str = "Test Shop") -> BusinessEntity:
    return BusinessEntity(
        osm_type="n",
        osm_id=osm_id,
        version=version,
        changeset_id=1,
        osm_timestamp=datetime.now(timezone.utc),
        name=name,
        brand=None,
        operator=None,
        business_key="shop",
        business_value="bakery",
        phone=None,
        website="https://example.com",
        email=None,
        addr_housenumber=None,
        addr_street=None,
        addr_city=None,
        addr_postcode=None,
        addr_country=None,
        tags={"shop": "bakery", "name": name},
        geom_wkt="POINT(13.4 52.5)",
        lon=13.4,
        lat=52.5,
    )


@pytest.fixture(scope="module")
def dsn() -> str:
    try:
        ensure_schema(DSN)
        with connection(DSN) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:
        pytest.skip(f"PostGIS not available: {exc}")
    return DSN


def test_upsert_idempotent(dsn: str) -> None:
    with connection(dsn) as conn:
        conn.execute(
            "DELETE FROM osm_businesses WHERE osm_type = 'n' AND osm_id = 900001"
        )
        conn.commit()
        e1 = _entity(900001, version=1, name="A")
        upsert_batch(conn, [e1])
        conn.commit()
        e2 = _entity(900001, version=2, name="B")
        upsert_batch(conn, [e2])
        conn.commit()
        row = conn.execute(
            "SELECT name, version, is_deleted FROM osm_businesses "
            "WHERE osm_type = 'n' AND osm_id = 900001"
        ).fetchone()
        assert row is not None
        assert row["name"] == "B"
        assert row["version"] == 2
        assert row["is_deleted"] is False

        # Older version must not overwrite
        e_old = _entity(900001, version=1, name="OLD")
        upsert_batch(conn, [e_old])
        conn.commit()
        row2 = conn.execute(
            "SELECT name, version FROM osm_businesses "
            "WHERE osm_type = 'n' AND osm_id = 900001"
        ).fetchone()
        assert row2["name"] == "B"
        assert row2["version"] == 2


def test_soft_delete(dsn: str) -> None:
    with connection(dsn) as conn:
        conn.execute(
            "DELETE FROM osm_businesses WHERE osm_type = 'n' AND osm_id = 900002"
        )
        conn.commit()
        upsert_batch(conn, [_entity(900002)])
        conn.commit()
        soft_delete_batch(conn, [("n", 900002)])
        conn.commit()
        row = conn.execute(
            "SELECT is_deleted FROM osm_businesses "
            "WHERE osm_type = 'n' AND osm_id = 900002"
        ).fetchone()
        assert row["is_deleted"] is True
        assert count_businesses(conn) >= 0

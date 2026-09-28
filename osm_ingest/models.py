"""Domain models for OSM business entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

OsmType = Literal["n", "w", "r"]


@dataclass(slots=True)
class BusinessEntity:
    """A single OSM business ready for PostGIS upsert."""

    osm_type: OsmType
    osm_id: int
    version: int
    changeset_id: int | None
    osm_timestamp: datetime | None
    name: str | None
    brand: str | None
    operator: str | None
    business_key: str
    business_value: str
    phone: str | None
    website: str | None
    email: str | None
    addr_housenumber: str | None
    addr_street: str | None
    addr_city: str | None
    addr_postcode: str | None
    addr_country: str | None
    tags: dict[str, str]
    # WKT geometry in EPSG:4326
    geom_wkt: str
    lon: float
    lat: float
    is_deleted: bool = False


@dataclass(slots=True)
class Checkpoint:
    """Persisted ingest job state for resume / replication."""

    job_name: str
    phase: str
    replication_seq: int | None = None
    replication_ts: datetime | None = None
    planet_url: str | None = None
    planet_md5: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

"""Stream OSM PBF / OSC into BusinessEntity records via pyosmium."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from osm_ingest.classify.tags import TagTaxonomy
from osm_ingest.extract.geometry import (
    area_outer_coords,
    centroid_of_coords,
    first_tag,
    linestring_wkt,
    node_point_wkt,
    ring_wkt,
    tags_to_dict,
    way_coords_from_osmium,
)
from osm_ingest.models import BusinessEntity, OsmType

logger = logging.getLogger(__name__)

FlushCallback = Callable[[list[BusinessEntity]], None]
DeleteCallback = Callable[[list[tuple[str, int]]], None]


def _osm_timestamp(obj: Any) -> datetime | None:
    ts = getattr(obj, "timestamp", None)
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts
    return None


def _base_fields(obj: Any, tags: dict[str, str], key: str, value: str) -> dict[str, Any]:
    return {
        "version": int(getattr(obj, "version", 0) or 0),
        "changeset_id": int(obj.changeset) if getattr(obj, "changeset", None) else None,
        "osm_timestamp": _osm_timestamp(obj),
        "name": first_tag(tags, "name", "name:en"),
        "brand": first_tag(tags, "brand"),
        "operator": first_tag(tags, "operator"),
        "business_key": key,
        "business_value": value,
        "phone": first_tag(tags, "phone", "contact:phone", "telephone"),
        "website": first_tag(tags, "website", "contact:website", "url"),
        "email": first_tag(tags, "email", "contact:email"),
        "addr_housenumber": first_tag(tags, "addr:housenumber"),
        "addr_street": first_tag(tags, "addr:street"),
        "addr_city": first_tag(tags, "addr:city"),
        "addr_postcode": first_tag(tags, "addr:postcode"),
        "addr_country": first_tag(tags, "addr:country"),
        "tags": tags,
    }


def entity_from_node(obj: Any, taxonomy: TagTaxonomy) -> BusinessEntity | None:
    tags = tags_to_dict(obj.tags)
    classified = taxonomy.classify(tags)
    if not classified:
        return None
    loc = obj.location
    if not loc.valid():
        return None
    lon, lat = float(loc.lon), float(loc.lat)
    key, value = classified
    return BusinessEntity(
        osm_type="n",
        osm_id=int(obj.id),
        geom_wkt=node_point_wkt(lon, lat),
        lon=lon,
        lat=lat,
        **_base_fields(obj, tags, key, value),
    )


def entity_from_way(obj: Any, taxonomy: TagTaxonomy) -> BusinessEntity | None:
    tags = tags_to_dict(obj.tags)
    classified = taxonomy.classify(tags)
    if not classified:
        return None
    coords = way_coords_from_osmium(obj)
    if not coords:
        return None
    closed = len(coords) >= 4 and coords[0] == coords[-1]
    geom = ring_wkt(coords) if closed else linestring_wkt(coords)
    center = centroid_of_coords(coords)
    if not geom or not center:
        return None
    key, value = classified
    return BusinessEntity(
        osm_type="w",
        osm_id=int(obj.id),
        geom_wkt=geom,
        lon=center[0],
        lat=center[1],
        **_base_fields(obj, tags, key, value),
    )


def entity_from_area(obj: Any, taxonomy: TagTaxonomy) -> BusinessEntity | None:
    """Areas come from closed ways / multipolygon relations when areas=True."""
    tags = tags_to_dict(obj.tags)
    classified = taxonomy.classify(tags)
    if not classified:
        return None
    coords = area_outer_coords(obj)
    if not coords:
        return None
    geom = ring_wkt(coords)
    center = centroid_of_coords(coords)
    if not geom or not center:
        return None

    # Prefer original OSM type: from_way / from_relation
    osm_type: OsmType = "w"
    osm_id = int(obj.orig_id()) if hasattr(obj, "orig_id") else int(obj.id)
    if hasattr(obj, "from_way") and not obj.from_way():
        osm_type = "r"

    key, value = classified
    return BusinessEntity(
        osm_type=osm_type,
        osm_id=osm_id,
        geom_wkt=geom,
        lon=center[0],
        lat=center[1],
        **_base_fields(obj, tags, key, value),
    )


def stream_entities(
    path: Path,
    taxonomy: TagTaxonomy,
    *,
    location_store: str = "dense_file_array",
    location_cache: Path | None = None,
    batch_size: int = 10_000,
    on_batch: FlushCallback | None = None,
) -> Iterator[list[BusinessEntity]]:
    """Stream business entities from a PBF file in batches.

    Yields batches; if on_batch is provided it is also called for each batch.
    """
    try:
        import osmium
    except ImportError as exc:
        raise ImportError(
            "pyosmium is required. Install with: uv sync --extra osm"
        ) from exc

    # Do NOT use EmptyTagFilter: untagged nodes are required for way/area locations.
    fp = osmium.FileProcessor(str(path))

    try:
        if location_store == "flex_mem":
            fp = fp.with_locations()
        elif location_cache is not None and location_store in (
            "dense_file_array",
            "sparse_file_array",
        ):
            location_cache.parent.mkdir(parents=True, exist_ok=True)
            # Older pyosmium: with_locations(store); file path via env / default store
            fp = fp.with_locations(location_store)
        else:
            fp = fp.with_locations(location_store)
    except TypeError:
        fp = fp.with_locations()
    except Exception as exc:
        logger.warning("with_locations(%s) failed (%s); falling back to flex_mem", location_store, exc)
        fp = fp.with_locations()

    try:
        fp = fp.with_areas()
    except Exception as exc:  # pragma: no cover - depends on pyosmium version
        logger.warning("Area processing unavailable: %s", exc)

    buffer: list[BusinessEntity] = []
    seen_area_ids: set[tuple[str, int]] = set()

    for obj in fp:
        entity: BusinessEntity | None = None

        if obj.is_node():
            entity = entity_from_node(obj, taxonomy)
        elif hasattr(obj, "is_area") and obj.is_area():
            entity = entity_from_area(obj, taxonomy)
            if entity:
                seen_area_ids.add((entity.osm_type, entity.osm_id))
        elif obj.is_way():
            eid = ("w", int(obj.id))
            if eid in seen_area_ids:
                continue
            entity = entity_from_way(obj, taxonomy)
        else:
            continue

        if entity is None:
            continue
        buffer.append(entity)
        if len(buffer) >= batch_size:
            if on_batch:
                on_batch(buffer)
            yield buffer
            buffer = []

    if buffer:
        if on_batch:
            on_batch(buffer)
        yield buffer


def extract_to_callback(
    path: Path,
    taxonomy: TagTaxonomy,
    on_batch: FlushCallback,
    **kwargs: Any,
) -> int:
    """Process file and flush via callback; return total entities."""
    total = 0
    for batch in stream_entities(path, taxonomy, on_batch=on_batch, **kwargs):
        total += len(batch)
    return total

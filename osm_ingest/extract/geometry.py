"""Geometry helpers for OSM nodes / ways / areas."""

from __future__ import annotations

from typing import Any


def tags_to_dict(tags: Any) -> dict[str, str]:
    """Convert osmium TagList / mapping to a plain dict."""
    if tags is None:
        return {}
    if isinstance(tags, dict):
        return {str(k): str(v) for k, v in tags.items()}
    return {str(t.k): str(t.v) for t in tags}


def first_tag(tags: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = tags.get(key)
        if value:
            return value
    return None


def node_point_wkt(lon: float, lat: float) -> str:
    return f"POINT({lon} {lat})"


def ring_wkt(coords: list[tuple[float, float]]) -> str | None:
    if len(coords) < 3:
        return None
    # Close ring if needed
    if coords[0] != coords[-1]:
        coords = [*coords, coords[0]]
    if len(coords) < 4:
        return None
    body = ", ".join(f"{lon} {lat}" for lon, lat in coords)
    return f"POLYGON(({body}))"


def linestring_wkt(coords: list[tuple[float, float]]) -> str | None:
    if len(coords) < 2:
        return None
    body = ", ".join(f"{lon} {lat}" for lon, lat in coords)
    return f"LINESTRING({body})"


def centroid_of_coords(coords: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not coords:
        return None
    # Drop closing duplicate for average
    pts = coords[:-1] if len(coords) > 1 and coords[0] == coords[-1] else coords
    if not pts:
        return None
    lon = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return lon, lat


def way_coords_from_osmium(way: Any) -> list[tuple[float, float]]:
    """Extract (lon, lat) from a pyosmium Way with locations enabled."""
    coords: list[tuple[float, float]] = []
    for node in way.nodes:
        if not node.location.valid():
            continue
        coords.append((node.location.lon, node.location.lat))
    return coords


def area_outer_coords(area: Any) -> list[tuple[float, float]]:
    """Best-effort outer ring from a pyosmium Area."""
    coords: list[tuple[float, float]] = []
    try:
        for ring in area.outer_rings():
            for node in ring:
                if node.location.valid():
                    coords.append((node.location.lon, node.location.lat))
            if coords:
                break
    except Exception:
        return []
    return coords

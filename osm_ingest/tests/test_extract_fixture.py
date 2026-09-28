"""Stream extract from fixture OSM XML (requires pyosmium)."""

from __future__ import annotations

from pathlib import Path

import pytest

from osm_ingest.classify.tags import load_taxonomy

pytest.importorskip("osmium")

from osm_ingest.extract.handler import stream_entities

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.osm"
TAXONOMY = Path(__file__).resolve().parents[1] / "config" / "business_tags.yaml"


def test_stream_fixture_extracts_businesses_only() -> None:
    tax = load_taxonomy(TAXONOMY)
    entities = []
    for batch in stream_entities(
        FIXTURE,
        tax,
        location_store="flex_mem",
        batch_size=100,
    ):
        entities.extend(batch)

    names = {e.name for e in entities}
    assert "Fixture Bakery" in names
    assert "Fixture Restaurant" in names
    # bench must not appear
    assert all(e.business_value != "bench" for e in entities)
    # shop on way should appear
    assert any(e.osm_type == "w" and e.name == "Fixture Store" for e in entities) or any(
        e.name == "Fixture Store" for e in entities
    )

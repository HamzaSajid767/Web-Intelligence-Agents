"""Unit tests for business tag taxonomy."""

from __future__ import annotations

from pathlib import Path

from osm_ingest.classify.tags import load_taxonomy

TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "config" / "business_tags.yaml"


def test_shop_is_business() -> None:
    tax = load_taxonomy(TAXONOMY_PATH)
    assert tax.classify({"shop": "bakery", "name": "Acme"}) == ("shop", "bakery")


def test_office_is_business() -> None:
    tax = load_taxonomy(TAXONOMY_PATH)
    assert tax.classify({"office": "lawyer"}) == ("office", "lawyer")


def test_amenity_restaurant_is_business() -> None:
    tax = load_taxonomy(TAXONOMY_PATH)
    assert tax.classify({"amenity": "restaurant", "name": "Pasta"}) == (
        "amenity",
        "restaurant",
    )


def test_amenity_bench_is_not_business() -> None:
    tax = load_taxonomy(TAXONOMY_PATH)
    assert tax.classify({"amenity": "bench"}) is None
    assert tax.classify({"amenity": "toilets"}) is None
    assert tax.classify({"amenity": "parking"}) is None


def test_tourism_hotel_vs_viewpoint() -> None:
    tax = load_taxonomy(TAXONOMY_PATH)
    assert tax.classify({"tourism": "hotel", "name": "Inn"}) == ("tourism", "hotel")
    assert tax.classify({"tourism": "viewpoint"}) is None


def test_leisure_allow_list() -> None:
    tax = load_taxonomy(TAXONOMY_PATH)
    assert tax.classify({"leisure": "fitness_centre"}) == ("leisure", "fitness_centre")
    assert tax.classify({"leisure": "park"}) is None
    assert tax.classify({"leisure": "playground"}) is None


def test_building_requires_name() -> None:
    tax = load_taxonomy(TAXONOMY_PATH)
    assert tax.classify({"building": "retail"}) is None
    assert tax.classify({"building": "retail", "name": "Mall Wing"}) == (
        "building",
        "retail",
    )


def test_primary_key_priority_shop_over_amenity() -> None:
    tax = load_taxonomy(TAXONOMY_PATH)
    result = tax.classify({"shop": "convenience", "amenity": "cafe", "name": "X"})
    assert result == ("shop", "convenience")


def test_osmium_expressions_nonempty() -> None:
    tax = load_taxonomy(TAXONOMY_PATH)
    assert len(tax.osmium_expressions) >= 5
    assert any(e.startswith("nwr/shop") for e in tax.osmium_expressions)

"""Re-export tag classification helpers."""

from osm_ingest.classify.tags import TagTaxonomy, get_taxonomy, load_taxonomy

__all__ = ["TagTaxonomy", "get_taxonomy", "load_taxonomy"]

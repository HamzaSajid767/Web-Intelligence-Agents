"""Classify OSM tags as businesses using configurable taxonomy."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True, slots=True)
class ValueFilter:
    mode: str  # deny | allow | allow_if_named
    values: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class TagTaxonomy:
    include_keys: frozenset[str]
    value_filters: dict[str, ValueFilter]
    osmium_expressions: tuple[str, ...]
    primary_key_priority: tuple[str, ...]

    def is_business(self, tags: Mapping[str, str]) -> bool:
        return self.classify(tags) is not None

    def classify(self, tags: Mapping[str, str]) -> tuple[str, str] | None:
        """Return (business_key, business_value) or None if not a business."""
        if not tags:
            return None

        named = bool(tags.get("name") or tags.get("brand") or tags.get("operator"))
        candidates: list[tuple[str, str]] = []

        for key in self.include_keys:
            value = tags.get(key)
            if value:
                candidates.append((key, value))

        for key, filt in self.value_filters.items():
            value = tags.get(key)
            if not value:
                continue
            if filt.mode == "deny":
                if value not in filt.values:
                    candidates.append((key, value))
            elif filt.mode == "allow":
                if value in filt.values:
                    candidates.append((key, value))
            elif filt.mode == "allow_if_named":
                if named and (not filt.values or value in filt.values):
                    candidates.append((key, value))

        if not candidates:
            return None

        priority = {k: i for i, k in enumerate(self.primary_key_priority)}
        candidates.sort(key=lambda kv: priority.get(kv[0], 999))
        return candidates[0]


def _parse_taxonomy(raw: dict[str, Any]) -> TagTaxonomy:
    value_filters: dict[str, ValueFilter] = {}
    for key, cfg in (raw.get("value_filters") or {}).items():
        value_filters[key] = ValueFilter(
            mode=str(cfg.get("mode", "deny")),
            values=frozenset(str(v) for v in (cfg.get("values") or [])),
        )
    return TagTaxonomy(
        include_keys=frozenset(raw.get("include_keys") or []),
        value_filters=value_filters,
        osmium_expressions=tuple(raw.get("osmium_expressions") or []),
        primary_key_priority=tuple(raw.get("primary_key_priority") or []),
    )


def load_taxonomy(path: Path) -> TagTaxonomy:
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid taxonomy file: {path}")
    return _parse_taxonomy(raw)


@lru_cache(maxsize=4)
def get_taxonomy(path_str: str) -> TagTaxonomy:
    return load_taxonomy(Path(path_str))

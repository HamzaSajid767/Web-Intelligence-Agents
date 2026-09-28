#!/usr/bin/env python3
"""Bootstrap worldwide OSM business ingest."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running without install: repo root on path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from osm_ingest.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["bootstrap", *sys.argv[1:]]))

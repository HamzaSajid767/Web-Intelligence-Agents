#!/usr/bin/env python3
"""Apply OSM replication updates for business ingest."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from osm_ingest.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["update", *sys.argv[1:]]))

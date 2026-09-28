"""CLI: osm-ingest bootstrap | update | status | ensure-schema."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from osm_ingest.config.settings import get_settings
from osm_ingest.persist.db import ensure_schema
from osm_ingest.pipeline import bootstrap, status, update


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="osm-ingest",
        description=(
            "Worldwide OSM business ingest: Planet PBF -> osmium filter -> "
            "pyosmium stream -> PostGIS (with replication updates)."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    boot = sub.add_parser("bootstrap", help="Download planet, filter, extract into PostGIS")
    boot.add_argument("--skip-download", action="store_true")
    boot.add_argument("--skip-filter", action="store_true")
    boot.add_argument("--skip-extract", action="store_true")
    boot.add_argument("--no-verify-md5", action="store_true")

    sub.add_parser("update", help="Apply OSM replication diffs since last checkpoint")
    sub.add_parser("status", help="Show checkpoint and DB counts")
    sub.add_parser("ensure-schema", help="Create PostGIS tables/indexes if missing")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    settings = get_settings()

    if args.command == "ensure-schema":
        ensure_schema(settings.postgis_dsn)
        print(json.dumps({"ok": True, "dsn": settings.postgis_dsn}))
        return 0

    if args.command == "bootstrap":
        result = bootstrap(
            settings,
            skip_download=args.skip_download,
            skip_filter=args.skip_filter,
            skip_extract=args.skip_extract,
            verify_md5=not args.no_verify_md5,
        )
        print(json.dumps(result, default=str))
        return 0

    if args.command == "update":
        result = update(settings)
        print(json.dumps(result, default=str))
        return 0

    if args.command == "status":
        result = status(settings)
        print(json.dumps(result, default=str, indent=2))
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

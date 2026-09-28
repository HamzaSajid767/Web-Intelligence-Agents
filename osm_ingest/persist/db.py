"""PostGIS connection helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO_ROOT / "docker" / "init-postgis.sql"


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=False)


@contextmanager
def connection(dsn: str) -> Iterator[psycopg.Connection]:
    conn = connect(dsn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema(dsn: str, schema_path: Path | None = None) -> None:
    """Apply init SQL if tables are missing (safe to re-run)."""
    path = schema_path or _SCHEMA_PATH
    if not path.exists():
        raise FileNotFoundError(f"Schema SQL not found: {path}")
    sql = path.read_text(encoding="utf-8")
    with connection(dsn) as conn:
        conn.execute(sql)

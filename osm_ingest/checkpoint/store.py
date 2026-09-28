"""Checkpoint store for resume and replication sequence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from osm_ingest.models import Checkpoint

_UPSERT = """
INSERT INTO ingest_checkpoints (
  job_name, phase, replication_seq, replication_ts,
  planet_url, planet_md5, extra, updated_at
) VALUES (
  %(job_name)s, %(phase)s, %(replication_seq)s, %(replication_ts)s,
  %(planet_url)s, %(planet_md5)s, %(extra)s, now()
)
ON CONFLICT (job_name) DO UPDATE SET
  phase = EXCLUDED.phase,
  replication_seq = EXCLUDED.replication_seq,
  replication_ts = EXCLUDED.replication_ts,
  planet_url = COALESCE(EXCLUDED.planet_url, ingest_checkpoints.planet_url),
  planet_md5 = COALESCE(EXCLUDED.planet_md5, ingest_checkpoints.planet_md5),
  extra = ingest_checkpoints.extra || EXCLUDED.extra,
  updated_at = now()
"""

_SELECT = """
SELECT job_name, phase, replication_seq, replication_ts,
       planet_url, planet_md5, extra
FROM ingest_checkpoints
WHERE job_name = %s
"""


def save_checkpoint(conn: psycopg.Connection, checkpoint: Checkpoint) -> None:
    conn.execute(
        _UPSERT,
        {
            "job_name": checkpoint.job_name,
            "phase": checkpoint.phase,
            "replication_seq": checkpoint.replication_seq,
            "replication_ts": checkpoint.replication_ts,
            "planet_url": checkpoint.planet_url,
            "planet_md5": checkpoint.planet_md5,
            "extra": Jsonb(checkpoint.extra or {}),
        },
    )


def load_checkpoint(conn: psycopg.Connection, job_name: str) -> Checkpoint | None:
    row = conn.execute(_SELECT, (job_name,)).fetchone()
    if not row:
        return None
    extra = row["extra"] or {}
    if not isinstance(extra, dict):
        extra = dict(extra)
    return Checkpoint(
        job_name=row["job_name"],
        phase=row["phase"],
        replication_seq=row["replication_seq"],
        replication_ts=row["replication_ts"],
        planet_url=row["planet_url"],
        planet_md5=row["planet_md5"],
        extra=extra,
    )


def merge_extra(conn: psycopg.Connection, job_name: str, patch: dict[str, Any]) -> None:
    ckpt = load_checkpoint(conn, job_name)
    if ckpt is None:
        ckpt = Checkpoint(job_name=job_name, phase="unknown", extra=patch)
    else:
        ckpt.extra = {**ckpt.extra, **patch}
    save_checkpoint(conn, ckpt)

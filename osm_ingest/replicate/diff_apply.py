"""Apply OSM replication diffs (OSC) to the business table."""

from __future__ import annotations

import gzip
import logging
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from osm_ingest.classify.tags import TagTaxonomy
from osm_ingest.extract.geometry import tags_to_dict
from osm_ingest.extract.handler import entity_from_node, entity_from_way
from osm_ingest.models import BusinessEntity
from osm_ingest.persist.upsert import soft_delete_batch, upsert_batch

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReplicationState:
    sequence: int
    timestamp: datetime | None = None


def _seq_path(sequence: int) -> str:
    """Map sequence number to replication path segments (e.g. 123/456/789)."""
    s = f"{sequence:09d}"
    return f"{s[0:3]}/{s[3:6]}/{s[6:9]}"


def parse_state_txt(text: str) -> ReplicationState:
    seq: int | None = None
    ts: datetime | None = None
    for line in text.splitlines():
        if line.startswith("sequenceNumber="):
            seq = int(line.split("=", 1)[1].strip())
        elif line.startswith("timestamp="):
            raw = line.split("=", 1)[1].strip().replace("\\:", ":")
            # 2024-01-01T00:00:00Z
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if seq is None:
        raise ValueError("state.txt missing sequenceNumber")
    return ReplicationState(sequence=seq, timestamp=ts)


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=30))
def fetch_remote_state(base_url: str) -> ReplicationState:
    url = urljoin(base_url.rstrip("/") + "/", "state.txt")
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return parse_state_txt(resp.text)


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=30))
def download_osc(base_url: str, sequence: int, dest: Path) -> Path:
    rel = _seq_path(sequence)
    url = urljoin(base_url.rstrip("/") + "/", f"{rel}.osc.gz")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=httpx.Timeout(60.0, read=300.0), follow_redirects=True) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    fh.write(chunk)
    return dest


def read_pbf_replication_seq(pbf_path: Path) -> int | None:
    """Best-effort read of osmosis_replication_sequence_number from PBF headers via osmium."""
    osmium = shutil.which("osmium")
    if not osmium:
        return None
    result = subprocess.run(
        [osmium, "fileinfo", "-e", "-g", "header.option.osmosis_replication_sequence_number", str(pbf_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    text = (result.stdout or "").strip()
    if text.isdigit():
        return int(text)
    return None


def apply_osc_file(
    conn: Any,
    osc_path: Path,
    taxonomy: TagTaxonomy,
    *,
    batch_size: int = 5_000,
) -> tuple[int, int]:
    """Apply one OSC/OSC.GZ file. Returns (upserted, soft_deleted)."""
    try:
        import osmium
    except ImportError as exc:
        raise ImportError("pyosmium is required. Install with: uv sync --extra osm") from exc

    # Decompress .gz to temp path if needed — FileProcessor accepts .osc.gz
    path = str(osc_path)

    upserts: list[BusinessEntity] = []
    deletes: list[tuple[str, int]] = []
    upserted = 0
    deleted = 0

    def flush() -> None:
        nonlocal upserted, deleted, upserts, deletes
        if upserts:
            upserted += upsert_batch(conn, upserts)
            upserts = []
        if deletes:
            deleted += soft_delete_batch(conn, deletes)
            deletes = []

    fp = osmium.FileProcessor(path)
    try:
        fp = fp.with_locations()
    except Exception as exc:
        logger.warning("OSC locations unavailable: %s", exc)

    for obj in fp:
        osm_type = "n"
        if obj.is_node():
            osm_type = "n"
        elif obj.is_way():
            osm_type = "w"
        elif obj.is_relation():
            osm_type = "r"
        else:
            continue

        osm_id = int(obj.id)
        if getattr(obj, "deleted", False):
            deletes.append((osm_type, osm_id))
            if len(deletes) >= batch_size:
                flush()
            continue

        tags = tags_to_dict(obj.tags)
        if not taxonomy.is_business(tags):
            # Was possibly a business before; soft-delete if present
            deletes.append((osm_type, osm_id))
            if len(deletes) >= batch_size:
                flush()
            continue

        entity: BusinessEntity | None = None
        if obj.is_node():
            entity = entity_from_node(obj, taxonomy)
        elif obj.is_way():
            entity = entity_from_way(obj, taxonomy)
        # Relations without area assembly: skip geometry; soft-delete handled above

        if entity is not None:
            upserts.append(entity)
            if len(upserts) >= batch_size:
                flush()
        else:
            # Business tags but no geometry (incomplete way in OSC) — leave existing row
            logger.debug("Skipping %s/%s: no geometry in change file", osm_type, osm_id)

    flush()
    conn.commit()
    return upserted, deleted


def apply_replication_batch(
    conn: Any,
    *,
    base_url: str,
    from_seq: int,
    changes_dir: Path,
    taxonomy: TagTaxonomy,
    max_bytes: int,
    batch_size: int = 5_000,
) -> ReplicationState:
    """Download and apply OSC files from from_seq+1 until size budget or tip.

    Returns the new replication state (last applied sequence).
    """
    remote = fetch_remote_state(base_url)
    if from_seq >= remote.sequence:
        logger.info("Already up to date at sequence %s", from_seq)
        return ReplicationState(sequence=from_seq, timestamp=remote.timestamp)

    changes_dir.mkdir(parents=True, exist_ok=True)
    applied = from_seq
    bytes_used = 0
    total_up = 0
    total_del = 0

    for seq in range(from_seq + 1, remote.sequence + 1):
        dest = changes_dir / f"{seq:09d}.osc.gz"
        if not dest.exists():
            download_osc(base_url, seq, dest)
        size = dest.stat().st_size
        if bytes_used + size > max_bytes and applied > from_seq:
            logger.info("Hit replication byte budget (%s); stopping at %s", max_bytes, applied)
            break
        bytes_used += size
        up, de = apply_osc_file(conn, dest, taxonomy, batch_size=batch_size)
        total_up += up
        total_del += de
        applied = seq
        # Remove applied change to save disk
        dest.unlink(missing_ok=True)
        logger.info(
            "Applied sequence %s (upserts=%s deletes=%s)",
            seq,
            up,
            de,
        )

    logger.info(
        "Replication batch done: %s → %s (upserts=%s deletes=%s)",
        from_seq,
        applied,
        total_up,
        total_del,
    )
    return ReplicationState(sequence=applied, timestamp=remote.timestamp)


def gunzip_file(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(src, "rb") as zin, dest.open("wb") as zout:
        shutil.copyfileobj(zin, zout)
    return dest

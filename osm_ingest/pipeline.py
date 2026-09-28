"""Bootstrap and update orchestration for worldwide OSM business ingest."""

from __future__ import annotations

import logging

from osm_ingest.checkpoint.store import load_checkpoint, save_checkpoint
from osm_ingest.classify.tags import load_taxonomy
from osm_ingest.config.settings import Settings, get_settings
from osm_ingest.download.planet import download_planet, file_md5
from osm_ingest.extract.handler import stream_entities
from osm_ingest.filter.osmium_filter import run_tags_filter
from osm_ingest.models import Checkpoint
from osm_ingest.persist.db import connection, ensure_schema
from osm_ingest.persist.upsert import count_businesses, upsert_batch
from osm_ingest.replicate.diff_apply import (
    apply_replication_batch,
    fetch_remote_state,
    read_pbf_replication_seq,
)

logger = logging.getLogger(__name__)


def _ensure_dirs(settings: Settings) -> None:
    settings.osm_data_dir.mkdir(parents=True, exist_ok=True)
    settings.planet_path.parent.mkdir(parents=True, exist_ok=True)
    settings.filtered_path.parent.mkdir(parents=True, exist_ok=True)
    settings.changes_dir.mkdir(parents=True, exist_ok=True)
    settings.location_cache_path.parent.mkdir(parents=True, exist_ok=True)


def bootstrap(
    settings: Settings | None = None,
    *,
    skip_download: bool = False,
    skip_filter: bool = False,
    skip_extract: bool = False,
    verify_md5: bool = True,
) -> dict[str, object]:
    """Full planet download → filter → extract → PostGIS."""
    settings = settings or get_settings()
    _ensure_dirs(settings)
    taxonomy = load_taxonomy(settings.osm_tags_config)
    ensure_schema(settings.postgis_dsn)

    stats: dict[str, object] = {"entities": 0}

    with connection(settings.postgis_dsn) as conn:
        ckpt = load_checkpoint(conn, settings.osm_job_name)
        phase = ckpt.phase if ckpt else "init"

        # --- download ---
        need_download = (not skip_download) and (
            phase in ("init", "downloading") or not settings.planet_path.exists()
        )
        if need_download:
            save_checkpoint(
                conn,
                Checkpoint(
                    job_name=settings.osm_job_name,
                    phase="downloading",
                    planet_url=settings.osm_planet_url,
                ),
            )
            conn.commit()
            download_planet(
                settings.osm_planet_url,
                settings.planet_path,
                chunk_bytes=settings.osm_download_chunk_bytes,
                md5_url=settings.osm_planet_md5_url,
                verify_md5=verify_md5,
            )
        elif settings.planet_path.exists():
            logger.info("Planet already present at %s", settings.planet_path)

        if settings.planet_path.exists() and phase in (
            "init",
            "downloading",
            "downloaded",
        ):
            md5 = file_md5(settings.planet_path)
            seq = read_pbf_replication_seq(settings.planet_path)
            save_checkpoint(
                conn,
                Checkpoint(
                    job_name=settings.osm_job_name,
                    phase="downloaded",
                    planet_url=settings.osm_planet_url,
                    planet_md5=md5,
                    replication_seq=seq,
                ),
            )
            conn.commit()
            phase = "downloaded"

        # --- filter ---
        need_filter = (not skip_filter) and (
            phase in ("downloaded", "filtering")
            or (phase == "filtered" and not settings.filtered_path.exists())
        )
        if need_filter:
            if not settings.planet_path.exists():
                raise FileNotFoundError(
                    f"Planet PBF missing at {settings.planet_path}; run download first"
                )
            save_checkpoint(
                conn,
                Checkpoint(job_name=settings.osm_job_name, phase="filtering"),
            )
            conn.commit()
            run_tags_filter(
                settings.planet_path,
                settings.filtered_path,
                taxonomy.osmium_expressions,
                osmium_bin=settings.osm_osmium_bin,
            )
            save_checkpoint(
                conn,
                Checkpoint(job_name=settings.osm_job_name, phase="filtered"),
            )
            conn.commit()
            phase = "filtered"

        # --- extract ---
        need_extract = (not skip_extract) and phase in ("filtered", "extracting")
        if need_extract:
            if not settings.filtered_path.exists():
                raise FileNotFoundError(
                    f"Filtered PBF missing at {settings.filtered_path}; run filter first"
                )
            save_checkpoint(
                conn,
                Checkpoint(job_name=settings.osm_job_name, phase="extracting"),
            )
            conn.commit()

            total = 0

            def on_batch(batch: list) -> None:
                nonlocal total
                upsert_batch(conn, batch)
                conn.commit()
                total += len(batch)
                if total % (settings.osm_batch_size * 5) == 0:
                    logger.info("Extracted %s businesses so far…", total)
                    save_checkpoint(
                        conn,
                        Checkpoint(
                            job_name=settings.osm_job_name,
                            phase="extracting",
                            extra={"entities_so_far": total},
                        ),
                    )
                    conn.commit()

            for _batch in stream_entities(
                settings.filtered_path,
                taxonomy,
                location_store=settings.osm_location_store,
                location_cache=settings.location_cache_path,
                batch_size=settings.osm_batch_size,
                on_batch=on_batch,
            ):
                pass

            stats["entities"] = total
            seq = read_pbf_replication_seq(settings.planet_path)
            if seq is None:
                remote = fetch_remote_state(settings.osm_replication_base_url)
                seq = remote.sequence
            save_checkpoint(
                conn,
                Checkpoint(
                    job_name=settings.osm_job_name,
                    phase="ready",
                    replication_seq=seq,
                    extra={"entities": total},
                ),
            )
            conn.commit()

        count = count_businesses(conn)
        stats["db_count"] = count
        final = load_checkpoint(conn, settings.osm_job_name)
        stats["phase"] = final.phase if final else "unknown"
        stats["replication_seq"] = final.replication_seq if final else None
        logger.info("Bootstrap complete: %s", stats)
        return stats


def update(settings: Settings | None = None) -> dict[str, object]:
    """Apply replication diffs since last checkpoint."""
    settings = settings or get_settings()
    _ensure_dirs(settings)
    taxonomy = load_taxonomy(settings.osm_tags_config)
    ensure_schema(settings.postgis_dsn)

    with connection(settings.postgis_dsn) as conn:
        ckpt = load_checkpoint(conn, settings.osm_job_name)
        if ckpt is None or ckpt.replication_seq is None:
            raise RuntimeError(
                "No replication checkpoint. Run `osm-ingest bootstrap` first."
            )
        if ckpt.phase not in ("ready", "updating"):
            raise RuntimeError(
                f"Checkpoint phase is {ckpt.phase!r}; expected 'ready'. "
                "Finish bootstrap before update."
            )

        save_checkpoint(
            conn,
            Checkpoint(
                job_name=settings.osm_job_name,
                phase="updating",
                replication_seq=ckpt.replication_seq,
            ),
        )
        conn.commit()

        new_state = apply_replication_batch(
            conn,
            base_url=settings.osm_replication_base_url,
            from_seq=ckpt.replication_seq,
            changes_dir=settings.changes_dir,
            taxonomy=taxonomy,
            max_bytes=settings.osm_replication_max_bytes,
            batch_size=settings.osm_batch_size,
        )

        save_checkpoint(
            conn,
            Checkpoint(
                job_name=settings.osm_job_name,
                phase="ready",
                replication_seq=new_state.sequence,
                replication_ts=new_state.timestamp,
            ),
        )
        conn.commit()
        return {
            "from_seq": ckpt.replication_seq,
            "to_seq": new_state.sequence,
            "db_count": count_businesses(conn),
        }


def status(settings: Settings | None = None) -> dict[str, object]:
    settings = settings or get_settings()
    ensure_schema(settings.postgis_dsn)
    with connection(settings.postgis_dsn) as conn:
        ckpt = load_checkpoint(conn, settings.osm_job_name)
        remote = None
        try:
            remote = fetch_remote_state(settings.osm_replication_base_url)
        except Exception as exc:
            logger.warning("Could not fetch remote replication state: %s", exc)
        return {
            "phase": ckpt.phase if ckpt else None,
            "replication_seq": ckpt.replication_seq if ckpt else None,
            "replication_ts": ckpt.replication_ts.isoformat() if ckpt and ckpt.replication_ts else None,
            "planet_url": ckpt.planet_url if ckpt else None,
            "planet_md5": ckpt.planet_md5 if ckpt else None,
            "extra": ckpt.extra if ckpt else {},
            "db_count": count_businesses(conn),
            "db_count_with_deleted": count_businesses(conn, include_deleted=True),
            "remote_seq": remote.sequence if remote else None,
            "planet_exists": settings.planet_path.exists(),
            "filtered_exists": settings.filtered_path.exists(),
        }

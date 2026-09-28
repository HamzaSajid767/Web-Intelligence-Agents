#!/usr/bin/env python
"""Process bulk audit URLs from a MongoDB-backed queue.

Usage:
    uv run python scripts/process_queue.py --file urls.txt
    uv run python scripts/process_queue.py --file urls.txt --enqueue-only
    uv run python scripts/process_queue.py --file urls.txt --force
    uv run python scripts/process_queue.py --resume
    uv run python scripts/process_queue.py --batch-id <uuid> --status-only
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.database.session import get_sync_db
from app.queue.manager import QueueManager
from app.queue.scheduler import WorkerManager


def _resolved_db_name(uri: str, fallback: str) -> str:
    path = urlparse(uri).path.lstrip("/")
    if path:
        return path.split("?")[0] or fallback
    return fallback


def _print_db_target() -> None:
    settings = get_settings()
    db_name = _resolved_db_name(settings.mongodb_uri, settings.mongodb_db_name)
    print(f"MongoDB URI: {settings.mongodb_uri}", flush=True)
    print(f"Database:    {db_name}", flush=True)
    print(
        "Inspect in Compass/mongosh: database "
        f"'{db_name}' (not Postgres). "
        "Queue rows live in audit_queue_batches / audit_queue_jobs; "
        "website_audits fill when workers process jobs.",
        flush=True,
    )


def _print_collection_counts() -> None:
    db = get_sync_db()
    batches = db.audit_queue_batches.count_documents({})
    jobs = db.audit_queue_jobs.count_documents({})
    audits = db.website_audits.count_documents({})
    status_counts = Counter(
        doc.get("status", "?") for doc in db.audit_queue_jobs.find({}, {"status": 1})
    )
    print(f"Collections: batches={batches} jobs={jobs} website_audits={audits}", flush=True)
    if status_counts:
        status_str = ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items()))
        print(f"Job statuses: {status_str}", flush=True)


def _print_progress(batch_id: uuid.UUID) -> None:
    manager = QueueManager()
    progress = manager.get_batch_progress(batch_id)
    counts = progress.get("counts", {})
    print(f"Batch: {progress['batch_id']}", flush=True)
    print(f"Status: {progress['batch_status']}", flush=True)
    print(f"Total jobs: {progress['total_jobs']}", flush=True)
    print(f"Completed: {progress['completed']}", flush=True)
    print(f"Pending: {progress['pending']}", flush=True)
    for status, count in sorted(counts.items()):
        print(f"  {status}: {count}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bulk audit queue processor")
    parser.add_argument("--file", type=Path, help="Path to a file with one URL per line")
    parser.add_argument("--batch-id", type=uuid.UUID, help="Process or inspect a specific batch")
    parser.add_argument(
        "--enqueue-only",
        action="store_true",
        help="Enqueue URLs without starting workers",
    )
    parser.add_argument("--resume", action="store_true", help="Process all unfinished queue jobs")
    parser.add_argument("--status-only", action="store_true", help="Print batch progress and exit")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-scrape URLs even when a successful audit already exists",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    settings = get_settings()
    setup_logging(settings.log_level)
    manager = QueueManager(settings)

    _print_db_target()

    if args.status_only:
        if not args.batch_id:
            parser.error("--status-only requires --batch-id")
        _print_progress(args.batch_id)
        _print_collection_counts()
        return 0

    # Reclaim jobs stuck in running from prior interrupted runs before new work.
    recovered = manager.recover_stale_jobs()
    if recovered:
        print(f"Recovered {recovered} stale running job(s).", flush=True)

    batch_id: uuid.UUID | None = args.batch_id

    if args.file:
        result = manager.enqueue_file(args.file, force=args.force)
        batch_id = result.batch_id
        print(
            f"Enqueued batch {batch_id} from {args.file} "
            f"({result.enqueued} jobs, {result.skipped} skipped)",
            flush=True,
        )
        _print_collection_counts()
        if args.enqueue_only:
            _print_progress(batch_id)
            return 0

    if args.resume and batch_id is None:
        unfinished = manager.list_unfinished_batches()
        if not unfinished:
            print("No unfinished batches found.", flush=True)
            return 0
        print(f"Resuming {len(unfinished)} unfinished batch(es).", flush=True)
        batch_id = None

    if batch_id is None and not args.resume and not args.file:
        parser.error("Provide --file, --batch-id, or --resume")

    if args.enqueue_only and not args.file:
        parser.error("--enqueue-only requires --file")

    worker_manager = WorkerManager(settings)
    worker_manager.run_until_complete(batch_id=batch_id if args.file or args.batch_id else None)

    if batch_id:
        _print_progress(batch_id)
    _print_collection_counts()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

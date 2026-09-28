"""Structured logging configuration."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

audit_id_ctx: ContextVar[str | None] = ContextVar("audit_id", default=None)
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
worker_id_ctx: ContextVar[str | None] = ContextVar("worker_id", default=None)
job_id_ctx: ContextVar[str | None] = ContextVar("job_id", default=None)
batch_id_ctx: ContextVar[str | None] = ContextVar("batch_id", default=None)


class StructuredFormatter(logging.Formatter):
    """JSON log formatter with contextual fields."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        audit_id = audit_id_ctx.get()
        if audit_id:
            payload["audit_id"] = audit_id

        request_id = request_id_ctx.get()
        if request_id:
            payload["request_id"] = request_id

        worker_id = worker_id_ctx.get()
        if worker_id:
            payload["worker_id"] = worker_id

        job_id = job_id_ctx.get()
        if job_id:
            payload["job_id"] = job_id

        batch_id = batch_id_ctx.get()
        if batch_id:
            payload["batch_id"] = batch_id

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for key in (
            "agent_name",
            "duration_ms",
            "crawl_ms",
            "agents_ms",
            "total_ms",
            "website_url",
            "status",
            "retry_count",
            "extra",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)

        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with structured JSON output."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    root.addHandler(handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger."""
    return logging.getLogger(name)

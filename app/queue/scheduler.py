"""Multiprocessing worker pool manager."""

from __future__ import annotations

import multiprocessing as mp
import signal
import time
import uuid
from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.queue.manager import QueueManager
from app.queue.worker import worker_process_main

logger = get_logger(__name__)


class WorkerManager:
    """Spawn and supervise multiprocessing audit workers."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.queue_manager = QueueManager(self.settings)
        self._stop_event: Any = None
        self._processes: list[mp.Process] = []

    def start(self, *, batch_id: uuid.UUID | None = None) -> None:
        """Recover stale jobs and start worker processes."""
        self.queue_manager.recover_stale_jobs()
        self._stop_event = mp.Event()
        worker_count = self.settings.queue_workers
        batch_id_str = str(batch_id) if batch_id else None

        logger.info(
            "Starting worker pool",
            extra={"worker_count": worker_count, "batch_id": batch_id_str},
        )

        for index in range(worker_count):
            worker_id = f"worker-{index + 1}"
            process = mp.Process(
                target=worker_process_main,
                args=(worker_id, self._stop_event, batch_id_str),
                name=worker_id,
                daemon=False,
            )
            process.start()
            self._processes.append(process)

        if batch_id:
            self.queue_manager.update_batch_status(batch_id)

    def wait(self) -> None:
        """Block until all workers exit."""
        for process in self._processes:
            process.join()

    def shutdown(self, *, graceful: bool = True) -> None:
        """Signal workers to stop and wait for completion."""
        if self._stop_event is not None:
            self._stop_event.set()
        if not graceful:
            for process in self._processes:
                if process.is_alive():
                    process.terminate()
        deadline = time.time() + self.settings.queue_shutdown_timeout_seconds
        for process in self._processes:
            remaining = max(0, deadline - time.time())
            process.join(timeout=remaining)
            if process.is_alive():
                logger.warning("Force terminating worker", extra={"worker": process.name})
                process.terminate()
                process.join(timeout=5)
        self._processes.clear()

    def run_until_complete(self, *, batch_id: uuid.UUID | None = None) -> None:
        """Start workers, handle signals, and wait for queue drain."""
        previous_handlers: dict[int, Any] = {}

        def _handle_signal(signum: int, _frame: Any) -> None:
            logger.info("Shutdown signal received", extra={"signal": signum})
            self.shutdown(graceful=True)

        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.signal(sig, _handle_signal)

        try:
            self.start(batch_id=batch_id)
            self.wait()
        finally:
            self.shutdown(graceful=True)
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)

"""Bulk audit queue processing."""

__all__ = ["QueueManager", "QueueWorker", "WorkerManager"]


def __getattr__(name: str):
    if name == "QueueManager":
        from app.queue.manager import QueueManager

        return QueueManager
    if name == "QueueWorker":
        from app.queue.worker import QueueWorker

        return QueueWorker
    if name == "WorkerManager":
        from app.queue.scheduler import WorkerManager

        return WorkerManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

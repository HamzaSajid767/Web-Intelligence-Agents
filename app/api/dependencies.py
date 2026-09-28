"""FastAPI dependency injection."""

from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import Depends

from app.database.session import get_async_session
from app.services.audit_service import AuditService
from app.services.email_service import EmailService
from app.services.report_service import ReportService
from app.workflows.job_manager import JobManager


async def get_db() -> AsyncGenerator[Any, None]:
    """Yield async MongoDB database handle."""
    async for session in get_async_session():
        yield session


def get_job_manager() -> JobManager:
    """Provide JobManager instance."""
    return JobManager()


async def get_audit_service(
    session: Annotated[Any, Depends(get_db)],
    job_manager: Annotated[JobManager, Depends(get_job_manager)],
) -> AuditService:
    """Provide AuditService instance."""
    return AuditService(session, job_manager)


async def get_report_service(
    session: Annotated[Any, Depends(get_db)],
) -> ReportService:
    """Provide ReportService instance."""
    return ReportService(session)


async def get_email_service(
    session: Annotated[Any, Depends(get_db)],
) -> EmailService:
    """Provide EmailService instance."""
    return EmailService(session)

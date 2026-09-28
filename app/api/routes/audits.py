"""Audit API routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_audit_service, get_email_service, get_report_service
from app.api.schemas.audit import (
    ApproveEmailResponse,
    AuditReportResponse,
    CreateAuditRequest,
    CreateAuditResponse,
    EmailResponse,
)
from app.services.audit_service import AuditService
from app.services.email_service import EmailService
from app.services.report_service import ReportService

router = APIRouter()


@router.post("", response_model=CreateAuditResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_audit(
    request: CreateAuditRequest,
    service: AuditService = Depends(get_audit_service),
) -> CreateAuditResponse:
    """Create a new website audit and enqueue background processing."""
    try:
        audit_id, audit_status = await service.create_audit(str(request.website_url))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return CreateAuditResponse(audit_id=audit_id, status=audit_status)


@router.get("/{audit_id}", response_model=AuditReportResponse)
async def get_audit(
    audit_id: uuid.UUID,
    service: ReportService = Depends(get_report_service),
) -> AuditReportResponse:
    """Get full audit result by ID."""
    report = await service.get_full_report(audit_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")
    return AuditReportResponse(**report)


@router.get("/{audit_id}/email", response_model=EmailResponse)
async def get_audit_email(
    audit_id: uuid.UUID,
    service: EmailService = Depends(get_email_service),
) -> EmailResponse:
    """Get generated outreach email for an audit."""
    email = await service.get_email(audit_id)
    if not email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    return EmailResponse(
        audit_id=uuid.UUID(email["audit_id"]),
        email_id=uuid.UUID(email["email_id"]) if email.get("email_id") else None,
        subject=email["subject"],
        body=email["body"],
        status=email["status"],
        approved_at=email.get("approved_at"),
    )


@router.post("/{audit_id}/approve", response_model=ApproveEmailResponse)
async def approve_audit_email(
    audit_id: uuid.UUID,
    service: EmailService = Depends(get_email_service),
) -> ApproveEmailResponse:
    """Approve email for manual send — does not send automatically."""
    result = await service.approve_email(audit_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    return ApproveEmailResponse(
        audit_id=uuid.UUID(result["audit_id"]),
        email_id=uuid.UUID(result["email_id"]),
        subject=result["subject"],
        body=result["body"],
        status=result["status"],
        approved_at=result.get("approved_at"),
        message=result["message"],
    )

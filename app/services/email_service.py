"""Email draft and approval service — no automatic sending."""

import uuid
from typing import Any

from app.database.repositories import GeneratedEmailRepository, UserRepository


class EmailService:
    """Manages generated email drafts and human approval."""

    def __init__(self, session: Any) -> None:
        self.email_repo = GeneratedEmailRepository(session)
        self.user_repo = UserRepository(session)

    async def get_email(self, audit_id: uuid.UUID) -> dict | None:
        """Get generated email for an audit."""
        email = await self.email_repo.get_by_audit_id_async(audit_id)
        if not email:
            return None
        return {
            "audit_id": str(audit_id),
            "email_id": str(email.id),
            "subject": email.subject,
            "body": email.body,
            "status": email.status,
            "approved_at": email.approved_at.isoformat() if email.approved_at else None,
        }

    async def approve_email(self, audit_id: uuid.UUID) -> dict | None:
        """Approve email for manual send — does NOT send email."""
        user = await self.user_repo.get_default_user_async()
        email = await self.email_repo.approve_async(audit_id, user.id if user else None)
        if not email:
            return None
        return {
            "audit_id": str(audit_id),
            "email_id": str(email.id),
            "subject": email.subject,
            "body": email.body,
            "status": email.status,
            "approved_at": email.approved_at.isoformat() if email.approved_at else None,
            "message": "Email approved for manual send. No email was sent automatically.",
        }

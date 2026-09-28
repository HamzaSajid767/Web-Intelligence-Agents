"""Repository layer for MongoDB access."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pymongo import ReturnDocument, UpdateOne
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.core.constants import (
    AuditRunStatus,
    AuditStatus,
    EmailStatus,
    QueueBatchStatus,
    QueueJobStatus,
)
from app.core.url_identity import lookup_keys, normalize_identity_url
from app.database.models import (
    AgentExecutionLog,
    AuditQueueBatch,
    AuditQueueJob,
    AuditRun,
    BusinessProfile,
    GeneratedEmail,
    PainPoint,
    Recommendation,
    User,
    WebsiteAudit,
    WebsitePage,
)
from app.database.models.base import new_uuid
from app.database.session import SyncMongoSession, resolve_db


def _now() -> datetime:
    return datetime.now(UTC)


def _sync_session(session: Any) -> SyncMongoSession | None:
    return session if isinstance(session, SyncMongoSession) else None


def _audit_reset_fields() -> dict[str, Any]:
    """Fields cleared when upserting an existing website audit for a re-scrape."""
    return {
        "status": AuditStatus.PENDING.value,
        "error_message": None,
        "metadata": None,
        "pages": [],
        "pain_points": [],
        "recommendations": [],
        "business_profile": None,
        "generated_email": None,
        "agent_logs": [],
        "emails": [],
        "phone_numbers": [],
        "social_links": [],
        "updated_at": _now(),
    }


def _alias_match_filter(keys: list[str]) -> dict[str, Any]:
    """Match audits whose canonical URL or aliases hit any lookup key."""
    return {
        "$or": [
            {"website_url": {"$in": keys}},
            {"submitted_urls": {"$in": keys}},
        ]
    }


class UserRepository:
    """User data access."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.db = resolve_db(session)

    async def get_default_user_async(self) -> User | None:
        """Return default user for v1 single-tenant mode."""
        settings = get_settings()
        doc = await self.db.users.find_one({"email": settings.default_user_email})
        return User.from_document(doc) if doc else None

    def get_default_user_sync(self) -> User | None:
        """Return default user (sync)."""
        settings = get_settings()
        doc = self.db.users.find_one({"email": settings.default_user_email})
        return User.from_document(doc) if doc else None

    async def create_default_user_async(self) -> User:
        """Create default user if missing."""
        user = await self.get_default_user_async()
        if user:
            return user
        settings = get_settings()
        user = User(
            email=settings.default_user_email,
            name=settings.default_user_name,
            is_active=True,
        )
        await self.db.users.insert_one(user.to_document())
        return user

    def create_default_user_sync(self) -> User:
        """Create default user if missing (sync)."""
        user = self.get_default_user_sync()
        if user:
            return user
        settings = get_settings()
        user = User(
            id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
            email=settings.default_user_email,
            name=settings.default_user_name,
            is_active=True,
        )
        self.db.users.insert_one(user.to_document())
        return user


class WebsiteAuditRepository:
    """Website audit aggregate repository."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.db = resolve_db(session)

    async def claim_or_create_by_url_async(
        self,
        *,
        user_id: uuid.UUID,
        submitted_url: str,
    ) -> WebsiteAudit:
        """Claim existing audit by canonical/alias or create a provisional one."""
        identity = normalize_identity_url(submitted_url)
        keys = lookup_keys(identity)
        now = _now()
        reset = _audit_reset_fields()
        reset["updated_at"] = now
        reset["latest_submitted_url"] = identity

        existing = await self.db.website_audits.find_one(_alias_match_filter(keys))
        if existing:
            doc = await self.db.website_audits.find_one_and_update(
                {"_id": existing["_id"]},
                {
                    "$set": reset,
                    "$addToSet": {"submitted_urls": {"$each": keys}},
                },
                return_document=ReturnDocument.AFTER,
            )
            if not doc:
                raise RuntimeError(f"Failed to claim website audit for {identity}")
            return WebsiteAudit.from_document(doc)

        audit_id = new_uuid()
        try:
            doc = await self.db.website_audits.find_one_and_update(
                {"website_url": identity},
                {
                    "$setOnInsert": {
                        "_id": str(audit_id),
                        "user_id": str(user_id),
                        "website_url": identity,
                        "created_at": now,
                        "audit_runs": [],
                        "submitted_urls": keys,
                        "redirect_history": [],
                    },
                    "$set": reset,
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            doc = await self.db.website_audits.find_one_and_update(
                _alias_match_filter(keys),
                {
                    "$set": reset,
                    "$addToSet": {"submitted_urls": {"$each": keys}},
                },
                return_document=ReturnDocument.AFTER,
            )
        if not doc:
            raise RuntimeError(f"Failed to claim website audit for {identity}")
        return WebsiteAudit.from_document(doc)

    def claim_or_create_by_url_sync(
        self,
        *,
        user_id: uuid.UUID,
        submitted_url: str,
    ) -> WebsiteAudit:
        """Claim existing audit by canonical/alias or create a provisional one (sync)."""
        identity = normalize_identity_url(submitted_url)
        keys = lookup_keys(identity)
        now = _now()
        reset = _audit_reset_fields()
        reset["updated_at"] = now
        reset["latest_submitted_url"] = identity

        existing = self.db.website_audits.find_one(_alias_match_filter(keys))
        if existing:
            doc = self.db.website_audits.find_one_and_update(
                {"_id": existing["_id"]},
                {
                    "$set": reset,
                    "$addToSet": {"submitted_urls": {"$each": keys}},
                },
                return_document=ReturnDocument.AFTER,
            )
            if not doc:
                raise RuntimeError(f"Failed to claim website audit for {identity}")
            audit = WebsiteAudit.from_document(doc)
            sync = _sync_session(self.session)
            if sync:
                sync.track_audit(audit)
            return audit

        audit_id = new_uuid()
        try:
            doc = self.db.website_audits.find_one_and_update(
                {"website_url": identity},
                {
                    "$setOnInsert": {
                        "_id": str(audit_id),
                        "user_id": str(user_id),
                        "website_url": identity,
                        "created_at": now,
                        "audit_runs": [],
                        "submitted_urls": keys,
                        "redirect_history": [],
                    },
                    "$set": reset,
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            doc = self.db.website_audits.find_one_and_update(
                _alias_match_filter(keys),
                {
                    "$set": reset,
                    "$addToSet": {"submitted_urls": {"$each": keys}},
                },
                return_document=ReturnDocument.AFTER,
            )
        if not doc:
            raise RuntimeError(f"Failed to claim website audit for {identity}")
        audit = WebsiteAudit.from_document(doc)
        sync = _sync_session(self.session)
        if sync:
            sync.track_audit(audit)
        return audit

    async def upsert_by_website_url_async(
        self,
        *,
        user_id: uuid.UUID,
        website_url: str,
    ) -> WebsiteAudit:
        """Backward-compatible alias for claim_or_create_by_url_async."""
        return await self.claim_or_create_by_url_async(
            user_id=user_id,
            submitted_url=website_url,
        )

    def upsert_by_website_url_sync(
        self,
        *,
        user_id: uuid.UUID,
        website_url: str,
    ) -> WebsiteAudit:
        """Backward-compatible alias for claim_or_create_by_url_sync."""
        return self.claim_or_create_by_url_sync(
            user_id=user_id,
            submitted_url=website_url,
        )

    def rebase_audit_to_canonical_sync(
        self,
        audit_id: uuid.UUID,
        canonical_url: str,
        *,
        submitted_url: str | None = None,
        final_url: str | None = None,
        redirect_history: list[dict[str, Any]] | None = None,
    ) -> uuid.UUID:
        """Rebind audit identity to canonical URL; merge if another doc owns it.

        Returns the surviving audit id (may differ from ``audit_id`` after merge).
        """
        canonical = normalize_identity_url(canonical_url)
        alias_keys = lookup_keys(canonical)
        if submitted_url:
            alias_keys = list(dict.fromkeys([*alias_keys, *lookup_keys(submitted_url)]))

        current = self.db.website_audits.find_one({"_id": str(audit_id)})
        if not current:
            raise RuntimeError(f"Audit {audit_id} not found for identity rebase")

        identity_fields: dict[str, Any] = {
            "final_url": final_url or canonical,
            "latest_submitted_url": (
                normalize_identity_url(submitted_url)
                if submitted_url
                else current.get("latest_submitted_url")
            ),
            "updated_at": _now(),
        }
        if redirect_history is not None:
            identity_fields["redirect_history"] = list(redirect_history)

        if current.get("website_url") == canonical:
            self.db.website_audits.update_one(
                {"_id": str(audit_id)},
                {
                    "$set": identity_fields,
                    "$addToSet": {"submitted_urls": {"$each": alias_keys}},
                },
            )
            return audit_id

        try:
            self.db.website_audits.update_one(
                {"_id": str(audit_id)},
                {
                    "$set": {**identity_fields, "website_url": canonical},
                    "$addToSet": {"submitted_urls": {"$each": alias_keys}},
                },
            )
            return audit_id
        except DuplicateKeyError:
            return self._merge_into_canonical_owner_sync(
                orphan_id=audit_id,
                orphan_doc=current,
                canonical=canonical,
                alias_keys=alias_keys,
                identity_fields=identity_fields,
            )

    def _merge_into_canonical_owner_sync(
        self,
        *,
        orphan_id: uuid.UUID,
        orphan_doc: dict[str, Any],
        canonical: str,
        alias_keys: list[str],
        identity_fields: dict[str, Any],
    ) -> uuid.UUID:
        """Transfer runs/aliases from orphan into the audit that owns canonical."""
        winner = self.db.website_audits.find_one({"website_url": canonical})
        if not winner:
            # Rare race: owner vanished; retry rename.
            self.db.website_audits.update_one(
                {"_id": str(orphan_id)},
                {
                    "$set": {**identity_fields, "website_url": canonical},
                    "$addToSet": {"submitted_urls": {"$each": alias_keys}},
                },
            )
            return orphan_id

        winner_id = uuid.UUID(str(winner["_id"]))
        if winner_id == orphan_id:
            return orphan_id

        # Re-read orphan so runs created after the initial load are transferred.
        fresh_orphan = self.db.website_audits.find_one({"_id": str(orphan_id)}) or orphan_doc
        orphan_runs = list(fresh_orphan.get("audit_runs") or [])
        orphan_logs = list(fresh_orphan.get("agent_logs") or [])
        orphan_aliases = list(fresh_orphan.get("submitted_urls") or [])
        all_aliases = list(dict.fromkeys([*alias_keys, *orphan_aliases]))

        push_ops: dict[str, Any] = {}
        if orphan_runs:
            push_ops["audit_runs"] = {"$each": orphan_runs}
        if orphan_logs:
            push_ops["agent_logs"] = {"$each": orphan_logs}

        update: dict[str, Any] = {
            "$set": identity_fields,
            "$addToSet": {"submitted_urls": {"$each": all_aliases}},
        }
        if push_ops:
            update["$push"] = push_ops

        self.db.website_audits.update_one({"_id": str(winner_id)}, update)
        self.db.website_audits.delete_one({"_id": str(orphan_id)})

        sync = _sync_session(self.session)
        if sync:
            sync._dirty_audits.pop(str(orphan_id), None)
            winner_doc = self.db.website_audits.find_one({"_id": str(winner_id)})
            if winner_doc:
                sync.track_audit(WebsiteAudit.from_document(winner_doc))
        return winner_id

    async def get_by_id_async(self, audit_id: uuid.UUID) -> WebsiteAudit | None:
        """Fetch audit by ID with related data."""
        doc = await self.db.website_audits.find_one({"_id": str(audit_id)})
        return WebsiteAudit.from_document(doc) if doc else None

    def get_by_id_sync(self, audit_id: uuid.UUID) -> WebsiteAudit | None:
        """Fetch audit by ID (sync)."""
        doc = self.db.website_audits.find_one({"_id": str(audit_id)})
        if not doc:
            return None
        audit = WebsiteAudit.from_document(doc)
        sync = _sync_session(self.session)
        if sync:
            sync.track_audit(audit)
        return audit

    def list_successful_urls_sync(self, urls: list[str], *, chunk_size: int = 500) -> set[str]:
        """Return input URLs that already have a successful scrape (alias-aware).

        Requires a completed/awaiting_review audit with at least one page and no
        crawl_errors, so DNS/empty crawls are not skipped forever.
        Matching uses canonical ``website_url`` and ``submitted_urls`` aliases.
        """
        if not urls:
            return set()
        successful_statuses = [
            AuditStatus.COMPLETED.value,
            AuditStatus.AWAITING_REVIEW.value,
        ]
        query_base: dict[str, Any] = {
            "status": {"$in": successful_statuses},
            "pages.0": {"$exists": True},
            "$and": [
                {
                    "$or": [
                        {"error_message": None},
                        {"error_message": ""},
                        {"error_message": {"$exists": False}},
                    ],
                },
                {
                    "$or": [
                        {"metadata.crawl_errors": {"$exists": False}},
                        {"metadata.crawl_errors": None},
                        {"metadata.crawl_errors": []},
                    ],
                },
            ],
        }
        # Expand each input URL to lookup keys, map key -> original inputs.
        key_to_inputs: dict[str, set[str]] = {}
        for raw in urls:
            try:
                for key in lookup_keys(raw):
                    key_to_inputs.setdefault(key, set()).add(raw)
            except ValueError:
                continue
        all_keys = list(key_to_inputs.keys())
        if not all_keys:
            return set()

        found_inputs: set[str] = set()
        for start in range(0, len(all_keys), chunk_size):
            chunk = all_keys[start : start + chunk_size]
            cursor = self.db.website_audits.find(
                {
                    **query_base,
                    "$or": [
                        {"website_url": {"$in": chunk}},
                        {"submitted_urls": {"$in": chunk}},
                    ],
                },
                {"website_url": 1, "submitted_urls": 1},
            )
            for doc in cursor:
                known = {doc.get("website_url"), *(doc.get("submitted_urls") or [])}
                known.discard(None)
                for key in known:
                    found_inputs.update(key_to_inputs.get(key, set()))
        return found_inputs

    async def update_status_async(
        self,
        audit_id: uuid.UUID,
        status: AuditStatus,
        error_message: str | None = None,
    ) -> None:
        """Update audit status."""
        await self.db.website_audits.update_one(
            {"_id": str(audit_id)},
            {
                "$set": {
                    "status": status.value,
                    "error_message": error_message,
                    "updated_at": _now(),
                }
            },
        )

    def update_status_sync(
        self,
        audit_id: uuid.UUID,
        status: AuditStatus,
        error_message: str | None = None,
    ) -> None:
        """Update audit status (sync)."""
        self.db.website_audits.update_one(
            {"_id": str(audit_id)},
            {
                "$set": {
                    "status": status.value,
                    "error_message": error_message,
                    "updated_at": _now(),
                }
            },
        )
        sync = _sync_session(self.session)
        if sync and str(audit_id) in sync._dirty_audits:
            audit = sync._dirty_audits[str(audit_id)]
            audit.status = status.value
            audit.error_message = error_message

    def update_contacts_sync(
        self,
        audit_id: uuid.UUID,
        *,
        emails: list[str],
        phone_numbers: list[str],
        social_links: list[str],
    ) -> None:
        """Persist extracted contact fields on the audit document."""
        self.db.website_audits.update_one(
            {"_id": str(audit_id)},
            {
                "$set": {
                    "emails": emails,
                    "phone_numbers": phone_numbers,
                    "social_links": social_links,
                    "updated_at": _now(),
                }
            },
        )
        sync = _sync_session(self.session)
        if sync and str(audit_id) in sync._dirty_audits:
            audit = sync._dirty_audits[str(audit_id)]
            audit.emails = list(emails)
            audit.phone_numbers = list(phone_numbers)
            audit.social_links = list(social_links)

    def hydrate_from_state_sync(
        self,
        audit_id: uuid.UUID,
        state: dict[str, Any],
        *,
        final_state_snapshot: dict[str, Any] | None = None,
    ) -> None:
        """Replace root WebsiteAudit fields from graph state (source of truth).

        Idempotent: arrays/objects are fully replaced rather than appended, so
        mid-graph checkpoints cannot leave a reused worker in a dirty state.
        """
        crawl_data = state.get("crawl_data") or {}
        contacts = crawl_data.get("contacts") or {}
        emails = list(contacts.get("emails") or state.get("emails") or [])
        phone_numbers = list(contacts.get("phone_numbers") or state.get("phone_numbers") or [])
        social_links = list(contacts.get("social_links") or state.get("social_links") or [])

        page_docs = []
        for page_data in crawl_data.get("pages") or []:
            if not isinstance(page_data, dict) or not page_data.get("url"):
                continue
            page = WebsitePage(
                url=page_data["url"],
                title=page_data.get("title"),
                raw_html=page_data.get("raw_html"),
                clean_text=page_data.get("clean_text"),
                metadata_json=page_data.get("metadata"),
                headings_json=page_data.get("headings"),
                links_json=page_data.get("links"),
            )
            page_docs.append(page.to_document())

        business_profile_doc = None
        profile_data = state.get("business_profile") or {}
        if isinstance(profile_data, dict) and any(
            profile_data.get(key)
            for key in ("industry", "services", "target_audience", "value_proposition")
        ):
            profile = BusinessProfile(
                industry=profile_data.get("industry"),
                services_json=profile_data.get("services"),
                target_audience=profile_data.get("target_audience"),
                value_proposition=profile_data.get("value_proposition"),
                raw_ai_output_json=profile_data,
            )
            business_profile_doc = profile.to_document()

        pain_docs = []
        for item in state.get("pain_points") or []:
            if not isinstance(item, dict):
                continue
            pain_point = PainPoint(
                category=item.get("category", "general"),
                severity=item.get("severity", "medium"),
                description=item.get("description", ""),
                evidence_json=item.get("evidence"),
                score=item.get("score"),
            )
            pain_docs.append(pain_point.to_document())

        rec_docs = []
        for item in state.get("recommendations") or []:
            if not isinstance(item, dict):
                continue
            problem = item.get("problem") or item.get("title", "")
            fix = item.get("fix") or item.get("description", "")
            expected_benefit = item.get("expected_benefit", "")
            description = fix
            if expected_benefit:
                description = f"{fix}\n\nExpected benefit: {expected_benefit}"
            rec = Recommendation(
                title=problem,
                description=description,
                priority=item.get("priority", "medium"),
                impact_score=item.get("impact_score"),
                effort_estimate=item.get("effort_estimate"),
                raw_ai_output_json=item,
            )
            rec_docs.append(rec.to_document())

        email_doc = None
        email_draft = state.get("email_draft") or {}
        if email_draft.get("subject") and email_draft.get("body"):
            email_doc = GeneratedEmail(
                subject=email_draft["subject"],
                body=email_draft["body"],
                status=EmailStatus.DRAFT.value,
            ).to_document()

        existing = self.db.website_audits.find_one({"_id": str(audit_id)}, {"metadata": 1}) or {}
        metadata = dict(existing.get("metadata") or {})
        metadata["scores"] = state.get("scores") or {}
        metadata["seo_analysis"] = state.get("seo_analysis") or {}
        metadata["chatbot_analysis"] = state.get("chatbot_analysis") or {}
        metadata["crawl_analysis"] = crawl_data.get("analysis")
        metadata["crawl_errors"] = crawl_data.get("errors")
        metadata["page_context"] = crawl_data.get("page_context")
        if crawl_data.get("site_validity") is not None:
            metadata["site_validity"] = crawl_data.get("site_validity")
        canonical = (
            crawl_data.get("canonical_url")
            or crawl_data.get("canonical_website_url")
        )
        if canonical:
            metadata["canonical_website_url"] = canonical
            metadata["canonical_url"] = canonical
        if final_state_snapshot is not None:
            metadata["final_state"] = final_state_snapshot

        status = state.get("status") or AuditStatus.RUNNING.value
        error_message = state.get("error")

        set_fields: dict[str, Any] = {
            "status": status,
            "error_message": error_message,
            "emails": emails,
            "phone_numbers": phone_numbers,
            "social_links": social_links,
            "pages": page_docs,
            "business_profile": business_profile_doc,
            "pain_points": pain_docs,
            "recommendations": rec_docs,
            "generated_email": email_doc,
            "metadata": metadata,
            "updated_at": _now(),
        }
        # Identity (website_url) is never mutated here — rebase_audit_to_canonical owns it.
        if crawl_data.get("final_url"):
            set_fields["final_url"] = crawl_data["final_url"]
        redirect_history = crawl_data.get("redirect_history") or crawl_data.get("redirect_chain")
        if redirect_history is not None:
            set_fields["redirect_history"] = list(redirect_history)
        if crawl_data.get("submitted_url"):
            set_fields["latest_submitted_url"] = crawl_data["submitted_url"]

        self.db.website_audits.update_one(
            {"_id": str(audit_id)},
            {"$set": set_fields},
        )
        sync = _sync_session(self.session)
        if sync and str(audit_id) in sync._dirty_audits:
            # Drop stale tracked copy so commit cannot overwrite hydrated fields.
            del sync._dirty_audits[str(audit_id)]


class AuditRunRepository:
    """Audit run job repository (embedded on website_audits)."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.db = resolve_db(session)

    async def create_async(self, audit_id: uuid.UUID) -> AuditRun:
        """Create pending audit run."""
        run = AuditRun(status=AuditRunStatus.PENDING.value)
        await self.db.website_audits.update_one(
            {"_id": str(audit_id)},
            {"$push": {"audit_runs": run.to_document()}, "$set": {"updated_at": _now()}},
        )
        return run

    def create_sync(self, audit_id: uuid.UUID) -> AuditRun:
        """Create pending audit run (sync)."""
        run = AuditRun(status=AuditRunStatus.PENDING.value)
        self.db.website_audits.update_one(
            {"_id": str(audit_id)},
            {"$push": {"audit_runs": run.to_document()}, "$set": {"updated_at": _now()}},
        )
        return run

    async def get_latest_async(self, audit_id: uuid.UUID) -> AuditRun | None:
        """Get latest audit run for an audit."""
        doc = await self.db.website_audits.find_one(
            {"_id": str(audit_id)},
            {"audit_runs": 1},
        )
        if not doc or not doc.get("audit_runs"):
            return None
        runs = [AuditRun.from_document(r) for r in doc["audit_runs"]]
        return max(runs, key=lambda r: r.created_at)

    def get_latest_sync(self, audit_id: uuid.UUID) -> AuditRun | None:
        """Get latest audit run (sync)."""
        doc = self.db.website_audits.find_one({"_id": str(audit_id)}, {"audit_runs": 1})
        if not doc or not doc.get("audit_runs"):
            return None
        runs = [AuditRun.from_document(r) for r in doc["audit_runs"]]
        return max(runs, key=lambda r: r.created_at)

    async def mark_running_async(self, run_id: uuid.UUID, celery_task_id: str) -> None:
        """Mark run as running."""
        await self.db.website_audits.update_one(
            {"audit_runs.id": str(run_id)},
            {
                "$set": {
                    "audit_runs.$.status": AuditRunStatus.RUNNING.value,
                    "audit_runs.$.celery_task_id": celery_task_id,
                    "audit_runs.$.started_at": _now(),
                    "updated_at": _now(),
                }
            },
        )

    def mark_running_sync(self, run_id: uuid.UUID, celery_task_id: str) -> None:
        """Mark run as running (sync)."""
        self.db.website_audits.update_one(
            {"audit_runs.id": str(run_id)},
            {
                "$set": {
                    "audit_runs.$.status": AuditRunStatus.RUNNING.value,
                    "audit_runs.$.celery_task_id": celery_task_id,
                    "audit_runs.$.started_at": _now(),
                    "updated_at": _now(),
                }
            },
        )

    async def mark_completed_async(self, run_id: uuid.UUID) -> None:
        """Mark run as completed."""
        await self.db.website_audits.update_one(
            {"audit_runs.id": str(run_id)},
            {
                "$set": {
                    "audit_runs.$.status": AuditRunStatus.COMPLETED.value,
                    "audit_runs.$.finished_at": _now(),
                    "updated_at": _now(),
                }
            },
        )

    def mark_completed_sync(self, run_id: uuid.UUID) -> None:
        """Mark run as completed (sync)."""
        self.db.website_audits.update_one(
            {"audit_runs.id": str(run_id)},
            {
                "$set": {
                    "audit_runs.$.status": AuditRunStatus.COMPLETED.value,
                    "audit_runs.$.finished_at": _now(),
                    "updated_at": _now(),
                }
            },
        )

    async def mark_failed_async(self, run_id: uuid.UUID, error_trace: str) -> None:
        """Mark run as failed."""
        await self.db.website_audits.update_one(
            {"audit_runs.id": str(run_id)},
            {
                "$set": {
                    "audit_runs.$.status": AuditRunStatus.FAILED.value,
                    "audit_runs.$.finished_at": _now(),
                    "audit_runs.$.error_trace": error_trace,
                    "updated_at": _now(),
                }
            },
        )

    def mark_failed_sync(self, run_id: uuid.UUID, error_trace: str) -> None:
        """Mark run as failed (sync)."""
        self.db.website_audits.update_one(
            {"audit_runs.id": str(run_id)},
            {
                "$set": {
                    "audit_runs.$.status": AuditRunStatus.FAILED.value,
                    "audit_runs.$.finished_at": _now(),
                    "audit_runs.$.error_trace": error_trace,
                    "updated_at": _now(),
                }
            },
        )


class WebsitePageRepository:
    """Website page repository (embedded)."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.db = resolve_db(session)

    def _page_docs(self, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        docs = []
        for page_data in pages:
            page = WebsitePage(
                url=page_data["url"],
                title=page_data.get("title"),
                raw_html=page_data.get("raw_html"),
                clean_text=page_data.get("clean_text"),
                metadata_json=page_data.get("metadata"),
                headings_json=page_data.get("headings"),
                links_json=page_data.get("links"),
            )
            docs.append(page.to_document())
        return docs

    def bulk_create_sync(self, audit_id: uuid.UUID, pages: list[dict[str, Any]]) -> None:
        """Persist crawled pages (sync)."""
        docs = self._page_docs(pages)
        if docs:
            self.db.website_audits.update_one(
                {"_id": str(audit_id)},
                {"$push": {"pages": {"$each": docs}}, "$set": {"updated_at": _now()}},
            )

    def replace_sync(self, audit_id: uuid.UUID, pages: list[dict[str, Any]]) -> None:
        """Replace crawled pages (idempotent checkpoint)."""
        self.db.website_audits.update_one(
            {"_id": str(audit_id)},
            {"$set": {"pages": self._page_docs(pages), "updated_at": _now()}},
        )


class BusinessProfileRepository:
    """Business profile repository (embedded)."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.db = resolve_db(session)

    def upsert_sync(self, audit_id: uuid.UUID, data: dict[str, Any]) -> BusinessProfile:
        """Create or update business profile (sync)."""
        profile = BusinessProfile(
            industry=data.get("industry"),
            services_json=data.get("services"),
            target_audience=data.get("target_audience"),
            value_proposition=data.get("value_proposition"),
            raw_ai_output_json=data,
        )
        self.db.website_audits.update_one(
            {"_id": str(audit_id)},
            {
                "$set": {
                    "business_profile": profile.to_document(),
                    "updated_at": _now(),
                }
            },
        )
        return profile


class PainPointRepository:
    """Pain point repository (embedded)."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.db = resolve_db(session)

    def _pain_docs(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        docs = []
        for item in items:
            pain_point = PainPoint(
                category=item.get("category", "general"),
                severity=item.get("severity", "medium"),
                description=item.get("description", ""),
                evidence_json=item.get("evidence"),
                score=item.get("score"),
            )
            docs.append(pain_point.to_document())
        return docs

    def bulk_create_sync(self, audit_id: uuid.UUID, items: list[dict[str, Any]]) -> None:
        """Persist pain points (sync)."""
        docs = self._pain_docs(items)
        if docs:
            self.db.website_audits.update_one(
                {"_id": str(audit_id)},
                {"$push": {"pain_points": {"$each": docs}}, "$set": {"updated_at": _now()}},
            )

    def replace_sync(self, audit_id: uuid.UUID, items: list[dict[str, Any]]) -> None:
        """Replace pain points (idempotent checkpoint)."""
        self.db.website_audits.update_one(
            {"_id": str(audit_id)},
            {"$set": {"pain_points": self._pain_docs(items), "updated_at": _now()}},
        )

    def update_scores_sync(self, audit_id: uuid.UUID, items: list[dict[str, Any]]) -> None:
        """Update pain point scores after impact scoring."""
        doc = self.db.website_audits.find_one({"_id": str(audit_id)}, {"pain_points": 1})
        if not doc:
            return
        existing = list(doc.get("pain_points") or [])
        for item, pain_point in zip(items, existing, strict=False):
            if "score" in item:
                pain_point["score"] = item["score"]
        self.db.website_audits.update_one(
            {"_id": str(audit_id)},
            {"$set": {"pain_points": existing, "updated_at": _now()}},
        )


class RecommendationRepository:
    """Recommendation repository (embedded)."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.db = resolve_db(session)

    def _rec_docs(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        docs = []
        for item in items:
            problem = item.get("problem") or item.get("title", "")
            fix = item.get("fix") or item.get("description", "")
            expected_benefit = item.get("expected_benefit", "")
            description = fix
            if expected_benefit:
                description = f"{fix}\n\nExpected benefit: {expected_benefit}"

            rec = Recommendation(
                title=problem,
                description=description,
                priority=item.get("priority", "medium"),
                impact_score=item.get("impact_score"),
                effort_estimate=item.get("effort_estimate"),
                raw_ai_output_json=item,
            )
            docs.append(rec.to_document())
        return docs

    def bulk_create_sync(self, audit_id: uuid.UUID, items: list[dict[str, Any]]) -> None:
        """Persist recommendations (sync)."""
        docs = self._rec_docs(items)
        if docs:
            self.db.website_audits.update_one(
                {"_id": str(audit_id)},
                {
                    "$push": {"recommendations": {"$each": docs}},
                    "$set": {"updated_at": _now()},
                },
            )

    def replace_sync(self, audit_id: uuid.UUID, items: list[dict[str, Any]]) -> None:
        """Replace recommendations (idempotent checkpoint)."""
        self.db.website_audits.update_one(
            {"_id": str(audit_id)},
            {"$set": {"recommendations": self._rec_docs(items), "updated_at": _now()}},
        )


class GeneratedEmailRepository:
    """Generated email repository (embedded)."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.db = resolve_db(session)

    def create_sync(self, audit_id: uuid.UUID, subject: str, body: str) -> GeneratedEmail:
        """Create email draft (sync)."""
        email = GeneratedEmail(
            subject=subject,
            body=body,
            status=EmailStatus.DRAFT.value,
        )
        self.db.website_audits.update_one(
            {"_id": str(audit_id)},
            {
                "$set": {
                    "generated_email": email.to_document(),
                    "updated_at": _now(),
                }
            },
        )
        return email

    async def get_by_audit_id_async(self, audit_id: uuid.UUID) -> GeneratedEmail | None:
        """Get email by audit ID."""
        doc = await self.db.website_audits.find_one(
            {"_id": str(audit_id)},
            {"generated_email": 1},
        )
        if not doc:
            return None
        return GeneratedEmail.from_document(doc.get("generated_email"))

    async def approve_async(
        self,
        audit_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
    ) -> GeneratedEmail | None:
        """Approve email for manual send."""
        email = await self.get_by_audit_id_async(audit_id)
        if not email:
            return None
        email.status = EmailStatus.APPROVED.value
        email.approved_at = _now()
        email.approved_by_user_id = user_id
        await self.db.website_audits.update_one(
            {"_id": str(audit_id)},
            {
                "$set": {
                    "generated_email": email.to_document(),
                    "updated_at": _now(),
                }
            },
        )
        return email


class AgentExecutionLogRepository:
    """Agent execution log repository (embedded)."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.db = resolve_db(session)

    def create_sync(
        self,
        *,
        audit_id: uuid.UUID,
        agent_name: str,
        status: str,
        input_snapshot: dict[str, Any] | None = None,
        output_snapshot: dict[str, Any] | None = None,
        duration_ms: int | None = None,
        token_usage: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> AgentExecutionLog:
        """Create agent execution log (sync)."""
        log = AgentExecutionLog(
            agent_name=agent_name,
            status=status,
            input_snapshot_json=input_snapshot,
            output_snapshot_json=output_snapshot,
            duration_ms=duration_ms,
            token_usage_json=token_usage or {"prompt_tokens": 0, "completion_tokens": 0},
            error_message=error_message,
        )
        self.db.website_audits.update_one(
            {"_id": str(audit_id)},
            {"$push": {"agent_logs": log.to_document()}, "$set": {"updated_at": _now()}},
        )
        return log


class AuditQueueBatchRepository:
    """Bulk queue batch repository."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.db = resolve_db(session)

    def create_sync(
        self,
        *,
        name: str | None,
        source: str,
        total_jobs: int,
    ) -> AuditQueueBatch:
        """Create a new queue batch."""
        batch = AuditQueueBatch(
            name=name,
            source=source,
            total_jobs=total_jobs,
            status=QueueBatchStatus.PENDING.value,
        )
        self.db.audit_queue_batches.insert_one(batch.to_document())
        return batch

    def get_by_id_sync(self, batch_id: uuid.UUID) -> AuditQueueBatch | None:
        """Fetch batch by ID."""
        doc = self.db.audit_queue_batches.find_one({"_id": str(batch_id)})
        return AuditQueueBatch.from_document(doc) if doc else None

    def update_status_sync(self, batch_id: uuid.UUID, status: QueueBatchStatus) -> None:
        """Update batch status."""
        self.db.audit_queue_batches.update_one(
            {"_id": str(batch_id)},
            {"$set": {"status": status.value, "updated_at": _now()}},
        )

    def list_unfinished_sync(self) -> list[AuditQueueBatch]:
        """Return batches that are not completed."""
        cursor = self.db.audit_queue_batches.find(
            {
                "status": {
                    "$in": [
                        QueueBatchStatus.PENDING.value,
                        QueueBatchStatus.RUNNING.value,
                    ]
                }
            }
        )
        return [AuditQueueBatch.from_document(doc) for doc in cursor]


class AuditQueueJobRepository:
    """Bulk queue job repository."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.db = resolve_db(session)

    def bulk_create_sync(self, jobs: list[AuditQueueJob]) -> None:
        """Insert multiple queue jobs."""
        if not jobs:
            return
        self.db.audit_queue_jobs.insert_many([job.to_document() for job in jobs])

    def claim_next_sync(
        self,
        worker_id: str,
        *,
        batch_id: uuid.UUID | None = None,
    ) -> AuditQueueJob | None:
        """Atomically claim the next available job."""
        query: dict[str, Any] = {
            "status": {
                "$in": [QueueJobStatus.QUEUED.value, QueueJobStatus.RETRYING.value],
            },
            "$expr": {"$lt": ["$retry_count", "$max_retries"]},
        }
        if batch_id is not None:
            query["batch_id"] = str(batch_id)

        doc = self.db.audit_queue_jobs.find_one_and_update(
            query,
            {
                "$set": {
                    "status": QueueJobStatus.RUNNING.value,
                    "worker_id": worker_id,
                    "started_at": _now(),
                    "updated_at": _now(),
                }
            },
            sort=[("queued_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        return AuditQueueJob.from_document(doc) if doc else None

    def mark_success_sync(
        self,
        job_id: uuid.UUID,
        *,
        audit_id: uuid.UUID,
        duration_ms: int,
        final_state_json: dict[str, Any] | None,
    ) -> None:
        """Mark job as successfully completed."""
        self.db.audit_queue_jobs.update_one(
            {"_id": str(job_id)},
            {
                "$set": {
                    "status": QueueJobStatus.SUCCESS.value,
                    "audit_id": str(audit_id),
                    "duration_ms": duration_ms,
                    "final_state": final_state_json,
                    "completed_at": _now(),
                    "error_message": None,
                    "error_trace": None,
                    "updated_at": _now(),
                }
            },
        )

    def mark_failure_sync(
        self,
        job_id: uuid.UUID,
        *,
        error_message: str,
        error_trace: str,
        will_retry: bool,
    ) -> None:
        """Mark job as failed or retrying."""
        status = (
            QueueJobStatus.RETRYING.value if will_retry else QueueJobStatus.FAILED.value
        )
        update: dict[str, Any] = {
            "$inc": {"retry_count": 1},
            "$set": {
                "status": status,
                "error_message": error_message,
                "error_trace": error_trace,
                "completed_at": _now(),
                "worker_id": None,
                "updated_at": _now(),
            },
        }
        if will_retry:
            update["$set"]["started_at"] = None
        self.db.audit_queue_jobs.update_one({"_id": str(job_id)}, update)

    def recover_stale_jobs_sync(self, stale_before: datetime) -> int:
        """Reset stale running jobs back to queued/retrying."""
        cursor = self.db.audit_queue_jobs.find(
            {
                "status": QueueJobStatus.RUNNING.value,
                "started_at": {"$lt": stale_before},
            }
        )
        ops: list[UpdateOne] = []
        count = 0
        for doc in cursor:
            count += 1
            if doc.get("retry_count", 0) < doc.get("max_retries", 3):
                status = QueueJobStatus.RETRYING.value
                error_message = doc.get("error_message")
            else:
                status = QueueJobStatus.FAILED.value
                error_message = doc.get("error_message") or (
                    "Job exceeded max retries after stale recovery"
                )
            ops.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {
                        "$set": {
                            "status": status,
                            "error_message": error_message,
                            "worker_id": None,
                            "started_at": None,
                            "updated_at": _now(),
                        }
                    },
                )
            )
        if ops:
            self.db.audit_queue_jobs.bulk_write(ops)
        return count

    def count_by_status_sync(self, batch_id: uuid.UUID | None = None) -> dict[str, int]:
        """Count jobs grouped by status."""
        match: dict[str, Any] = {}
        if batch_id is not None:
            match["batch_id"] = str(batch_id)
        pipeline: list[dict[str, Any]] = []
        if match:
            pipeline.append({"$match": match})
        pipeline.append({"$group": {"_id": "$status", "count": {"$sum": 1}}})
        rows = self.db.audit_queue_jobs.aggregate(pipeline)
        return {row["_id"]: row["count"] for row in rows}

    def has_pending_jobs_sync(self, batch_id: uuid.UUID | None = None) -> bool:
        """Return True if any jobs are queued, running, or retrying."""
        query: dict[str, Any] = {
            "status": {
                "$in": [
                    QueueJobStatus.QUEUED.value,
                    QueueJobStatus.RUNNING.value,
                    QueueJobStatus.RETRYING.value,
                ]
            }
        }
        if batch_id is not None:
            query["batch_id"] = str(batch_id)
        return self.db.audit_queue_jobs.find_one(query, {"_id": 1}) is not None

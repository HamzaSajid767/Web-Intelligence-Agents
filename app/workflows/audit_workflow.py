"""Audit workflow orchestration."""

import traceback
import uuid
from typing import Any

from app.agents.deps import AgentDependencies
from app.agents.graph import build_audit_graph
from app.agents.state import AuditState
from app.ai.ollama_client import OllamaClient
from app.core.constants import AgentExecutionStatus, AgentName, AuditRunStatus, AuditStatus
from app.core.exceptions import InvalidSiteError
from app.core.logging import audit_id_ctx, get_logger
from app.crawler.crawler_service import CrawlerService
from app.database.repositories import (
    AgentExecutionLogRepository,
    AuditRunRepository,
    BusinessProfileRepository,
    GeneratedEmailRepository,
    PainPointRepository,
    RecommendationRepository,
    WebsiteAuditRepository,
    WebsitePageRepository,
)
from app.database.session import SyncSessionLocal
from app.utils.audit_state import serialize_audit_state
from app.vector.noop_retriever import NoOpVectorRetriever

logger = get_logger(__name__)


class AuditWorkflow:
    """Runs the LangGraph audit pipeline with per-node persistence."""

    def __init__(self, deps: AgentDependencies | None = None) -> None:
        self.deps = deps or AgentDependencies(
            ollama=OllamaClient(),
            crawler=CrawlerService(),
            vector_retriever=NoOpVectorRetriever(),
        )
        self._persisted: set[str] = set()
        self._saved_log_count = 0

    def _reset_run_state(self) -> None:
        """Clear per-execute checkpoint gates (workflow may be reused by workers)."""
        self._persisted.clear()
        self._saved_log_count = 0

    def _persist_new_logs(
        self,
        session: Any,
        audit_id: uuid.UUID,
        state: AuditState,
    ) -> None:
        """Persist agent execution logs added since last checkpoint."""
        log_repo = AgentExecutionLogRepository(session)
        logs = state.get("agent_logs", [])
        for log_entry in logs[self._saved_log_count :]:
            log_repo.create_sync(
                audit_id=audit_id,
                agent_name=log_entry.get("agent_name", "unknown"),
                status=log_entry.get("status", AgentExecutionStatus.COMPLETED.value),
                input_snapshot=log_entry.get("input_snapshot"),
                output_snapshot=log_entry.get("output"),
                duration_ms=log_entry.get("duration_ms"),
                token_usage=log_entry.get("token_usage"),
                error_message=log_entry.get("error"),
            )
        self._saved_log_count = len(logs)

    def _persist_node(
        self,
        session: Any,
        audit_id: uuid.UUID,
        agent_name: str,
        state: AuditState,
    ) -> None:
        """Persist results for a completed graph node (checkpoint salvage)."""
        page_repo = WebsitePageRepository(session)
        profile_repo = BusinessProfileRepository(session)
        pain_repo = PainPointRepository(session)
        rec_repo = RecommendationRepository(session)
        email_repo = GeneratedEmailRepository(session)
        audit_repo = WebsiteAuditRepository(session)

        if agent_name == AgentName.CRAWLER.value and "pages" not in self._persisted:
            crawl_data = state.get("crawl_data", {}) or {}
            canonical = crawl_data.get("canonical_url") or crawl_data.get("canonical_website_url")
            if canonical:
                surviving_id = audit_repo.rebase_audit_to_canonical_sync(
                    audit_id,
                    canonical,
                    submitted_url=crawl_data.get("submitted_url") or state.get("website_url"),
                    final_url=crawl_data.get("final_url"),
                    redirect_history=(
                        crawl_data.get("redirect_history") or crawl_data.get("redirect_chain")
                    ),
                )
                if surviving_id != audit_id:
                    state["audit_id"] = str(surviving_id)
                    audit_id = surviving_id
                    audit_id_ctx.set(str(surviving_id))

            pages = crawl_data.get("pages", [])
            if pages:
                page_repo.replace_sync(audit_id, pages)
            contacts = crawl_data.get("contacts") or {}
            audit_repo.update_contacts_sync(
                audit_id,
                emails=list(contacts.get("emails") or []),
                phone_numbers=list(contacts.get("phone_numbers") or []),
                social_links=list(contacts.get("social_links") or []),
            )
            audit = audit_repo.get_by_id_sync(audit_id)
            if audit:
                metadata = dict(audit.metadata_json or {})
                metadata["crawl_analysis"] = crawl_data.get("analysis")
                metadata["crawl_errors"] = crawl_data.get("errors")
                metadata["page_context"] = crawl_data.get("page_context")
                if crawl_data.get("site_validity") is not None:
                    metadata["site_validity"] = crawl_data.get("site_validity")
                if canonical:
                    metadata["canonical_url"] = canonical
                    metadata["canonical_website_url"] = canonical
                audit.metadata_json = metadata
            self._persisted.add("pages")

        elif agent_name == AgentName.BUSINESS_ANALYSIS.value and "profile" not in self._persisted:
            profile = state.get("business_profile")
            if profile:
                profile_repo.upsert_sync(audit_id, profile)
            self._persisted.add("profile")

        elif agent_name == AgentName.PAIN_POINTS.value and "pain_points" not in self._persisted:
            pain_points = state.get("pain_points", [])
            if pain_points:
                pain_repo.replace_sync(audit_id, pain_points)
            audit = audit_repo.get_by_id_sync(audit_id)
            if audit:
                metadata = dict(audit.metadata_json or {})
                metadata["seo_analysis"] = state.get("seo_analysis", {})
                metadata["chatbot_analysis"] = state.get("chatbot_analysis", {})
                audit.metadata_json = metadata
            self._persisted.add("pain_points")

        elif agent_name == AgentName.IMPACT_SCORING.value and "scores" not in self._persisted:
            pain_points = state.get("pain_points", [])
            if pain_points:
                pain_repo.update_scores_sync(audit_id, pain_points)
            audit = audit_repo.get_by_id_sync(audit_id)
            if audit:
                metadata = dict(audit.metadata_json or {})
                metadata["scores"] = state.get("scores", {})
                audit.metadata_json = metadata
            self._persisted.add("scores")

        elif agent_name == AgentName.RECOMMENDATIONS.value and "recommendations" not in self._persisted:
            recommendations = state.get("recommendations", [])
            if recommendations:
                rec_repo.replace_sync(audit_id, recommendations)
            self._persisted.add("recommendations")

        elif agent_name == AgentName.EMAIL_WRITER.value and "email" not in self._persisted:
            email_draft = state.get("email_draft", {})
            if email_draft.get("subject") and email_draft.get("body"):
                email_repo.create_sync(
                    audit_id,
                    subject=email_draft["subject"],
                    body=email_draft["body"],
                )
            self._persisted.add("email")

        elif agent_name == AgentName.HUMAN_REVIEW.value and "review" not in self._persisted:
            audit_repo.update_status_sync(audit_id, AuditStatus.AWAITING_REVIEW)
            self._persisted.add("review")

        self._persist_new_logs(session, audit_id, state)

    async def execute(self, audit_id: uuid.UUID, website_url: str, run_id: uuid.UUID) -> AuditState:
        """Execute audit pipeline asynchronously with per-node persistence."""
        audit_id_ctx.set(str(audit_id))
        self._reset_run_state()
        session = SyncSessionLocal()
        run_repo = AuditRunRepository(session)
        audit_repo = WebsiteAuditRepository(session)
        final_state: AuditState = {}
        last_crawl_state: AuditState | None = None

        try:
            audit_repo.update_status_sync(audit_id, AuditStatus.RUNNING)
            session.commit()

            initial_state: AuditState = {
                "audit_id": str(audit_id),
                "website_url": website_url,
                "crawl_data": {},
                "business_profile": {},
                "pain_points": [],
                "seo_analysis": {},
                "chatbot_analysis": {},
                "scores": {},
                "recommendations": [],
                "email_draft": {},
                "agent_logs": [],
                "status": AuditStatus.RUNNING.value,
                "error": None,
                "current_agent": None,
            }

            graph = build_audit_graph(self.deps)
            async for state in graph.astream(initial_state, stream_mode="values"):
                final_state = state
                if state.get("crawl_data", {}).get("pages"):
                    last_crawl_state = state
                current_agent = state.get("current_agent")
                if current_agent:
                    self._persist_node(session, audit_id, current_agent, state)
                    if state.get("audit_id"):
                        audit_id = uuid.UUID(str(state["audit_id"]))
                        audit_id_ctx.set(str(audit_id))
                    session.commit()

            # Ensure remaining agent logs are checkpointed even if astream skips a step.
            if final_state:
                if final_state.get("audit_id"):
                    audit_id = uuid.UUID(str(final_state["audit_id"]))
                self._persist_new_logs(session, audit_id, final_state)

            snapshot = serialize_audit_state(final_state) if final_state else {}
            if final_state.get("status") == AuditStatus.INVALID_SITE.value:
                audit_repo.hydrate_from_state_sync(
                    audit_id,
                    final_state,
                    final_state_snapshot=snapshot,
                )
                run_repo.mark_failed_sync(
                    run_id,
                    final_state.get("error") or "Invalid or unusable website",
                )
                session.commit()
                logger.warning(
                    "Audit rejected as invalid site",
                    extra={
                        "audit_id": str(audit_id),
                        "website_url": website_url,
                        "error": final_state.get("error"),
                    },
                )
                raise InvalidSiteError(
                    final_state.get("error") or "Invalid or unusable website",
                    audit_id=audit_id,
                    website_url=website_url,
                )

            if not final_state.get("status") or final_state.get("status") == AuditStatus.RUNNING.value:
                final_state["status"] = AuditStatus.AWAITING_REVIEW.value

            audit_repo.hydrate_from_state_sync(
                audit_id,
                final_state,
                final_state_snapshot=snapshot,
            )
            run_repo.mark_completed_sync(run_id)
            session.commit()
            logger.info(
                "Audit workflow completed",
                extra={
                    "audit_id": str(audit_id),
                    "status": final_state.get("status"),
                    "pages": len((final_state.get("crawl_data") or {}).get("pages") or []),
                },
            )
            return final_state

        except InvalidSiteError:
            raise
        except Exception as exc:
            session.rollback()
            try:
                salvage = final_state if final_state.get("crawl_data", {}).get("pages") else last_crawl_state
                if salvage and salvage.get("crawl_data", {}).get("pages"):
                    self._persisted.discard("pages")
                    self._persist_node(
                        session,
                        audit_id,
                        AgentName.CRAWLER.value,
                        salvage,
                    )
                    audit_repo.hydrate_from_state_sync(
                        audit_id,
                        {
                            **salvage,
                            "status": AuditStatus.FAILED.value,
                            "error": str(exc),
                        },
                        final_state_snapshot=serialize_audit_state(salvage),
                    )
                elif final_state:
                    current_agent = final_state.get("current_agent")
                    if current_agent:
                        self._persist_node(session, audit_id, current_agent, final_state)
                session.commit()
            except Exception:
                session.rollback()

            session = SyncSessionLocal()
            run_repo = AuditRunRepository(session)
            audit_repo = WebsiteAuditRepository(session)
            error_trace = traceback.format_exc()
            run_repo.mark_failed_sync(run_id, error_trace)
            audit_repo.update_status_sync(audit_id, AuditStatus.FAILED, str(exc))
            session.commit()
            logger.exception("Audit workflow failed", extra={"audit_id": str(audit_id)})
            raise
        finally:
            try:
                await self.deps.ollama.aclose()
            except Exception:
                logger.warning(
                    "Failed to close Ollama client after audit execute",
                    extra={"audit_id": str(audit_id)},
                    exc_info=True,
                )
            session.close()

    def execute_sync(self, audit_id: uuid.UUID, website_url: str, run_id: uuid.UUID) -> AuditState:
        """Sync entry point for Celery workers and CLI."""
        import asyncio

        return asyncio.run(self.execute(audit_id, website_url, run_id))

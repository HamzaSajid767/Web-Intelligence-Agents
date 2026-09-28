"""Crawler agent node."""

from app.agents.deps import AgentDependencies
from app.agents.nodes import append_agent_log, build_input_snapshot
from app.agents.state import AuditState
from app.ai.ollama_client import NUM_PREDICT_CRAWLER
from app.ai.prompt_loader import load_prompt
from app.ai.schemas import CrawlerAnalysisOutput
from app.analysis.site_validity import assess_site_validity
from app.core.constants import AgentExecutionStatus, AgentName, AuditStatus
from app.core.logging import get_logger
from app.crawler.contact_extractor import aggregate_contacts
from app.crawler.page_context import build_page_context

logger = get_logger(__name__)


async def crawler_handler(state: AuditState, deps: AgentDependencies) -> AuditState:
    """Crawl website, validate usability, and optionally analyze content.

    Pages/contacts are always placed on state before the LLM so a remote Ollama
    outage cannot lose crawl data once this node finishes.
    """
    website_url = state["website_url"]
    logger.info("Crawler node started", extra={"website_url": website_url})
    crawl_result = await deps.crawler.crawl(website_url)
    crawl_data = deps.crawler.to_state_dict(crawl_result)
    canonical = crawl_result.canonical_url or crawl_result.canonical_website_url
    if canonical:
        crawl_data["canonical_url"] = canonical
        crawl_data["canonical_website_url"] = canonical
        state["website_url"] = canonical
    if crawl_result.submitted_url:
        crawl_data["submitted_url"] = crawl_result.submitted_url
    if crawl_result.final_url:
        crawl_data["final_url"] = crawl_result.final_url

    state["crawl_data"] = crawl_data
    state["status"] = AuditStatus.RUNNING.value

    successful_pages = [
        page
        for page in crawl_data.get("pages") or []
        if page.get("success", True)
        and (page.get("raw_html") or page.get("clean_text") or page.get("markdown"))
    ]
    if crawl_result.total_pages == 0 or not successful_pages:
        detail = "; ".join(crawl_result.errors) if crawl_result.errors else "no pages retrieved"
        raise RuntimeError(f"Crawl produced no usable pages for {website_url}: {detail}")

    page_context = build_page_context(crawl_data["pages"])
    crawl_data["page_context"] = page_context
    crawl_data["contacts"] = aggregate_contacts(crawl_data["pages"])
    crawl_data["analysis"] = {}

    validity = assess_site_validity(
        crawl_data["pages"],
        crawl_errors=crawl_data.get("errors") or [],
    )
    crawl_data["site_validity"] = validity.to_dict()
    state["crawl_data"] = crawl_data

    token_usage: dict = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "model": deps.ollama.model,
    }
    log_status = AgentExecutionStatus.COMPLETED
    error_message: str | None = None

    if not validity.is_valid:
        state["status"] = AuditStatus.INVALID_SITE.value
        state["error"] = validity.reason
        state["business_profile"] = {}
        state["pain_points"] = []
        state["recommendations"] = []
        state["email_draft"] = {}
        crawl_data["analysis"] = {
            "summary": f"Site rejected: {validity.reason}",
            "primary_topics": [],
            "content_quality": "unusable",
            "notable_elements": validity.signals[:10],
        }
        state["crawl_data"] = crawl_data
        logger.warning(
            "Crawler rejected invalid site",
            extra={
                "website_url": website_url,
                "reason": validity.reason,
                "signals": validity.signals[:8],
                "pages_crawled": crawl_result.total_pages,
            },
        )
        append_agent_log(
            state,
            agent_name=AgentName.CRAWLER,
            status=AgentExecutionStatus.COMPLETED,
            input_snapshot=build_input_snapshot(state, AgentName.CRAWLER),
            output={
                "total_pages": crawl_result.total_pages,
                "analysis": crawl_data.get("analysis") or {},
                "contacts": crawl_data["contacts"],
                "site_validity": validity.to_dict(),
            },
            error=validity.reason,
            token_usage=token_usage,
        )
        logger.info(
            "Crawler node finished",
            extra={
                "website_url": website_url,
                "status": state["status"],
                "pages": crawl_result.total_pages,
                "contacts_emails": len((crawl_data.get("contacts") or {}).get("emails") or []),
            },
        )
        return state

    analysis_context = build_page_context(
        crawl_data["pages"],
        max_pages=3,
        max_chars_per_page=800,
    )
    prompt = load_prompt(
        "crawler_analysis.txt",
        website_url=state["website_url"],
        page_count=str(crawl_result.total_pages),
        content_summary=analysis_context or "No content extracted",
    )

    try:
        analysis, token_usage = await deps.ollama.generate_json(
            prompt,
            CrawlerAnalysisOutput,
            num_predict=NUM_PREDICT_CRAWLER,
        )
        crawl_data["analysis"] = analysis.model_dump()
    except Exception as exc:
        error_message = str(exc)
        log_status = AgentExecutionStatus.FAILED
        crawl_data["analysis"] = {
            "summary": f"LLM analysis unavailable: {error_message}",
            "primary_topics": [],
            "content_quality": "unknown",
            "notable_elements": [],
        }
        logger.error(
            "Crawler LLM analysis failed; keeping crawl pages and contacts",
            extra={
                "website_url": website_url,
                "error": error_message,
                "error_type": type(exc).__name__,
            },
            exc_info=True,
        )

    state["crawl_data"] = crawl_data
    append_agent_log(
        state,
        agent_name=AgentName.CRAWLER,
        status=log_status,
        input_snapshot=build_input_snapshot(state, AgentName.CRAWLER),
        output={
            "total_pages": crawl_result.total_pages,
            "analysis": crawl_data.get("analysis") or {},
            "contacts": crawl_data["contacts"],
            "site_validity": validity.to_dict(),
        },
        error=error_message,
        token_usage=token_usage,
    )
    logger.info(
        "Crawler node finished",
        extra={
            "website_url": state["website_url"],
            "pages": crawl_result.total_pages,
            "llm_status": log_status.value,
            "usable_pages": validity.usable_page_count,
        },
    )
    return state

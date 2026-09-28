"""Business analysis agent node."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.agents.deps import AgentDependencies
from app.agents.nodes import append_agent_log, build_input_snapshot
from app.agents.state import AuditState
from app.ai.ollama_client import NUM_PREDICT_BUSINESS
from app.ai.prompt_loader import load_prompt
from app.ai.schemas import BusinessProfileOutput
from app.core.constants import AgentExecutionStatus, AgentName, AuditStatus
from app.core.logging import get_logger
from app.crawler.page_context import build_downstream_context

logger = get_logger(__name__)

_MIN_EVIDENCE_CHARS = 200
_UNKNOWN_PROFILE = {
    "industry": "Unknown",
    "services": [],
    "target_audience": "Unknown",
    "value_proposition": "Insufficient crawl evidence to determine business profile",
    "confidence": 0.1,
    "evidence_urls": [],
}


def _usable_text_chars(pages: list[dict[str, Any]]) -> int:
    total = 0
    for page in pages:
        if page.get("success") is False:
            continue
        total += len((page.get("clean_text") or "").strip())
    return total


def _evidence_urls(pages: list[dict[str, Any]], limit: int = 5) -> list[str]:
    urls: list[str] = []
    for page in pages:
        if page.get("success") is False:
            continue
        url = page.get("url")
        text = (page.get("clean_text") or "").strip()
        if url and len(text) >= 80 and url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def _profile_from_crawl(crawl_data: dict[str, Any], pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Minimal profile when LLM business analysis fails — never invent industry."""
    chars = _usable_text_chars(pages)
    if chars < _MIN_EVIDENCE_CHARS:
        return {**_UNKNOWN_PROFILE, "evidence_urls": _evidence_urls(pages)}

    analysis = crawl_data.get("analysis") or {}
    topics = [t for t in (analysis.get("primary_topics") or []) if t and str(t).lower() != "unknown"]
    if not topics and not analysis.get("summary"):
        return {**_UNKNOWN_PROFILE, "confidence": 0.2, "evidence_urls": _evidence_urls(pages)}

    return {
        "industry": topics[0] if topics else "Unknown",
        "services": list(topics)[:5],
        "target_audience": "website visitors",
        "value_proposition": analysis.get("summary") or "Not determined",
        "confidence": 0.35 if topics else 0.2,
        "evidence_urls": _evidence_urls(pages),
    }


async def business_analysis_handler(state: AuditState, deps: AgentDependencies) -> AuditState:
    """Analyze business from crawl data; refuse when evidence is insufficient."""
    if state.get("status") == AuditStatus.INVALID_SITE.value:
        state["business_profile"] = {**_UNKNOWN_PROFILE}
        append_agent_log(
            state,
            agent_name=AgentName.BUSINESS_ANALYSIS,
            status=AgentExecutionStatus.FAILED,
            input_snapshot=build_input_snapshot(state, AgentName.BUSINESS_ANALYSIS),
            output=state["business_profile"],
            error="Skipped: invalid site",
        )
        return state

    crawl_data = state.get("crawl_data", {})
    pages = crawl_data.get("pages", [])
    evidence_chars = _usable_text_chars(pages)
    evidence_urls = _evidence_urls(pages)

    token_usage: dict[str, Any] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "model": getattr(deps.ollama, "model", "unknown"),
    }
    error_message: str | None = None
    used_fallback = False

    if evidence_chars < _MIN_EVIDENCE_CHARS:
        profile = {**_UNKNOWN_PROFILE, "evidence_urls": evidence_urls}
        used_fallback = True
        error_message = f"Insufficient crawl evidence ({evidence_chars} chars)"
        logger.warning(
            "Business analysis skipped due to weak crawl evidence",
            extra={"website_url": state.get("website_url"), "chars": evidence_chars},
        )
    else:
        page_context = build_downstream_context(crawl_data, pages)
        prompt = load_prompt(
            "business_analysis.txt",
            website_url=state["website_url"],
            crawl_summary=json.dumps(crawl_data.get("analysis", {}), indent=2),
            page_context=page_context or "No page content",
        )
        try:
            result, token_usage = await deps.ollama.generate_json(
                prompt,
                BusinessProfileOutput,
                num_predict=NUM_PREDICT_BUSINESS,
            )
            profile = result.model_dump()
            industry = (profile.get("industry") or "").strip()
            if not industry or industry.lower() in {"unknown", "n/a", "none", "general"}:
                profile = _profile_from_crawl(crawl_data, pages)
                used_fallback = True
            else:
                profile.setdefault("confidence", 0.7)
                profile["evidence_urls"] = evidence_urls
        except (json.JSONDecodeError, ValidationError, Exception) as exc:
            used_fallback = True
            error_message = str(exc)
            profile = _profile_from_crawl(crawl_data, pages)
            logger.warning(
                "Business analysis LLM failed; using crawl-derived profile",
                extra={"website_url": state.get("website_url"), "error": error_message},
            )

    state["business_profile"] = profile
    append_agent_log(
        state,
        agent_name=AgentName.BUSINESS_ANALYSIS,
        status=AgentExecutionStatus.COMPLETED,
        input_snapshot=build_input_snapshot(state, AgentName.BUSINESS_ANALYSIS),
        output={**profile, "fallback": used_fallback},
        error=error_message,
        token_usage=token_usage,
    )
    return state

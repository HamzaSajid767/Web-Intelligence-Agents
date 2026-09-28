"""Email writer agent node."""

import json

from pydantic import ValidationError

from app.agents.deps import AgentDependencies
from app.agents.nodes import append_agent_log, build_input_snapshot
from app.analysis.chatbot_analyzer import format_chatbot_gaps_for_prompt
from app.analysis.seo_analyzer import format_seo_gaps_for_prompt
from app.agents.state import AuditState
from app.ai.ollama_client import NUM_PREDICT_EMAIL
from app.ai.prompt_loader import load_prompt
from app.ai.schemas import EmailOutput
from app.core.constants import AgentExecutionStatus, AgentName, AuditStatus
from app.core.logging import get_logger

logger = get_logger(__name__)

_MIN_PROFILE_CONFIDENCE = 0.3


def _fallback_email_draft(state: AuditState) -> dict[str, str]:
    """Template outreach draft when the LLM is unavailable."""
    website_url = state.get("website_url") or "your website"
    profile = state.get("business_profile") or {}
    industry = profile.get("industry") or "your industry"
    if str(industry).lower() == "unknown":
        industry = "your industry"
    recommendations = state.get("recommendations") or []
    pain_points = state.get("pain_points") or []

    highlights: list[str] = []
    for rec in recommendations[:3]:
        fix = rec.get("fix") or rec.get("title") or rec.get("description")
        if fix:
            highlights.append(f"- {fix}")
    if not highlights:
        for point in pain_points[:3]:
            desc = point.get("description")
            if desc:
                highlights.append(f"- {desc}")
    if not highlights:
        highlights = ["- Improve on-page SEO clarity and contact accessibility"]

    bullet_block = "\n".join(highlights)
    return {
        "subject": f"Quick ideas to strengthen {website_url}",
        "body": (
            f"Hi,\n\n"
            f"I reviewed {website_url} and noticed a few opportunities that could help "
            f"visitors in {industry} convert more easily:\n\n"
            f"{bullet_block}\n\n"
            f"Happy to share a short walkthrough if useful.\n\n"
            f"Best regards"
        ),
    }


def _should_skip_email(state: AuditState) -> str | None:
    if state.get("status") == AuditStatus.INVALID_SITE.value:
        return "invalid_site"
    profile = state.get("business_profile") or {}
    industry = str(profile.get("industry") or "").strip().lower()
    confidence = float(profile.get("confidence") or 0.0)
    if industry in {"", "unknown", "n/a", "none"} or confidence < _MIN_PROFILE_CONFIDENCE:
        if not state.get("pain_points") and not state.get("recommendations"):
            return "low_confidence_profile"
    if not state.get("pain_points") and not state.get("recommendations"):
        return "no_findings"
    return None


async def email_handler(state: AuditState, deps: AgentDependencies) -> AuditState:
    """Generate personalized outreach email draft; skip on invalid/low-confidence audits."""
    skip_reason = _should_skip_email(state)
    if skip_reason:
        state["email_draft"] = {}
        append_agent_log(
            state,
            agent_name=AgentName.EMAIL_WRITER,
            status=AgentExecutionStatus.COMPLETED,
            input_snapshot=build_input_snapshot(state, AgentName.EMAIL_WRITER),
            output={"skipped": True, "reason": skip_reason},
        )
        return state

    top_pain_points = state.get("pain_points", [])[:3]
    top_seo_gaps = (state.get("seo_analysis") or {}).get("gaps", [])[:3]
    top_chatbot_gaps = (state.get("chatbot_analysis") or {}).get("gaps", [])[:3]
    top_recommendations = state.get("recommendations", [])[:3]
    seo_analysis = state.get("seo_analysis", {})
    chatbot_analysis = state.get("chatbot_analysis", {})
    prompt = load_prompt(
        "email_writer.txt",
        website_url=state["website_url"],
        business_profile=json.dumps(state.get("business_profile", {}), indent=2),
        pain_points=json.dumps(top_pain_points, indent=2),
        seo_gaps=format_seo_gaps_for_prompt({"summary": seo_analysis.get("summary", ""), "gaps": top_seo_gaps}),
        chatbot_gaps=format_chatbot_gaps_for_prompt(
            {
                "summary": chatbot_analysis.get("summary", ""),
                "gaps": top_chatbot_gaps,
                "efficiency": chatbot_analysis.get("efficiency", {}),
            }
        ),
        recommendations=json.dumps(top_recommendations, indent=2),
    )

    token_usage: dict = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "model": deps.ollama.model,
    }
    used_fallback = False
    error_message: str | None = None

    try:
        result, token_usage = await deps.ollama.generate_json(
            prompt,
            EmailOutput,
            num_predict=NUM_PREDICT_EMAIL,
        )
        email_draft = result.model_dump()
    except (json.JSONDecodeError, ValidationError, Exception) as exc:
        used_fallback = True
        error_message = str(exc)
        email_draft = _fallback_email_draft(state)
        token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model": deps.ollama.model,
            "fallback": True,
        }
        logger.warning(
            "Email writer LLM failed; using template draft",
            extra={"website_url": state.get("website_url"), "error": error_message},
        )

    state["email_draft"] = email_draft
    append_agent_log(
        state,
        agent_name=AgentName.EMAIL_WRITER,
        status=AgentExecutionStatus.COMPLETED,
        input_snapshot=build_input_snapshot(state, AgentName.EMAIL_WRITER),
        output={"subject": email_draft.get("subject"), "fallback": used_fallback},
        error=error_message,
        token_usage=token_usage,
    )
    return state

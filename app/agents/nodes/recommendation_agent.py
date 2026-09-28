"""Recommendation agent node."""

import json

from pydantic import ValidationError

from app.agents.deps import AgentDependencies
from app.agents.nodes import append_agent_log, build_input_snapshot
from app.analysis.chatbot_analyzer import format_chatbot_gaps_for_prompt
from app.analysis.seo_analyzer import (
    format_seo_gaps_for_prompt,
    pain_points_to_recommendations,
    select_top_pain_points,
)
from app.agents.state import AuditState
from app.ai.ollama_client import NUM_PREDICT_RECOMMENDATIONS
from app.ai.prompt_loader import load_prompt
from app.ai.schemas import RecommendationsOutput
from app.core.constants import AgentExecutionStatus, AgentName
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_PROMPT_PAIN_POINTS = 10
_MAX_RECOMMENDATIONS = 8

_GENERIC_FILLER = (
    "improve overall website",
    "enhance user experience",
    "optimize for better results",
    "general improvements",
)


def _ground_recommendations(
    recommendations: list[dict],
    pain_points: list[dict],
) -> list[dict]:
    """Keep only recommendations that reference surviving pain points; ban generic filler."""
    if not pain_points:
        return []

    check_index = {
        str(p.get("check")).lower(): p
        for p in pain_points
        if p.get("check")
    }
    descriptions = {
        str(p.get("description") or "").strip().lower()
        for p in pain_points
        if p.get("description")
    }

    grounded: list[dict] = []
    for rec in recommendations:
        problem = str(rec.get("problem") or "").strip()
        fix = str(rec.get("fix") or "").strip()
        blob = f"{problem} {fix}".lower()
        if any(filler in blob for filler in _GENERIC_FILLER) and len(problem) < 40:
            continue

        source_check = rec.get("source_check") or rec.get("check")
        matched = None
        if source_check and str(source_check).lower() in check_index:
            matched = check_index[str(source_check).lower()]
        else:
            for desc in descriptions:
                if desc and (desc in blob or blob in desc):
                    matched = next(
                        (p for p in pain_points if (p.get("description") or "").strip().lower() == desc),
                        None,
                    )
                    break
            if matched is None:
                # Token overlap: at least one distinctive word from a pain point description.
                for point in pain_points:
                    desc = str(point.get("description") or "")
                    tokens = [t for t in desc.lower().split() if len(t) > 4][:6]
                    if tokens and sum(1 for t in tokens if t in blob) >= max(2, len(tokens) // 2):
                        matched = point
                        break

        if matched is None:
            continue

        grounded.append(
            {
                **rec,
                "source_check": matched.get("check") or source_check,
                "source_finding": matched.get("description") or problem,
            }
        )
        if len(grounded) >= _MAX_RECOMMENDATIONS:
            break

    return grounded


async def recommendation_handler(state: AuditState, deps: AgentDependencies) -> AuditState:
    """Generate improvement recommendations grounded in pain points only."""
    pain_points = state.get("pain_points", [])
    if not pain_points:
        state["recommendations"] = []
        append_agent_log(
            state,
            agent_name=AgentName.RECOMMENDATIONS,
            status=AgentExecutionStatus.COMPLETED,
            input_snapshot=build_input_snapshot(state, AgentName.RECOMMENDATIONS),
            output={"count": 0, "fallback": False, "reason": "no_pain_points"},
        )
        return state

    top_pain_points = select_top_pain_points(pain_points, limit=_MAX_PROMPT_PAIN_POINTS)
    seo_analysis = state.get("seo_analysis", {})
    chatbot_analysis = state.get("chatbot_analysis", {})
    prompt = load_prompt(
        "recommendations.txt",
        website_url=state["website_url"],
        business_profile=json.dumps(state.get("business_profile", {}), indent=2),
        pain_points=json.dumps(top_pain_points, indent=2),
        seo_gaps=format_seo_gaps_for_prompt(seo_analysis),
        chatbot_gaps=format_chatbot_gaps_for_prompt(chatbot_analysis),
        scores=json.dumps(state.get("scores", {}), indent=2),
        max_recommendations=_MAX_RECOMMENDATIONS,
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
            RecommendationsOutput,
            num_predict=NUM_PREDICT_RECOMMENDATIONS,
        )
        recommendations = [item.model_dump() for item in result.recommendations]
    except (json.JSONDecodeError, ValidationError, Exception) as exc:
        error_message = str(exc)
        logger.warning(
            "LLM recommendations failed; using rule-based fallback",
            extra={"website_url": state.get("website_url"), "error": error_message},
        )
        recommendations = pain_points_to_recommendations(pain_points, limit=_MAX_RECOMMENDATIONS)
        token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "model": deps.ollama.model,
            "fallback": True,
        }
        used_fallback = True

    recommendations = _ground_recommendations(recommendations, pain_points)
    if not recommendations:
        recommendations = pain_points_to_recommendations(pain_points, limit=_MAX_RECOMMENDATIONS)
        used_fallback = True

    state["recommendations"] = recommendations[:_MAX_RECOMMENDATIONS]
    append_agent_log(
        state,
        agent_name=AgentName.RECOMMENDATIONS,
        status=AgentExecutionStatus.COMPLETED,
        input_snapshot=build_input_snapshot(state, AgentName.RECOMMENDATIONS),
        output={"count": len(state["recommendations"]), "fallback": used_fallback},
        error=error_message,
        token_usage=token_usage,
    )
    return state

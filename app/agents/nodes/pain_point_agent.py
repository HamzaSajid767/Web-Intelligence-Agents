"""Pain point identification agent node."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.agents.deps import AgentDependencies
from app.agents.nodes import append_agent_log, build_input_snapshot
from app.agents.state import AuditState
from app.ai.ollama_client import NUM_PREDICT_PAIN_POINTS
from app.ai.prompt_loader import load_prompt
from app.ai.schemas import PainPointsBundleOutput, PainPointsOutput
from app.analysis.chatbot_analyzer import (
    analyze_chatbot,
    chatbot_gaps_to_pain_points,
    format_chatbot_gaps_for_prompt,
    merge_chatbot_assessment,
)
from app.analysis.seo_analyzer import (
    analyze_seo_gaps,
    format_seo_gaps_for_prompt,
    gaps_to_pain_points,
    merge_pain_points,
)
from app.core.constants import AgentExecutionStatus, AgentName
from app.core.logging import get_logger
from app.crawler.page_context import build_downstream_context

logger = get_logger(__name__)

_SIMPLE_SHAPE = (
    '{"pain_points":[{"category":"seo","severity":"high",'
    '"description":"...","evidence":{"page_url":"https://..."}}]}'
)
_BUNDLE_SHAPE = (
    '{"pain_points":[...],'
    '"design_rating":"fair","response_readiness":"poor",'
    '"design_notes":"...","response_notes":"...","chatbot_gaps":[]}'
)


async def pain_point_handler(state: AuditState, deps: AgentDependencies) -> AuditState:
    """Identify website pain points; fall back to rule-based gaps if LLM JSON fails."""
    crawl_data = state.get("crawl_data", {})
    pages = crawl_data.get("pages", [])

    seo_analysis = analyze_seo_gaps(pages)
    chatbot_analysis = analyze_chatbot(pages)
    structured_context = build_downstream_context(crawl_data, pages)
    chatbot_detected = bool(chatbot_analysis.get("detected"))

    state["seo_analysis"] = seo_analysis
    state["chatbot_analysis"] = chatbot_analysis

    rule_pain_points = gaps_to_pain_points(seo_analysis["gaps"]) + chatbot_gaps_to_pain_points(
        chatbot_analysis["gaps"]
    )

    if chatbot_detected:
        schema: type = PainPointsBundleOutput
        chatbot_instructions = (
            "Also assess the chatbot from crawl-visible cues and fill "
            "design_rating, response_readiness, design_notes, response_notes, chatbot_gaps."
        )
        json_shape = _BUNDLE_SHAPE
    else:
        schema = PainPointsOutput
        chatbot_instructions = (
            "Do not invent chatbot assessment fields. Return only pain_points."
        )
        json_shape = _SIMPLE_SHAPE

    prompt = load_prompt(
        "pain_points.txt",
        website_url=state["website_url"],
        business_profile=json.dumps(state.get("business_profile", {}), indent=2),
        crawl_summary=json.dumps(crawl_data.get("analysis", {}), indent=2),
        seo_gaps=format_seo_gaps_for_prompt(seo_analysis),
        chatbot_gaps=format_chatbot_gaps_for_prompt(chatbot_analysis),
        chatbot_detected=str(chatbot_detected),
        structured_context=structured_context or "No structured context",
        chatbot_instructions=chatbot_instructions,
        json_shape=json_shape,
    )

    token_usage: dict[str, Any] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "model": getattr(deps.ollama, "model", "unknown"),
    }
    llm_pain_points: list[dict[str, Any]] = []
    used_fallback = False
    chatbot_assessed = False
    log_status = AgentExecutionStatus.COMPLETED
    error_message: str | None = None

    try:
        result, token_usage = await deps.ollama.generate_json(
            prompt,
            schema,
            num_predict=NUM_PREDICT_PAIN_POINTS,
        )
        if isinstance(result, PainPointsBundleOutput):
            if result.design_rating and result.response_readiness:
                assessment = {
                    "design_rating": result.design_rating,
                    "response_readiness": result.response_readiness,
                    "design_notes": result.design_notes,
                    "response_notes": result.response_notes,
                    "gaps": [
                        {
                            **gap.model_dump(),
                            "evidence": {
                                "providers": chatbot_analysis.get("providers", []),
                                "coverage_pct": chatbot_analysis.get("coverage_pct"),
                            },
                        }
                        for gap in result.chatbot_gaps
                    ],
                }
                chatbot_analysis = merge_chatbot_assessment(chatbot_analysis, assessment)
                state["chatbot_analysis"] = chatbot_analysis
                chatbot_assessed = True
            llm_pain_points = [item.model_dump() for item in result.pain_points]
        else:
            llm_pain_points = [item.model_dump() for item in result.pain_points]
    except (json.JSONDecodeError, ValidationError, Exception) as exc:
        used_fallback = True
        log_status = AgentExecutionStatus.FAILED
        error_message = str(exc)
        logger.warning(
            "Pain points LLM failed; using rule-based gaps only",
            extra={"website_url": state.get("website_url"), "error": error_message},
        )

    pain_points = merge_pain_points(rule_pain_points, llm_pain_points)
    if not pain_points and rule_pain_points:
        pain_points = rule_pain_points
    if chatbot_analysis.get("detected"):
        pain_points = [
            point
            for point in pain_points
            if point.get("check") != "missing_chatbot"
            and "missing chatbot" not in (point.get("description") or "").lower()
            and "no live chat" not in (point.get("description") or "").lower()
        ]
    state["pain_points"] = pain_points

    append_agent_log(
        state,
        agent_name=AgentName.PAIN_POINTS,
        status=log_status if not used_fallback else AgentExecutionStatus.COMPLETED,
        input_snapshot=build_input_snapshot(state, AgentName.PAIN_POINTS),
        output={
            "count": len(pain_points),
            "seo_gap_count": len(seo_analysis["gaps"]),
            "chatbot_gap_count": len(chatbot_analysis["gaps"]),
            "chatbot_detected": chatbot_detected,
            "rule_based_count": len(rule_pain_points),
            "llm_count": len(llm_pain_points),
            "fallback": used_fallback,
            "chatbot_assessed_in_same_call": chatbot_assessed,
        },
        error=error_message,
        token_usage=token_usage,
    )
    return state

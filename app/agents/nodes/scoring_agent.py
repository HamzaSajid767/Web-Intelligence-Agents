"""Impact scoring agent node.

Scoring formula (documented per productionization plan):
- Each pain point contributes its severity weight (critical=100, high=75, medium=50, low=25).
- Category bucket score = mean of contributing weights in that bucket (not max).
- Inactive buckets (no pain points) stay 0 and are omitted from Overall.
- Overall = mean of active bucket scores only.
"""

from app.agents.deps import AgentDependencies
from app.agents.nodes import append_agent_log, build_input_snapshot
from app.agents.state import AuditState
from app.core.constants import AgentExecutionStatus, AgentName

SEVERITY_WEIGHTS = {
    "critical": 100,
    "high": 75,
    "medium": 50,
    "low": 25,
}

CATEGORY_BUCKETS = ("SEO", "Trust", "Conversion", "Content")

CATEGORY_MAP = {
    "seo": "SEO",
    "trust": "Trust",
    "conversion": "Conversion",
    "content": "Content",
}


async def scoring_handler(state: AuditState, deps: AgentDependencies) -> AuditState:
    """Score opportunities using evidence-weighted SEO/Trust/Conversion/Content averages."""
    pain_points = state.get("pain_points", [])
    bucket_totals: dict[str, list[float]] = {bucket: [] for bucket in CATEGORY_BUCKETS}

    for point in pain_points:
        severity = point.get("severity", "medium").lower()
        weight = float(SEVERITY_WEIGHTS.get(severity, 50))
        evidence = point.get("evidence") or {}
        # Slight down-weight when no page evidence is attached.
        if not evidence.get("page_url") and not point.get("check"):
            weight *= 0.85
        raw_category = point.get("category", "content").lower()
        bucket = CATEGORY_MAP.get(raw_category, "Content")
        bucket_totals[bucket].append(weight)
        point["score"] = weight

    bucket_scores = {
        bucket: round(sum(values) / len(values), 2) if values else 0.0
        for bucket, values in bucket_totals.items()
    }

    active_scores = [score for score in bucket_scores.values() if score > 0]
    overall = round(sum(active_scores) / len(active_scores), 2) if active_scores else 0.0

    scores = {
        "SEO": bucket_scores["SEO"],
        "Trust": bucket_scores["Trust"],
        "Conversion": bucket_scores["Conversion"],
        "Content": bucket_scores["Content"],
        "Overall": overall,
        "pain_point_count": len(pain_points),
        "active_buckets": [b for b, s in bucket_scores.items() if s > 0],
    }
    state["pain_points"] = pain_points
    state["scores"] = scores
    append_agent_log(
        state,
        agent_name=AgentName.IMPACT_SCORING,
        status=AgentExecutionStatus.COMPLETED,
        input_snapshot=build_input_snapshot(state, AgentName.IMPACT_SCORING),
        output=scores,
    )
    return state

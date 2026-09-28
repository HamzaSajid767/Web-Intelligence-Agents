"""Human review node — marks audit awaiting manual email send."""

from app.agents.deps import AgentDependencies
from app.agents.nodes import append_agent_log, build_input_snapshot
from app.agents.state import AuditState
from app.core.constants import AgentExecutionStatus, AgentName, AuditStatus


async def reviewer_handler(state: AuditState, deps: AgentDependencies) -> AuditState:
    """Prepare audit for human review — no automatic email sending."""
    state["status"] = AuditStatus.AWAITING_REVIEW.value
    append_agent_log(
        state,
        agent_name=AgentName.HUMAN_REVIEW,
        status=AgentExecutionStatus.COMPLETED,
        input_snapshot=build_input_snapshot(state, AgentName.HUMAN_REVIEW),
        output={"review_status": "awaiting_human_review"},
    )
    return state

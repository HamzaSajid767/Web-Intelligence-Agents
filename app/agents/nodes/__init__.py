"""Agent node utilities."""

import time
from typing import Any, Callable, Coroutine

from app.agents.state import AuditState
from app.core.constants import AgentExecutionStatus, AgentName


def build_input_snapshot(state: AuditState, agent_name: AgentName) -> dict[str, Any]:
    """Build minimal input snapshot for agent execution logging."""
    snapshot: dict[str, Any] = {
        "agent": agent_name.value,
        "website_url": state.get("website_url"),
    }
    if agent_name == AgentName.CRAWLER:
        snapshot["audit_id"] = state.get("audit_id")
    elif agent_name == AgentName.BUSINESS_ANALYSIS:
        snapshot["pages_crawled"] = state.get("crawl_data", {}).get("total_pages", 0)
    elif agent_name == AgentName.PAIN_POINTS:
        snapshot["has_business_profile"] = bool(state.get("business_profile"))
    elif agent_name == AgentName.IMPACT_SCORING:
        snapshot["pain_point_count"] = len(state.get("pain_points", []))
    elif agent_name == AgentName.RECOMMENDATIONS:
        snapshot["scores"] = state.get("scores", {})
    elif agent_name in (AgentName.EMAIL_WRITER, AgentName.HUMAN_REVIEW):
        snapshot["recommendation_count"] = len(state.get("recommendations", []))
    return snapshot


def append_agent_log(
    state: AuditState,
    *,
    agent_name: AgentName,
    status: AgentExecutionStatus,
    duration_ms: int | None = None,
    input_snapshot: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    error: str | None = None,
    token_usage: dict[str, Any] | None = None,
) -> None:
    """Append execution log entry to state."""
    logs = list(state.get("agent_logs", []))
    logs.append(
        {
            "agent_name": agent_name.value,
            "status": status.value,
            "duration_ms": duration_ms,
            "input_snapshot": input_snapshot or build_input_snapshot(state, agent_name),
            "output": output or {},
            "error": error,
            "token_usage": token_usage or {"prompt_tokens": 0, "completion_tokens": 0},
        }
    )
    state["agent_logs"] = logs


def make_node_runner(
    agent_name: AgentName,
    handler: Callable[[AuditState, Any], Coroutine[Any, Any, AuditState]],
    deps: Any,
) -> Callable[[AuditState], Coroutine[Any, Any, AuditState]]:
    """Wrap agent handler with timing and error logging."""

    async def node(state: AuditState) -> AuditState:
        state = dict(state)
        state["current_agent"] = agent_name.value
        start = time.perf_counter()
        try:
            result = await handler(state, deps)
            duration_ms = int((time.perf_counter() - start) * 1000)
            for log in result.get("agent_logs", []):
                if log.get("agent_name") == agent_name.value:
                    if log.get("duration_ms") is None:
                        log["duration_ms"] = duration_ms
                    return result
            append_agent_log(
                result,
                agent_name=agent_name,
                status=AgentExecutionStatus.COMPLETED,
                duration_ms=duration_ms,
                input_snapshot=build_input_snapshot(state, agent_name),
            )
            return result
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            append_agent_log(
                state,
                agent_name=agent_name,
                status=AgentExecutionStatus.FAILED,
                duration_ms=duration_ms,
                input_snapshot=build_input_snapshot(state, agent_name),
                error=str(exc),
            )
            state["error"] = str(exc)
            state["status"] = "failed"
            raise

    return node

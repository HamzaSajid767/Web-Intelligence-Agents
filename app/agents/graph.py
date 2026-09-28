"""LangGraph audit pipeline graph definition."""

from langgraph.graph import END, START, StateGraph

from app.agents.deps import AgentDependencies
from app.agents.nodes import make_node_runner
from app.agents.nodes.business_analysis_agent import business_analysis_handler
from app.agents.nodes.crawler_agent import crawler_handler
from app.agents.nodes.email_agent import email_handler
from app.agents.nodes.pain_point_agent import pain_point_handler
from app.agents.nodes.recommendation_agent import recommendation_handler
from app.agents.nodes.reviewer_agent import reviewer_handler
from app.agents.nodes.scoring_agent import scoring_handler
from app.agents.state import AuditState
from app.ai.ollama_client import OllamaClient
from app.core.constants import AgentName, AuditStatus
from app.crawler.crawler_service import CrawlerService
from app.vector.noop_retriever import NoOpVectorRetriever


def _route_after_crawler(state: AuditState) -> str:
    """Continue analysis only for valid sites."""
    if state.get("status") == AuditStatus.INVALID_SITE.value:
        return "invalid"
    validity = (state.get("crawl_data") or {}).get("site_validity") or {}
    if validity.get("is_valid") is False:
        return "invalid"
    return "valid"


def build_audit_graph(deps: AgentDependencies | None = None):
    """Build and compile the audit LangGraph workflow."""
    if deps is None:
        deps = AgentDependencies(
            ollama=OllamaClient(),
            crawler=CrawlerService(),
            vector_retriever=NoOpVectorRetriever(),
        )

    graph = StateGraph(AuditState)

    graph.add_node(
        AgentName.CRAWLER.value,
        make_node_runner(AgentName.CRAWLER, crawler_handler, deps),
    )
    graph.add_node(
        AgentName.BUSINESS_ANALYSIS.value,
        make_node_runner(AgentName.BUSINESS_ANALYSIS, business_analysis_handler, deps),
    )
    graph.add_node(
        AgentName.PAIN_POINTS.value,
        make_node_runner(AgentName.PAIN_POINTS, pain_point_handler, deps),
    )
    graph.add_node(
        AgentName.IMPACT_SCORING.value,
        make_node_runner(AgentName.IMPACT_SCORING, scoring_handler, deps),
    )
    graph.add_node(
        AgentName.RECOMMENDATIONS.value,
        make_node_runner(AgentName.RECOMMENDATIONS, recommendation_handler, deps),
    )
    graph.add_node(
        AgentName.EMAIL_WRITER.value,
        make_node_runner(AgentName.EMAIL_WRITER, email_handler, deps),
    )
    graph.add_node(
        AgentName.HUMAN_REVIEW.value,
        make_node_runner(AgentName.HUMAN_REVIEW, reviewer_handler, deps),
    )

    graph.add_edge(START, AgentName.CRAWLER.value)
    graph.add_conditional_edges(
        AgentName.CRAWLER.value,
        _route_after_crawler,
        {
            "valid": AgentName.BUSINESS_ANALYSIS.value,
            "invalid": END,
        },
    )
    graph.add_edge(AgentName.BUSINESS_ANALYSIS.value, AgentName.PAIN_POINTS.value)
    graph.add_edge(AgentName.PAIN_POINTS.value, AgentName.IMPACT_SCORING.value)
    graph.add_edge(AgentName.IMPACT_SCORING.value, AgentName.RECOMMENDATIONS.value)
    graph.add_edge(AgentName.RECOMMENDATIONS.value, AgentName.EMAIL_WRITER.value)
    graph.add_edge(AgentName.EMAIL_WRITER.value, AgentName.HUMAN_REVIEW.value)
    graph.add_edge(AgentName.HUMAN_REVIEW.value, END)

    return graph.compile()

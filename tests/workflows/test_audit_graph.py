"""LangGraph workflow tests."""

import pytest

from app.agents.graph import build_audit_graph


@pytest.mark.asyncio
async def test_audit_graph_full_run(sample_audit_state, agent_deps):
    """Full graph should run all nodes and reach awaiting_review status."""
    graph = build_audit_graph(agent_deps)
    result = await graph.ainvoke(sample_audit_state)

    assert result["crawl_data"]["total_pages"] >= 1
    assert result["business_profile"]
    assert result.get("seo_analysis")
    assert len(result["seo_analysis"].get("gaps", [])) >= 1
    assert result.get("chatbot_analysis")
    assert any(gap["check"] == "missing_chatbot" for gap in result["chatbot_analysis"].get("gaps", []))
    assert len(result["pain_points"]) >= 1
    assert any(point["category"] == "seo" for point in result["pain_points"])
    assert any(point["category"] == "conversion" for point in result["pain_points"])
    assert "SEO" in result["scores"]
    assert result["scores"]["SEO"] > 0
    assert "Overall" in result["scores"]
    assert len(result["recommendations"]) >= 1
    assert result["email_draft"]["subject"]
    assert result["status"] == "awaiting_review"
    assert len(result["agent_logs"]) >= 6

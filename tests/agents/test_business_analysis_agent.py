"""Business analysis agent unit tests."""

import pytest

from app.agents.nodes.business_analysis_agent import business_analysis_handler


@pytest.mark.asyncio
async def test_business_analysis_agent(sample_audit_state, agent_deps):
    """Business analysis agent should populate business_profile."""
    sample_audit_state["crawl_data"] = {
        "pages": [
            {
                "url": "https://example.com",
                "title": "Home",
                "clean_text": (
                    "Welcome to Acme Web Development. We build custom websites and apps "
                    "for growing businesses. Our team delivers reliable digital products "
                    "with clear pricing and ongoing support for SMBs nationwide. "
                    "Visit our services page to learn how we help clients ship faster."
                ),
                "success": True,
            }
        ],
        "analysis": {"summary": "A business site"},
    }

    result = await business_analysis_handler(sample_audit_state, agent_deps)

    assert result["business_profile"]["industry"] == "Technology"
    assert "Web Development" in result["business_profile"]["services"]
    assert result["business_profile"]["confidence"] >= 0.7


@pytest.mark.asyncio
async def test_business_analysis_refuses_weak_crawl(sample_audit_state, agent_deps):
    """Weak crawl evidence must not invent an industry."""
    sample_audit_state["crawl_data"] = {
        "pages": [{"url": "https://example.com", "title": "Home", "clean_text": "Hi", "success": True}],
        "analysis": {},
    }

    result = await business_analysis_handler(sample_audit_state, agent_deps)

    assert result["business_profile"]["industry"] == "Unknown"
    assert result["business_profile"]["confidence"] <= 0.2

"""Scoring agent unit tests."""

import pytest

from app.agents.nodes.scoring_agent import scoring_handler


@pytest.mark.asyncio
async def test_scoring_agent_calculates_fixed_categories(sample_audit_state, agent_deps):
    """Scoring agent should compute fixed SEO/Trust/Conversion/Content scores."""
    sample_audit_state["pain_points"] = [
        {
            "category": "seo",
            "severity": "high",
            "description": "Missing titles",
            "check": "missing_title",
            "evidence": {"page_url": "https://example.com"},
        },
        {
            "category": "trust",
            "severity": "medium",
            "description": "No testimonials",
            "check": "missing_testimonials",
            "evidence": {"page_url": "https://example.com"},
        },
        {
            "category": "conversion",
            "severity": "critical",
            "description": "Weak CTA",
            "check": "weak_cta",
            "evidence": {"page_url": "https://example.com"},
        },
    ]

    result = await scoring_handler(sample_audit_state, agent_deps)

    assert "scores" in result
    # Category scores are averages of severity weights; inactive Content stays 0.
    assert result["scores"]["SEO"] == 75
    assert result["scores"]["Trust"] == 50
    assert result["scores"]["Conversion"] == 100
    assert result["scores"]["Content"] == 0
    assert result["scores"]["Overall"] == round((75 + 50 + 100) / 3, 2)
    assert "Content" not in result["scores"]["active_buckets"]
    assert result["scores"]["pain_point_count"] == 3


@pytest.mark.asyncio
async def test_scoring_agent_empty_pain_points(sample_audit_state, agent_deps):
    """Scoring agent handles empty pain points gracefully."""
    result = await scoring_handler(sample_audit_state, agent_deps)
    assert result["scores"]["Overall"] == 0
    assert result["scores"]["SEO"] == 0

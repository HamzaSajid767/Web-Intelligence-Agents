"""Pain point agent integration tests."""

import json

import pytest

from app.agents.nodes.pain_point_agent import pain_point_handler


@pytest.mark.asyncio
async def test_pain_point_agent_includes_rule_based_seo_gaps(sample_audit_state, agent_deps):
    """Pain point agent should add SEO gaps even when LLM returns empty list."""
    sample_audit_state["crawl_data"] = {
        "pages": [
            {
                "url": "https://example.com/",
                "title": "Short",
                "metadata": {},
                "headings": [],
                "clean_text": "Brief",
                "image_stats": {"total_images": 1, "images_with_alt": 0, "images_without_alt": 1},
            }
        ],
        "analysis": {"summary": "Test site"},
    }

    agent_deps.ollama.generate_json = _empty_pain_points_response

    result = await pain_point_handler(sample_audit_state, agent_deps)

    assert result.get("seo_analysis")
    assert len(result["seo_analysis"]["gaps"]) >= 1
    assert len(result["pain_points"]) >= 1
    assert any(point["category"] == "seo" for point in result["pain_points"])
    assert any(point.get("source") == "seo_analyzer" for point in result["pain_points"])


@pytest.mark.asyncio
async def test_pain_point_agent_includes_rule_based_chatbot_gaps(sample_audit_state, agent_deps):
    """Pain point agent should add chatbot gaps when no widget is detected."""
    sample_audit_state["crawl_data"] = {
        "pages": [
            {
                "url": "https://example.com/",
                "title": "Home",
                "metadata": {"description": "Test"},
                "headings": [{"level": "h1", "text": "Home"}],
                "clean_text": (
                    "Welcome to our website with enough content for analysis. "
                    "We describe services, team expertise, and contact options for visitors "
                    "looking for professional help with their business operations."
                ),
                "raw_html": "<html><body><h1>Home</h1><p>Welcome</p></body></html>",
            }
        ],
        "analysis": {"summary": "Test site"},
    }

    agent_deps.ollama.generate_json = _empty_pain_points_response

    result = await pain_point_handler(sample_audit_state, agent_deps)

    assert result.get("chatbot_analysis")
    assert result["chatbot_analysis"]["detected"] is False
    assert any(gap["check"] == "missing_chatbot" for gap in result["chatbot_analysis"]["gaps"])
    assert any(point["category"] == "conversion" for point in result["pain_points"])
    assert any(point.get("source") == "chatbot_analyzer" for point in result["pain_points"])


async def _empty_pain_points_response(prompt: str, schema: type, **kwargs):
    from app.ai.schemas import PainPointsBundleOutput, PainPointsOutput

    token_usage = {"prompt_tokens": 10, "completion_tokens": 5, "model": "mock"}
    if schema is PainPointsBundleOutput:
        return PainPointsBundleOutput(pain_points=[]), token_usage
    return PainPointsOutput(pain_points=[]), token_usage


@pytest.mark.asyncio
async def test_pain_point_agent_falls_back_on_llm_json_error(sample_audit_state, agent_deps):
    """Rule-based gaps should still populate when LLM returns invalid JSON."""
    sample_audit_state["crawl_data"] = {
        "pages": [
            {
                "url": "https://example.com/",
                "title": "Short",
                "metadata": {},
                "headings": [],
                "clean_text": "Brief",
                "image_stats": {"total_images": 1, "images_with_alt": 0, "images_without_alt": 1},
            }
        ],
        "analysis": {"summary": "Test site"},
    }

    async def _raise(*_args, **_kwargs):
        raise json.JSONDecodeError("Expecting value", "", 0)

    agent_deps.ollama.generate_json = _raise
    result = await pain_point_handler(sample_audit_state, agent_deps)

    assert len(result["pain_points"]) >= 1
    assert any(point.get("source") == "seo_analyzer" for point in result["pain_points"])

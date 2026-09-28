"""Recommendation agent soft-fail tests."""

import httpx
import pytest

from app.agents.nodes.recommendation_agent import recommendation_handler


@pytest.mark.asyncio
async def test_recommendation_falls_back_on_ollama_http_error(sample_audit_state, agent_deps):
    sample_audit_state["pain_points"] = [
        {
            "category": "seo",
            "severity": "high",
            "description": "Missing meta description",
            "evidence": {},
            "score": 75,
        }
    ]

    async def _raise(*_args, **_kwargs):
        raise httpx.HTTPStatusError(
            "Ollama API unavailable",
            request=httpx.Request("POST", "https://example.com/api/generate"),
            response=httpx.Response(404),
        )

    agent_deps.ollama.generate_json = _raise
    result = await recommendation_handler(sample_audit_state, agent_deps)

    assert result["recommendations"]
    assert result["agent_logs"][-1]["output"]["fallback"] is True


def test_ground_recommendations_requires_pain_points():
    from app.agents.nodes.recommendation_agent import _ground_recommendations

    pain = [
        {
            "check": "missing_meta_description",
            "description": "Missing meta description",
            "category": "seo",
            "severity": "high",
        }
    ]
    assert (
        _ground_recommendations(
            [{"problem": "Totally unrelated generic advice", "fix": "Do stuff", "priority": "low"}],
            pain,
        )
        == []
    )
    grounded = _ground_recommendations(
        [
            {
                "problem": "Missing meta description",
                "fix": "Write one",
                "priority": "high",
                "source_check": "missing_meta_description",
            }
        ],
        pain,
    )
    assert len(grounded) == 1
    assert grounded[0]["source_check"] == "missing_meta_description"

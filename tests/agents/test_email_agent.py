"""Email writer agent soft-fail tests."""

import httpx
import pytest

from app.agents.nodes.email_agent import email_handler


@pytest.mark.asyncio
async def test_email_falls_back_on_ollama_http_error(sample_audit_state, agent_deps):
    sample_audit_state["business_profile"] = {
        "industry": "Accounting",
        "confidence": 0.8,
    }
    sample_audit_state["pain_points"] = [
        {
            "category": "seo",
            "severity": "high",
            "description": "Weak contact page",
            "check": "weak_contact",
            "evidence": {"page_url": "https://example.com/contact"},
        }
    ]
    sample_audit_state["recommendations"] = [
        {
            "problem": "Weak contact page",
            "fix": "Add phone and email in the footer",
            "expected_benefit": "More inbound leads",
            "priority": "high",
            "source_check": "weak_contact",
        }
    ]

    async def _raise(*_args, **_kwargs):
        raise httpx.HTTPStatusError(
            "Ollama API unavailable",
            request=httpx.Request("POST", "https://example.com/api/generate"),
            response=httpx.Response(404),
        )

    agent_deps.ollama.generate_json = _raise
    result = await email_handler(sample_audit_state, agent_deps)

    draft = result["email_draft"]
    assert draft["subject"]
    assert draft["body"]
    assert "Add phone and email" in draft["body"]
    assert result["agent_logs"][-1]["output"]["fallback"] is True

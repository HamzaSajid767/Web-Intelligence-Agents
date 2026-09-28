#!/usr/bin/env python
"""Run a complete audit workflow from the command line.

Usage:
    uv run python scripts/test_audit.py https://example.com

Requires MongoDB and Ollama (llama3.2:3b) running locally.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on path when run as script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.services.audit_runner import AuditRunner


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print("=" * 60)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/test_audit.py <website_url>")
        return 1

    settings = get_settings()
    setup_logging(settings.log_level)

    try:
        result = AuditRunner().run(sys.argv[1])
        final_state = result.final_state

        print(f"Starting audit for: {result.website_url}")
        print(f"Audit ID: {result.audit_id}")

        _print_section("RESULT")
        print(f"Status: {final_state.get('status', 'unknown')}")

        crawl_data = final_state.get("crawl_data", {})
        print(f"Pages crawled: {crawl_data.get('total_pages', 0)}")
        for page in crawl_data.get("pages", [])[:5]:
            print(f"  - {page.get('title') or page.get('url')}")

        profile = final_state.get("business_profile", {})
        _print_section("BUSINESS PROFILE")
        print(f"Industry: {profile.get('industry')}")
        print(f"Services: {profile.get('services')}")
        print(f"Target audience: {profile.get('target_audience')}")
        print(f"Value proposition: {profile.get('value_proposition')}")

        scores = final_state.get("scores", {})
        _print_section("SCORES")
        print(
            f"SEO={scores.get('SEO', 0)} Trust={scores.get('Trust', 0)} "
            f"Conversion={scores.get('Conversion', 0)} Content={scores.get('Content', 0)} "
            f"Overall={scores.get('Overall', 0)}"
        )

        seo_analysis = final_state.get("seo_analysis", {})
        seo_gaps = seo_analysis.get("gaps", [])
        _print_section(f"SEO GAPS ({len(seo_gaps)})")
        if seo_analysis.get("summary"):
            print(seo_analysis["summary"])
        if seo_analysis.get("score") is not None:
            print(f"SEO health score: {seo_analysis['score']}/100")
        for gap in seo_gaps:
            page_url = gap.get("page_url") or "site-wide"
            print(f"- [{gap.get('severity')}] {gap.get('description')}")
            print(f"  Page: {page_url}")

        chatbot_analysis = final_state.get("chatbot_analysis", {})
        chatbot_gaps = chatbot_analysis.get("gaps", [])
        _print_section("CHATBOT ANALYSIS")
        detected = chatbot_analysis.get("detected", False)
        print(f"Detected: {'Yes' if detected else 'No'}")
        if chatbot_analysis.get("providers"):
            print(f"Providers: {', '.join(chatbot_analysis['providers'])}")
        if chatbot_analysis.get("summary"):
            print(chatbot_analysis["summary"])
        if detected and chatbot_analysis.get("coverage_pct") is not None:
            pages_with = len(chatbot_analysis.get("pages_with_chatbot", []))
            total_pages = crawl_data.get("total_pages", pages_with)
            print(f"Coverage: {pages_with}/{total_pages} pages ({chatbot_analysis['coverage_pct']:.0f}%)")
        efficiency = chatbot_analysis.get("efficiency") or {}
        if efficiency.get("design_rating"):
            print(f"Design: {efficiency['design_rating']} — {efficiency.get('design_notes', '')}")
        if efficiency.get("response_readiness"):
            print(
                f"Response readiness: {efficiency['response_readiness']} — "
                f"{efficiency.get('response_notes', '')}"
            )
        if chatbot_analysis.get("score") is not None and detected:
            print(f"Chatbot effectiveness score: {chatbot_analysis['score']}/100")
        for gap in chatbot_gaps:
            page_url = gap.get("page_url") or "site-wide"
            print(f"- [{gap.get('severity')}] {gap.get('description')}")
            print(f"  Page: {page_url}")

        pain_points = final_state.get("pain_points", [])
        _print_section(f"PAIN POINTS ({len(pain_points)})")
        for point in pain_points:
            print(f"- [{point.get('category')}/{point.get('severity')}] {point.get('description')}")

        recommendations = final_state.get("recommendations", [])
        _print_section(f"RECOMMENDATIONS ({len(recommendations)})")
        for rec in recommendations:
            print(f"- [{rec.get('priority')}] {rec.get('problem')}")
            print(f"  Fix: {rec.get('fix')}")
            print(f"  Benefit: {rec.get('expected_benefit')}")

        email = final_state.get("email_draft", {})
        _print_section("GENERATED EMAIL")
        print(f"Subject: {email.get('subject')}")
        print(f"Body:\n{email.get('body')}")

        if final_state.get("error"):
            print(f"\nError: {final_state['error']}")
            return 1

        return 0
    except Exception as exc:
        print(f"\nAudit failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

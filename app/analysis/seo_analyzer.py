"""Rule-based on-page SEO gap detection from crawled page data."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

_THIN_CONTENT_THRESHOLD = 100
_TITLE_MIN_LENGTH = 30
_TITLE_MAX_LENGTH = 60
_META_DESC_MIN_LENGTH = 70
_META_DESC_MAX_LENGTH = 160

_SEVERITY_WEIGHTS = {
    "critical": 100,
    "high": 75,
    "medium": 50,
    "low": 25,
}


def _safe_text(value: Any) -> str:
    """Coerce nullable crawl fields (e.g. Webclaw null JSON) to a stripped string."""
    if value is None:
        return ""
    return str(value).strip()


def format_seo_gaps_for_prompt(seo_analysis: dict) -> str:
    """Format SEO analysis gaps for LLM prompt injection."""
    gaps = seo_analysis.get("gaps", [])
    if not gaps:
        return "None detected"
    lines = [seo_analysis.get("summary", "")]
    for gap in gaps[:20]:
        page_url = gap.get("page_url") or "site-wide"
        lines.append(f"- [{gap.get('severity')}] {gap.get('description')} ({page_url})")
    return "\n".join(lines)


def analyze_seo_gaps(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze crawled pages and return structured SEO gap findings."""
    gaps: list[dict[str, Any]] = []

    for page in pages:
        gaps.extend(_check_page(page))

    gaps.extend(_check_cross_page(pages))

    summary = _build_summary(gaps, len(pages))
    score = _compute_health_score(gaps)

    return {
        "summary": summary,
        "score": score,
        "gaps": gaps,
    }


def gaps_to_pain_points(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert SEO gaps into pain-point dicts for the scoring pipeline."""
    pain_points: list[dict[str, Any]] = []
    for gap in gaps:
        evidence = dict(gap.get("evidence") or {})
        if gap.get("page_url"):
            evidence.setdefault("page_url", gap["page_url"])
        pain_points.append(
            {
                "category": "seo",
                "severity": gap.get("severity", "medium"),
                "description": gap.get("description", ""),
                "evidence": evidence,
                "source": "seo_analyzer",
                "check": gap.get("check"),
            }
        )
    return pain_points


def _pain_point_key(point: dict[str, Any]) -> str:
    check = (point.get("check") or "").strip().lower()
    evidence = point.get("evidence") or {}
    page_url = (evidence.get("page_url") or point.get("page_url") or "").strip().lower()
    description = (point.get("description") or "").strip().lower()
    if check:
        return f"{check}|{page_url}"
    return description or f"{point.get('category')}|{point.get('severity')}"


def merge_pain_points(
    rule_points: list[dict[str, Any]],
    llm_points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge rule-based and LLM pain points, deduplicating by check+page (then description)."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for point in list(rule_points) + list(llm_points):
        key = _pain_point_key(point)
        if not key or key in seen:
            continue
        evidence = point.get("evidence") or {}
        if not evidence.get("page_url") and point.get("page_url"):
            evidence = {**evidence, "page_url": point["page_url"]}
            point = {**point, "evidence": evidence}
        merged.append(point)
        seen.add(key)

    return _drop_contradictory_pain_points(merged)


def _drop_contradictory_pain_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop conflicting chatbot missing vs detected-style findings."""
    checks = {str(p.get("check") or "") for p in points}
    drop: set[str] = set()
    if "missing_chatbot" in checks and any(
        c.startswith("chatbot_") and c != "missing_chatbot" for c in checks
    ):
        drop.add("missing_chatbot")
    return [p for p in points if str(p.get("check") or "") not in drop]


_RECOMMENDATION_FIXES: dict[str, str] = {
    "missing_title": "Add a unique, descriptive title tag (30-60 characters) with primary keywords.",
    "title_too_short": "Expand the page title to 30-60 characters including primary keywords and brand.",
    "title_too_long": "Shorten the page title to 30-60 characters while keeping keywords near the front.",
    "missing_meta_description": "Write a compelling meta description (70-160 characters) with a clear value proposition.",
    "meta_description_length": "Rewrite the meta description to 70-160 characters with a call to action.",
    "missing_h1": "Add a single descriptive H1 heading that matches the page topic and primary keyword.",
    "multiple_h1": "Use one H1 per page; demote extra H1s to H2 or H3 headings.",
    "missing_canonical": "Add a canonical link tag pointing to the preferred URL for this page.",
    "thin_content": "Expand page content with useful, keyword-relevant copy (aim for 300+ words on key pages).",
    "missing_robots_meta": "Add a robots meta tag (e.g. index,follow) or rely on a valid robots.txt policy.",
    "missing_schema": "Add JSON-LD structured data (Organization, Product, or LocalBusiness as appropriate).",
    "images_missing_alt": "Add descriptive alt text to images that conveys content and context.",
    "duplicate_titles": "Give each page a unique title tag that reflects its specific content.",
    "duplicate_meta_descriptions": "Write unique meta descriptions for each page to avoid duplicate snippets.",
}


def select_top_pain_points(
    pain_points: list[dict[str, Any]],
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return the highest-severity pain points for LLM context."""
    return sorted(
        pain_points,
        key=lambda point: _SEVERITY_WEIGHTS.get(point.get("severity", "medium"), 50),
        reverse=True,
    )[:limit]


def pain_points_to_recommendations(
    pain_points: list[dict[str, Any]],
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Build rule-based recommendations when LLM output is unavailable."""
    priority_map = {"critical": "high", "high": "high", "medium": "medium", "low": "low"}
    recommendations: list[dict[str, Any]] = []

    for point in select_top_pain_points(pain_points, limit=limit):
        check = point.get("check") or ""
        description = point.get("description", "")
        fix = _RECOMMENDATION_FIXES.get(
            check,
            f"Address the reported issue: {description}" if description else "Resolve this website issue.",
        )
        severity = point.get("severity", "medium")
        recommendations.append(
            {
                "problem": description,
                "fix": fix,
                "expected_benefit": "Improves search visibility, crawlability, and on-page SEO performance.",
                "priority": priority_map.get(severity, "medium"),
                "source_check": check or None,
                "source_finding": description,
            }
        )

    return recommendations


def _check_page(page: dict[str, Any]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    url = page.get("url") or ""
    title = _safe_text(page.get("title"))
    metadata = page.get("metadata") or {}
    headings = page.get("headings") or []
    clean_text = _safe_text(page.get("clean_text"))
    image_stats = page.get("image_stats") or {}

    evidence_base = {
        "page_url": url,
        "title": title or None,
        "meta": {k: metadata[k] for k in ("description", "canonical", "robots") if metadata.get(k)},
    }

    if not title:
        gaps.append(
            _gap(
                "missing_title",
                "critical",
                "Page is missing a title tag",
                url,
                evidence_base,
            )
        )
    else:
        if len(title) < _TITLE_MIN_LENGTH:
            gaps.append(
                _gap(
                    "title_too_short",
                    "medium",
                    f"Title is too short ({len(title)} chars, recommended 30-60)",
                    url,
                    {**evidence_base, "title_length": len(title)},
                )
            )
        elif len(title) > _TITLE_MAX_LENGTH:
            gaps.append(
                _gap(
                    "title_too_long",
                    "high",
                    f"Title is too long ({len(title)} chars, recommended 30-60)",
                    url,
                    {**evidence_base, "title_length": len(title)},
                )
            )

    description = _safe_text(metadata.get("description"))
    if not description:
        gaps.append(
            _gap(
                "missing_meta_description",
                "high",
                "Page is missing a meta description",
                url,
                evidence_base,
            )
        )
    else:
        desc_len = len(description)
        if desc_len < _META_DESC_MIN_LENGTH or desc_len > _META_DESC_MAX_LENGTH:
            gaps.append(
                _gap(
                    "meta_description_length",
                    "medium",
                    f"Meta description length is suboptimal ({desc_len} chars, recommended 70-160)",
                    url,
                    {**evidence_base, "meta_description_length": desc_len},
                )
            )

    h1_headings = [h for h in headings if str(h.get("level", "")).lower() == "h1"]
    if not h1_headings:
        gaps.append(
            _gap(
                "missing_h1",
                "high",
                "Page is missing an H1 heading",
                url,
                evidence_base,
            )
        )
    elif len(h1_headings) > 1:
        gaps.append(
            _gap(
                "multiple_h1",
                "medium",
                f"Page has multiple H1 headings ({len(h1_headings)})",
                url,
                {
                    **evidence_base,
                    "h1_texts": [h.get("text", "") for h in h1_headings[:5]],
                },
            )
        )

    if not metadata.get("canonical"):
        gaps.append(
            _gap(
                "missing_canonical",
                "medium",
                "Page is missing a canonical link",
                url,
                evidence_base,
            )
        )

    if len(clean_text) < _THIN_CONTENT_THRESHOLD:
        gaps.append(
            _gap(
                "thin_content",
                "medium",
                f"Page has thin content ({len(clean_text)} chars)",
                url,
                {**evidence_base, "content_length": len(clean_text)},
            )
        )

    if not metadata.get("robots"):
        gaps.append(
            _gap(
                "missing_robots_meta",
                "low",
                "Page is missing a robots meta tag",
                url,
                evidence_base,
            )
        )

    if not metadata.get("has_schema"):
        gaps.append(
            _gap(
                "missing_schema",
                "medium",
                "Page is missing structured data (JSON-LD schema)",
                url,
                evidence_base,
            )
        )

    images_without_alt = image_stats.get("images_without_alt", 0)
    total_images = image_stats.get("total_images", 0)
    if total_images > 0 and images_without_alt > 0:
        gaps.append(
            _gap(
                "images_missing_alt",
                "medium",
                f"{images_without_alt} of {total_images} images are missing alt text",
                url,
                {
                    **evidence_base,
                    "total_images": total_images,
                    "images_without_alt": images_without_alt,
                },
            )
        )

    return gaps


def _check_cross_page(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []

    title_map: dict[str, list[str]] = defaultdict(list)
    desc_map: dict[str, list[str]] = defaultdict(list)

    for page in pages:
        url = page.get("url") or ""
        title = _safe_text(page.get("title"))
        if title:
            title_map[title].append(url)
        metadata = page.get("metadata") or {}
        description = _safe_text(metadata.get("description"))
        if description:
            desc_map[description].append(url)

    for title, urls in title_map.items():
        if len(urls) > 1:
            gaps.append(
                {
                    "check": "duplicate_titles",
                    "severity": "high",
                    "description": f'Duplicate title "{title}" used on {len(urls)} pages',
                    "page_url": urls[0],
                    "evidence": {"title": title, "pages": urls},
                }
            )

    for description, urls in desc_map.items():
        if len(urls) > 1:
            gaps.append(
                {
                    "check": "duplicate_meta_descriptions",
                    "severity": "medium",
                    "description": f"Duplicate meta description used on {len(urls)} pages",
                    "page_url": urls[0],
                    "evidence": {
                        "meta_description": description[:160],
                        "pages": urls,
                    },
                }
            )

    return gaps


def _gap(
    check: str,
    severity: str,
    description: str,
    page_url: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "check": check,
        "severity": severity,
        "description": description,
        "page_url": page_url,
        "evidence": evidence,
    }


def _build_summary(gaps: list[dict[str, Any]], page_count: int) -> str:
    if not gaps:
        return f"No SEO gaps detected across {page_count} page(s)"

    severity_counts: dict[str, int] = defaultdict(int)
    for gap in gaps:
        severity_counts[gap.get("severity", "medium")] += 1

    parts = [f"{count} {severity}" for severity, count in sorted(
        severity_counts.items(),
        key=lambda item: _SEVERITY_WEIGHTS.get(item[0], 0),
        reverse=True,
    )]
    return f"{', '.join(parts)} SEO gap(s) across {page_count} page(s)"


def _compute_health_score(gaps: list[dict[str, Any]]) -> float:
    """Compute SEO health score 0-100 (higher is better)."""
    if not gaps:
        return 100.0

    penalty = sum(_SEVERITY_WEIGHTS.get(gap.get("severity", "medium"), 50) for gap in gaps)
    max_penalty = len(gaps) * _SEVERITY_WEIGHTS["critical"]
    health = max(0.0, 100.0 - (penalty / max_penalty * 100))
    return round(health, 1)

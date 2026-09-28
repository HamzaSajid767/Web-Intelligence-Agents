"""Tests for rule-based SEO gap analyzer."""

from app.analysis.seo_analyzer import (
    analyze_seo_gaps,
    gaps_to_pain_points,
    merge_pain_points,
)


def _page(
    *,
    url: str = "https://example.com/",
    title: str | None = "Example Page Title For SEO Testing",
    description: str | None = "A well-written meta description that is long enough for search engines to display properly in results.",
    canonical: str | None = "https://example.com/",
    headings: list | None = None,
    clean_text: str = "x" * 200,
    robots: str | None = "index, follow",
    has_schema: bool = True,
    image_stats: dict | None = None,
) -> dict:
    metadata: dict = {}
    if description is not None:
        metadata["description"] = description
    if canonical is not None:
        metadata["canonical"] = canonical
    if robots is not None:
        metadata["robots"] = robots
    metadata["has_schema"] = has_schema

    return {
        "url": url,
        "title": title,
        "metadata": metadata,
        "headings": headings or [{"level": "h1", "text": "Main Heading"}],
        "clean_text": clean_text,
        "image_stats": image_stats or {"total_images": 2, "images_with_alt": 2, "images_without_alt": 0},
    }


def test_analyze_seo_gaps_handles_null_metadata_values() -> None:
    """Webclaw can return explicit nulls for title, description, and clean_text."""
    page = {
        "url": "https://www.alpinehomeair.com/",
        "title": None,
        "metadata": {"description": None, "has_schema": False, "title": "Just a moment..."},
        "headings": [],
        "clean_text": None,
        "raw_html": '<div><noscript>Enable JavaScript and cookies to continue</noscript></div>',
    }

    result = analyze_seo_gaps([page])

    assert result["gaps"]
    checks = {gap["check"] for gap in result["gaps"]}
    assert "missing_title" in checks
    assert "missing_meta_description" in checks


def test_analyze_seo_gaps_no_issues_on_healthy_page() -> None:
    result = analyze_seo_gaps([_page()])

    assert result["gaps"] == []
    assert result["score"] == 100.0
    assert "No SEO gaps" in result["summary"]


def test_analyze_seo_gaps_detects_missing_meta_description() -> None:
    page = _page(description=None)
    result = analyze_seo_gaps([page])

    checks = {gap["check"] for gap in result["gaps"]}
    assert "missing_meta_description" in checks


def test_analyze_seo_gaps_detects_missing_title() -> None:
    result = analyze_seo_gaps([_page(title=None)])

    assert any(gap["check"] == "missing_title" for gap in result["gaps"])


def test_analyze_seo_gaps_detects_title_length_issues() -> None:
    short = analyze_seo_gaps([_page(title="Short")])
    long_title = "x" * 70
    long = analyze_seo_gaps([_page(title=long_title)])

    assert any(gap["check"] == "title_too_short" for gap in short["gaps"])
    assert any(gap["check"] == "title_too_long" for gap in long["gaps"])


def test_analyze_seo_gaps_detects_heading_issues() -> None:
    missing_h1 = analyze_seo_gaps([_page(headings=[{"level": "h2", "text": "Sub"}])])
    multiple_h1 = analyze_seo_gaps(
        [
            _page(
                headings=[
                    {"level": "h1", "text": "One"},
                    {"level": "h1", "text": "Two"},
                ]
            )
        ]
    )

    assert any(gap["check"] == "missing_h1" for gap in missing_h1["gaps"])
    assert any(gap["check"] == "multiple_h1" for gap in multiple_h1["gaps"])


def test_analyze_seo_gaps_detects_duplicate_titles() -> None:
    pages = [
        _page(url="https://example.com/a", title="Same Title For Duplicate Check"),
        _page(url="https://example.com/b", title="Same Title For Duplicate Check"),
    ]
    result = analyze_seo_gaps(pages)

    assert any(gap["check"] == "duplicate_titles" for gap in result["gaps"])


def test_analyze_seo_gaps_detects_duplicate_meta_descriptions() -> None:
    description = "A well-written meta description that is long enough for search engines to display properly in results."
    pages = [
        _page(url="https://example.com/a", description=description),
        _page(url="https://example.com/b", description=description),
    ]
    result = analyze_seo_gaps(pages)

    assert any(gap["check"] == "duplicate_meta_descriptions" for gap in result["gaps"])


def test_analyze_seo_gaps_detects_missing_schema_and_alt_text() -> None:
    result = analyze_seo_gaps(
        [
            _page(
                has_schema=False,
                image_stats={"total_images": 3, "images_with_alt": 1, "images_without_alt": 2},
            )
        ]
    )

    checks = {gap["check"] for gap in result["gaps"]}
    assert "missing_schema" in checks
    assert "images_missing_alt" in checks


def test_gaps_to_pain_points_maps_seo_category() -> None:
    gaps = [
        {
            "check": "missing_meta_description",
            "severity": "high",
            "description": "Page is missing a meta description",
            "page_url": "https://example.com/",
            "evidence": {"page_url": "https://example.com/"},
        }
    ]
    pain_points = gaps_to_pain_points(gaps)

    assert len(pain_points) == 1
    assert pain_points[0]["category"] == "seo"
    assert pain_points[0]["severity"] == "high"
    assert pain_points[0]["source"] == "seo_analyzer"


def test_merge_pain_points_deduplicates_descriptions() -> None:
    rule_points = [
        {"category": "seo", "severity": "high", "description": "Missing meta description"},
    ]
    llm_points = [
        {"category": "seo", "severity": "medium", "description": "Missing meta description"},
        {"category": "trust", "severity": "low", "description": "No testimonials"},
    ]

    merged = merge_pain_points(rule_points, llm_points)

    assert len(merged) == 2
    assert merged[0]["description"] == "Missing meta description"
    assert merged[1]["description"] == "No testimonials"

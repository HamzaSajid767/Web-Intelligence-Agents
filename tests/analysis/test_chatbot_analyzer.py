"""Tests for chatbot detection and gap analysis."""

from app.analysis.chatbot_analyzer import (
    analyze_chatbot,
    chatbot_gaps_to_pain_points,
    merge_chatbot_assessment,
)


def _page(
    *,
    url: str = "https://example.com/",
    raw_html: str = "<html><body><p>Hello world content here</p></body></html>",
    clean_text: str | None = None,
    chatbot_signals: dict | None = None,
    success: bool = True,
) -> dict:
    text = clean_text or (
        "Hello world content here with enough readable copy for crawl quality checks "
        "so missing chatbot gaps can be emitted when appropriate for usable pages."
    )
    return {
        "url": url,
        "raw_html": raw_html,
        "clean_text": text,
        "success": success,
        "chatbot_signals": chatbot_signals or {},
    }


def test_analyze_chatbot_missing_widget() -> None:
    result = analyze_chatbot([_page()])

    assert result["detected"] is False
    assert any(gap["check"] == "missing_chatbot" for gap in result["gaps"])
    assert result["score"] == 0.0
    assert result["confidence"] == 0.0


def test_analyze_chatbot_detects_intercom() -> None:
    html = """
    <html><head>
    <script src="https://widget.intercom.io/widget/abc123"></script>
    </head><body><p>Welcome to our store</p></body></html>
    """
    result = analyze_chatbot(
        [
            _page(
                raw_html=html,
                chatbot_signals={
                    "script_urls": ["https://widget.intercom.io/widget/abc123"],
                    "launcher_labels": ["Chat with us"],
                    "welcome_messages": ["Hello! How can we help?"],
                    "iframe_chat_urls": [],
                },
            )
        ]
    )

    assert result["detected"] is True
    assert result["confidence"] >= 0.75
    assert "intercom" in result["providers"]
    assert not any(gap["check"] == "missing_chatbot" for gap in result["gaps"])


def test_maps_iframe_not_detected_as_chat() -> None:
    result = analyze_chatbot(
        [
            _page(
                chatbot_signals={
                    "script_urls": [],
                    "launcher_labels": [],
                    "welcome_messages": [],
                    "iframe_chat_urls": [
                        "https://www.google.com/maps/embed?pb=example",
                        "https://player.vimeo.com/video/123",
                    ],
                },
            )
        ]
    )
    assert result["detected"] is False
    assert result["confidence"] == 0.0


def test_analyze_chatbot_low_coverage() -> None:
    chat_html = '<script src="https://widget.intercom.io/widget/abc"></script>'
    pages = [
        _page(url="https://example.com/", raw_html=chat_html),
        _page(url="https://example.com/about", raw_html="<html><body>About</body></html>"),
        _page(url="https://example.com/contact", raw_html="<html><body>Contact</body></html>"),
    ]
    result = analyze_chatbot(pages)

    assert result["detected"] is True
    assert result["coverage_pct"] < 50
    assert any(gap["check"] == "chatbot_low_coverage" for gap in result["gaps"])


def test_analyze_chatbot_no_welcome_message_gap() -> None:
    html = '<script src="https://widget.intercom.io/widget/abc"></script>'
    result = analyze_chatbot([_page(raw_html=html)])

    assert result["detected"] is True
    assert any(gap["check"] == "chatbot_no_welcome_message" for gap in result["gaps"])


def test_chatbot_gaps_to_pain_points_uses_conversion_category() -> None:
    gaps = [
        {
            "check": "missing_chatbot",
            "severity": "high",
            "description": "No live chat detected",
            "page_url": "site-wide",
            "evidence": {},
        }
    ]
    pain_points = chatbot_gaps_to_pain_points(gaps)

    assert pain_points[0]["category"] == "conversion"
    assert pain_points[0]["source"] == "chatbot_analyzer"


def test_merge_chatbot_assessment_adds_efficiency_and_gaps() -> None:
    analysis = analyze_chatbot([_page()])
    assessment = {
        "design_rating": "fair",
        "response_readiness": "poor",
        "design_notes": "No visible launcher label",
        "response_notes": "No proactive greeting",
        "gaps": [
            {
                "check": "chatbot_poor_design",
                "severity": "medium",
                "description": "Chat launcher is hard to find",
                "page_url": "https://example.com/",
            }
        ],
    }

    merged = merge_chatbot_assessment(analysis, assessment)

    assert merged["efficiency"]["design_rating"] == "fair"
    assert merged["efficiency"]["response_readiness"] == "poor"
    assert any(gap["check"] == "chatbot_poor_design" for gap in merged["gaps"])

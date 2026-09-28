"""Rule-based chatbot/live-chat detection and gap analysis from crawled page data."""

from __future__ import annotations

import re
from typing import Any

_COVERAGE_THRESHOLD_PCT = 50.0
_HIGH_CONFIDENCE = 0.75
_MEDIUM_CONFIDENCE = 0.45

_SEVERITY_WEIGHTS = {
    "critical": 100,
    "high": 75,
    "medium": 50,
    "low": 25,
}

_RATING_PENALTIES = {
    "good": 0,
    "fair": 15,
    "poor": 35,
}

_VENDOR_SIGNATURES: dict[str, list[str]] = {
    "intercom": ["intercom.io", "widget.intercom.io", "intercom("],
    "drift": ["drift.com", "js.driftt.com", "driftt.com"],
    "tidio": ["tidio.co", "code.tidio.co"],
    "zendesk": ["zendesk.com/embeddable", "zdassets.com", "zendesk.com/snippet"],
    "livechat": ["livechatinc.com", "livechat.com"],
    "crisp": ["crisp.chat"],
    "tawk": ["tawk.to"],
    "hubspot": ["js.hs-scripts.com", "hubspot.com/conversations", "hs-scripts.com"],
    "olark": ["olark.com"],
    "freshchat": ["freshchat.com", "wchat.freshchat.com"],
}

_GENERIC_PATTERNS = [
    "chat-widget",
    "live-chat",
    "livechat",
    "chatbot",
    "data-chat",
    "chat-launcher",
    "chat-button",
    "messenger-widget",
]

_IGNORE_IFRAME_HOST_MARKERS = (
    "google.com/maps",
    "maps.google.",
    "maps.googleapis.com",
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "player.vimeo.com",
    "facebook.com/plugins",
    "platform.twitter.com",
    "wix.com",
    "static.wixstatic.com",
    "parastorage.com",
)

_NAV_FALSE_LAUNCHERS = re.compile(
    r"\b(chat\s*gpt|live\s*chat\s*support\s*hours|customer\s*service\s*hours|"
    r"help\s*center|help\s*desk|message\s*us\s*on\s*(facebook|instagram|linkedin))\b",
    re.IGNORECASE,
)

_WELCOME_KEYWORDS = re.compile(
    r"\b(welcome|greeting|hello|how can we help|how may we help|chat with us|need help)\b",
    re.IGNORECASE,
)


def analyze_chatbot(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze crawled pages for chatbot presence and conversion gaps."""
    if not pages:
        return _empty_analysis(page_count=0)

    page_results: list[dict[str, Any]] = []
    all_providers: set[str] = set()
    pages_with_chatbot: list[str] = []
    confidences: list[float] = []
    aggregated_signals: dict[str, list[Any]] = {
        "welcome_messages": [],
        "launcher_labels": [],
        "iframe_chat_urls": [],
        "script_urls": [],
    }

    for page in pages:
        result = _analyze_page(page)
        page_results.append(result)
        if result["detected"]:
            pages_with_chatbot.append(page.get("url") or "")
            all_providers.update(result["providers"])
            confidences.append(float(result.get("confidence") or 0.0))
            for key in aggregated_signals:
                for value in result.get("signals", {}).get(key, []):
                    if value not in aggregated_signals[key]:
                        aggregated_signals[key].append(value)

    confidence = max(confidences) if confidences else 0.0
    detected = bool(pages_with_chatbot) and confidence >= _MEDIUM_CONFIDENCE
    coverage_pct = round(len(pages_with_chatbot) / len(pages) * 100, 1) if pages else 0.0
    crawl_quality_ok = _crawl_quality_sufficient(pages)
    gaps = _build_gaps(
        page_results,
        pages,
        detected,
        coverage_pct,
        aggregated_signals,
        confidence=confidence,
        crawl_quality_ok=crawl_quality_ok,
    )
    summary = _build_summary(detected, all_providers, len(pages_with_chatbot), len(pages), coverage_pct, confidence)
    score = _compute_effectiveness_score(gaps, detected, coverage_pct)

    return {
        "detected": detected,
        "confidence": confidence,
        "providers": sorted(all_providers),
        "pages_with_chatbot": pages_with_chatbot if detected else [],
        "coverage_pct": coverage_pct if detected else 0.0,
        "summary": summary,
        "score": score,
        "signals": aggregated_signals,
        "gaps": gaps,
        "efficiency": {},
    }


def chatbot_gaps_to_pain_points(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert chatbot gaps into pain-point dicts for the scoring pipeline."""
    pain_points: list[dict[str, Any]] = []
    for gap in gaps:
        evidence = dict(gap.get("evidence") or {})
        if gap.get("page_url"):
            evidence.setdefault("page_url", gap["page_url"])
        pain_points.append(
            {
                "category": "conversion",
                "severity": gap.get("severity", "medium"),
                "description": gap.get("description", ""),
                "evidence": evidence,
                "source": "chatbot_analyzer",
                "check": gap.get("check"),
            }
        )
    return pain_points


def format_chatbot_gaps_for_prompt(analysis: dict[str, Any]) -> str:
    """Format chatbot analysis for LLM prompt injection."""
    gaps = analysis.get("gaps", [])
    if not gaps and not analysis.get("detected"):
        return analysis.get("summary", "No chatbot detected")

    lines: list[str] = [analysis.get("summary", "")]
    efficiency = analysis.get("efficiency") or {}
    if efficiency:
        design = efficiency.get("design_rating")
        response = efficiency.get("response_readiness")
        if design:
            lines.append(f"Design rating: {design} — {efficiency.get('design_notes', '')}")
        if response:
            lines.append(f"Response readiness: {response} — {efficiency.get('response_notes', '')}")

    for gap in gaps[:20]:
        page_url = gap.get("page_url") or "site-wide"
        lines.append(f"- [{gap.get('severity')}] {gap.get('description')} ({page_url})")
    return "\n".join(line for line in lines if line)


def merge_chatbot_assessment(
    analysis: dict[str, Any],
    assessment: dict[str, Any],
) -> dict[str, Any]:
    """Merge LLM chatbot assessment into rule-based analysis."""
    merged = dict(analysis)
    efficiency = {
        "design_rating": assessment.get("design_rating"),
        "response_readiness": assessment.get("response_readiness"),
        "design_notes": assessment.get("design_notes", ""),
        "response_notes": assessment.get("response_notes", ""),
    }
    merged["efficiency"] = efficiency

    existing_checks = {gap.get("check") for gap in merged.get("gaps", [])}
    for gap in assessment.get("gaps", []):
        check = gap.get("check")
        if check and check in existing_checks:
            continue
        merged.setdefault("gaps", []).append(gap)
        if check:
            existing_checks.add(check)

    merged["score"] = _compute_effectiveness_score(
        merged.get("gaps", []),
        merged.get("detected", False),
        merged.get("coverage_pct", 0.0),
        efficiency,
    )
    return merged


def _analyze_page(page: dict[str, Any]) -> dict[str, Any]:
    url = page.get("url") or ""
    html = (page.get("raw_html") or page.get("clean_text") or "").lower()
    signals = page.get("chatbot_signals") or _signals_from_html(html)
    signals = _sanitize_signals(signals)
    providers = _detect_providers(html, signals)

    vendor_script = bool(providers)
    chat_iframes = list(signals.get("iframe_chat_urls") or [])
    launchers = [
        label
        for label in (signals.get("launcher_labels") or [])
        if not _is_false_launcher(str(label))
    ]
    generic_match = any(pattern in html for pattern in _GENERIC_PATTERNS)

    confidence = 0.0
    if vendor_script:
        confidence = _HIGH_CONFIDENCE
    elif chat_iframes and launchers:
        confidence = 0.65
    elif chat_iframes:
        confidence = 0.35
    elif launchers and generic_match:
        confidence = 0.4
    elif launchers or generic_match:
        confidence = 0.2

    detected = confidence >= _MEDIUM_CONFIDENCE
    if detected and not providers and (chat_iframes or generic_match):
        providers.add("generic")

    welcome_messages = list(signals.get("welcome_messages") or [])
    if not welcome_messages and html and detected:
        welcome_messages = _extract_welcome_from_html(html)

    page_signals = {
        "welcome_messages": welcome_messages,
        "launcher_labels": launchers,
        "iframe_chat_urls": chat_iframes,
        "script_urls": list(signals.get("script_urls") or []),
    }

    return {
        "url": url,
        "detected": detected,
        "confidence": confidence,
        "providers": sorted(providers),
        "signals": page_signals,
    }


def _sanitize_signals(signals: dict[str, Any]) -> dict[str, Any]:
    cleaned = {
        "welcome_messages": list(signals.get("welcome_messages") or []),
        "launcher_labels": list(signals.get("launcher_labels") or []),
        "iframe_chat_urls": [],
        "script_urls": list(signals.get("script_urls") or []),
    }
    for url in signals.get("iframe_chat_urls") or []:
        if not _is_ignored_embed(str(url)):
            cleaned["iframe_chat_urls"].append(str(url))
    cleaned["launcher_labels"] = [
        label for label in cleaned["launcher_labels"] if not _is_ignored_embed(str(label))
    ]
    return cleaned


def _is_ignored_embed(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in _IGNORE_IFRAME_HOST_MARKERS)


def _is_false_launcher(label: str) -> bool:
    if _NAV_FALSE_LAUNCHERS.search(label):
        return True
    lowered = label.lower().strip()
    # Bare nav words without chat-widget semantics.
    if lowered in {"help", "support", "message", "contact", "chat"}:
        return True
    return False


def _detect_providers(html: str, signals: dict[str, Any]) -> set[str]:
    providers: set[str] = set()
    haystack = html
    for script_url in signals.get("script_urls", []):
        haystack += " " + str(script_url).lower()
    for iframe_url in signals.get("iframe_chat_urls", []):
        haystack += " " + str(iframe_url).lower()

    for provider, patterns in _VENDOR_SIGNATURES.items():
        if any(pattern in haystack for pattern in patterns):
            providers.add(provider)
    return providers


def _signals_from_html(html: str) -> dict[str, list[str]]:
    """Fallback signal extraction when chatbot_signals not on page dict."""
    signals: dict[str, list[str]] = {
        "welcome_messages": [],
        "launcher_labels": [],
        "iframe_chat_urls": [],
        "script_urls": [],
    }
    if not html:
        return signals

    for match in _WELCOME_KEYWORDS.finditer(html):
        snippet = html[max(0, match.start() - 20) : match.end() + 40].strip()
        if snippet and snippet not in signals["welcome_messages"]:
            signals["welcome_messages"].append(snippet[:120])

    for pattern in _GENERIC_PATTERNS:
        if pattern in html and pattern not in signals["launcher_labels"]:
            signals["launcher_labels"].append(pattern)

    for match in re.finditer(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE):
        src = match.group(1)
        if not _is_ignored_embed(src) and any(k in src.lower() for k in ("chat", "messenger", "tidio", "tawk")):
            signals["iframe_chat_urls"].append(src)

    return signals


def _extract_welcome_from_html(html: str) -> list[str]:
    messages: list[str] = []
    for match in _WELCOME_KEYWORDS.finditer(html):
        snippet = html[max(0, match.start() - 20) : match.end() + 60].strip()
        if snippet and snippet not in messages:
            messages.append(snippet[:120])
    return messages[:5]


def _crawl_quality_sufficient(pages: list[dict[str, Any]]) -> bool:
    """Missing-chatbot gaps only when the crawl looks like a real usable site."""
    usable = 0
    for page in pages:
        if page.get("success") is False:
            continue
        text = (page.get("clean_text") or "").strip()
        if len(text) >= 120:
            usable += 1
    return usable >= 1


def _build_gaps(
    page_results: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    detected: bool,
    coverage_pct: float,
    aggregated_signals: dict[str, list[Any]],
    *,
    confidence: float,
    crawl_quality_ok: bool,
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    page_count = len(pages)

    if not detected:
        if crawl_quality_ok:
            gaps.append(
                _gap(
                    "missing_chatbot",
                    "high",
                    "No live chat or chatbot widget detected on any crawled page",
                    "site-wide",
                    {"pages_crawled": page_count, "confidence": confidence},
                )
            )
        return gaps

    if confidence < _HIGH_CONFIDENCE:
        # Low/medium confidence detections: do not emit quality gaps as if confirmed.
        return gaps

    if page_count > 1 and coverage_pct < _COVERAGE_THRESHOLD_PCT:
        missing_pages = [
            result["url"]
            for result in page_results
            if not result["detected"] and result.get("url")
        ]
        gaps.append(
            _gap(
                "chatbot_low_coverage",
                "medium",
                f"Chatbot detected on only {coverage_pct:.0f}% of crawled pages",
                page_results[0].get("url", "site-wide"),
                {
                    "coverage_pct": coverage_pct,
                    "pages_without_chatbot": missing_pages[:10],
                },
            )
        )

    if not aggregated_signals.get("welcome_messages"):
        gaps.append(
            _gap(
                "chatbot_no_welcome_message",
                "medium",
                "Chatbot detected but no welcome or greeting message found in page HTML",
                page_results[0].get("url", "site-wide"),
                {"providers": sorted({p for r in page_results for p in r.get("providers", [])})},
            )
        )

    for result in page_results:
        providers = result.get("providers", [])
        named_providers = [p for p in providers if p != "generic"]
        if len(named_providers) > 1:
            gaps.append(
                _gap(
                    "multiple_chat_widgets",
                    "medium",
                    f"Multiple chat widgets detected on the same page ({', '.join(named_providers)})",
                    result.get("url", "site-wide"),
                    {"providers": named_providers},
                )
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


def _build_summary(
    detected: bool,
    providers: set[str],
    pages_with: int,
    page_count: int,
    coverage_pct: float,
    confidence: float,
) -> str:
    if not detected:
        return f"No live chat or chatbot widget detected across {page_count} page(s)"

    provider_label = ", ".join(sorted(providers)) if providers else "unknown provider"
    return (
        f"{provider_label} chatbot detected on {pages_with}/{page_count} pages "
        f"({coverage_pct:.0f}% coverage, confidence={confidence:.2f})"
    )


def _compute_effectiveness_score(
    gaps: list[dict[str, Any]],
    detected: bool,
    coverage_pct: float,
    efficiency: dict[str, Any] | None = None,
) -> float:
    """Compute chatbot effectiveness score 0-100 (higher is better)."""
    if not detected:
        return 0.0

    penalty = sum(_SEVERITY_WEIGHTS.get(gap.get("severity", "medium"), 50) for gap in gaps)
    if coverage_pct < _COVERAGE_THRESHOLD_PCT:
        penalty += 10

    efficiency = efficiency or {}
    for key in ("design_rating", "response_readiness"):
        rating = efficiency.get(key)
        if rating:
            penalty += _RATING_PENALTIES.get(str(rating).lower(), 0)

    max_penalty = max(100, len(gaps) * _SEVERITY_WEIGHTS["critical"] + 70)
    health = max(0.0, 100.0 - (penalty / max_penalty * 100))
    return round(health, 1)


def _empty_analysis(*, page_count: int) -> dict[str, Any]:
    return {
        "detected": False,
        "confidence": 0.0,
        "providers": [],
        "pages_with_chatbot": [],
        "coverage_pct": 0.0,
        "summary": f"No live chat or chatbot widget detected across {page_count} page(s)",
        "score": 0.0,
        "signals": {
            "welcome_messages": [],
            "launcher_labels": [],
            "iframe_chat_urls": [],
            "script_urls": [],
        },
        "gaps": [],
        "efficiency": {},
    }

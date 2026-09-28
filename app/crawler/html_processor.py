"""HTML processing utilities."""

from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.core.url_identity import same_org_host


def extract_headings(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract heading hierarchy from HTML."""
    headings: list[dict[str, str]] = []
    for level in range(1, 7):
        for tag in soup.find_all(f"h{level}"):
            text = tag.get_text(strip=True)
            if text:
                headings.append({"level": f"h{level}", "text": text})
    return headings


def extract_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    """Extract internal and external links (www/apex treated as same org)."""
    links: list[dict[str, str]] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        if absolute in seen:
            continue
        seen.add(absolute)
        is_internal = bool(urlparse(absolute).netloc) and same_org_host(base_url, absolute)
        links.append(
            {
                "url": absolute,
                "text": anchor.get_text(strip=True)[:200],
                "type": "internal" if is_internal else "external",
            }
        )
    return links


_CHAT_LAUNCHER_KEYWORDS = ("live chat", "chat with us", "chat now", "message us", "start chat")
_CHAT_IFRAME_KEYWORDS = ("chat", "messenger", "livechat", "intercom", "drift", "tidio", "zendesk", "crisp", "tawk")
_CHAT_VENDOR_DOMAINS = (
    "intercom.io",
    "drift.com",
    "driftt.com",
    "tidio.co",
    "zendesk.com",
    "zdassets.com",
    "livechatinc.com",
    "crisp.chat",
    "tawk.to",
    "hs-scripts.com",
    "olark.com",
    "freshchat.com",
)
_IGNORE_IFRAME_MARKERS = (
    "google.com/maps",
    "maps.google.",
    "maps.googleapis.com",
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "player.vimeo.com",
    "wix.com",
    "static.wixstatic.com",
    "parastorage.com",
)


def extract_chatbot_signals(soup: BeautifulSoup) -> dict[str, list[str]]:
    """Extract chatbot-related signals from HTML."""
    signals: dict[str, list[str]] = {
        "welcome_messages": [],
        "launcher_labels": [],
        "iframe_chat_urls": [],
        "script_urls": [],
    }

    for script in soup.find_all("script"):
        src = script.get("src")
        if src:
            src_lower = str(src).lower()
            signals["script_urls"].append(str(src))
            if any(domain in src_lower for domain in _CHAT_VENDOR_DOMAINS):
                signals["launcher_labels"].append(str(src))
        inline = script.string or script.get_text()
        if inline:
            inline_lower = inline.lower()
            for keyword in ("welcome", "greeting", "how can we help", "how may we help", "hello"):
                if keyword in inline_lower:
                    snippet = inline.strip()[:120]
                    if snippet not in signals["welcome_messages"]:
                        signals["welcome_messages"].append(snippet)
                    break

    for iframe in soup.find_all("iframe", src=True):
        src = str(iframe["src"])
        src_lower = src.lower()
        if any(marker in src_lower for marker in _IGNORE_IFRAME_MARKERS):
            continue
        if any(keyword in src_lower for keyword in _CHAT_IFRAME_KEYWORDS):
            signals["iframe_chat_urls"].append(src)
            signals["launcher_labels"].append(src)

    for element in soup.find_all(True):
        attrs_text = " ".join(
            str(element.get(attr, ""))
            for attr in ("id", "class", "aria-label", "data-testid", "role")
        ).lower()
        if any(keyword in attrs_text for keyword in ("chat-widget", "live-chat", "chatbot", "chat-launcher")):
            label = element.get("aria-label") or element.get_text(strip=True)
            if label and label not in signals["launcher_labels"]:
                signals["launcher_labels"].append(str(label)[:120])

    for button in soup.find_all(["button", "a"]):
        label = (button.get("aria-label") or button.get_text(strip=True) or "").strip()
        label_lower = label.lower()
        if label and any(keyword in label_lower for keyword in _CHAT_LAUNCHER_KEYWORDS):
            if label not in signals["launcher_labels"]:
                signals["launcher_labels"].append(label[:120])

    return signals


def extract_image_stats(soup: BeautifulSoup) -> dict[str, int]:
    """Count images with and without alt text."""
    total_images = 0
    images_with_alt = 0
    images_without_alt = 0

    for img in soup.find_all("img"):
        total_images += 1
        alt = img.get("alt")
        if alt is not None and str(alt).strip():
            images_with_alt += 1
        else:
            images_without_alt += 1

    return {
        "total_images": total_images,
        "images_with_alt": images_with_alt,
        "images_without_alt": images_without_alt,
    }


def extract_clean_text(soup: BeautifulSoup) -> str:
    """Extract readable text content from HTML."""
    for element in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        element.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def process_html(html: str, page_url: str) -> dict[str, Any]:
    """Process raw HTML into structured page data."""
    soup = BeautifulSoup(html, "lxml")
    from app.crawler.extractor import extract_metadata, extract_title

    chatbot_soup = BeautifulSoup(html, "lxml")
    return {
        "url": page_url,
        "title": extract_title(soup),
        "metadata": extract_metadata(soup),
        "headings": extract_headings(soup),
        "links": extract_links(soup, page_url),
        "image_stats": extract_image_stats(soup),
        "chatbot_signals": extract_chatbot_signals(chatbot_soup),
        "clean_text": extract_clean_text(soup),
        "raw_html": html,
    }

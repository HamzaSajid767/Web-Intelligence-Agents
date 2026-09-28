"""Fast HTML contact extraction from crawled pages."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.crawler.contact_extractor import aggregate_contacts, extract_contacts
from app.crawler.crawler_service import CrawlerService
from app.services.audit_service import AuditService


def extract(
    html: str | None,
    text: str | None,
    markdown: str | None = None,
) -> dict[str, list[str]]:
    """Extract emails and phone numbers (CLI compatibility wrapper)."""
    contacts = extract_contacts(html, text, markdown)
    return {
        "emails": contacts["emails"],
        "phones": contacts["phone_numbers"],
        "social_links": contacts["social_links"],
    }


async def crawl_site(url: str) -> dict:
    """Crawl one website and extract contacts from its pages."""
    crawl = await CrawlerService().crawl(url)
    page_dicts = [page.model_dump() for page in crawl.pages]
    aggregated = aggregate_contacts(page_dicts)
    pages: list[dict] = []
    for page in crawl.pages:
        found = extract(page.raw_html, page.clean_text, page.markdown)
        pages.append({"url": page.url, "title": page.title, **found})
    return {
        "website_url": url,
        "pages_crawled": len(pages),
        "errors": crawl.errors,
        "aggregated": {
            "emails": aggregated["emails"],
            "phones": aggregated["phone_numbers"],
            "social_links": aggregated["social_links"],
        },
        "pages": pages,
    }


async def main(urls: list[str]) -> None:
    """Crawl each URL and print combined JSON results."""
    sites: list[dict] = []
    for url in urls:
        try:
            sites.append(await crawl_site(url))
        except Exception as exc:
            sites.append(
                {
                    "website_url": url,
                    "pages_crawled": 0,
                    "errors": [str(exc)],
                    "aggregated": {"emails": [], "phones": [], "social_links": []},
                    "pages": [],
                }
            )

    out = {
        "total_sites": len(sites),
        "sites": sites,
    }
    path = Path(__file__).parent / "html_contacts.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


def parse_args() -> list[str]:
    """Parse CLI URLs (one or more)."""
    parser = argparse.ArgumentParser(
        description="Extract emails, phones, and social links from websites.",
    )
    parser.add_argument(
        "urls",
        nargs="+",
        help="Website URL(s) to crawl, e.g. https://example.com https://other.com",
    )
    args = parser.parse_args()
    return [AuditService.validate_url(url) for url in args.urls]


if __name__ == "__main__":
    asyncio.run(main(parse_args()))

"""HTML processor unit tests."""

from app.crawler.html_processor import extract_clean_text, extract_headings, extract_links, process_html


def test_process_html_extracts_structure():
    """HTML processor should extract title, headings, and text."""
    html = """
    <html>
    <head><title>Test Site</title>
    <meta name="description" content="A test site">
    <meta name="robots" content="index, follow">
    <script type="application/ld+json">{"@type": "Organization", "name": "Test"}</script>
    </head>
    <body>
    <h1>Welcome</h1>
    <p>Hello world</p>
    <a href="/about">About</a>
    <img src="/logo.png" alt="Logo">
    <img src="/hero.png">
    </body>
    </html>
    """
    result = process_html(html, "https://example.com")

    assert result["title"] == "Test Site"
    assert result["metadata"]["description"] == "A test site"
    assert result["metadata"]["robots"] == "index, follow"
    assert result["metadata"]["has_schema"] is True
    assert "Organization" in result["metadata"]["schema_types"]
    assert result["image_stats"]["total_images"] == 2
    assert result["image_stats"]["images_without_alt"] == 1
    assert len(result["headings"]) == 1
    assert "Hello world" in result["clean_text"]

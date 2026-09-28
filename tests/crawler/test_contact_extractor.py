"""Tests for contact extraction (emails, phones, social links)."""

from app.crawler.contact_extractor import aggregate_contacts, extract_contacts


def test_extract_emails_from_text_and_mailto():
    html = '<a href="mailto:sales%40example.com">Email us</a>'
    text = "Contact info@example.com for help"
    result = extract_contacts(html, text)
    assert "info@example.com" in result["emails"]
    assert "sales@example.com" in result["emails"]


def test_extract_phones_from_tel_and_pattern():
    html = '<a href="tel:+1-415-555-2671">Call</a><p>Also (212) 555-1234</p>'
    result = extract_contacts(html, None)
    assert "(415) 555-2671" in result["phone_numbers"]
    assert "(212) 555-1234" in result["phone_numbers"]


def test_reject_svg_coordinate_false_phones():
    html = "<svg><path d='M 123.456 789.012'/></svg><p>Call 800-555-0199</p>"
    result = extract_contacts(html, None)
    assert "(800) 555-0199" in result["phone_numbers"]
    assert not any(p.startswith("(123)") for p in result["phone_numbers"])


def test_extract_social_links_and_ignore_unrelated():
    html = """
    <a href="https://www.linkedin.com/company/acme">LinkedIn</a>
    <a href="https://twitter.com/acme">Twitter</a>
    <a href="https://other-blog.com/post">Blog</a>
    <a href="/about">About</a>
    """
    result = extract_contacts(html, None, base_url="https://acme.com")
    assert "https://www.linkedin.com/company/acme" in result["social_links"]
    assert "https://twitter.com/acme" in result["social_links"]
    assert not any("other-blog.com" in url for url in result["social_links"])
    assert not any(url.endswith("/about") for url in result["social_links"])


def test_aggregate_contacts_dedupes_across_pages():
    pages = [
        {
            "url": "https://example.com/",
            "raw_html": '<a href="mailto:a@example.com">A</a>'
            '<a href="https://instagram.com/example">IG</a>',
            "clean_text": "Call (415) 555-0100",
        },
        {
            "url": "https://example.com/contact",
            "raw_html": '<a href="mailto:a@example.com">A</a>'
            '<a href="https://www.facebook.com/example">FB</a>',
            "clean_text": "Also (415) 555-0100 or b@example.com",
        },
    ]
    result = aggregate_contacts(pages)
    assert result["emails"] == ["a@example.com", "b@example.com"]
    assert result["phone_numbers"] == ["(415) 555-0100"]
    assert "https://instagram.com/example" in result["social_links"]
    assert "https://www.facebook.com/example" in result["social_links"]


def test_extract_json_ld_email_phone_and_same_as():
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Organization",
      "email": "hello@acme.com",
      "telephone": "+44 20 7946 0958",
      "sameAs": [
        "https://www.facebook.com/acme",
        "https://www.linkedin.com/company/acme"
      ]
    }
    </script>
    """
    result = extract_contacts(html, None, base_url="https://acme.com")
    assert "hello@acme.com" in result["emails"]
    assert "+442079460958" in result["phone_numbers"]
    assert "https://www.facebook.com/acme" in result["social_links"]
    assert "https://www.linkedin.com/company/acme" in result["social_links"]


def test_extract_json_ld_nested_graph():
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@graph": [
        {
          "@type": "Organization",
          "email": "mailto:team@example.com",
          "telephone": "+1-415-555-9999",
          "sameAs": "https://twitter.com/example"
        }
      ]
    }
    </script>
    """
    result = extract_contacts(html, None)
    assert "team@example.com" in result["emails"]
    assert "(415) 555-9999" in result["phone_numbers"]
    assert "https://twitter.com/example" in result["social_links"]


def test_extract_international_tel_link():
    html = '<a href="tel:+44-20-7946-0958">Call UK</a>'
    result = extract_contacts(html, None)
    assert "+442079460958" in result["phone_numbers"]


def test_reject_noise_emails():
    html = """
    <img src="user@cdn.example.com/logo.png"/>
    <p>Contact real@example.com</p>
    <span>photo@cdn.example.com.jpg</span>
    """
    text = "Reach us at support@example.com or image.png@cdn.example.com"
    result = extract_contacts(html, text)
    assert "support@example.com" in result["emails"]
    assert "real@example.com" in result["emails"]
    assert "image.png@cdn.example.com" not in result["emails"]
    assert not any(e.endswith(".jpg") for e in result["emails"])


def test_reject_share_intent_social_links():
    html = """
    <a href="https://www.facebook.com/DTGDCPAS">FB</a>
    <a href="https://www.facebook.com/sharer.php?u=https://example.com">Share</a>
    <a href="https://x.com/intent/post?url=https://example.com">Tweet</a>
    <a href="https://www.linkedin.com/shareArticle?mini=true&url=https://example.com">LI</a>
    <a href="https://twitter.com/dtgdcpas">Twitter</a>
    """
    result = extract_contacts(html, None)
    assert "https://www.facebook.com/DTGDCPAS" in result["social_links"]
    assert "https://twitter.com/dtgdcpas" in result["social_links"]
    assert not any("sharer.php" in url for url in result["social_links"])
    assert not any("/intent/" in url for url in result["social_links"])
    assert not any("shareArticle" in url for url in result["social_links"])


def test_reject_placeholder_phones():
    html = "<p>Call (718) 667-1500 or (999) 999-9999</p>"
    result = extract_contacts(html, None)
    assert "(718) 667-1500" in result["phone_numbers"]
    assert "(999) 999-9999" not in result["phone_numbers"]


def test_reject_map_cid_and_sequential_junk_phones():
    html = "<p>Call (688) 123-4567 or (123) 456-7890 or (415) 555-0199</p>"
    result = extract_contacts(html, None)
    assert "(415) 555-0199" in result["phone_numbers"]
    assert not any(p.startswith("(688)") for p in result["phone_numbers"])
    assert "(123) 456-7890" not in result["phone_numbers"]


def test_reject_youtube_watch_as_social():
    html = """
    <a href="https://www.youtube.com/watch?v=dQw4w9WgXcQ">Video</a>
    <a href="https://www.linkedin.com/company/acme">LinkedIn</a>
    """
    result = extract_contacts(html, None)
    assert "https://www.linkedin.com/company/acme" in result["social_links"]
    assert not any("youtube.com" in url for url in result["social_links"])


def test_extract_yelp_and_reject_facebook_search():
    html = """
    <a href="https://www.yelp.com/biz/balboa-tax-and-accounting-services-newport-beach-3">Yelp</a>
    <a href="https://www.facebook.com/search/top?q=balboa%20tax">FB Search</a>
    <a href="https://www.linkedin.com/company/balboa-tax-accounting-services">LinkedIn</a>
    """
    result = extract_contacts(html, None, base_url="https://www.balboatax.com/")
    assert (
        "https://www.yelp.com/biz/balboa-tax-and-accounting-services-newport-beach-3"
        in result["social_links"]
    )
    assert (
        "https://www.linkedin.com/company/balboa-tax-accounting-services"
        in result["social_links"]
    )
    assert not any("facebook.com/search" in url for url in result["social_links"])

from app.ingest.chunking import chunk_document, clean_text, content_hash, split_sections
from app.ingest.crawl import Site, normalize_url, parse_page

MARKDOWN = """# Working while studying
Intro text about student jobs in Germany and the rules that apply to them.

## Hour limits
Students from non-EU countries may work 140 full days or 280 half days per year.

## Short
Twenty hours.

## Insurance
Werkstudenten pay pension insurance but usually no health or unemployment insurance.
"""


def test_split_sections_keeps_heading_path() -> None:
    sections = split_sections(MARKDOWN, title="Studying")
    paths = [p for p, _ in sections]
    assert paths[0] == "Studying > Working while studying"
    assert paths[1] == "Studying > Working while studying > Hour limits"


def test_chunk_document_windows_long_text_with_overlap() -> None:
    long_body = " ".join(f"w{i}" for i in range(700))
    chunks = chunk_document(f"# Title\n{long_body}", max_words=280, overlap=40)
    assert len(chunks) == 3
    first, second = chunks[0].text.split(), chunks[1].text.split()
    assert first[-40:] == second[:40]  # overlap
    assert all(c.heading_path == "Title" for c in chunks)


def test_short_section_is_carried_not_dropped() -> None:
    chunks = chunk_document(MARKDOWN)
    joined = " ".join(c.text for c in chunks)
    assert "Twenty hours." in joined


def test_clean_text_and_hash_are_stable() -> None:
    raw = "Hello   world\r\n\n\n\nZum Seitenanfang\nBye"
    cleaned = clean_text(raw)
    assert cleaned == "Hello world\n\nBye"
    assert content_hash(cleaned) == content_hash("Hello world\n\nBye")


def test_site_allow_and_deny_rules() -> None:
    site = Site(
        name="t",
        base="https://example.de",
        max_pages=5,
        allow=["/studium/"],
        deny=["/jobsuche"],
        seeds=[],
    )
    assert site.allows("https://example.de/studium/jobben")
    assert not site.allows("https://example.de/other")
    assert not site.allows("https://example.de/studium/jobsuche")
    assert not site.allows("https://other.de/studium/x")
    assert site.allows_twin("https://example.de/en/study/jobs")


def test_normalize_url_drops_fragment_and_trailing_slash() -> None:
    assert normalize_url("https://a.de/x/#top") == "https://a.de/x"


def test_parse_page_extracts_text_links_and_twin() -> None:
    body = " ".join(["Students may work part-time while they study in Germany."] * 12)
    html = f"""<html lang="de"><head><title>Jobben im Studium | BA</title>
    <link rel="alternate" hreflang="en" href="https://a.de/en/jobs"></head>
    <body><nav><a href="/menu">Menu</a></nav>
    <main><article><h1>Jobben im Studium</h1><h2>Regeln</h2><p>{body}</p>
    <p><a href="https://a.de/studium/minijob">Minijob</a></p></article></main></body></html>"""
    page = parse_page(html, "https://a.de/studium/jobben", seed_lang=None, topic="work")
    assert page is not None
    assert page.lang == "de"
    assert page.title == "Jobben im Studium"
    assert "part-time" in page.text
    assert "https://a.de/en/jobs" in page.alternates
    assert "https://a.de/studium/minijob" in page.links

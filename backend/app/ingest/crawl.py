"""Crawl the official sources in sources.yaml into PostgreSQL + pgvector.

Pipeline per page: fetch -> extract main text (trafilatura, headings kept) -> clean ->
detect language -> chunk by heading -> embed -> upsert with a SHA-256 content hash.

Usage (from backend/):
    python -m app.ingest.crawl --list        # discover + print URLs, store nothing
    python -m app.ingest.crawl               # full crawl (idempotent)
    python -m app.ingest.crawl --limit 5     # quick test with 5 pages per site

Re-running is safe: a page whose cleaned text has the same hash as last time is skipped.
"""

import argparse
import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urldefrag, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import lxml.html
import trafilatura
import yaml
from langdetect import LangDetectException, detect

from app.ingest.chunking import chunk_document, clean_text, content_hash

SOURCES_FILE = Path(__file__).parent / "sources.yaml"
BLOCK_MARKERS = ("perfdrive.com", "radware", "captcha")
MIN_PAGE_WORDS = 50


# ---------------------------------------------------------------- config ---


@dataclass
class Seed:
    url: str
    lang: str | None = None
    topic: str | None = None


@dataclass
class Site:
    name: str
    base: str
    max_pages: int
    allow: list[str]
    deny: list[str]
    seeds: list[Seed]

    def allows(self, url: str) -> bool:
        if not url.startswith(self.base):
            return False
        path = urlparse(url).path
        if any(d in url for d in self.deny):
            return False
        return any(path.startswith(a) for a in self.allow)

    def allows_twin(self, url: str) -> bool:
        """Language twins only need to be on the same site and not denied."""
        return url.startswith(self.base) and not any(d in url for d in self.deny)


@dataclass
class Config:
    user_agent: str
    delay_seconds: float
    follow_depth: int
    sites: list[Site]


def load_config(path: Path = SOURCES_FILE) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    sites = [
        Site(
            name=s["name"],
            base=s["base"].rstrip("/"),
            max_pages=int(s.get("max_pages", 30)),
            allow=s.get("allow", []),
            deny=s.get("deny", []),
            seeds=[Seed(**seed) for seed in s["seeds"]],
        )
        for s in raw["sites"]
    ]
    return Config(
        user_agent=raw["user_agent"],
        delay_seconds=float(raw.get("delay_seconds", 1.0)),
        follow_depth=int(raw.get("follow_depth", 1)),
        sites=sites,
    )


def normalize_url(url: str) -> str:
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


# ---------------------------------------------------------------- fetching ---


class PoliteFetcher:
    """httpx client with a global delay between requests and robots.txt checks."""

    def __init__(self, user_agent: str, delay_seconds: float) -> None:
        self.delay = delay_seconds
        self.user_agent = user_agent
        self.client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Language": "en,de;q=0.8"},
            follow_redirects=True,
            timeout=20.0,
        )
        self._last = 0.0
        self._robots: dict[str, RobotFileParser] = {}

    def _wait(self) -> None:
        pause = self.delay - (time.monotonic() - self._last)
        if pause > 0:
            time.sleep(pause)
        self._last = time.monotonic()

    def get(self, url: str) -> httpx.Response:
        self._wait()
        return self.client.get(url)

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host not in self._robots:
            rp = RobotFileParser()
            try:
                resp = self.get(f"{host}/robots.txt")
                if resp.status_code >= 500:
                    rp.disallow_all = True
                elif resp.status_code >= 400:
                    rp.allow_all = True
                else:
                    rp.parse(resp.text.splitlines())
            except httpx.HTTPError:
                rp.allow_all = True
            self._robots[host] = rp
        return self._robots[host].can_fetch(self.user_agent, url)

    def close(self) -> None:
        self.client.close()


def looks_blocked(resp: httpx.Response) -> bool:
    """Bot-protection pages (e.g. Radware) return 200 with a captcha instead of content."""
    if any(m in str(resp.url).lower() for m in BLOCK_MARKERS):
        return True
    head = resp.text[:3000].lower()
    return "radware" in head or ("captcha" in head and "<form" in head)


# ---------------------------------------------------------------- parsing ---


@dataclass
class Page:
    url: str
    title: str
    lang: str
    text: str  # cleaned markdown
    topic: str | None = None
    links: list[str] = field(default_factory=list)
    alternates: list[str] = field(default_factory=list)


# Pages built with Nuxt/Vue (study-in-germany.com) keep pop-up panel content ("offcanvas")
# in an inline JavaScript state object instead of the HTML. Example: the EU / non-EU working
# rules. We read those escaped HTML strings so this content is not lost. Panel titles are
# often variables (headline:al), so we also map Nuxt's function parameters to their values.
_JS_STR = r'"(?:[^"\\]|\\.)*"'
PANEL_RE = re.compile(
    rf"(?:headline:(\w+|{_JS_STR}),\s*offcanvas:\s*\{{\s*headline:[^,]+,\s*)?introHtml:({_JS_STR})"
)


def _js_args(src: str) -> list[str | None]:
    """Parse a comma-separated list of JS literals; only strings are kept."""
    out: list[str | None] = []
    i = 0
    while i < len(src):
        ch = src[i]
        if ch in " ,\n":
            i += 1
        elif ch == '"':
            m = re.match(_JS_STR, src[i:])
            if not m:
                break
            try:
                out.append(json.loads(m.group(0)))
            except json.JSONDecodeError:
                out.append(None)
            i += m.end()
        elif ch in "[{":  # skip nested objects/arrays by bracket depth
            depth, j = 0, i
            while j < len(src):
                depth += src[j] in "[{"
                depth -= src[j] in "]}"
                j += 1
                if depth == 0:
                    break
            out.append(None)
            i = j
        else:  # number, true/false/null, void 0
            m = re.match(r"[^,]+", src[i:])
            out.append(None)
            i += m.end() if m else 1
    return out


def nuxt_variables(html: str) -> dict[str, str]:
    start = html.find("__NUXT__=(function(")
    if start < 0:
        return {}
    end = html.find("</script>", start)
    blob = html[start:end]
    params = blob[len("__NUXT__=(function(") : blob.find(")")].split(",")
    call = blob.rfind("}(")
    if call < 0:
        return {}
    args = _js_args(blob[call + 2 :].rstrip(";) \n"))
    return {p: a for p, a in zip(params, args, strict=False) if isinstance(a, str)}


# Removed before extraction:
# - page chrome: <nav>, <footer>, and <header> blocks that contain a menu (arbeitsagentur.de
#   also uses <header> inside articles for section titles, so a plain //header would be wrong)
# - glossary/tooltip pop-ups (rundfunkbeitrag.de): copied into every page, they would put the
#   same definitions into dozens of chunks and push real answers out of the top 5
REMOVE_XPATH = (
    "//nav | //footer | //header[.//nav]"
    " | //*[contains(@class, 'glossary_popover') or contains(@class, 'tooltip')]"
)
# Unwrapped (tag removed, text kept): trafilatura drops link text nested in <span>s and drops
# <button>s, but rundfunkbeitrag.de writes glossary words as inline buttons:
#   "...angemeldeten <button data-glossary-id="wohnung">Wohnung</button> zugeordnet..."
UNWRAP_XPATH = "//body//a | //p//button | //li//button | //td//button"


def prepare_html(html: str) -> str:
    """Clean the HTML before trafilatura extracts the main text."""
    tree = lxml.html.fromstring(html)
    for el in tree.xpath(REMOVE_XPATH):
        el.drop_tree()
    for el in tree.xpath(UNWRAP_XPATH):
        el.drop_tag()
    return lxml.html.tostring(tree, encoding="unicode")


SKIP_INSIDE = {"script", "style", "noscript", "form", "button", "template", "svg"}


def structural_markdown(clean_html: str) -> str:
    """Fallback extractor: headings, paragraphs and list items of the page, in order.

    trafilatura looks for ONE main article. FAQ pages built from many separate content blocks
    (rundfunkbeitrag.de: one block per question) defeat that heuristic and only one answer is
    kept. This walk keeps every block. It runs on HTML that prepare_html() already cleaned.
    """
    tree = lxml.html.fromstring(clean_html)
    lines: list[str] = []
    for el in tree.iter("h1", "h2", "h3", "h4", "p", "li"):
        if any(a.tag in SKIP_INSIDE or a.get("aria-hidden") == "true" for a in el.iterancestors()):
            continue
        if el.tag == "p" and any(a.tag == "li" for a in el.iterancestors()):
            continue  # the <li> already contains this paragraph
        text = " ".join(el.text_content().split())
        if not text:
            continue
        if el.tag.startswith("h"):
            lines.append(f"\n{'#' * int(el.tag[1])} {text}\n")
        elif el.tag == "li":
            lines.append(f"- {text}")
        else:
            lines.append(f"{text}\n")
    return "\n".join(lines)


def embedded_html_text(html: str) -> list[str]:
    """Return "Title: text" for each pop-up panel stored in the inline Nuxt state."""
    variables = nuxt_variables(html)
    texts: list[str] = []
    for head, body in PANEL_RE.findall(html):
        try:
            snippet = json.loads(body)  # undo JS escapes like \u003C
            title = json.loads(head) if head.startswith('"') else variables.get(head, "")
        except json.JSONDecodeError:
            continue
        text = " ".join(lxml.html.fromstring(f"<div>{snippet}</div>").text_content().split())
        if len(text.split()) < 5 or text in texts:
            continue
        texts.append(f"{title.strip()}: {text}" if title.strip() else text)
    return texts


def parse_page(html: str, url: str, seed_lang: str | None, topic: str | None) -> Page | None:
    cleaned = prepare_html(html)
    extracted = trafilatura.extract(
        cleaned,
        url=url,
        output_format="markdown",
        include_tables=True,
        include_links=False,
        include_images=False,
        include_comments=False,
        include_formatting=True,  # needed to keep headings as "#" lines
        favor_precision=False,  # precision mode drops most h2/h3 headings on these sites
    )
    fallback = structural_markdown(cleaned)
    # Use the fallback when trafilatura kept less than half of the page's real text.
    if not extracted or len(extracted.split()) < 0.5 * len(fallback.split()):
        extracted = fallback
    if not extracted.strip():
        return None
    text = clean_text(extracted)
    extra = [t for t in embedded_html_text(html) if t[:80] not in text]
    if extra:
        text += "\n\n## More details\n" + "\n\n".join(extra)
    if len(text.split()) < MIN_PAGE_WORDS:
        return None

    meta = trafilatura.extract_metadata(html, default_url=url)
    title = (meta.title if meta and meta.title else "").split(" | ")[0].split(" - ")[0].strip()

    tree = lxml.html.fromstring(html)
    tree.make_links_absolute(url)
    links = sorted({normalize_url(h) for h in tree.xpath("//a/@href") if h.startswith("http")})
    alternates = sorted(
        {
            normalize_url(h)
            for h in tree.xpath("//link[@rel='alternate'][@hreflang='de' or @hreflang='en']/@href")
        }
    )
    # Text detection, not <html lang>: rundfunkbeitrag.de marks its English pages as lang="de".
    lang = seed_lang or detect_lang(text)
    return Page(url, title, lang, text, topic, links, alternates)


def detect_lang(text: str) -> str:
    try:
        return "de" if detect(text[:2000]) == "de" else "en"
    except LangDetectException:
        return "en"


# ---------------------------------------------------------------- crawling ---


def crawl_site(site: Site, fetcher: PoliteFetcher, depth: int, limit: int | None) -> list[Page]:
    """Breadth-first over seeds, hreflang twins and allowed links (up to `depth` hops)."""
    max_pages = min(site.max_pages, limit) if limit else site.max_pages
    queue: list[tuple[str, int, str | None, str | None]] = [
        (normalize_url(s.url), 0, s.lang, s.topic) for s in site.seeds
    ]
    seen: set[str] = set()
    pages: list[Page] = []
    stats: Counter[str] = Counter()

    while queue and len(pages) < max_pages:
        url, level, lang, topic = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        if not fetcher.allowed(url):
            stats["robots"] += 1
            print(f"  robots.txt disallows {url}")
            continue
        try:
            resp = fetcher.get(url)
        except httpx.HTTPError as exc:
            stats["failed"] += 1
            print(f"  FAILED {url}: {exc}")
            continue
        if looks_blocked(resp):
            stats["blocked"] += 1
            print(f"  BLOCKED (bot protection) {url}")
            continue
        if resp.status_code != 200 or "html" not in resp.headers.get("content-type", ""):
            stats["failed"] += 1
            print(f"  HTTP {resp.status_code} {url}")
            continue

        final_url = normalize_url(str(resp.url))
        seen.add(final_url)
        page = parse_page(resp.text, final_url, lang, topic)
        if page is None:
            stats["empty"] += 1
            continue
        pages.append(page)

        # hreflang twins are always followed (same depth); normal links only below `depth`.
        for alt in page.alternates:
            if alt not in seen and site.allows_twin(alt):
                queue.insert(0, (alt, level, None, topic))
        if level < depth:
            for link in page.links:
                if link not in seen and site.allows(link):
                    queue.append((link, level + 1, None, topic))

    print(f"[{site.name}] {len(pages)} pages kept; skipped: {dict(stats) or 'none'}")
    return pages


# ---------------------------------------------------------------- storing ---


def store_pages(pages: list[Page]) -> Counter[str]:
    """Upsert pages. Unchanged pages (same hash) are skipped; changed pages get new chunks."""
    # Imported here so `--list` works without a database or the ML extras.
    from sqlalchemy import delete, select, update
    from sqlalchemy.orm import Session

    from app.db import get_engine, init_db
    from app.models import Chunk, Source
    from app.rag.embed import embed_passages

    init_db()
    result: Counter[str] = Counter()
    with Session(get_engine()) as session:
        for page in pages:
            digest = content_hash(page.text)
            source = session.scalar(select(Source).where(Source.url == page.url))
            if source and source.content_hash == digest:
                if source.lang != page.lang:  # metadata fix without re-embedding
                    source.lang = page.lang
                    session.execute(
                        update(Chunk).where(Chunk.source_id == source.id).values(lang=page.lang)
                    )
                    session.commit()
                    result["lang_fixed"] += 1
                result["unchanged"] += 1
                continue

            chunks = chunk_document(page.text, page.title)
            if not chunks:
                result["no_chunks"] += 1
                continue
            vectors = embed_passages([f"{page.title} > {c.heading_path}\n{c.text}" for c in chunks])

            result["changed" if source else "added"] += 1
            if source is None:
                source = Source(url=page.url)
                session.add(source)
            source.title = page.title
            source.lang = page.lang
            source.fetched_at = datetime.now(UTC)
            source.content_hash = digest
            session.flush()  # gives a new source its id

            session.execute(delete(Chunk).where(Chunk.source_id == source.id))
            for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
                session.add(
                    Chunk(
                        source_id=source.id,
                        chunk_index=i,
                        heading_path=chunk.heading_path,
                        text=chunk.text,
                        lang=page.lang,
                        embedding=vector,
                    )
                )
            session.commit()
            print(f"  stored {len(chunks):>3} chunks  {page.url}")
    return result


def prune_stale(pages: list[Page]) -> int:
    """Delete stored pages that this full crawl no longer produced (e.g. newly denied URLs).

    Only hosts that returned at least one page are pruned, so a temporary network problem
    on one site never wipes that site's data.
    """
    from sqlalchemy import delete, select
    from sqlalchemy.orm import Session

    from app.db import get_engine
    from app.models import Source

    kept = {p.url for p in pages}
    hosts = {urlparse(u).netloc for u in kept}
    with Session(get_engine()) as session:
        stale = [
            s.id
            for s in session.scalars(select(Source))
            if urlparse(s.url).netloc in hosts and s.url not in kept
        ]
        if stale:
            session.execute(delete(Source).where(Source.id.in_(stale)))  # chunks cascade
            session.commit()
    return len(stale)


# ---------------------------------------------------------------- CLI ---


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl BriefKlar's official sources.")
    parser.add_argument("--list", action="store_true", help="only print the discovered URLs")
    parser.add_argument("--limit", type=int, default=None, help="max pages per site")
    parser.add_argument("--site", default=None, help="only crawl this site name")
    args = parser.parse_args()

    config = load_config()
    fetcher = PoliteFetcher(config.user_agent, config.delay_seconds)
    all_pages: list[Page] = []
    try:
        for site in config.sites:
            if args.site and site.name != args.site:
                continue
            print(f"Crawling {site.name} ...")
            all_pages.extend(crawl_site(site, fetcher, config.follow_depth, args.limit))
    finally:
        fetcher.close()

    if args.list:
        print(f"\n{len(all_pages)} pages:")
        for p in all_pages:
            print(f"  [{p.lang}] {len(p.text.split()):>5} words  {p.url}")
        return

    result = store_pages(all_pages)
    if not args.site and not args.limit:  # only a full crawl knows what should exist
        result["pruned"] = prune_stale(all_pages)
    print(f"\nDone. {dict(result)}")


if __name__ == "__main__":
    main()

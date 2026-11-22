"""Pure text helpers for ingestion: cleaning, hashing and heading-aware chunking.

Kept free of network and database code so they are easy to unit-test.
"""

import hashlib
import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")

# Lines that are page chrome, not content. Matched case-insensitively against the whole line.
BOILERPLATE_RE = re.compile(
    r"^(zum seitenanfang|nach oben|back to top|teilen|share|drucken|print|"
    r"cookie[- ]?einstellungen|cookie settings|seite drucken)$",
    re.IGNORECASE,
)

# About 400 tokens: e5's tokenizer produces ~1.3 tokens per English word and ~1.5 per German
# word, so 280 words stays safely under the model's 512-token limit in both languages.
MAX_WORDS = 280
OVERLAP_WORDS = 40
MIN_WORDS = 8


@dataclass(frozen=True)
class TextChunk:
    heading_path: str
    text: str


def clean_text(markdown: str) -> str:
    """Normalise whitespace and drop obvious navigation lines."""
    lines: list[str] = []
    # Soft hyphens (U+00AD) are invisible but split words: "Melde\u00adämter" != "Meldeämter".
    markdown = markdown.replace("\u00ad", "")
    for raw in markdown.replace("\r\n", "\n").split("\n"):
        line = re.sub(r"[ \t ]+", " ", raw).strip()
        if BOILERPLATE_RE.match(line):
            continue
        lines.append(line)
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_sections(markdown: str, title: str = "") -> list[tuple[str, str]]:
    """Split markdown by headings. Returns (heading_path, body) pairs.

    heading_path looks like "Studying in Germany > Working while studying > Hour limits".
    """
    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []  # (level, heading text)
    body: list[str] = []

    def path() -> str:
        parts = [h for _, h in stack]
        if title and (not parts or parts[0] != title):
            parts.insert(0, title)
        return " > ".join(parts)

    def flush() -> None:
        text = "\n".join(body).strip()
        if text:
            sections.append((path(), text))
        body.clear()

    for line in markdown.split("\n"):
        match = HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, match.group(2).strip()))
        else:
            body.append(line)
    flush()
    return sections


def window_words(text: str, max_words: int, overlap: int) -> list[str]:
    """Split text into overlapping word windows."""
    words = text.split()
    if len(words) <= max_words:
        return [text]
    step = max_words - overlap
    windows: list[str] = []
    for start in range(0, len(words), step):
        windows.append(" ".join(words[start : start + max_words]))
        if start + max_words >= len(words):
            break
    return windows


def chunk_document(
    markdown: str,
    title: str = "",
    max_words: int = MAX_WORDS,
    overlap: int = OVERLAP_WORDS,
) -> list[TextChunk]:
    """Heading first, then fixed-size word windows with overlap.

    Very short sections (e.g. one sentence under a heading) are not dropped: they are carried
    into the next section, so a short but important rule still ends up in a chunk.
    """
    chunks: list[TextChunk] = []
    carry = ""
    last_path = title
    for heading_path, body in split_sections(markdown, title):
        body = f"{carry}\n{body}".strip() if carry else body
        last_path = heading_path
        if len(body.split()) < MIN_WORDS:
            carry = body
            continue
        carry = ""
        for piece in window_words(body, max_words, overlap):
            chunks.append(TextChunk(heading_path=heading_path, text=piece))
    if carry:
        if chunks:
            prev = chunks[-1]
            chunks[-1] = TextChunk(prev.heading_path, f"{prev.text}\n{carry}")
        else:
            chunks.append(TextChunk(heading_path=last_path, text=carry))
    return chunks

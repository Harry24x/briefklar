"""Dump all stored chunks to eval/corpus.jsonl (one JSON object per line).

Used to draft and check the eval questions against what is really in the database.
The file is git-ignored: it is a copy of public pages, regenerated any time.

Usage (from backend/):  python -m app.ingest.export
"""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Chunk, Source

OUT = Path(__file__).resolve().parents[3] / "eval" / "corpus.jsonl"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with Session(get_engine()) as session, OUT.open("w", encoding="utf-8") as f:
        rows = session.execute(
            select(Chunk, Source)
            .join(Source, Chunk.source_id == Source.id)
            .order_by(Source.url, Chunk.chunk_index)
        )
        for chunk, source in rows:
            record = {
                "chunk_id": chunk.id,
                "url": source.url,
                "title": source.title,
                "lang": chunk.lang,
                "heading_path": chunk.heading_path,
                "text": chunk.text,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    print(f"Wrote {count} chunks to {OUT}")


if __name__ == "__main__":
    main()

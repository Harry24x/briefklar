"""Load eval/fixtures/corpus.jsonl.gz into an EMPTY database (used by the CI eval job).

Usage (from backend/):  python -m app.ingest.load_fixture
"""

import gzip
import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_engine, init_db
from app.ingest.export import FIXTURE
from app.models import Chunk, Source


def main() -> None:
    init_db()
    with Session(get_engine()) as session:
        if session.scalar(select(func.count()).select_from(Source)):
            raise SystemExit("Database is not empty; refusing to load the fixture on top of it.")
        sources: dict[str, Source] = {}
        count = 0
        with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r["url"] not in sources:
                    sources[r["url"]] = Source(
                        url=r["url"],
                        title=r["title"],
                        lang=r["source_lang"],
                        fetched_at=datetime.fromisoformat(r["fetched_at"])
                        if r["fetched_at"]
                        else None,
                        content_hash=r["content_hash"],
                    )
                    session.add(sources[r["url"]])
                    session.flush()
                session.add(
                    Chunk(
                        source_id=sources[r["url"]].id,
                        chunk_index=r["chunk_index"],
                        heading_path=r["heading_path"],
                        text=r["text"],
                        lang=r["lang"],
                        embedding=r["embedding"],
                    )
                )
                count += 1
        session.commit()
    print(f"Loaded {count} chunks from {len(sources)} pages.")


if __name__ == "__main__":
    main()

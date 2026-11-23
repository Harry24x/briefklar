"""Export the stored chunks.

python -m app.ingest.export            -> eval/corpus.jsonl (text only, git-ignored; for
                                          drafting and checking eval questions)
python -m app.ingest.export --fixture  -> eval/fixtures/corpus.jsonl.gz (text + embeddings,
                                          committed; CI loads it with app.ingest.load_fixture
                                          so the eval job needs no live crawling)
"""

import argparse
import gzip
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Chunk, Source

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "eval" / "corpus.jsonl"
FIXTURE = ROOT / "eval" / "fixtures" / "corpus.jsonl.gz"


def rows(session: Session):
    query = (
        select(Chunk, Source)
        .join(Source, Chunk.source_id == Source.id)
        .order_by(Source.url, Chunk.chunk_index)
    )
    yield from session.execute(query)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", action="store_true", help="include embeddings, gzip")
    args = parser.parse_args()

    out = FIXTURE if args.fixture else CORPUS
    out.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if args.fixture else open
    count = 0
    with Session(get_engine()) as session, opener(out, "wt", encoding="utf-8") as f:
        for chunk, source in rows(session):
            record = {
                "chunk_id": chunk.id,
                "url": source.url,
                "title": source.title,
                "lang": chunk.lang,
                "heading_path": chunk.heading_path,
                "text": chunk.text,
            }
            if args.fixture:
                record |= {
                    "chunk_index": chunk.chunk_index,
                    "source_lang": source.lang,
                    "fetched_at": source.fetched_at.isoformat() if source.fetched_at else None,
                    "content_hash": source.content_hash,
                    "embedding": [round(float(x), 6) for x in chunk.embedding],
                }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    print(f"Wrote {count} chunks to {out}")


if __name__ == "__main__":
    main()

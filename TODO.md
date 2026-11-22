# TODO

## Build plan (3 sessions)

- [x] **Part 1 (Sat night):** repo skeleton, Docker Compose DB, `/health`, CI, `sources.yaml` seeds, crawler code
- [ ] **Part 2 (Sunday):** crawl + embeddings → `/ask` vector baseline → eval sets + `run_eval.py` → hybrid + RRF → re-ranker + threshold + citation check (eval after each)
- [ ] **Part 3 (Monday):** letter path + agent (2 tools) + .ics → Next.js frontend → tests to ~15 + CI eval job → deploy → README + LEARNING.md

## Open decisions / risks

- [ ] Approve the final crawl URL list (`python -m app.ingest.crawl --list`)
- [x] make-it-in-germany.com blocked 12/12 requests (Radware bot protection). Replaced with study-in-germany.com (DAAD, federally funded); we do not bypass bot protection.
- [ ] `sentence-transformers` pulls in PyTorch (CPU build is large). Installed only via the `ml` extra and in the Docker image, not in CI.
- [ ] Oracle ARM VM: create account + try to get capacity on Sunday; fallback Render + Neon (`RERANKER_ENABLED=false`).

## Decisions

- Re-ranker: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (~470 MB, multilingual) instead of `BAAI/bge-reranker-v2-m3` (~2.3 GB): lighter and faster on CPU. Swap via `RERANKER_MODEL` to compare later.

- LLM: Groq shut down `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` on 16.08.2026. Switched to Groq's recommended replacements `openai/gpt-oss-120b` (answers) and `openai/gpt-oss-20b` (fallback, query rewrite, eval judge). Reasoning effort `low`.

## Skipped for the MVP (v2 roadmap)

- Photo/PDF upload, OCR, Presidio, weekly re-crawl, admin page, feedback buttons
- More than 2 agent tools, more than 3 sources
- Terraform (stretch goal only)

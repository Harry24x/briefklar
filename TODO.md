# TODO

## Build plan (3 sessions)

- [x] **Part 1 (Sat night):** repo skeleton, Docker Compose DB, `/health`, CI, `sources.yaml` seeds, crawler code
- [ ] **Part 2 (Sunday):** crawl + embeddings → `/ask` vector baseline → eval sets + `run_eval.py` → hybrid + RRF → re-ranker + threshold + citation check (eval after each)
- [ ] **Part 3 (Monday):** letter path + agent (2 tools) + .ics → Next.js frontend → tests to ~15 + CI eval job → deploy → README + LEARNING.md

## Open decisions / risks

- [ ] Approve the final crawl URL list (`python -m app.ingest.crawl --list`)
- [ ] make-it-in-germany.com uses Radware bot protection. The crawler detects block pages and reports them as `BLOCKED`. If many pages are blocked, swap the site (e.g. bamf.de) — needs Harman's OK.
- [ ] `sentence-transformers` pulls in PyTorch (CPU build is large). Installed only via the `ml` extra and in the Docker image, not in CI.
- [ ] Oracle ARM VM: create account + try to get capacity on Sunday; fallback Render + Neon (`RERANKER_ENABLED=false`).

## Skipped for the MVP (v2 roadmap)

- Photo/PDF upload, OCR, Presidio, weekly re-crawl, admin page, feedback buttons
- More than 2 agent tools, more than 3 sources
- Terraform (stretch goal only)

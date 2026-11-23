# TODO

## Build plan (3 sessions)

- [x] **Part 1 (Sat night):** repo skeleton, Docker Compose DB, `/health`, CI, `sources.yaml` seeds, crawler code
- [x] **Part 2 (Sunday):** crawl + embeddings → `/ask` → eval sets + `run_eval.py` → hybrid + RRF → re-ranker + threshold + citation check (results in `eval/NOTES.md`)
- [x] **Part 3 (Sunday evening):** letter path + agent (2 tools) + .ics → Next.js frontend → tests (46) + CI eval job → deploy files → README + LEARNING.md
- [x] Letter eval: field accuracy 1.00, 0 PII leaks, calendar 5/5 (calendar safety net added after the first run)
- [ ] **Monday:** export CI fixture, move CI file, commit + push, add `GROQ_API_KEY` secret, screenshot in README
- [ ] **Later:** deploy (DEPLOY.md, needs a free Oracle Ampere VM), fill Impressum/Privacy, live link

## Open decisions / risks

- [x] Approve the final crawl URL list
- [ ] q30 safety: query rewrite now returns one German + one English query, and the prompt forbids yes/no without a source for that exact case. Measure: `run_eval.py --answers --rewrite`
- [ ] q04: prompt now tells the model to name both values when sources disagree. Measure: `run_eval.py --answers`
- [x] make-it-in-germany.com blocked 12/12 requests (Radware bot protection). Replaced with study-in-germany.com (DAAD, federally funded); we do not bypass bot protection.
- [ ] `sentence-transformers` pulls in PyTorch (CPU build is large). Installed only via the `ml` extra and in the Docker image, not in CI.
- [ ] Hosting: Oracle Always Free Ampere A1 (free for life, but often "out of capacity"). Free 512 MB–1 GB hosts are too small for PyTorch; Hugging Face Docker Spaces now need a paid plan. Postponed.
- [ ] Add `GROQ_API_KEY` as a GitHub Actions secret so the CI eval job runs

## Decisions

- Re-ranker: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (~470 MB, multilingual) instead of `BAAI/bge-reranker-v2-m3` (~2.3 GB): lighter and faster on CPU. Swap via `RERANKER_MODEL` to compare later.

- LLM: Groq shut down `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` on 16.08.2026. Switched to Groq's recommended replacements `openai/gpt-oss-120b` (answers) and `openai/gpt-oss-20b` (fallback, query rewrite, eval judge). Reasoning effort `low`.

## Skipped for the MVP (v2 roadmap)

- Photo/PDF upload, OCR, Presidio, weekly re-crawl, admin page, feedback buttons
- More than 2 agent tools, more than 3 sources
- Terraform (stretch goal only)

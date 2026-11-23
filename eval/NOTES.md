# Eval notes (results, failures and decisions)

All numbers come from `eval/run_eval.py` output in `eval/results/` (see `summary.md`).
Eval set: 30 answerable questions (15 EN, 15 DE), 10 unanswerable, 5 synthetic letters.

## Final results — 22./23.11.2026

| Mode | hit@5 | MRR | Correctness | Refusal acc | p95 latency |
|---|---|---|---|---|---|
| vector | 0.83 | 0.73 | – | 0.00 | 0.08 s |
| hybrid (vector + full-text, RRF k=60) | 0.77 | 0.64 | – | 0.00 | 0.08 s |
| hybrid + re-rank | **0.97** | **0.83** | – | 0.80 | 5.22 s |
| hybrid + re-rank + answers (judge v1, strict) | 0.97 | 0.83 | 0.70 | 0.90 | 19.95 s |
| hybrid + re-rank + answers (judge v2) | 0.97 | 0.83 | 0.93 | 1.00 | 19.95 s |
| hybrid + re-rank + answers, answer prompt v2 (23.11.) | **0.97** | **0.84** | **0.93** | **1.00** | 48.18 s |

Setup: embeddings `intfloat/multilingual-e5-small`, re-ranker `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`,
answers `openai/gpt-oss-120b` (Groq), judge `openai/gpt-oss-20b`, refusal threshold `MIN_SCORE = -1.0`.
Latency measured on a laptop CPU; the answer runs include waiting for Groq's free-tier rate limit
(the 23.11. run hit the tokens-per-minute limit more often, hence the higher p95).

## What the numbers show

1. **Hybrid search alone was worse than vector search** (hit@5 0.77 vs 0.83). Full-text search
   with OR-matching favours long, keyword-heavy pages (e.g. the "companies and institutions"
   page), and RRF gives that noisy list the same weight as the vector list.
2. **The re-ranker is the biggest win** (+0.20 hit@5 over hybrid). It reads question and chunk
   together and pushes the keyword noise down.
3. **Refusal needs the re-ranker.** e5 cosine similarities were ~0.82–0.91 for answerable and
   unanswerable questions alike, so no vector threshold separates them (refusal acc 0.00).
   Re-ranker logits (-6.9 … +10.9) do. The answer step adds a second guard: the LLM refused
   u01 (citizenship) although retrieval passed it.
4. **Latency is the cost:** 0.1 s → 5 s with the re-ranker on CPU; ~20 s p95 end-to-end on the
   free Groq tier (8,000 tokens/min for gpt-oss-120b ≈ 2–3 answers per minute).

## Remaining failures (answer prompt v2, 23.11.2026)

Answer prompt v2 added two rules: name both values when sources disagree (rule 7), and only
answer yes/no when a source covers exactly that situation (rule 8). Correctness stayed at 0.93,
but the type of failure changed.

| id | Before (prompt v1) | Now (prompt v2) | Why |
|---|---|---|---|
| **q30** | Confident wrong **"Ja"** (correct: "Nein", apprentices with Ausbildungsvergütung get no exemption) | **Refuses** ("nothing found in the official sources") | Retrieval miss: German question, answer only on the English page. A refusal is still a failure, but a safe one: **no confident wrong answer left in the set.** Query rewrite (one German + one English query) should fix the retrieval; the run with `--rewrite` stopped at Groq's daily token limit (200k) and is still open. |
| **q04** | Income tax above 603 €/month | Same answer | **Conflict between official sources**: study-in-germany.com says "up to 603 euros a month … without paying taxes"; arbeitsagentur.de gives the annual tax-free allowance of 12,348 €. The arbeitsagentur chunk was only rank 4 and rule 7 did not trigger; the model still followed source [1]. Possible next step: give the more specific official source (arbeitsagentur) priority for tax questions. |

## Changes made after seeing results (documented on purpose)

These make the numbers more correct, but they were made after looking at the outputs, so the
final scores are somewhat optimistic. A held-out set is planned for v2.

- **Judge rubric v1 → v2.** v1 marked short correct answers as wrong when they left out secondary
  details of my long expected answers (q01, q03, q06, q18, q25). v2 grades the core fact for the
  question and still fails contradictions. Both scores are reported above.
- **Label fixes (each checked against the page by hand):**
  - q09: the English students page also answers it → added to `expected_urls`.
  - q21: study-in-germany gives ~140 €/month in total, which matches the arbeitsagentur
    breakdown (87 € + extra contribution + care insurance) → expected answer covers both.
  - q27: arbeitsagentur states a 90-calendar-day limit; the model's answer was correct → added.
  - u07: the original question (fare-dodging fine) *is* answered by the corpus ("at least 60
    euros"), so it was not unanswerable → replaced with a dog-tax question.
- **Refusal threshold:** `--tune` suggested -0.76 (exactly q19's score, i.e. fitted to this set);
  chose the rounder **-1.0** with the same accuracy. Tuned and measured on the same 40 questions.

## Letter path (`--letters`, 5 synthetic letters)

- Field accuracy 1.00 (20/20 fields: type, sender, deadline, amount), 0 fake names, IBANs or
  addresses found in any prompt sent to the LLM, p95 latency 26.8 s.
- 3/5 explanations answered. l04 (Ausländerbehörde) and l05 (Krankenkasse) were refused because
  no crawled source covers them. That is correct, and the fix is more sources, not a lower threshold.
- First run: only 3/5 letters got a calendar file. l01 hit the 20 s time budget after one search
  (CPU re-ranking plus Groq rate-limit waits), and in l03 the planner finished without the
  calendar step. The calendar needs no LLM, so it is now a deterministic step after planning:
  5/5 letters get a reminder.
- The planner also repeated an identical search (l04, l05). Identical queries are now rejected
  and the fixed plan takes over.

## Crawling problems found and fixed

- make-it-in-germany.com blocked 12/12 requests (Radware bot protection) → replaced with
  study-in-germany.com; bot protection is respected, not bypassed.
- study-in-germany.com: link text nested in `<span>`s was dropped, and the EU / non-EU work rules
  live in JavaScript pop-up state → links flattened, pop-up text read with its titles.
- rundfunkbeitrag.de: glossary pop-ups were copied into almost every chunk (one amount appeared
  in 57 chunks), glossary words were inline `<button>`s, soft hyphens split words, and FAQ pages
  with one block per question kept only one answer → pop-ups removed, buttons unwrapped, soft
  hyphens stripped, structural fallback extractor when trafilatura keeps < 50 % of the text.

## Model change during the project

Groq shut down `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` on 16.08.2026. BriefKlar uses
Groq's recommended replacements `openai/gpt-oss-120b` and `openai/gpt-oss-20b` (reasoning effort
`low`). Retrieval numbers are unaffected; answer numbers are for gpt-oss-120b.

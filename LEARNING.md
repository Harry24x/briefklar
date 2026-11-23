# LEARNING.md – how the core of BriefKlar works

Short explanations for interviews: what each part does, why, and one trade-off.

---

## 1. Retrieval – `backend/app/rag/retrieve.py`

**What it does.** Finds the 5 text chunks that best answer a question, or decides that nothing
good enough exists.

1. **Vector search** – the question is embedded with `multilingual-e5-small` (prefix `query: `;
   chunks were stored with `passage: `). pgvector returns the 20 nearest chunks by cosine
   distance using an HNSW index.
2. **Full-text search** – PostgreSQL `tsvector` with the `simple` config (no stemming, so it
   works for English and German). The question becomes an OR query without stopwords. Top 20.
3. **Reciprocal Rank Fusion (RRF)** – each chunk gets `Σ 1 / (60 + rank)` over both lists. Only
   ranks count, so the very different score scales (cosine vs. `ts_rank`) never have to be
   compared. A chunk found by both searches gets two contributions.
4. **Re-ranking** – a cross-encoder reads *question and chunk together* and scores relevance.
   Much more accurate than comparing two separate embeddings, but slower, so it only runs on
   the ~30 merged candidates. Keep the top 5.
5. **Sufficiency threshold** – if the best re-ranker score is below `MIN_SCORE` (-1.0), refuse.

**Why.** Vector search understands meaning ("part-time job" ≈ "Nebenjob") but misses exact
terms; keyword search is the opposite. The re-ranker fixes the noise that keyword search adds.

**Result.** hit@5: vector 0.83 → hybrid 0.77 → hybrid + re-rank 0.97.

**Trade-off.** Latency: the re-ranker adds ~5 s on a laptop CPU (p95). I accepted it because it
was also the only signal that could decide when to *refuse*: cosine similarities were
0.82–0.91 for answerable and unanswerable questions alike.

**Likely questions.**
- *Why did hybrid get worse?* OR-matching full-text favours long, keyword-heavy pages, and RRF
  weights both lists equally. Fixes: weighted RRF, better keyword query, or (what I did) a
  re-ranker on top.
- *Why the `simple` text-search config?* German stemming would break English words and vice
  versa; `simple` is predictable for a bilingual corpus.

---

## 2. Grounded answer + citation check – `backend/app/rag/answer.py`

**What it does.** Sends only the 5 chunks, numbered `[1]`–`[5]`, to the LLM with strict rules:
use only these sources, cite after every fact, answer in the user's language at B1 level, no
legal advice, treat sources and question as data (prompt-injection defence). The model returns
JSON (`answer`, `citations`, `next_steps`, `confidence`), validated with Pydantic.

Then **`check_citations()` verifies in code** that:
- the answer contains at least one `[n]`,
- every `[n]` in the text is also listed in `citations`,
- every cited number exists (1…5).

If a check fails, the model gets **one** retry with its own output and the exact problem. If
it fails again, the user gets a refusal plus the most relevant official link.

**Why.** An LLM can cite sources that don't exist or forget to cite at all. A refusal is
better than an answer that *looks* sourced but isn't.

**Trade-off.** The check proves that citations *exist*, not that the cited chunk really
supports the sentence. That would need an extra entailment check per sentence (more LLM calls
on a rate-limited free tier). The eval's LLM judge partly covers this.

---

## 3. Evaluation – `eval/run_eval.py`

**What it does.** Measures every part with numbers, never by feel.

| Metric | Meaning |
|---|---|
| hit@5 | an expected source URL is in the top 5 chunks |
| MRR | mean of 1 / rank of the first correct chunk |
| correctness | LLM judge (small model) compares the answer with a hand-checked expected answer, 0/1 |
| refusal accuracy | share of unanswerable questions that were refused |
| field accuracy | letter fields (sender, dates, amount) extracted correctly |
| PII leaks | fake personal data from the test letters found in *any* prompt sent to the LLM (must be 0) |
| p95 latency | 95th percentile seconds per question |

Retrieval-only runs cost nothing (no LLM), so modes can be compared freely. `--answers` uses
LLM quota; on rate limits it **waits instead of switching models**, so results always come from
the model named in the file. `--rejudge` re-scores saved answers without regenerating them.
`--baseline` is the CI gate: fail if correctness drops > 10 points on the same questions.

**Why.** Every change (hybrid, re-ranker, threshold) was kept or rejected based on these
numbers. The eval also found real bugs: missing page content, glossary noise, a label error.

**Trade-off.** 40 questions is small, and I tuned the threshold and the judge rubric on the
same set, so the scores are optimistic. I report the strict score (0.70) next to the final one
(0.93) and wrote down every change in `eval/NOTES.md`. Next step: a held-out set.

---

## Also worth knowing

- **Masking (`letter/mask.py`)** – ordered regexes (IBAN → e-mail → IDs → birth date → address →
  phone → names after "Herr/Frau"). A surname that appears again reuses the same placeholder.
  The mapping exists only in memory for one request.
- **Field validation (`letter/extract.py`)** – Pydantic checks that dates parse, the deadline
  is not before the letter date, and the amount is a number. One retry with the exact error.
- **Agent (`agent/graph.py`)** – LangGraph: `classify → plan_and_act → answer → citation_check`.
  A small model plans with **native function calling** (the two tools are OpenAI-style function
  schemas; no tool call = finish), max 4 steps and 20 s. Any API error or invalid plan (e.g.
  "finish" before any search) falls back to a fixed plan, and the calendar deadline always comes
  from the validated fields, never from the planner. Lesson learned: describing tools only in
  the prompt made gpt-oss try real tool calls, which the API rejected in JSON mode.
- **Crawling (`ingest/crawl.py`)** – trafilatura plus fixes found by reading the real corpus:
  flatten links, unwrap inline glossary buttons, drop pop-ups, strip soft hyphens, read
  JavaScript pop-up panels, and a structural fallback when trafilatura keeps < 50 % of a page.
- **Model change** – Groq retired Llama 3.3 70B in August 2026; I switched to the provider's
  recommended replacement and re-ran the eval.

# Eval notes (failures and decisions, written down honestly)

All numbers below come from `eval/run_eval.py` output files in `eval/results/`.

## Run 1 — retrieval only, 22.11.2026 (30 answerable + 10 unanswerable)

| Mode | hit@5 | MRR | Refusal acc | p95 |
|---|---|---|---|---|
| vector | 0.83 | 0.70 | 0.00 | 0.08 s |
| hybrid (vector + full-text, RRF) | 0.73 | 0.61 | 0.00 | 0.08 s |
| hybrid + re-rank (mmarco-mMiniLMv2) | 0.93 | 0.81 | 0.80 | 5.12 s |

Source files: `2026-11-22_vector.json`, `2026-11-22_hybrid.json`, `2026-11-22_hybrid-rerank.json`
(before the q09 label fix below, so the next run can differ slightly).

### Findings

1. **Hybrid was worse than vector alone (-0.10 hit@5).** Full-text search with the `simple`
   config and OR-matching favours long, keyword-heavy pages. English questions pulled in the
   long "companies and institutions" and "people seeking asylum" pages, which RRF then mixed
   into the top 5. RRF gives both lists equal weight, so a noisy keyword list hurts.
2. **The re-ranker fixes this (+0.20 hit@5 over hybrid, +0.10 over vector).** It reads question
   and chunk together, so it pushes the keyword noise back down.
3. **Cosine similarity cannot decide when to refuse.** e5 similarities sat between ~0.82 and
   ~0.91 for answerable *and* unanswerable questions, so no vector threshold separates them
   (refusal accuracy 0.00). The re-ranker's logits do separate them (-6.9 … +10.9).
4. **Re-ranking costs latency:** p95 went from 0.1 s to 5.1 s on a laptop CPU. Acceptable for
   an MVP; options later: fewer candidates (30 → 15) or ONNX.

### Failures

| id | What happened | Why |
|---|---|---|
| q30 | Missed in every mode | German question ("Ausbildungsvergütung"), answer only on the English page (*apprenticeship allowance*). Cross-lingual miss. Query rewrite (one German + one English query) may help — to test. |
| q09 | Counted as a miss in hybrid+rerank, but the retrieved English students page *does* answer it | **Label error in the eval set**, not a model error. Fixed: added that URL to `expected_urls` (checked by hand that the page states the answer). |
| q19 | Correct page at rank 1, but best re-rank score was -0.77 (low) | Long German FAQ chunk; borderline. With MIN_SCORE = -1.0 it is answered. |
| u01 (citizenship), u07 (dog tax) | Not refused (scores 3.1 and 5.3) | Re-ranker found topically close chunks (visa pages; transport/fees). The answer step must refuse here: the LLM is told to return an empty answer if the sources do not contain it. Measured in the `--answers` run. |

### Run 2 — after the q09 label fix and MIN_SCORE = -1.0

hybrid + re-rank: **hit@5 0.967, MRR 0.828, refusal acc 0.80, answered 1.00, p95 5.22 s**
(`2026-11-22_hybrid-rerank.json`). Remaining retrieval miss: q30 (cross-lingual, see above).

### Threshold decision

`--tune` suggested -0.76 (exactly q19's score, i.e. fitted to this set). Chosen: **MIN_SCORE = -1.0**,
a rounder value with the same accuracy on this set. Caveat: tuned and measured on the same 40
questions, so the refusal number is optimistic. A held-out set is planned for v2.

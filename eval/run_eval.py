"""BriefKlar evaluation.

Run from the repo root with the backend venv active:
    python eval/run_eval.py --mode vector                  # retrieval metrics only (no LLM, free)
    python eval/run_eval.py --mode hybrid+rerank --answers # + answers and LLM-as-judge (uses quota)
    python eval/run_eval.py --mode hybrid+rerank --tune    # suggest a refusal threshold

Metrics
  hit@5        share of answerable questions where an expected URL is among the top-5 chunks
  MRR          mean of 1/rank of the first chunk from an expected URL (0 if none in top 5)
  correctness  LLM judge (GROQ_FALLBACK_MODEL = openai/gpt-oss-20b): does the answer match
               the expected answer? 0/1
  refusal acc  share of unanswerable questions that were refused
  answered     share of answerable questions that were NOT refused (catches over-refusing)
  p95 latency  95th percentile seconds per question for the full path that was run

Each run writes eval/results/<date>_<mode>[_answers].json and adds a row to summary.md.
Numbers in the README must come from these files, never typed by hand.
"""

import argparse
import json
import random
import statistics
import sys
import time
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.ingest.crawl import normalize_url
from app.llm import LLMError, chat_json, record_prompts
from app.rag.pipeline import ask
from app.rag.retrieve import MODES, retrieve

EVAL_DIR = Path(__file__).resolve().parent
RESULTS = EVAL_DIR / "results"

# Rubric v2 (22.11.2026). v1 also required every secondary detail of the (long) expected
# answer, so short but correct answers scored 0. v2 judges the core fact for THIS question.
JUDGE_PROMPT = """You grade answers of a question-answering system about German bureaucracy.
Compare the SYSTEM ANSWER with the EXPECTED ANSWER for the given QUESTION.
Score 1 if the system answer gives the core fact that answers the question (the right number,
limit, deadline, yes/no or condition) and nothing it says contradicts the expected answer.
Missing secondary details from the expected answer are fine.
Score 0 if the core fact is missing or wrong, if any statement contradicts the expected
answer, or if the system refused.
Return only JSON: {"score": 0 or 1, "reason": "<one short sentence>"}"""
JUDGE_VERSION = "v2"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def ranks_of_expected(urls: list[str], expected: list[str]) -> int | None:
    """1-based rank of the first retrieved chunk whose page is an expected URL."""
    wanted = {normalize_url(u) for u in expected}
    for rank, url in enumerate(urls, start=1):
        if normalize_url(url) in wanted:
            return rank
    return None


def judge(question: str, expected: str, answer: str) -> tuple[int, str]:
    settings = get_settings()
    messages = [
        {"role": "system", "content": JUDGE_PROMPT},
        {
            "role": "user",
            "content": f"QUESTION: {question}\nEXPECTED ANSWER: {expected}\n"
            f"SYSTEM ANSWER: {answer}",
        },
    ]
    result = chat_json(
        messages, model=settings.groq_fallback_model, max_tokens=100, allow_fallback=False
    )
    data = json.loads(result.content)
    return int(data.get("score", 0) == 1), str(data.get("reason", ""))


def with_retry(fn, *args, tries: int = 3, wait: float = 30.0):
    """The eval must not silently switch models, so on rate limits it waits instead."""
    for attempt in range(tries):
        try:
            return fn(*args)
        except LLMError as exc:
            if "tokens per day" in str(exc):
                # Waiting 30 s does not help with the daily limit; stop cleanly instead.
                raise SystemExit(
                    "Groq's daily token limit is used up. Nothing was saved. "
                    "Run the eval again tomorrow (the limit resets every 24 h)."
                ) from exc
            if attempt == tries - 1:
                raise
            print(f"    rate limited / error, waiting {wait:.0f}s ({exc})")
            time.sleep(wait)
    return None


def ask_or_raise(session: Session, q: dict, args: argparse.Namespace):
    """The API turns LLM errors into a polite refusal. For the eval that would count a rate
    limit as a refusal, so here we raise instead and let with_retry wait and try again."""
    trace = ask(
        session,
        q["question"],
        q.get("lang"),
        args.mode,
        allow_fallback=False,
        query_rewrite=args.rewrite,
    )
    if trace.outcome and (trace.outcome.failure or "").startswith("llm_error"):
        raise LLMError(trace.outcome.failure)
    return trace


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


def suggest_threshold(pos: list[float], neg: list[float]) -> tuple[float, float]:
    """Pick the threshold that maximises (answerable kept + unanswerable refused) / total."""
    best_t, best_acc = 0.0, -1.0
    for t in sorted(set(pos + neg + [0.0])):
        kept = sum(s >= t for s in pos)
        refused = sum(s < t for s in neg)
        acc = (kept + refused) / max(1, len(pos) + len(neg))
        if acc > best_acc:
            best_t, best_acc = t, acc
    return best_t, best_acc


def run(args: argparse.Namespace) -> dict:
    questions = load_jsonl(EVAL_DIR / "questions.jsonl")
    unanswerable = load_jsonl(EVAL_DIR / "unanswerable.jsonl")
    if args.limit:
        questions, unanswerable = questions[: args.limit], unanswerable[: max(1, args.limit // 3)]
    if not questions:
        sys.exit("eval/questions.jsonl is empty or missing.")

    rows: list[dict] = []
    latencies: list[float] = []

    with Session(get_engine()) as session:
        for kind, items in (("answerable", questions), ("unanswerable", unanswerable)):
            for q in items:
                start = time.perf_counter()
                if args.answers:
                    trace = with_retry(ask_or_raise, session, q, args)
                    retrieval, response = trace.retrieval, trace.response
                    refused = response.refused
                    model = trace.outcome.model if trace.outcome else None
                else:
                    retrieval = retrieve(session, q["question"], mode=args.mode)
                    response, refused, model = None, not retrieval.sufficient, None
                latencies.append(time.perf_counter() - start)

                urls = [c.url for c in retrieval.chunks]
                rank = (
                    ranks_of_expected(urls, q.get("expected_urls", []))
                    if kind == "answerable"
                    else None
                )
                row = {
                    "id": q["id"],
                    "kind": kind,
                    "question": q["question"],
                    "lang": q.get("lang"),
                    "rank": rank,
                    "best_score": round(retrieval.best_score, 4),
                    "refused": refused,
                    "top_urls": list(dict.fromkeys(urls)),
                    "model": model,
                }
                if args.answers and response is not None:
                    row["answer"] = response.answer
                    if kind == "answerable":
                        if refused:
                            row["score"], row["judge_reason"] = 0, "refused"
                        else:
                            time.sleep(args.sleep)
                            row["score"], row["judge_reason"] = with_retry(
                                judge, q["question"], q["expected_answer"], response.answer
                            )
                    time.sleep(args.sleep)
                rows.append(row)
                print(
                    f"  {q['id']:>6} rank={rank} best={retrieval.best_score:.3f} refused={refused}"
                )

    ans = [r for r in rows if r["kind"] == "answerable"]
    una = [r for r in rows if r["kind"] == "unanswerable"]
    metrics = {
        "hit@5": round(sum(r["rank"] is not None for r in ans) / len(ans), 3),
        "mrr": round(sum(1 / r["rank"] for r in ans if r["rank"]) / len(ans), 3),
        "answered_rate": round(sum(not r["refused"] for r in ans) / len(ans), 3),
        "refusal_acc": round(sum(r["refused"] for r in una) / len(una), 3) if una else None,
        "correctness": (
            round(statistics.mean(r["score"] for r in ans), 3) if args.answers else None
        ),
        "p95_latency_s": round(p95(latencies), 2),
        "field_acc": None,  # letters path: added on Monday
        "pii_leaks": None,  # letters path: added on Monday
    }

    if args.tune or not una:
        pos = [r["best_score"] for r in ans if r["rank"] is not None]
        neg = [r["best_score"] for r in una]
        if neg:
            t, acc = suggest_threshold(pos, neg)
            metrics["suggested_threshold"] = {"value": t, "accuracy": round(acc, 3)}

    settings = get_settings()
    return {
        "date": date.today().isoformat(),
        "mode": args.mode,
        "answers": args.answers,
        "query_rewrite": args.rewrite,
        "thresholds": {"min_score": settings.min_score, "min_vector_sim": settings.min_vector_sim},
        "answer_model": settings.groq_model if args.answers else None,
        "judge_version": JUDGE_VERSION if args.answers else None,
        "n_answerable": len(ans),
        "n_unanswerable": len(una),
        "metrics": metrics,
        "rows": rows,
    }


def rejudge(path: Path, args: argparse.Namespace) -> dict:
    """Re-score saved answers with the current judge and expected answers (no new answers).

    Unanswerable questions whose text changed since the run are asked again, so the refusal
    number matches the current eval set. Saves a new file; the original run stays untouched.
    """
    old = json.loads(path.read_text("utf-8"))
    questions = {q["id"]: q for q in load_jsonl(EVAL_DIR / "questions.jsonl")}
    unanswerable = {q["id"]: q for q in load_jsonl(EVAL_DIR / "unanswerable.jsonl")}
    args.mode, args.rewrite = old["mode"], old["query_rewrite"]
    with Session(get_engine()) as session:
        for row in old["rows"]:
            if row["kind"] == "answerable" and not row["refused"]:
                q = questions[row["id"]]
                time.sleep(args.sleep)
                row["score"], row["judge_reason"] = with_retry(
                    judge, q["question"], q["expected_answer"], row["answer"]
                )
                print(f"  {row['id']} score={row['score']}")
            elif (
                row["kind"] == "unanswerable"
                and row["question"] != unanswerable[row["id"]]["question"]
            ):
                q = unanswerable[row["id"]]
                trace = with_retry(ask_or_raise, session, q, args)
                row.update(
                    question=q["question"],
                    refused=trace.response.refused,
                    answer=trace.response.answer,
                )
                print(f"  {row['id']} re-asked (question changed) refused={row['refused']}")
    ans = [r for r in old["rows"] if r["kind"] == "answerable"]
    una = [r for r in old["rows"] if r["kind"] == "unanswerable"]
    old["metrics"]["correctness"] = round(statistics.mean(r["score"] for r in ans), 3)
    old["metrics"]["refusal_acc"] = round(sum(r["refused"] for r in una) / len(una), 3)
    old["rejudged_from"] = path.name
    old["judge_version"] = JUDGE_VERSION
    old["date"] = date.today().isoformat()
    return old


# ---------------------------------------------------------------- letters ---

LETTER_FIELDS = ("sender", "letter_date", "deadline", "amount_eur")


def field_correct(name: str, predicted: object, expected: object) -> bool:
    if name == "sender":  # free text: enough if most words of the expected sender appear
        if not predicted or not expected:
            return predicted == expected
        want = set(str(expected).lower().replace("–", " ").split())
        got = set(str(predicted).lower().replace("–", " ").split())
        return len(want & got) / len(want) >= 0.5
    if name == "amount_eur":
        if predicted is None or expected is None:
            return predicted == expected
        return abs(float(predicted) - float(expected)) < 0.01
    return (str(predicted) if predicted is not None else None) == expected


def run_letters(args: argparse.Namespace) -> dict:
    """Letter path: mask -> extract fields -> agent explanation.

    field_acc  share of correct fields (sender, letter_date, deadline, amount_eur)
    pii_leaks  number of letters where any of its fake personal data appeared in ANY prompt
               sent to the LLM (extraction, planner, answer). Must be 0.
    """
    from app.agent.graph import run_agent
    from app.letter.extract import extract_fields
    from app.letter.mask import mask

    letters = load_jsonl(EVAL_DIR / "letters.jsonl")[: args.limit or None]
    rows, latencies = [], []
    with Session(get_engine()) as session:
        for letter in letters:
            start = time.perf_counter()
            with record_prompts() as prompts:
                masked = mask(letter["text"])
                fields = with_retry(lambda t=masked.text: extract_fields(t, allow_fallback=False))
                time.sleep(args.sleep)
                state = run_agent(session, fields=fields, lang="en")
            latencies.append(time.perf_counter() - start)
            sent = "\n".join(prompts)
            leaked = [p for p in letter["pii"] if p in sent]
            predicted = fields.model_dump(mode="json")
            correct = {
                f: field_correct(f, predicted[f], letter["fields"][f]) for f in LETTER_FIELDS
            }
            rows.append(
                {
                    "id": letter["id"],
                    "kind": "letter",
                    "fields": predicted,
                    "correct": correct,
                    "leaked": leaked,
                    "refused": state["response"].refused,
                    "tool_log": state.get("tool_log"),
                    "answer": state["response"].answer,
                }
            )
            print(
                f"  {letter['id']} correct={sum(correct.values())}/{len(correct)} "
                f"leaks={len(leaked)} tools={state.get('tool_log')}"
            )
            time.sleep(args.sleep)
    total = sum(len(r["correct"]) for r in rows)
    return {
        "date": date.today().isoformat(),
        "mode": "letters",
        "answers": True,
        "query_rewrite": False,
        "answer_model": get_settings().groq_model,
        "n_answerable": len(rows),
        "n_unanswerable": 0,
        "metrics": {
            "hit@5": None,
            "mrr": None,
            "correctness": None,
            "refusal_acc": None,
            "answered_rate": round(sum(not r["refused"] for r in rows) / len(rows), 3),
            "field_acc": round(sum(sum(r["correct"].values()) for r in rows) / total, 3),
            "pii_leaks": sum(bool(r["leaked"]) for r in rows),
            "p95_latency_s": round(p95(latencies), 2),
        },
        "rows": rows,
    }


def check_baseline(result: dict, baseline_path: Path, max_drop: float) -> bool:
    """CI quality gate: correctness on the SAME questions must not drop more than max_drop."""
    base = {r["id"]: r for r in json.loads(baseline_path.read_text("utf-8"))["rows"]}
    now = [r for r in result["rows"] if r["kind"] == "answerable" and "score" in r]
    pairs = [(r["score"], base[r["id"]]["score"]) for r in now if "score" in base.get(r["id"], {})]
    if not pairs:
        print("No overlapping judged questions with the baseline.")
        return False
    current = statistics.mean(p[0] for p in pairs)
    reference = statistics.mean(p[1] for p in pairs)
    ok = current >= reference - max_drop
    print(
        f"\nBaseline check on {len(pairs)} questions: now {current:.2f}, "
        f"baseline {reference:.2f}, allowed drop {max_drop:.2f} -> {'PASS' if ok else 'FAIL'}"
    )
    return ok


def fmt(v: float | None) -> str:
    return "TBD" if v is None else f"{v:.2f}"


def save(result: dict) -> Path:
    RESULTS.mkdir(exist_ok=True)
    suffix = "_answers" if result["answers"] else ""
    name = f"{result['date']}_{result['mode'].replace('+', '-')}{suffix}"
    if result["query_rewrite"]:
        name += "_rewrite"
    if result.get("rejudged_from"):
        name += f"_rejudged-{result['judge_version']}"
    path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), "utf-8")

    summary = RESULTS / "summary.md"
    header = (
        "| Date | Mode | Answers | Rewrite | n | hit@5 | MRR | Correctness | Refusal acc "
        "| Answered | Field acc | PII leaks | p95 s |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    m = result["metrics"]
    answers = "yes" if result["answers"] else "no"
    if result.get("judge_version"):
        answers += f" (judge {result['judge_version']})"
    key = (
        f"| {result['date']} | {result['mode']} | {answers} "
        f"| {'yes' if result['query_rewrite'] else 'no'} |"
    )
    line = (
        f"{key} {result['n_answerable']}+{result['n_unanswerable']} | {fmt(m['hit@5'])} "
        f"| {fmt(m['mrr'])} | {fmt(m['correctness'])} | {fmt(m['refusal_acc'])} "
        f"| {fmt(m['answered_rate'])} | {fmt(m['field_acc'])} | {fmt(m['pii_leaks'])} "
        f"| {m['p95_latency_s']} |\n"
    )
    rows: list[str] = []
    if summary.exists():  # keep other rows; a re-run of the same configuration replaces its row
        rows = [r for r in summary.read_text("utf-8").splitlines(keepends=True)[2:] if r.strip()]
        rows = [r for r in rows if not r.startswith(key)]
    summary.write_text(header + "".join(rows) + line, "utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate BriefKlar retrieval and answers.")
    parser.add_argument("--mode", choices=MODES)
    parser.add_argument("--rejudge", type=Path, help="re-score a saved --answers result file")
    parser.add_argument("--answers", action="store_true", help="generate + judge answers (LLM)")
    parser.add_argument("--rewrite", action="store_true", help="enable query rewrite")
    parser.add_argument("--tune", action="store_true", help="suggest a refusal threshold")
    parser.add_argument("--limit", type=int, default=None, help="only the first N questions")
    parser.add_argument("--sleep", type=float, default=2.5, help="seconds between LLM calls")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--letters", action="store_true", help="evaluate the letter path")
    parser.add_argument("--baseline", type=Path, help="fail if correctness drops vs this run")
    parser.add_argument("--max-drop", type=float, default=0.10)
    args = parser.parse_args()
    if not (args.mode or args.rejudge or args.letters):
        parser.error("use --mode, --rejudge FILE or --letters")

    if args.letters:
        result = run_letters(args)
    elif args.rejudge:
        result = rejudge(args.rejudge, args)
    else:
        result = run(args)
    print("\n" + json.dumps(result["metrics"], indent=2))

    if (
        args.answers or args.rejudge
    ) and not args.letters:  # print 5 random judgments so a human can check the judge
        judged = [r for r in result["rows"] if "score" in r and r["judge_reason"] != "refused"]
        print("\n--- 5 random judgments to check by hand ---")
        for r in random.sample(judged, min(5, len(judged))):
            print(f"\n[{r['id']}] {r['question']}\nANSWER: {r['answer'][:400]}")
            print(f"JUDGE: {r['score']} - {r['judge_reason']}")

    if not args.no_save:
        print(f"\nSaved {save(result)}")
    if args.baseline and not check_baseline(result, args.baseline, args.max_drop):
        sys.exit(1)


if __name__ == "__main__":
    main()

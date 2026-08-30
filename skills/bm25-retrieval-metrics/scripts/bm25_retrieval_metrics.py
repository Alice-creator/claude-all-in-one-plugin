#!/usr/bin/env python3
"""bm25-retrieval-metrics: the mandatory BM25 retrieval BASELINE + a deterministic retrieval GRADER for RAG
research.

Two jobs, both deterministic, free, in-session (NO LLM keys):
  1. BASELINE — build a pure-python BM25 (Okapi) index over the corpus and retrieve for each eval query. BM25 is
     the low-cost baseline any fancier retriever (dense/hybrid/rerank) MUST be shown to beat ("BM25 Wins at Scale",
     BEIR): a research claim that skips this control is not defensible.
  2. GRADER — score retrieval quality against gold document ids with recall@k, precision@k, MRR, nDCG@k,
     context-recall. With --predictions it grades ANY retriever's output (a treatment arm) identically, and emits
     PER-QUERY scores so they can become the `success` field of an agent-researcher trials.jsonl row and be
     bootstrapped over tasks by analyze-trials.

Honest boundary: retrieval quality is NOT answer quality (good documents, bad answer is still bad — see
judge-rag-answers), and an offline score on a static corpus is NOT production performance (no live corpus drift,
no real-query distribution). Deterministic + free; the LLM half is judge-rag-answers, the user's keys.

eval.jsonl rows:   {"id","question","gold_doc_ids":[...][,"answer"]}
corpus.jsonl rows: {"doc_id","text"}
predictions rows (optional): {"id","retrieved_doc_ids":[...ranked]}

Exit codes: 0 ok · 2 dependency/IO · 3 bad input.

NOTE: helpers here are deliberately self-contained (the plugin copies helpers byte-identical across scripts).
"""
import argparse
import json
import math
import os
import re
import sys


def die(msg, code):
    print(msg, file=sys.stderr)
    sys.exit(code)


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def tokenize(text):
    """Lowercase word tokens. Deterministic and dependency-free (kept identical across the RAG skills)."""
    return re.findall(r"[a-z0-9]+", str(text).lower())


def build_bm25(corpus_tokens):
    """Build an Okapi-BM25 index from a list of token-lists. Pure python, self-contained (no rank_bm25 dep).
    Returns the stats bm25_scores() needs. Kept byte-identical across the RAG skills."""
    n = len(corpus_tokens)
    doc_len = [len(d) for d in corpus_tokens]
    avgdl = (sum(doc_len) / n) if n else 0.0
    df = {}
    doc_tf = []
    for d in corpus_tokens:
        tf = {}
        for t in d:
            tf[t] = tf.get(t, 0) + 1
        doc_tf.append(tf)
        for t in tf:
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log(1 + (n - dft + 0.5) / (dft + 0.5)) for t, dft in df.items()}
    return {"n": n, "avgdl": avgdl, "doc_len": doc_len, "doc_tf": doc_tf, "idf": idf}


def bm25_scores(query_tokens, index, k1=1.5, b=0.75):
    """Score every document against the query tokens. Returns a list of floats (one per doc). Kept byte-identical
    across the RAG skills (pure Okapi BM25; a dense O(query-terms x N) scan over all docs — fine for a bounded
    research corpus, not a web-scale index)."""
    n = index["n"]
    scores = [0.0] * n
    if n == 0:
        return scores
    avgdl = index["avgdl"] or 1.0
    idf = index["idf"]
    doc_tf = index["doc_tf"]
    doc_len = index["doc_len"]
    for t in set(query_tokens):
        w = idf.get(t)
        if w is None:
            continue
        for i in range(n):
            f = doc_tf[i].get(t, 0)
            if not f:
                continue
            denom = f + k1 * (1 - b + b * doc_len[i] / avgdl)
            scores[i] += w * (f * (k1 + 1)) / denom
    return scores


def read_jsonl(path):
    rows = []
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                rows.append(json.loads(ln))
    return rows


def dcg(rels):
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


def query_metrics(retrieved_ids, gold_ids, k):
    """Deterministic retrieval metrics for one query. gold relevance is binary (a doc is gold or not)."""
    topk = retrieved_ids[:k]
    gold = set(gold_ids)
    hits = [1 if d in gold else 0 for d in topk]
    n_hit = sum(hits)
    recall = n_hit / len(gold) if gold else 0.0
    precision = n_hit / k if k else 0.0
    mrr = 0.0
    for i, d in enumerate(topk):
        if d in gold:
            mrr = 1.0 / (i + 1)
            break
    ideal = dcg([1] * min(len(gold), k))
    ndcg = (dcg(hits) / ideal) if ideal > 0 else 0.0
    return {"recall@k": recall, "precision@k": precision, "mrr": mrr, "ndcg@k": ndcg,
            "n_gold": len(gold), "n_hit": n_hit}


def main():
    ap = argparse.ArgumentParser(description="BM25 retrieval baseline + deterministic retrieval grader for RAG.")
    ap.add_argument("--eval", required=True, help="eval.jsonl (id, question, gold_doc_ids)")
    ap.add_argument("--corpus", help="corpus.jsonl (doc_id, text) — required unless --predictions is given")
    ap.add_argument("--predictions", help="grade an external retriever: rows {id, retrieved_doc_ids}")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--retriever-name", default=None, help="label for the report (default bm25 or 'external')")
    ap.add_argument("--per-query", default=None, help="write per-query scores here (feeds trials.jsonl / analyze)")
    ap.add_argument("--out", default="retrieval_metrics.json")
    args = ap.parse_args()

    try:
        import numpy as np
    except Exception:
        die("numpy required — use the project venv: .venv/bin/python", 2)
    for p, what in ((args.eval, "--eval"),):
        if not os.path.exists(p):
            die(f"{what} not found: {p}", 3)
    ev = read_jsonl(args.eval)
    if not ev:
        die("eval set is empty", 3)
    for r in ev:
        if "gold_doc_ids" not in r or not isinstance(r["gold_doc_ids"], list):
            die(f"eval row {r.get('id')} missing gold_doc_ids (a list) — retrieval metrics need gold docs.", 3)

    preds = None
    if args.predictions:
        if not os.path.exists(args.predictions):
            die(f"--predictions not found: {args.predictions}", 3)
        preds = {str(r["id"]): [str(d) for d in r.get("retrieved_doc_ids", [])] for r in read_jsonl(args.predictions)}
        retriever = args.retriever_name or "external"
    else:
        if not args.corpus or not os.path.exists(args.corpus):
            die("need --corpus (to run BM25) or --predictions (to grade an external retriever).", 3)
        corpus = read_jsonl(args.corpus)
        doc_ids = [str(r["doc_id"]) for r in corpus]
        index = build_bm25([tokenize(r.get("text", "")) for r in corpus])
        retriever = args.retriever_name or "bm25"

    per_query = []
    agg = {"recall@k": [], "precision@k": [], "mrr": [], "ndcg@k": []}
    missing_pred = 0
    for r in ev:
        qid = str(r["id"])
        gold = [str(d) for d in r["gold_doc_ids"]]
        if preds is not None:
            retrieved = preds.get(qid)
            if retrieved is None:
                missing_pred += 1
                retrieved = []
        else:
            sc = bm25_scores(tokenize(r.get("question", "")), index)
            order = np.argsort(sc, kind="stable")[::-1][:args.k]  # stable → reproducible ranking on tied scores
            retrieved = [doc_ids[i] for i in order]
        m = query_metrics(retrieved, gold, args.k)
        per_query.append({"id": qid, **{kk: round(m[kk], 4) for kk in agg}, "n_gold": m["n_gold"], "n_hit": m["n_hit"]})
        for kk in agg:
            agg[kk].append(m[kk])

    empty_gold = sum(1 for r in ev if not r["gold_doc_ids"])
    summary = {
        "retriever": retriever, "k": args.k, "n_queries": len(ev),
        "recall@k": round(float(np.mean(agg["recall@k"])), 4),
        "precision@k": round(float(np.mean(agg["precision@k"])), 4),
        "mrr": round(float(np.mean(agg["mrr"])), 4),
        "ndcg@k": round(float(np.mean(agg["ndcg@k"])), 4),
        "precision_at_k_convention": "denominator is k even when fewer than k docs are retrieved",
        "context_recall_note": "gold-document recall@k above IS the context-recall; it is binary and deterministic, "
                               "NOT RAGAS's LLM-judged 'context recall' — do not conflate the two.",
        "predictions_missing": missing_pred, "queries_with_empty_gold": empty_gold,
        "per_query_path": args.per_query,
        "deterministic": True, "needs_llm_keys": False,
        "offline_only": True, "matches_production": False, "measures_answer_quality": False,
        "boundary": "Retrieval quality is NOT answer quality (good docs + bad answer still fails — see "
                    "judge-rag-answers) and an offline score on a static corpus is NOT production performance. "
                    "BM25 is the baseline a fancier retriever must beat; per-query scores feed a trials.jsonl "
                    "'success' for clustered-bootstrap analysis.",
    }
    with open(args.out, "w") as f:
        json.dump(summary, f, indent=2)
    if args.per_query:
        with open(args.per_query, "w") as f:
            for row in per_query:
                f.write(json.dumps(row) + "\n")
    write_report(summary)
    print(f"Wrote {args.out}"
          + (f" + {args.per_query}" if args.per_query else "")
          + f" — {retriever} (retrieval only): recall@{args.k}={summary['recall@k']}, MRR={summary['mrr']}, "
            f"nDCG@{args.k}={summary['ndcg@k']} over {len(ev)} queries")
    if missing_pred:
        eprint(f"  WARNING: {missing_pred} eval id(s) had no prediction — scored as 0 recall (not dropped).")
    if empty_gold:
        eprint(f"  WARNING: {empty_gold} query/queries have empty gold_doc_ids — scored 0 (they drag the mean down).")


def write_report(s):
    md = f"""# Retrieval metrics — {s['retriever']} @ k={s['k']}

## At a glance
```mermaid
flowchart LR
    Q["{s['n_queries']} queries"] --> R["{s['retriever']}"]
    R --> M["recall@{s['k']}={s['recall@k']}<br/>MRR={s['mrr']}<br/>nDCG@{s['k']}={s['ndcg@k']}"]
    M --> H["deterministic ✓ · free ✓<br/>≠ answer quality · ≠ production"]
```

- **Retriever:** {s['retriever']} (deterministic, no LLM keys)
- **recall@{s['k']}** {s['recall@k']} · **precision@{s['k']}** {s['precision@k']} · **MRR** {s['mrr']} · **nDCG@{s['k']}** {s['ndcg@k']}  _(recall@k is the binary gold-doc context-recall — NOT RAGAS's LLM-judged one)_
- **Queries:** {s['n_queries']}{f" · predictions missing: {s['predictions_missing']}" if s['predictions_missing'] else ""}

## What this is / isn't
- ✅ BM25 is the **baseline the fancier retriever must beat** (grade a dense/hybrid retriever with `--predictions`).
- ✅ Per-query scores feed a trials.jsonl `success` for clustered-bootstrap analysis (agent-researcher spine).
- ⛔ Retrieval quality is **not** answer quality — a faithful, relevant answer needs `judge-rag-answers` (LLM keys).
- ⛔ Offline on a static corpus is **not** production (no live drift, no real-query distribution).

## Next
→ grade a treatment retriever (`--predictions`), or score answer quality with `judge-rag-answers`.
"""
    with open("retrieval_metrics_report.md", "w") as f:
        f.write(md)


if __name__ == "__main__":
    main()

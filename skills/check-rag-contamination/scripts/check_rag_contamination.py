#!/usr/bin/env python3
"""check-rag-contamination: RAG-specific validity PROXIES that feed the agent-researcher hard validity gate
(validate-eval-task) — is the eval set leaky / trivially solvable BEFORE you spend money running trials?

Contamination is the RAG analog of the plugin's sacred leakage rule: on a contaminated eval set every RAG system
clusters within ~3% accuracy (indistinguishable), so an ablation literally cannot tell you whether a change
helped. This skill runs the DETERMINISTIC, in-session, no-key checks:

  1. gold-answer-retrievability — is the gold answer sitting verbatim in the top-k BM25 hits? A high rate means the
     task rewards string-matching / memorization, not retrieval reasoning.
  2. eval<->corpus n-gram overlap — is the question lifted near-verbatim from a corpus document (trivial retrieval)?
  3. no-context answerability PROXY — are the answer tokens all high-document-frequency ("common knowledge" in the
     corpus)? A cheap stand-in; TRUE parametric-memory probing needs the model and is DEFERRED to a user-key stage.
  4. eval-set near-duplicates — question<->question n-gram clusters (leakage inside the eval set).

Honest boundary: these are PROXIES — a floor on contamination, not a ceiling. They cannot detect paraphrased or
parametric-memory contamination (that needs the user's model, e.g. guided-instruction probing) and they never
REPLACE validate-eval-task's hard gate; they supply evidence for its ABC checklist. Verdict is advisory.

eval.jsonl:   {"id","question","answer"|"answer_aliases":[...][,"gold_doc_ids"]}
corpus.jsonl: {"doc_id","text"}

Exit codes: 0 ok · 2 dep/IO · 3 bad input.

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


def shingles(tokens, n):
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)} if len(tokens) >= n else set()


def containment(a_shingles, b_shingles):
    """|A ∩ B| / |A| — how much of the question's n-grams appear in a doc (asymmetric, catches lifted questions)."""
    if not a_shingles:
        return 0.0
    return len(a_shingles & b_shingles) / len(a_shingles)


def answer_aliases(row):
    al = row.get("answer_aliases")
    if isinstance(al, list) and al:
        return [str(x) for x in al]
    a = row.get("answer")
    return [str(a)] if a is not None else []


def main():
    ap = argparse.ArgumentParser(description="Deterministic RAG contamination proxies (feed validate-eval-task).")
    ap.add_argument("--eval", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--k", type=int, default=10, help="BM25 top-k inspected per question")
    ap.add_argument("--ngram", type=int, default=5,
                    help="token n-gram size for question<->corpus and near-dup overlap. Questions are short, so the "
                         "default is 5 (a 13-gram, classic for DOCUMENT contamination, silently exempts most questions).")
    ap.add_argument("--overlap-thresh", type=float, default=0.5, help="containment above this flags a lifted question")
    ap.add_argument("--high-df-frac", type=float, default=0.5, help="a token in >this fraction of docs is 'common'")
    ap.add_argument("--out", default="rag_contamination.json")
    args = ap.parse_args()

    try:
        import numpy as np
    except Exception:
        die("numpy required — use the project venv: .venv/bin/python", 2)
    for p, what in ((args.eval, "--eval"), (args.corpus, "--corpus")):
        if not os.path.exists(p):
            die(f"{what} not found: {p}", 3)
    ev = read_jsonl(args.eval)
    corpus = read_jsonl(args.corpus)
    if not ev or not corpus:
        die("eval set and corpus must be non-empty", 3)

    doc_texts = [str(r.get("text", "")) for r in corpus]
    doc_tokens = [tokenize(t) for t in doc_texts]
    doc_norm = [" ".join(tk) for tk in doc_tokens]     # normalized text for verbatim answer search
    doc_shingles = [shingles(tk, args.ngram) for tk in doc_tokens]
    index = build_bm25(doc_tokens)
    n_docs = len(corpus)
    # document frequency for the "common knowledge" proxy
    df = {}
    for tk in doc_tokens:
        for t in set(tk):
            df[t] = df.get(t, 0) + 1

    gold_retrievable = 0
    overlap_flagged = 0
    common_answer = 0
    q_shingle_list = []
    for r in ev:
        qtok = tokenize(r.get("question", ""))
        q_shingle_list.append(shingles(qtok, args.ngram))
        sc = bm25_scores(qtok, index)
        topk = list(np.argsort(sc, kind="stable")[::-1][:args.k])
        # 1. gold-answer-retrievability: any alias present as WHOLE WORDS in a top-k doc (space-padded so "cat"
        #    does not match inside "concatenation").
        aliases = [" ".join(tokenize(a)) for a in answer_aliases(r) if tokenize(a)]
        if aliases and any(al and (" " + al + " ") in (" " + doc_norm[i] + " ") for i in topk for al in aliases):
            gold_retrievable += 1
        # 2. question<->corpus overlap: max containment against the top-k docs
        qs = q_shingle_list[-1]
        if qs and max((containment(qs, doc_shingles[i]) for i in topk), default=0.0) >= args.overlap_thresh:
            overlap_flagged += 1
        # 3. common-knowledge proxy: are ALL answer tokens high-DF?
        atoks = [t for a in answer_aliases(r) for t in tokenize(a)]
        if atoks and all(df.get(t, 0) / n_docs >= args.high_df_frac for t in atoks):
            common_answer += 1

    # 4. eval near-dup clusters (question<->question containment >= overlap_thresh)
    n = len(ev)
    seen = [False] * n
    near_dup_clusters = 0
    for i in range(n):
        if seen[i] or not q_shingle_list[i]:
            continue
        members = 0
        for j in range(i + 1, n):
            if not seen[j] and q_shingle_list[j] and \
                    containment(q_shingle_list[i], q_shingle_list[j]) >= args.overlap_thresh:
                seen[j] = True
                members += 1
        if members:
            near_dup_clusters += 1

    ne = len(ev)
    gold_rate = round(gold_retrievable / ne, 4)
    overlap_rate = round(overlap_flagged / ne, 4)
    common_rate = round(common_answer / ne, 4)
    worst = max(gold_rate, overlap_rate, common_rate)
    verdict = "LEAKY" if worst >= 0.5 else "WARN" if (worst >= 0.2 or near_dup_clusters) else "OK"

    n_too_short = sum(1 for s in q_shingle_list if not s)   # questions shorter than --ngram: invisible to the overlap checks
    warnings = []
    if gold_rate >= 0.2:
        warnings.append(f"{gold_rate:.0%} of questions have the gold answer verbatim in top-{args.k} retrieval — the "
                        "task rewards string-matching/memory over retrieval reasoning.")
    if overlap_rate >= 0.2:
        warnings.append(f"{overlap_rate:.0%} of questions are near-verbatim from a corpus doc (containment ≥ "
                        f"{args.overlap_thresh}) — retrieval is trivial for these.")
    if common_rate >= 0.2:
        warnings.append(f"{common_rate:.0%} of answers are all high-frequency corpus terms — likely answerable "
                        "without real retrieval (deterministic proxy for parametric-memory answerability).")
    if near_dup_clusters:
        warnings.append(f"{near_dup_clusters} near-duplicate question cluster(s) inside the eval set (intra-set leakage).")
    if n_too_short:
        warnings.append(f"{n_too_short}/{ne} question(s) are shorter than --ngram ({args.ngram} tokens) and were NOT "
                        "checked for corpus-overlap or near-duplicates — lower --ngram for full coverage.")

    result = {
        "n_eval": ne, "n_corpus": n_docs, "k": args.k, "ngram": args.ngram,
        "gold_answer_retrievable_rate": gold_rate,
        "corpus_overlap_flagged_rate": overlap_rate,
        "common_knowledge_answer_rate": common_rate,
        "eval_near_dup_clusters": near_dup_clusters,
        "questions_too_short_to_shingle": n_too_short,
        "verdict": verdict,
        "advisory": True, "replaces_hard_gate": False, "is_floor_not_ceiling": True,
        "verdict_thresholds": {"WARN": 0.2, "LEAKY": 0.5, "note": "advisory cutoffs, not grounded constants"},
        "deferred_checks": ["parametric-memory / guided-instruction memorization detection (needs the user's model + keys)",
                            "paraphrased contamination (semantic, not n-gram)"],
        "warnings": warnings,
        "boundary": "PROXIES only — a floor on contamination, not a ceiling. Deterministic + free. This does NOT "
                    "replace validate-eval-task's hard gate; it supplies evidence for the ABC checklist. Memorization "
                    "and paraphrase detection are deferred to a user-key stage. Advisory verdict, not a pass/fail gate.",
    }
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    write_report(result)
    print(f"Wrote {args.out} — verdict {verdict} (gold-retrievable {gold_rate:.0%}, corpus-overlap {overlap_rate:.0%}, "
          f"common-answer {common_rate:.0%}, near-dup clusters {near_dup_clusters})")
    for w in warnings:
        eprint("  - " + w)


def write_report(r):
    badge = {"OK": "🟢 NO CHEAP LEAKAGE FOUND", "WARN": "🟠 WARN", "LEAKY": "🔴 LEAKY"}[r["verdict"]]
    md = f"""# RAG contamination proxies — {badge}

## At a glance
```mermaid
flowchart LR
    E["{r['n_eval']} eval Q<br/>{r['n_corpus']} docs"] --> C["proxies (deterministic)"]
    C --> V["{badge}<br/>gold-retr {r['gold_answer_retrievable_rate']:.0%} · overlap {r['corpus_overlap_flagged_rate']:.0%}<br/>common {r['common_knowledge_answer_rate']:.0%} · near-dup {r['eval_near_dup_clusters']}"]
    V --> G["→ evidence for validate-eval-task (hard gate)"]
```

- **Verdict (advisory):** {badge}
- gold-answer-retrievable **{r['gold_answer_retrievable_rate']:.0%}** · corpus-overlap **{r['corpus_overlap_flagged_rate']:.0%}** · common-knowledge answer **{r['common_knowledge_answer_rate']:.0%}** · eval near-dup clusters **{r['eval_near_dup_clusters']}**

## Findings
{chr(10).join('- ⚠️ ' + w for w in r['warnings']) if r['warnings'] else '- No contamination flagged by the deterministic proxies.'}

## Honesty
- These are **PROXIES** — a floor on contamination, not a ceiling. Deterministic + free (no keys).
- **Deferred to a user-key stage:** {', '.join(r['deferred_checks'])}.
- This does **not** replace `validate-eval-task`'s hard gate — it supplies evidence for the ABC checklist.

## Next
→ feed this into `validate-eval-task`; a LEAKY/WARN verdict means fix the eval set before spending on trials.
"""
    with open("rag_contamination_report.md", "w") as f:
        f.write(md)


if __name__ == "__main__":
    main()

---
name: bm25-retrieval-metrics
description: Build a pure-python BM25 baseline and compute DETERMINISTIC retrieval metrics (recall@k, precision@k, MRR, nDCG@k, context-recall) for RAG research — the free, in-session control every fancier retriever (dense/hybrid/rerank) must be shown to beat, and a grader that scores any retriever's output into per-query scores that become a trials.jsonl `success` for the agent-researcher spine. Use to measure "did retrieval get better?" without LLM keys, and to produce the mandatory BM25 baseline arm before you spend money on generation eval.
allowed-tools: Bash, Read, Write
---

# bm25-retrieval-metrics

The RAG-specific, deterministic half of retrieval research: a BM25 baseline + retrieval-quality grading that runs **for free, in-session, with no LLM keys**. It is one of three RAG skills that plug into the `agent-researcher` research spine (this one at the *baseline + retrieval-grader* point); it does not replace that pipeline's framing, validity gate, or bootstrap analysis.

## When to use
- To produce the **BM25 baseline** a fancier retriever must beat — a research claim that skips this control is not defensible.
- To **grade any retriever** (dense/hybrid/rerank) against gold documents with the same metrics (`--predictions`).
- To turn retrieval quality into **per-query scores** that feed a `trials.jsonl` `success` for `analyze-trials`.
- NOT for answer quality (that is `judge-rag-answers`, which needs LLM keys) and NOT for tabular retrieval.

## Contract (important)
- **Deterministic and free.** Pure-python Okapi BM25; no embeddings, no keys, no network. Same input → same number.
- **BM25 is the baseline, not the ceiling.** Report it as the control; grade a dense/hybrid retriever's output via
  `--predictions` and compare. This skill never runs embeddings itself (that is the user's compute/keys).
- **Needs gold document ids.** Retrieval metrics require `gold_doc_ids` per eval row; it refuses without them.
- **Retrieval quality ≠ answer quality.** Good documents with a wrong answer still fail — the report says so and
  points at `judge-rag-answers`.
- **Offline ≠ production.** A score on a static corpus is not production performance (no live corpus drift, no
  real-query distribution). Never present it as such.
- **Composes, doesn't orchestrate.** Emits per-query scores; the `agent-researcher` spine does the preregistration,
  the validity gate, and the clustered-bootstrap CI over tasks.

## Steps
1. **Run BM25 (baseline):**
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/bm25-retrieval-metrics/scripts/bm25_retrieval_metrics.py" \
       --eval eval.jsonl --corpus corpus.jsonl --k 10 --per-query bm25_per_query.jsonl
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/bm25-retrieval-metrics/scripts/bm25_retrieval_metrics.py`.)
   Needs numpy (in the venv). `eval.jsonl`: `{id, question, gold_doc_ids[, answer]}`; `corpus.jsonl`: `{doc_id, text}`.
2. **Grade a treatment retriever:** produce `retrieved.jsonl` (`{id, retrieved_doc_ids}`) from a dense/hybrid model,
   then `--predictions retrieved.jsonl` scores it with the same metrics. Compare to the BM25 baseline — a gain that
   doesn't beat BM25 is not a gain.
3. **Feed the ablation:** hand the per-query file to the `agent-researcher` trials (each score is a `success`), so
   `analyze-trials` reports a clustered-bootstrap interval, not a bare mean.

## Output style
- Lead with the Mermaid `## At a glance`: queries → retriever → recall/MRR/nDCG → "deterministic ✓ · ≠ answer quality · ≠ production".
- Always state that BM25 is the baseline to beat, and that retrieval quality is not answer quality.

## Grounding
BM25-as-mandatory-baseline is grounded: BM25 is a strong zero-shot retriever most dense models fail to beat
out-of-domain ([BEIR, Thakur et al., NeurIPS 2021](https://arxiv.org/abs/2104.08663)); it "defines the low-cost end
of the accuracy/cost Pareto frontier" and overtakes dense/agentic RAG as corpus size grows
([BM25 Wins at Scale](https://huggingface.co/papers/2607.26497)); and in a controlled RAG ablation plain BM25
(MRR@10 0.879) beat a hybrid BM25+dense (0.850), with only reranking (0.919) beating it
([The Chronicles of RAG, Finardi et al.](https://arxiv.org/abs/2401.07883)). The recall@k / MRR / nDCG definitions
are standard IR metrics; nDCG uses binary relevance over the gold document set.

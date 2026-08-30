---
name: check-rag-contamination
description: Run deterministic, in-session RAG contamination PROXIES (gold-answer-retrievability, eval↔corpus n-gram overlap, a common-knowledge answerability proxy, eval-set near-duplicates) that supply evidence for the agent-researcher validity gate — is your RAG eval set leaky or trivially solvable BEFORE you spend money on trials? Contamination is the RAG analog of train/test leakage: on a contaminated set every RAG system clusters within ~3% and an ablation can't tell you whether a change helped. Use right before validate-eval-task, on any RAG eval set you did not build leakage-free yourself.
allowed-tools: Bash, Read, Write
---

# check-rag-contamination

Contamination is the RAG version of the plugin's sacred leakage rule. A question the model can answer from memory, or whose gold answer is trivially retrievable, measures parametric recall — not retrieval quality — and collapses a benchmark's power to distinguish systems. This skill runs the **deterministic, key-free proxies** and feeds their evidence into the `agent-researcher` hard validity gate (`validate-eval-task`). It is one of three RAG skills on that spine (this one at the *validity* point).

## When to use
- Before `validate-eval-task`, on any RAG eval set you inherited or generated rather than built leakage-free.
- To catch the cheap, obvious leakage (lifted questions, verbatim-retrievable answers, intra-set duplicates) for free.
- NOT as the final word on contamination — the deep checks need the user's model (see Contract).

## Contract (important)
- **Proxies only — a floor, not a ceiling.** Deterministic + free. They flag obvious leakage; they CANNOT detect
  paraphrased or parametric-memory contamination. That needs the user's model (e.g. guided-instruction memorization
  probing) and is explicitly listed as `deferred_checks`.
- **Advisory, not a gate.** It emits a verdict (OK / WARN / LEAKY) and evidence; it does NOT exit-block. The hard
  stop is `validate-eval-task` — this supplies evidence for its ABC checklist. Never treat a green proxy as "clean".
- **Four deterministic checks:** gold-answer verbatim in top-k BM25 hits; question↔corpus n-gram containment
  (lifted questions); a common-knowledge proxy (all answer tokens are high-document-frequency); intra-eval-set
  near-duplicate question clusters.
- **Reads eval + corpus; writes a sidecar.** Never modifies the eval set.

## Steps
1. **Run it:**
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/check-rag-contamination/scripts/check_rag_contamination.py" \
       --eval eval.jsonl --corpus corpus.jsonl --k 10 --ngram 13
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/check-rag-contamination/scripts/check_rag_contamination.py`.)
   Needs numpy. `eval.jsonl`: `{id, question, answer|answer_aliases[, gold_doc_ids]}`; `corpus.jsonl`: `{doc_id, text}`.
2. **Read the verdict + rates, not just the badge.** A LEAKY or WARN verdict means fix the eval set (regenerate
   leakage-free, or drop the flagged items) before spending on trials — naively regenerating with an LLM only
   partially removes leakage.
3. **Carry the evidence into `validate-eval-task`.** State the deferred checks (memorization/paraphrase) that still
   need the user's model.

## Output style
- Lead with the Mermaid `## At a glance`: eval+corpus → proxies → verdict badge → "evidence for the hard gate".
- Always say these are proxies (a floor), name the deferred checks, and that they don't replace the hard gate.

## Grounding
Contamination as the decisive RAG validity threat is grounded: on multi-hop QA benchmarks LLMs answer 52–75% of
questions with NO retrieved context, and on contaminated sets RAG systems cluster within 3% (a leakage-free set
widens the spread to 10–18%) ([Generating Leakage-Free Benchmarks for Robust RAG Evaluation](https://arxiv.org/pdf/2605.08838)).
Naive LLM-regeneration of the eval set only partially removes leakage (18–53% residual), so structural constraints
plus a leakage-rejection filter are required (same source). Instance-level memorization is detectable with
"guided instruction" at 92–100% accuracy but needs the model itself and misses paraphrase
([Time Travel in LLMs, Golchin & Surdeanu, ICLR 2024](https://arxiv.org/pdf/2308.08493)) — which is exactly why
this skill runs only the deterministic proxies in-session and defers memorization detection to a user-key stage.

---
name: judge-rag-answers
description: Score RAG answer quality (faithfulness/groundedness, answer-relevance, answer-correctness) with an LLM judge and report it HONESTLY — repeated runs for a bootstrap CI (never a bare mean), chance-corrected Cohen's κ against a small human-labeled set (never raw % agreement), a verbosity diagnostic and a self-preference/circularity guard. Requires the USER's LLM key (the non-deterministic, paid half of RAG eval); a mock judge verifies the harness key-free but is NOT a result. Use as the generation-side grader on the agent-researcher spine, after retrieval is measured with bm25-retrieval-metrics.
allowed-tools: Bash, Read, Write
---

# judge-rag-answers

The generation-side, key-heavy half of RAG evaluation. An LLM judge is a **bounded proxy** for human judgement, and this skill is built around its failure modes rather than trusting it: it reports estimates-with-error, calibrates against humans, and never prints a bare judge number as truth. It is the third of three RAG skills on the `agent-researcher` spine (this one at the *generation-grader* point); the retrieval half is `bm25-retrieval-metrics`.

## When to use
- After retrieval is measured (`bm25-retrieval-metrics`), to score whether the generated **answers** are faithful,
  relevant, and correct.
- To produce per-item generation scores that become a `trials.jsonl` `success` for the `agent-researcher` analysis.
- NOT for retrieval quality (that is deterministic and free — `bm25-retrieval-metrics`).

## Contract (important)
- **Requires the user's LLM key** (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`). No key → exit 2 with a hint. `--judge
  mock:<name>` runs a deterministic fake judge to verify the harness + the honesty math WITHOUT keys — its numbers
  are labeled `produces_results: false` and are NOT a result (like `scaffold-trials`' mock agent).
- **Never a bare number.** Every metric is reported with a bootstrap 95% CI over items (the unit of generalization
  is the question, not the rep), and `--reps` (default 3) exposes the judge's non-determinism as a within-item std.
- **Chance-corrected, not raw %.** With `--human-labels` it reports Cohen's **κ** judge-vs-human (raw % agreement
  overstates κ by ~38 points). Without human labels it says plainly the judge is UNCALIBRATED and its absolute level
  is untrustworthy.
- **Bias diagnostics, not just stability.** Reports a verbosity diagnostic (answer-length ↔ score correlation) and a
  **self-preference guard** — it warns loudly when the judge shares the generator's model family (the circularity
  that inflates a RAG number). A reproducible judge can still be maximally biased.
- **No hard-coded verdict.** It reports diagnostics; it does NOT apply a pass/fail threshold as a result (the
  `--pass-threshold` only binarizes scores for κ). The human judges.
- **Offline ≠ production.** A judge score is not deployment quality. Never present it as such.

## Steps
1. **Verify the harness key-free (optional):** `--judge mock:m1` — confirms the CI/κ/variance math runs; the report
   is stamped NOT A RESULT.
2. **Run the real judge (your keys, your spend):**
   ```bash
   .venv/bin/python "${CLAUDE_PLUGIN_ROOT}/skills/judge-rag-answers/scripts/judge_rag_answers.py" \
       --answers answers.jsonl --judge anthropic:claude-opus-5-2026-05-01 \
       --metrics faithfulness,answer_relevance --reps 3 \
       --human-labels human_labels.jsonl --generator-family <your generator's family>
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/judge-rag-answers/scripts/judge_rag_answers.py`.) Needs numpy +
   the provider's client (`openai` / `anthropic`). `answers.jsonl`: `{id, question, contexts[], answer[, reference]}`.
3. **Read the CI and κ, not the mean.** If κ is absent (no human labels) or low, the judge is not trustworthy — get
   a few hundred human labels (ARES-style) before believing the absolute number. Heed the self-preference warning.
4. **Feed per-item scores** into the `agent-researcher` trials as `success`, so the verdict carries a clustered
   interval and cost beside accuracy.

## Output style
- Lead with the Mermaid `## At a glance` and whether this is a real judge or a MOCK (not a result).
- Quote the CI and κ, never a bare mean. Surface the self-preference/verbosity diagnostics.
- Never soften "uncalibrated judge" or "offline ≠ production" into a footnote.

## Grounding
LLM-as-judge is a bounded proxy: strong judges reach >80% agreement with humans (the human-human level) but carry
position, verbosity, and self-enhancement biases ([Judging LLM-as-a-Judge, Zheng et al., NeurIPS 2023](https://arxiv.org/abs/2306.05685)).
Raw exact-match agreement overstates chance-corrected κ by ~38 points, and the most *reproducible* judges can be the
least *valid* — reliability is not validity ([Reliability without Validity](https://arxiv.org/html/2606.19544v1)),
which is why this skill reports κ + bias diagnostics, not just stability, and hard-codes no threshold. Self-preference
bias is real and largest for GPT-4-class judges scoring their own family's outputs, disproportionate to actual
quality ([Panickssery et al., NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/file/7f1f0218e45f5414c79c0679633e47bc-Paper-Conference.pdf)),
so the same model must not both generate and judge. Calibrating the judge against a few hundred human labels
(prediction-powered inference) is ARES's thesis ([ARES, NAACL 2024](https://arxiv.org/abs/2311.09476)) — the RAG
analog of this plugin's "an offline metric is not the truth".

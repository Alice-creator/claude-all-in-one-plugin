---
name: select-model
description: Recommend a model family for your data — runs after baseline, before train-tune. Computes a data fingerprint (size, features, categorical cardinality, task, balance, modality) and applies a research-grounded decision tree to recommend classic ML vs deep learning (and flags reinforcement learning as a separate paradigm), bounded by the baseline number and any interpretability/latency vetoes. Advisory only — it recommends, it does not train. Writes model_recommendation.md with a Mermaid decision tree. Use when asked "what model should I use?" or "is deep learning worth it here?".
allowed-tools: Bash, Read, Write, Glob
---

# select-model

Turn "what model should I use?" into a **defensible, cited recommendation** instead of a gut pick. After you have splits and a baseline number, this skill fingerprints your data and walks a decision tree grounded in the evidence (tree-based models vs deep learning on tabular data, size/modality thresholds, interpretability/latency vetoes). It **recommends a family and the bar to beat** — it never trains. That's `train-tune`.

## When to use
- Right after `baseline`, before `train-tune` — when choosing what to actually train.
- When someone reaches for a neural net / XGBoost / transformer without justifying it against the data and the baseline.
- To get a recommendation you can defend in review (family + alternatives + why + citation), not a hunch.

## Contract (important)
- **Advisory only.** Never trains, tunes, or predicts; emits no model and no predictions file. The deliverable is `model_recommendation.md`. (train-tune is what produces predictions for evaluate-model.)
- **Anchored to the baseline number, not a "tuned plateau."** It reads `baseline/baseline_metric.json` to state the bar to beat. Note: baseline trains an *untuned* simple model — that number is a reference bar, **not** proof that simple models are exhausted. The actual "has the simple model plateaued?" judgment belongs to `train-tune`.
- **Bounds every claim to its evidence.** It does **not** assert "trees beat deep learning" universally — the strong evidence is medium-sized, feature-meaningful tabular data, and the gap is often negligible vs GBDT tuning. The report says so inline.
- **Modality is a heuristic the user confirms.** The script cannot reliably detect image/audio/text from arbitrary columns; it flags candidates and you confirm. It never silently assumes tabular when text/path columns are present — surface the flags.
- **Interpretability & latency are vetoes**, surfaced as questions: regulated/auditable use or tight CPU latency forces a glass-box recommendation regardless of any accuracy edge.

## Steps
1. **Preflight.** Need splits (else → `split-dataset`) and ideally a baseline number (else → `baseline`; the recommendation still works, but you won't have a bar to beat).
2. **Paradigm gate (ask, before running the script).** A static split file can't reveal this, so ask:
   - Do the model's *actions change the environment* and is feedback a delayed/evaluative **reward** (not labeled targets)? → **Reinforcement learning.** Stop — this is a different paradigm, and this plugin's tabular tooling does not cover RL. (Sutton & Barto.)
   - Are there **labeled targets**? → supervised — proceed.
   - No labels, just structure? → unsupervised (clustering / dim-reduction) — out of this skill's current scope; note it and stop.
3. **Confirm modality & constraints.** Ask (or pass as flags): modality (default tabular), interpretability (`none`/`preferred`/`required`), latency (`none`/`cpu-tight`).
4. **Ensure deps & run:**
   ```bash
   python3 -c "import pandas, sklearn" 2>/dev/null || pip install pandas scikit-learn pyarrow
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/select-model/scripts/select_model.py" \
       --splits-dir "<dir from split-dataset>" --target <col> \
       [--modality tabular] [--interpretability none] [--latency none]
   ```
   (If `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/select-model/scripts/select_model.py`.)
5. **Read back the verdict, surface the flags.** Lead with the recommended family + why + the number to beat. If the script printed modality flags, raise them and confirm modality before trusting the recommendation. State any veto that fired.
6. **Hand off:** `train-tune --model <family>` on the same splits → then `evaluate-model` on its predictions.

## Output style
- One-line verdict first: e.g. *"tabular, n=124, 0 high-card cats → GBDT (also try TabPFN); must beat f1_macro=0.96."*
- Show the Mermaid decision tree (fired branch highlighted) and the ranked recommendation with one-line whys.
- Always restate the bounded-claim caveat — never present "trees > deep learning" as universal.

## Grounding
Modality as the primary fork (LeCun et al. 2015); tree-based models still SOTA on medium tabular data (Grinsztajn 2022; Shwartz-Ziv 2022) with the gap often negligible vs tuning (McElfresh 2023); TabPFN v2 on small tabular (Hollmann, Nature 2025); size/estimator routing (scikit-learn algorithm cheat-sheet); start-simple (Google Rules of ML); RL only for genuine sequential-decision/reward problems (Sutton & Barto).

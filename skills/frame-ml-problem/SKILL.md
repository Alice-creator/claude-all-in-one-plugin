---
name: frame-ml-problem
description: Translate a business/product goal into a well-posed ML problem BEFORE any modeling — separate the ideal outcome from the model's goal, decide whether ML is even needed (non-ML benchmark first), pin down the model's output, and define business success metrics distinct from technical evaluation metrics. Produces a reviewable Problem Framing Brief. Use at the very start of any ML/DL/RL effort, when a stakeholder asks for "an AI/ML feature", or when a stalled project lacks a measurable definition of success.
allowed-tools: Read, Write, Edit, Glob
---

# frame-ml-problem

Stage 1 of the ML lifecycle: turn a fuzzy goal ("we want AI to do X") into a **well-posed problem with a measurable definition of success** — *before* anyone touches data or models. Skipping this is the single most common reason ML projects ship great offline metrics and zero business impact.

This skill does **not** train anything. It interrogates the goal, forces the right separations, and writes a **Problem Framing Brief** you and stakeholders can review and sign off on.

## When to use
- Kicking off any ML / DL / RL effort — this is the first thing you do.
- A stakeholder asks for "an AI feature" / "a model that predicts X" without a clear why or success criterion.
- A project is stalled or thrashing because nobody can answer *"how do we know if this worked?"*
- Before deciding **whether to use ML at all** (this skill includes that gate).

## Contract (important)
- **NO modeling, NO data work.** This is upstream of `profile-dataset` / `clean-data`. The deliverable is a document, not a model.
- **Don't assume — ask.** Framing answers live in the user's head and the business context, not in any file. Ask, then write down what they said.
- **Separate the two goals.** The *ideal outcome* (what the product should achieve, independent of any model) is NOT the same as the *model's goal* (what the model predicts). Conflating them is the core failure mode this skill prevents.
- **Business success ≠ model metrics.** Accuracy / precision / recall / AUC are model evaluation metrics. They are not proof of business success. Keep them in separate sections.

## Steps

Work through these as a conversation. Ask the questions, push back on vague answers, and fill the brief as you go — don't dump all questions at once.

1. **Capture the context & ideal outcome.**
   - What is the business/product goal in plain language? Who is the user, what decision or action does this feed?
   - *Independent of any model*, what is the ideal outcome? (e.g. "users get a same-day delivery estimate they trust" — not "predict delivery time").

2. **Run the "do you even need ML?" gate.** (Rules of ML #1)
   - Is there a non-ML solution (rules, heuristic, lookup, existing tool)? If yes, that is your **benchmark**, not your competitor — ML must beat it to justify its cost.
   - If no heuristic exists, sketch one. Then ask: *would the ML version justify its added cost and complexity?* It's fine — often correct — to ship the heuristic first.
   - Record the verdict: **heuristic-first**, **ML-justified**, or **needs-a-prototype-to-decide**.

3. **Define the model's goal & output.** Only if ML cleared the gate.
   - What exactly does the model predict/do? Name the **task type**: binary/multiclass classification, regression, ranking, recommendation, sequence/generation, sequential decision-making (→ RL), etc.
   - **Handoff if the goal is an *agent*, not a model.** If the deliverable is something that *acts* — plays a game / competes on a Kaggle agent ladder, or is a tool-using agent to attack/defend — this tabular framing doesn't fit. Stop and hand off: a Kaggle "submit-an-agent" competition → `game-agent-builder`; red-teaming/hardening a tool-using agent → `agent-redteamer`. (`model-builder` stays tabular and refuses RL/agents.)
   - **Handoff if the goal is *images*, not tabular rows.** If the input is images and the goal is object detection / image classification / segmentation (bounding boxes, masks, a COCO-annotated dataset, an mAP/IoU/Dice metric), this tabular framing doesn't fit either. Stop and hand off to `cv-modeler` (it scaffolds a leakage-safe, transfer-learning YOLO detection pipeline; it does NOT train the model — that's GPU-hours the user runs — and does NOT do vision-model security / machine-unlearning). (`model-builder` stays tabular and refuses images.)
   - What is the concrete **output format** and how is it consumed (a score? a label? a ranked list? an action)? What threshold/decision turns the output into the product behavior?

4. **Define SUCCESS METRICS (business) — separately from evaluation metrics.**
   - The test of a good success metric: *if the model improves, do we measurably get closer to the ideal outcome?* If improving the model wouldn't move it, it's the wrong metric.
   - Specify how each success metric is **measured and instrumented** — and note that instrumentation should exist on the *current* system **before** building the model (Rules of ML #2), so you're not reconstructing metrics from logs later.

5. **Choose evaluation metrics — one optimizing, the rest satisficing.** (Ng, Machine Learning Yearning)
   - Pick a **single-number optimizing metric** the team maximizes (e.g. F1, AUC, RMSE).
   - Express other requirements as **satisficing** thresholds the model must merely clear (e.g. "p99 latency ≤ 100ms", "model size ≤ 50MB", fairness gap ≤ x).

6. **Surface constraints & risks.**
   - Constraints: latency, cost/compute budget, interpretability/explainability needs, privacy, fairness/regulatory.
   - Risks: what data would constitute **leakage** (info not available at prediction time)? What does a wrong prediction cost? What's the failure mode if the model is confidently wrong?

7. **Write the brief.** Fill the template at
   `${CLAUDE_PLUGIN_ROOT}/skills/frame-ml-problem/templates/framing-brief.md`
   (if `${CLAUDE_PLUGIN_ROOT}` is unset, use `skills/frame-ml-problem/templates/framing-brief.md`)
   and save the result as `problem_framing_brief.md` in the user's working directory. Leave any unanswered question explicitly marked `❓ OPEN` rather than guessing.
   - **Fill the "Framing at a glance" Mermaid diagram** at the top with the real values — it is the brief in one picture and must not be left as placeholders. Keep node labels short; put detail in the sections below.

8. **Confirm & hand off.** Walk the user through the filled brief, flag open questions, and recommend the next step: if ML is justified and data exists → `profile-dataset`; if heuristic-first → ship that and instrument metrics; if undecided → a time-boxed prototype against the heuristic benchmark.

## Output style
- Conversational and Socratic during steps 1–6 — short, pointed questions, one cluster at a time. Push back on vague or unmeasurable answers.
- The brief itself is the artifact: concise, skimmable, with the **ideal outcome**, **model goal**, **success metrics**, and **evaluation metrics** in clearly separated sections.
- End with the verdict (ML-justified / heuristic-first / prototype-to-decide), the list of `❓ OPEN` questions, and the recommended next skill.

## Grounding
The separations enforced here come from established practice, not opinion: Google's [Problem Framing](https://developers.google.com/machine-learning/problem-framing/ml-framing) (ideal outcome vs. model goal; success ≠ evaluation metrics), the [Rules of ML](https://developers.google.com/machine-learning/guides/rules-of-ml) (#1 don't fear shipping without ML; #2 instrument metrics first), and Andrew Ng's *Machine Learning Yearning* (single optimizing metric + satisficing metrics).

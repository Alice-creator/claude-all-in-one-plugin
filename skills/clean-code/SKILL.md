---
name: clean-code
description: Recall and apply a pragmatic, language-agnostic clean-code ruleset (the "Part 7" rules) when writing, editing, reviewing, or refactoring source code. Covers naming, coupling/cohesion, DRY (rule of three), function size, guard clauses, comments (why-not-what), tests-before-refactor, and YAGNI — each as a heuristic with its trade-off and when NOT to apply it. Use before a coding task, when deciding how to structure code, or when the user asks how to write cleaner code. Backed by Martin Fowler (Refactoring), Kent Beck (TDD), John Ousterhout (A Philosophy of Software Design), and Robert C. Martin (Clean Code) — including where they disagree.
allowed-tools: Read, Grep, Glob
---

# clean-code

Apply a **pragmatic, language-agnostic** clean-code ruleset. These are **heuristics with trade-offs**, NOT laws. The single meta-goal underneath all of them: **manage complexity and optimize for the human reader** — code is read far more often than it is written.

> When two rules conflict, the one that makes the code *easier to understand and change in this specific situation* wins. If a "rule" makes the code more complex here, the rule is wrong here.

## When to use
- Before starting any non-trivial coding task (writing or editing source files).
- When deciding how to structure a function, module, or class.
- When reviewing or refactoring code, or when the user asks how to make code cleaner.
- Pairs with the `clean-code-reviewer` agent (which audits a diff against these same rules) and the PostToolUse hook (which surfaces the compact checklist on every code edit).

## The 10 rules (apply these)

1. **Optimize for the reader (tối ưu cho người đọc).** Before committing, ask: *"In 6 months, will someone understand this in 30 seconds?"* Clarity beats cleverness.
2. **Names are the biggest, cheapest lever (đặt tên rõ ý định).** Use intention-revealing names. Length scales with scope (`i` in a 3-line loop is fine; a field needs a full name). Invest here before any other technique.
3. **Low coupling, high cohesion (khớp nối lỏng, gắn kết cao).** Things that change together belong together; minimize what each module must know about others. This is the compass — most other rules (SRP, DIP, deep modules) are just ways to achieve it.
4. **DRY by the Rule of Three (DRY theo rule of three).** Duplication is a *hint, not a command* (Fowler). Don't abstract on the 2nd occurrence; wait for the 3rd, when you've seen enough variation to abstract correctly. **The wrong abstraction is more expensive than duplication.**
5. **Functions: one level of abstraction, not a line count (một mức trừu tượng, không phải số dòng).** Extract a function when you need to *name* a block or *reuse* it — NOT to hit a magic line count. Length by itself is not the problem (this is contested: Martin wants 2–4 lines; Ousterhout warns over-splitting creates shallow modules and *raises* cognitive load).
6. **Flatten with guard clauses (giảm nesting).** Handle edge cases with early return/throw; keep the happy path at the shallowest indentation. (Broad consensus.)
7. **Comment the WHY, not the WHAT (comment "tại sao", bỏ "cái gì").** Comment intent, business constraints, invariants, why you *didn't* take the obvious approach, and the public contract of a function. Don't comment obvious "what" (`i++ // increment i`) — rename instead. Missing "why" comments are expensive to reconstruct later.
8. **Test before refactor; small steps; one hat at a time (test trước refactor; bước nhỏ; một mũ một lúc).** Have green tests as a safety net. Refactor in tiny behavior-preserving steps, running tests after each. Never add a feature and refactor in the same step (Beck's "Two Hats"). In TDD, don't skip the *refactor* step — that's where clean code actually happens.
9. **YAGNI by default (YAGNI mặc định).** Don't build speculative features/abstractions for an imagined future — but don't paint yourself into an architectural corner either.
10. **Be skeptical of absolute rules — including these (hoài nghi luật tuyệt đối).** They are heuristics, not dogma. Know *why* each exists so you know *when* to break it.

## How to apply (workflow)
1. **Before writing:** skim rules 1–5 for the task. Pick names first; decide module boundaries by coupling/cohesion.
2. **While writing:** prefer guard clauses (rule 6); add WHY-comments only where intent isn't obvious (rule 7); resist speculative abstraction (rules 4, 9).
3. **After writing / before declaring done:** self-check against all 10. The fastest deep check is to invoke the `clean-code-reviewer` agent on your diff.
4. **When refactoring:** rule 8 is non-negotiable — green tests, tiny steps, one hat.

## Output style
- When asked to *apply* the rules to code, show concrete before → after with the rule number(s) that motivated each change.
- When asked to *explain*, name the rule, its value, **and its trade-off / when not to apply it** — never present a rule as absolute.
- Flag genuine trade-offs explicitly (e.g. "splitting this further would satisfy rule 5's letter but violate its spirit by creating a shallow module").

## Trade-offs & controversies (so you don't apply rules dogmatically)
- **Function size (rule 5):** Martin (*Clean Code*) pushes 2–4 line functions; Ousterhout (*A Philosophy of Software Design*) argues over-splitting hurts readability ("deep modules" > many tiny ones). The claim that *length itself* impairs comprehension is **not well established** — judge by levels of abstraction, not line count.
- **Comments (rule 7):** Martin says "comments are always failures"; Ousterhout says missing comments cost 10–100× later; Fowler is in between (comment the why). Consensus leans toward Ousterhout/Fowler — Martin's absolute framing is too strong.
- **SOLID:** Useful (especially Dependency Inversion + Interface Segregation), but contested — Dan North proposes CUPID instead. Note SRP means *"one reason to change / one actor"*, NOT the vague "a class does one thing."
- **Strong consensus (apply freely):** low coupling/high cohesion, good naming, guard clauses, small behavior-preserving refactoring with tests, TDD red-green-refactor.

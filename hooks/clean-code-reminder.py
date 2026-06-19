#!/usr/bin/env python3
"""PostToolUse hook: after a code file is written/edited, inject a compact
clean-code reminder (the "Part 7" rules) into the conversation so the rules
stay top-of-mind on every code change.

Contract:
- Reads the PostToolUse event JSON from stdin.
- If the edited file is a source-code file, prints JSON with
  hookSpecificOutput.additionalContext and exits 0.
- Otherwise prints nothing and exits 0.
- Never raises: any error -> silent exit 0 (must not disrupt the edit).
"""
import json
import os
import sys

# File extensions we treat as "code". Config/docs/data are intentionally excluded.
CODE_EXTS = {
    "py", "pyi", "js", "jsx", "ts", "tsx", "mjs", "cjs",
    "java", "kt", "kts", "go", "rb", "rs", "php", "swift",
    "c", "h", "cpp", "cc", "cxx", "hpp", "hh", "cs", "scala",
    "sh", "bash", "zsh", "sql", "lua", "dart", "r", "jl",
    "ex", "exs", "clj", "cljs", "vue", "svelte", "m", "mm",
}

REMINDER = (
    "📐 Clean-code check (Part 7 rules — apply, don't just acknowledge):\n"
    "1. Reader-first: would someone get this in 30s?\n"
    "2. Names reveal intent (biggest, cheapest lever).\n"
    "3. Low coupling, high cohesion (things that change together stay together).\n"
    "4. DRY by rule of three — duplication is a hint, not a command; wrong abstraction is worse.\n"
    "5. Functions = one level of abstraction, NOT a line count.\n"
    "6. Guard clauses to flatten nesting.\n"
    "7. Comment the WHY + public contract, not the obvious WHAT.\n"
    "8. Test before refactor; tiny steps; one hat at a time.\n"
    "9. YAGNI — no speculative abstractions.\n"
    "10. These are heuristics, not dogma — break them when clarity demands.\n"
    "For a full explanation invoke the `clean-code` skill; "
    "for a deeper audit of this change, invoke the `clean-code-reviewer` agent."
)


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        event = json.loads(raw)
    except Exception:
        return  # malformed input -> do nothing

    tool_input = event.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("filePath") or ""
    if not file_path:
        return

    ext = os.path.splitext(file_path)[1].lstrip(".").lower()
    if ext not in CODE_EXTS:
        return  # not a code file -> stay silent

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": REMINDER,
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # never disrupt the edit
    sys.exit(0)

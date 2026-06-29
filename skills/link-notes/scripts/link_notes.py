#!/usr/bin/env python3
"""link_notes.py — knowledge-base index + active-recall scheduler for paper notes.

The RETAIN & CONNECT phase. Two subcommands, both pure-stdlib (no pandas/yaml):

  index   Scan the notes dir, parse each note's frontmatter + [[wikilinks]], and write
          a Map-of-Content `index.md` (Mermaid knowledge graph + a table grouped by tag)
          plus an `index.json` sidecar. CONNECT.

  recall  Gather every note's `## Recall prompts`, and schedule them with an expanding
          spaced-repetition interval (1,3,7,16,35,90 days) tracked in `recall_log.json`.
          Plain run lists what's DUE today; `--reviewed <slug>` advances that note's
          interval. RETAIN — because linked notes alone do NOT deliver recall; retrieval
          practice does (Roediger & Karpicke 2006).

NEVER modifies the notes themselves — only writes index.md / recall.md / recall_log.json.
Exit 0 ok · 1 bad args · 2 no notes found.

Usage:
    python3 link_notes.py index  [--notes-dir research/notes] [--out research/index.md]
    python3 link_notes.py recall [--notes-dir research/notes] [--out research/recall.md]
                                 [--log research/recall_log.json] [--reviewed <slug>] [--count 5]
"""
import argparse
import glob
import json
import os
import re
import sys

INTERVALS = [1, 3, 7, 16, 35, 90]  # days; expanding schedule, capped at last value


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def parse_note(path):
    """Minimal frontmatter + section parser (no yaml dep)."""
    txt = open(path, encoding="utf-8", errors="replace").read()
    fm = {}
    m = re.match(r"^---\n(.*?)\n---\n", txt, re.S)
    body = txt[m.end():] if m else txt
    if m:
        for line in m.group(1).splitlines():
            km = re.match(r"\s*([A-Za-z_]+)\s*:\s*(.*)$", line)
            if not km:
                continue
            key, val = km.group(1), km.group(2).strip()
            val = val.strip().strip('"').strip("'")
            if val.startswith("[") and val.endswith("]"):
                val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
            fm[key] = val
    # wikilinks anywhere in the body
    wikilinks = [w.strip() for w in re.findall(r"\[\[([^\]]+)\]\]", body) if w.strip()]
    # recall prompts: capture the "## Recall prompts" section, pull Q/A pairs
    recall = []
    rm = re.search(r"^##\s+Recall prompts\s*$(.*?)(^##\s|\Z)", body, re.S | re.M)
    if rm:
        section = rm.group(1)
        qa = re.findall(r"\*\*Q:\*\*\s*(.*?)\s*\n.*?\*\*A:\*\*\s*(.*?)\s*(?:\n|$)", section, re.S)
        for q, a in qa:
            q, a = q.strip(), a.strip()
            # skip the empty template prompts (just underscores / blank)
            if q and q not in ("_…_", "…") and not re.fullmatch(r"[_…\s]*", q):
                recall.append({"q": re.sub(r"\s+", " ", q), "a": re.sub(r"\s+", " ", a)})
    slug = os.path.splitext(os.path.basename(path))[0]
    tags = fm.get("tags") if isinstance(fm.get("tags"), list) else ([fm["tags"]] if fm.get("tags") else [])
    return {"slug": slug, "path": path, "title": fm.get("title", slug),
            "venue": fm.get("venue", ""), "year": fm.get("year", ""),
            "status": fm.get("status", ""), "tags": [t for t in tags if t and t != "paper"],
            "wikilinks": wikilinks, "recall": recall}


def load_notes(notes_dir):
    notes = [parse_note(p) for p in sorted(glob.glob(os.path.join(notes_dir, "*.md")))
             if os.path.basename(p) not in ("index.md", "recall.md")]
    return notes


def esc(s):
    return str(s or "").replace('"', "'").replace("|", "\\|").replace("\n", " ").strip()


# --------------------------------------------------------------------------- index
def cmd_index(a):
    notes = load_notes(a.notes_dir)
    if not notes:
        eprint(f"No notes found in {a.notes_dir}/ — run digest-paper first.")
        sys.exit(2)
    by_tag = {}
    for n in notes:
        for t in (n["tags"] or ["untagged"]):
            by_tag.setdefault(t, []).append(n)

    # resolve wikilink edges to known notes (match by slug or title, case-insensitive)
    by_key = {}
    for n in notes:
        by_key[n["slug"].lower()] = n
        by_key[esc(n["title"]).lower()] = n
    edges = []
    for n in notes:
        for w in n["wikilinks"]:
            tgt = by_key.get(w.lower())
            if tgt and tgt["slug"] != n["slug"]:
                edges.append((n["slug"], tgt["slug"]))

    def nid(slug):  # mermaid-safe id
        return "N" + re.sub(r"[^A-Za-z0-9]", "", slug)[:24]
    mlines = ["```mermaid", "flowchart LR"]
    for n in notes:
        mlines.append(f'    {nid(n["slug"])}["{esc(n["title"])[:34]}"]')
    seen = set()
    for s, t in edges:
        key = tuple(sorted((s, t)))
        if key in seen:
            continue
        seen.add(key)
        mlines.append(f"    {nid(s)} --- {nid(t)}")
    if not edges:
        mlines.append("    %% no [[wikilinks]] between notes yet — add them in each note's Links section")
    mlines.append("```")

    L = [f"# 📚 Reading knowledge base\n",
         "## At a glance",
         f"**{len(notes)} note(s)** across **{len(by_tag)} topic(s)**, {len(set(map(tuple, map(sorted, edges))))} link(s).\n",
         "\n".join(mlines), ""]
    for tag in sorted(by_tag):
        L.append(f"## {tag}\n")
        L.append("| Paper | Venue | Year | Status |")
        L.append("|---|---|---|---|")
        for n in sorted(by_tag[tag], key=lambda x: str(x["year"]), reverse=True):
            rel = os.path.relpath(n["path"], os.path.dirname(os.path.abspath(a.out)))
            L.append(f"| [{esc(n['title'])}]({rel}) | {esc(n['venue'])} | {n['year']} | {n['status']} |")
        L.append("")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        f.write("\n".join(L))
    with open(os.path.splitext(a.out)[0] + ".json", "w") as f:
        json.dump({"n_notes": len(notes), "tags": sorted(by_tag),
                   "edges": [list(e) for e in sorted(seen)],
                   "notes": [{k: n[k] for k in ("slug", "title", "venue", "year", "status", "tags")} for n in notes]},
                  f, indent=2)
    print(f"index → {a.out}  ({len(notes)} notes, {len(by_tag)} topics, {len(seen)} links)")


# --------------------------------------------------------------------------- recall
def cmd_recall(a):
    notes = load_notes(a.notes_dir)
    if not notes:
        eprint(f"No notes found in {a.notes_dir}/ — run digest-paper first.")
        sys.exit(2)
    log = {}
    if os.path.exists(a.log):
        log = json.load(open(a.log))
    today = a.today  # injected (no Date.now in this env); ISO yyyy-mm-dd

    if a.reviewed:
        rec = log.get(a.reviewed, {"level": 0})
        rec["level"] = min(rec.get("level", 0) + 1, len(INTERVALS) - 1)
        rec["last_reviewed"] = today
        rec["next_due"] = _add_days(today, INTERVALS[rec["level"]])
        log[a.reviewed] = rec
        json.dump(log, open(a.log, "w"), indent=2)
        print(f"marked '{a.reviewed}' reviewed → next due {rec['next_due']} (interval {INTERVALS[rec['level']]}d)")
        return

    with_recall = [n for n in notes if n["recall"]]
    # a note is due if untracked (never reviewed) or next_due <= today
    due = []
    for n in with_recall:
        rec = log.get(n["slug"])
        if rec is None or rec.get("next_due", "0000") <= today:
            due.append(n)
    due = due[:a.count]

    L = ["# 🧠 Active recall — due now\n",
         f"_{len(due)} of {len(with_recall)} note(s) with prompts are due as of {today}. "
         "Answer from memory FIRST, then check. Then run `link_notes.py recall --reviewed <slug>` "
         "to advance each one's interval (spaced repetition: " + ",".join(map(str, INTERVALS)) + " days).\n"]
    if not due:
        L.append("_Nothing due — you're caught up. 🎉_")
    for n in due:
        L.append(f"## {esc(n['title'])}  \n`{n['slug']}`\n")
        for i, qa in enumerate(n["recall"], 1):
            L.append(f"{i}. **Q:** {qa['q']}")
            L.append(f"   <details><summary>answer</summary>\n\n   {qa['a']}\n\n   </details>")
        L.append("")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        f.write("\n".join(L))
    print(f"recall → {a.out}  ({len(due)} note(s) due, {len(with_recall)} have prompts)")


def _add_days(iso, days):
    import datetime
    y, m, d = map(int, iso.split("-"))
    return (datetime.date(y, m, d) + datetime.timedelta(days=days)).isoformat()


def main():
    ap = argparse.ArgumentParser(description="Knowledge-base index + active-recall scheduler.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("index", help="build the Map-of-Content index + graph")
    pi.add_argument("--notes-dir", default="research/notes")
    pi.add_argument("--out", default="research/index.md")
    pr = sub.add_parser("recall", help="schedule/surface active-recall prompts")
    pr.add_argument("--notes-dir", default="research/notes")
    pr.add_argument("--out", default="research/recall.md")
    pr.add_argument("--log", default="research/recall_log.json")
    pr.add_argument("--reviewed", default=None, help="slug to mark reviewed (advances its interval)")
    pr.add_argument("--count", type=int, default=5, help="max notes to surface as due")
    pr.add_argument("--today", default=None, help="override today's date (yyyy-mm-dd); default = system date")
    a = ap.parse_args()
    if getattr(a, "today", None) is None and a.cmd == "recall":
        import datetime
        a.today = datetime.date.today().isoformat()
    (cmd_index if a.cmd == "index" else cmd_recall)(a)


if __name__ == "__main__":
    main()

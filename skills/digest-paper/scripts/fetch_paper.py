#!/usr/bin/env python3
"""fetch_paper.py — resolve a paper id and scaffold its literature note + mechanism HTML.

The MECHANICAL half of the DIGEST phase: given a DOI / OpenAlex id / arXiv id / title,
fetch bibliographic metadata + abstract (OpenAlex, with an arXiv-API fallback for arXiv
ids), then write two files into --out-dir:
  <slug>.md             — the literature note, objective fields pre-filled, comprehension
                          fields left as prompts for YOU to fill (reading is what builds recall)
  <slug>-mechanism.html — the self-contained mechanism explainer scaffold, header pre-filled

It deliberately does NOT write the summary/method/limitations — that's the human+agent
comprehension step (the paper-researcher agent fills those after actually reading).

READ-ONLY on the network; never overwrites an existing note (warns + appends -2, -3...).
Exit 0 = ok. 1 = bad args. 2 = network/resolve error.

Usage:
    python3 fetch_paper.py "10.1038/s41586-023-06139-9"      # DOI
    python3 fetch_paper.py "arxiv:2305.12345"                # arXiv id
    python3 fetch_paper.py "W4385245566"                     # OpenAlex id
    python3 fetch_paper.py --title "Attention is all you need"
        [--quartile Q1] [--tags nlp,transformers] [--out-dir research/notes] [--mailto you@org.com]
"""
import argparse
import datetime
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(os.path.dirname(HERE), "templates")


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def http_get_bytes(url, headers, timeout=15, tries=3):
    """GET with retry: exponential backoff + Retry-After on 429/5xx and transient network errors
    (connection failures AND read timeouts). OpenAlex/arXiv 503s are routine and the weekly routine
    must survive them; the modest timeout/tries keep worst-case latency bounded (~timeout*tries on a
    dead endpoint) so interactive use isn't punished. Byte-identical across the research scripts
    (enforced by tests/check_helpers_synced.py)."""
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise
            ra = e.headers.get("Retry-After") if e.headers else None
            delay = float(ra) if (ra and str(ra).strip().isdigit()) else min(2 ** attempt, 30)
        except (urllib.error.URLError, socket.timeout) as e:
            last = e
            if attempt == tries - 1:
                raise
            delay = min(2 ** attempt, 30)
        time.sleep(delay)
    if last is not None:
        raise last
    raise RuntimeError("http_get_bytes: tries must be >= 1")


def get_json(url, mailto):
    return json.loads(http_get_bytes(url, {"User-Agent": f"paper-curator/0.1 (mailto:{mailto})"}))


def get_text(url):
    return http_get_bytes(url, {"User-Agent": "paper-curator/0.1"}).decode("utf-8", "replace")


def reconstruct_abstract(inv):
    if not inv:
        return ""
    pos = [(i, w) for w, idxs in inv.items() for i in idxs]
    pos.sort()
    return " ".join(w for _, w in pos)


def from_openalex(work):
    src = (work.get("primary_location") or {}).get("source") or {}
    ids = work.get("ids") or {}
    arxiv = ""
    # OpenAlex sometimes records the arXiv id under ids or in the landing url
    for v in ids.values():
        m = re.search(r"arxiv\.org/abs/([0-9]+\.[0-9]+)", str(v))
        if m:
            arxiv = m.group(1)
    return {
        "title": work.get("title") or "(untitled)",
        "authors": [au.get("author", {}).get("display_name", "")
                    for au in (work.get("authorships") or [])],
        "year": work.get("publication_year") or "",
        "venue": src.get("display_name") or "",
        "doi": (work.get("doi") or "").replace("https://doi.org/", ""),
        "arxiv": arxiv,
        "openalex": work.get("id") or "",
        "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
    }


def from_arxiv(arxiv_id, mailto):
    """arXiv API (Atom) fallback — best for preprints OpenAlex may not index well."""
    import html
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"id_list": arxiv_id, "max_results": "1"})
    xml = get_text(url)
    # Scope to the <entry> — the feed has its own top-level <title> (the query echo).
    m = re.search(r"<entry>(.*?)</entry>", xml, re.S)
    if not m:
        raise SystemExit(f"arXiv returned no entry for id {arxiv_id!r} (check the id).")
    entry = m.group(1)

    def tag(name):
        mm = re.search(rf"<{name}>(.*?)</{name}>", entry, re.S)
        return html.unescape(re.sub(r"\s+", " ", mm.group(1)).strip()) if mm else ""
    authors = [html.unescape(a.strip()) for a in re.findall(r"<author>\s*<name>(.*?)</name>", entry, re.S)]
    published = tag("published")
    return {
        "title": tag("title"), "authors": authors,
        "year": published[:4], "venue": "arXiv (preprint)",
        "doi": "", "arxiv": arxiv_id, "openalex": "",
        "abstract": tag("summary"),
    }


def resolve(identifier, title, mailto):
    if title:
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(
            {"search": title, "per-page": "1",
             "select": "id,doi,title,publication_year,authorships,primary_location,abstract_inverted_index,ids"})
        res = get_json(url, mailto).get("results")
        if not res:
            raise SystemExit(f"No OpenAlex match for title {title!r}")
        return from_openalex(res[0])
    ident = identifier.strip()
    low = ident.lower()
    if low.startswith("arxiv:") or re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", ident):
        return from_arxiv(ident.split(":", 1)[-1], mailto)
    if low.startswith("w") and ident[1:].isdigit():
        return from_openalex(get_json(f"https://api.openalex.org/works/{ident}", mailto))
    if "openalex.org/" in low:
        return from_openalex(get_json("https://api.openalex.org/works/" + ident.rstrip("/").split("/")[-1], mailto))
    # otherwise treat as a DOI (with or without the https://doi.org/ prefix)
    doi = re.sub(r"^https?://doi\.org/", "", ident, flags=re.I)
    return from_openalex(get_json("https://api.openalex.org/works/doi:" + urllib.parse.quote(doi), mailto))


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", (title or "paper").lower()).strip("-")
    return s[:50] or "paper"


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base}-{n}{ext}"):
        n += 1
    eprint(f"WARN: {path} exists — writing {base}-{n}{ext} instead (not overwriting your notes).")
    return f"{base}-{n}{ext}"


def fill(template, meta, mech_html_name, quartile, tags, html_escape=False):
    link = (f"https://doi.org/{meta['doi']}" if meta["doi"]
            else (f"https://arxiv.org/abs/{meta['arxiv']}" if meta["arxiv"] else meta["openalex"]))
    repl = {
        "TITLE": meta["title"], "AUTHORS": ", ".join(meta["authors"][:6]) + (" et al." if len(meta["authors"]) > 6 else ""),
        "YEAR": str(meta["year"] or ""), "VENUE": meta["venue"], "QUARTILE": quartile or "",
        "DOI": meta["doi"], "ARXIV": meta["arxiv"], "OPENALEX": meta["openalex"],
        "TAGS": tags or "", "DATE": datetime.date.today().isoformat(),
        "MECHANISM_HTML": mech_html_name, "LINK": link,
    }
    # HTML templates get the field values HTML-escaped (a title with & < > must not break the page
    # or inject markup). The markdown note is left raw — escaping it would be wrong (mangles the text).
    if html_escape:
        repl = {k: str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") for k, v in repl.items()}
    out = template
    for k, v in repl.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def main():
    p = argparse.ArgumentParser(description="Scaffold a literature note + mechanism HTML for a paper.")
    p.add_argument("identifier", nargs="?", help="DOI / arXiv id (arxiv:NNNN.NNNNN) / OpenAlex id")
    p.add_argument("--title", help="resolve by title search instead of an id")
    p.add_argument("--quartile", default="", help="carry the quartile from discover-papers (e.g. Q1)")
    p.add_argument("--tags", default="", help="comma list of tags for the note frontmatter")
    p.add_argument("--type", choices=["method", "survey", "benchmark", "analysis"], default="method",
                   help="paper type → picks the visual archetype. survey uses the taxonomy/landscape "
                        "template (a MAP of approaches); the others use the mechanism/pipeline template.")
    p.add_argument("--out-dir", default="research/notes")
    p.add_argument("--mailto", default="research@example.com")
    a = p.parse_args()
    if not a.identifier and not a.title:
        eprint("ERROR: give a DOI/arXiv/OpenAlex id, or --title.")
        sys.exit(1)

    try:
        meta = resolve(a.identifier or "", a.title, a.mailto)
    except SystemExit:
        raise
    except Exception as e:
        eprint(f"ERROR resolving paper: {type(e).__name__}: {e}")
        sys.exit(2)

    os.makedirs(a.out_dir, exist_ok=True)
    slug = slugify(meta["title"])
    note_path = unique_path(os.path.join(a.out_dir, slug + ".md"))
    mech_name = os.path.splitext(os.path.basename(note_path))[0] + "-mechanism.html"
    mech_path = os.path.join(a.out_dir, mech_name)

    note_tpl = open(os.path.join(TEMPLATES, "literature-note.md")).read()
    # paper type picks the visual archetype: survey -> taxonomy/landscape map; else mechanism/pipeline.
    archetype = "landscape.html" if a.type == "survey" else "mechanism.html"
    mech_tpl = open(os.path.join(TEMPLATES, archetype)).read()
    with open(note_path, "w") as f:
        f.write(fill(note_tpl, meta, mech_name, a.quartile, a.tags))  # markdown — raw, no HTML escaping
    with open(mech_path, "w") as f:
        f.write(fill(mech_tpl, meta, mech_name, a.quartile, a.tags, html_escape=True))  # HTML — escape & < >

    # machine-readable metadata for the agent (so it fills comprehension from real fields)
    print(json.dumps({
        "title": meta["title"], "authors": meta["authors"], "year": meta["year"],
        "venue": meta["venue"], "quartile": a.quartile, "doi": meta["doi"],
        "arxiv": meta["arxiv"], "openalex": meta["openalex"],
        "abstract": meta["abstract"],
        "note_path": note_path, "mechanism_path": mech_path,
    }, indent=2))
    eprint(f"scaffolded → {note_path}\n              {mech_path}  (archetype: {archetype})")
    eprint("Next: read the paper (3-pass) and fill the comprehension fields + the diagram.")
    if a.type == "method":
        eprint("Tip: if this is actually a SURVEY/benchmark/analysis, re-run with --type survey (etc.) "
               "for the right visual — a survey should be a MAP of approaches, not one pipeline.")


if __name__ == "__main__":
    main()

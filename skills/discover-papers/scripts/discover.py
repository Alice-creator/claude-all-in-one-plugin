#!/usr/bin/env python3
"""discover.py — find Q1 / high-impact ML papers for a keyword (DISCOVER phase).

Searches OpenAlex (free, keyless) by keyword, then keeps papers that are EITHER
published in a Q1 journal (Scimago SJR best-quartile) OR high-impact by citations,
and writes a ranked shortlist + a machine-readable JSON sidecar.

Why this design (grounded):
- OpenAlex is the workhorse: free, no key, full-text/abstract keyword search,
  returns venue + ISSN + citation counts + abstracts in ONE call.
- "Q1" is a JOURNAL ranking (Scimago SJR / JCR) — arXiv preprints have no quartile.
  Scimago blocks scripted download, so TRUE-Q1 needs a one-time manual CSV download
  from https://www.scimagojr.com/journalrank.php (the "Download data" button).
  Pass it with --scimago; without it we fall back to impact-only and SAY SO.
- "High-impact" = citations-per-year above a floor, so recent strong preprints
  that have no journal quartile yet still surface (your "Q1 OR high-impact" intent).

READ-ONLY on any local data. Writes only the shortlist + JSON into --out-dir.

Exit 0 = ran. 1 = bad args. 2 = network/API error. 3 = no candidates found.

Usage:
    python3 discover.py "graph neural network" [--from-year 2023] [--max 80]
        [--min-cites-per-year 5] [--require either|q1|impact]
        [--scimago /path/scimagojr.csv] [--mailto you@org.com] [--out-dir research/candidates]
"""
import argparse
import csv
import datetime
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

OPENALEX = "https://api.openalex.org/works"


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


def http_get_json(url, mailto):
    # OpenAlex asks for a mailto for the polite pool; harmless if absent.
    return json.loads(http_get_bytes(url, {"User-Agent": f"paper-curator/0.1 (mailto:{mailto})"}))


def reconstruct_abstract(inv):
    """OpenAlex returns abstracts as an inverted index {word: [positions]}; rebuild the text."""
    if not inv:
        return ""
    positions = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)


# --------------------------------------------------------------------------- Scimago
def load_scimago(path):
    """Parse a Scimago journalrank CSV (semicolon-delimited) into ISSN->quartile and
    title->quartile maps. Returns (issn_map, title_map) or (None, None) if unavailable."""
    if not path:
        return None, None
    if not os.path.exists(path):
        eprint(f"WARN: --scimago file not found: {path} — falling back to impact-only ranking.")
        return None, None
    issn_map, title_map = {}, {}
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        # Scimago uses ';' as delimiter; sniff but default to ';'.
        sample = f.read(4096)
        f.seek(0)
        delim = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.DictReader(f, delimiter=delim)
        # Column names vary slightly by year; match case-insensitively.
        cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}
        issn_c = cols.get("issn")
        title_c = cols.get("title")
        quart_c = cols.get("sjr best quartile") or cols.get("sjr_best_quartile")
        if not (quart_c and (issn_c or title_c)):
            eprint("WARN: Scimago CSV missing expected columns (Issn / Title / SJR Best Quartile) — impact-only.")
            return None, None
        for row in reader:
            q = (row.get(quart_c) or "").strip().upper()
            if q not in ("Q1", "Q2", "Q3", "Q4"):
                continue
            if title_c:
                t = (row.get(title_c) or "").strip().lower()
                if t:
                    title_map[t] = q
            if issn_c:
                # Scimago packs multiple ISSNs like "10459227, 19410093"
                for issn in (row.get(issn_c) or "").replace(" ", "").split(","):
                    issn = norm_issn(issn)
                    if issn:
                        issn_map[issn] = q
    return issn_map, title_map


def norm_issn(s):
    """Normalize an ISSN to 8 digits + X, no hyphen, uppercase."""
    s = (s or "").replace("-", "").strip().upper()
    return s if len(s) == 8 and s[:7].isdigit() else None


def quartile_for(work, issn_map, title_map):
    if issn_map is None:
        return None
    src = (work.get("primary_location") or {}).get("source") or {}
    issns = [src.get("issn_l")] + (src.get("issn") or [])
    for raw in issns:
        q = issn_map.get(norm_issn(raw) or "")
        if q:
            return q
    name = (src.get("display_name") or "").strip().lower()
    return title_map.get(name)


# --------------------------------------------------------------------------- scoring
def cites_per_year(work, this_year):
    yr = work.get("publication_year") or this_year
    age = max(1, this_year - yr + 1)
    return (work.get("cited_by_count") or 0) / age


def main():
    p = argparse.ArgumentParser(description="Discover Q1 / high-impact papers for a keyword (OpenAlex).")
    p.add_argument("query", help="keyword / phrase to search for")
    p.add_argument("--from-year", type=int, default=None, help="only papers published on/after this year")
    p.add_argument("--max", type=int, default=80, help="candidates to fetch from OpenAlex (max 200)")
    p.add_argument("--min-cites-per-year", type=float, default=5.0,
                   help="impact floor: citations/year to count as 'high-impact'")
    p.add_argument("--require", choices=["either", "q1", "impact"], default="either",
                   help="keep papers that are Q1 OR high-impact (default), or restrict to one")
    p.add_argument("--scimago", default=os.environ.get("SCIMAGO_CSV"),
                   help="path to a Scimago journalrank CSV for TRUE Q1 (else impact-only)")
    p.add_argument("--mailto", default="research@example.com", help="contact for OpenAlex polite pool")
    p.add_argument("--out-dir", default="research/candidates")
    p.add_argument("--top", type=int, default=25, help="max rows to keep in the shortlist")
    a = p.parse_args()

    this_year = datetime.date.today().year
    issn_map, title_map = load_scimago(a.scimago)
    have_scimago = issn_map is not None

    # Honesty guard: --require q1 is IMPOSSIBLE without a quartile table — say that, don't pretend
    # it's merely an empty result set. Without Scimago every quartile is None, so nothing can match.
    if a.require == "q1" and not have_scimago:
        eprint("REFUSED: --require q1 needs a Scimago quartile table to know which journals are Q1, but "
               "none was supplied (--scimago). Without it every paper's quartile is unknown, so NOTHING "
               "can match — this is impossible, not merely empty. Download journalrank.csv from "
               "https://www.scimagojr.com/journalrank.php and pass --scimago, or use --require either|impact.")
        sys.exit(1)

    filters = ["type:article"]
    if a.from_year:
        filters.append(f"from_publication_date:{a.from_year}-01-01")
    params = {
        "search": a.query,
        "filter": ",".join(filters),
        "per-page": str(min(200, max(1, a.max))),
        "select": "id,doi,title,publication_year,cited_by_count,authorships,primary_location,abstract_inverted_index",
    }
    url = OPENALEX + "?" + urllib.parse.urlencode(params)
    try:
        data = http_get_json(url, a.mailto)
    except Exception as e:
        eprint(f"ERROR querying OpenAlex: {type(e).__name__}: {e}")
        sys.exit(2)

    cands = []
    for w in data.get("results", []):
        src = (w.get("primary_location") or {}).get("source") or {}
        # skip non-journal/conference containers (ebooks, repositories) for a quality list
        if (src.get("type") or "") not in ("journal", "conference", "book series", ""):
            continue
        q = quartile_for(w, issn_map, title_map)
        cpy = cites_per_year(w, this_year)
        is_q1 = q == "Q1"
        is_impact = cpy >= a.min_cites_per_year
        if a.require == "q1" and not is_q1:
            continue
        if a.require == "impact" and not is_impact:
            continue
        if a.require == "either" and not (is_q1 or is_impact):
            continue
        authors = [au.get("author", {}).get("display_name", "") for au in (w.get("authorships") or [])][:4]
        cands.append({
            "title": w.get("title") or "(untitled)",
            "authors": authors,
            "year": w.get("publication_year"),
            "venue": src.get("display_name"),
            "venue_type": src.get("type"),
            "quartile": q,                      # None when no Scimago table / unmatched
            "is_q1": is_q1,
            "cited_by_count": w.get("cited_by_count") or 0,
            "cites_per_year": round(cpy, 1),
            "is_high_impact": is_impact,
            "openalex": w.get("id"),
            "doi": w.get("doi"),
            "abstract": reconstruct_abstract(w.get("abstract_inverted_index"))[:1200],
        })

    if not cands:
        eprint(f"No Q1/high-impact candidates for {a.query!r} "
               f"(require={a.require}, min_cites_per_year={a.min_cites_per_year}). "
               "Loosen --min-cites-per-year, drop --from-year, or widen --require.")
        sys.exit(3)

    # rank: Q1 first, then by citations/year (impact), then total citations
    cands.sort(key=lambda c: (c["is_q1"], c["cites_per_year"], c["cited_by_count"]), reverse=True)
    cands = cands[:a.top]

    os.makedirs(a.out_dir, exist_ok=True)
    slug = "".join(ch if ch.isalnum() else "-" for ch in a.query.lower()).strip("-")[:40]
    stamp = datetime.date.today().isoformat()
    base = f"{slug}-{stamp}"
    md_path = os.path.join(a.out_dir, base + ".md")
    json_path = os.path.join(a.out_dir, base + ".json")

    n_q1 = sum(c["is_q1"] for c in cands)
    n_imp = sum(c["is_high_impact"] and not c["is_q1"] for c in cands)
    quality_note = (f"Q1 from Scimago table `{os.path.basename(a.scimago)}`"
                    if have_scimago else
                    "⚠️ no Scimago table supplied (`--scimago`), so **quartiles are unknown** — "
                    "ranking is impact-only; pass a Scimago CSV for true Q1 labels")

    total_hits = data.get("meta", {}).get("count")
    hits_txt = f"{total_hits:,}" if isinstance(total_hits, int) else "?"
    mermaid = "\n".join([
        "```mermaid", "flowchart LR",
        f'    K["🔎 \\"{a.query}\\""] --> OA["OpenAlex<br/>{hits_txt} hits"]',
        f'    OA --> F["keep Q1 OR high-impact<br/>(≥{a.min_cites_per_year}/yr)"]',
        f'    F --> Q1["🏅 Q1 journal<br/>{n_q1}"]',
        f'    F --> IMP["📈 high-impact<br/>{n_imp}"]',
        "```",
    ])

    rows = []
    for i, c in enumerate(cands, 1):
        tag = "🏅 Q1" if c["is_q1"] else ("📈 impact" if c["is_high_impact"] else "—")
        link = (c["doi"] or c["openalex"] or "")
        au = ", ".join(c["authors"]) + (" et al." if len(c["authors"]) >= 4 else "")
        rows.append(f"| {i} | [{md_cell(c['title'])}]({link}) | {md_cell(au)} | "
                    f"{md_cell(c['venue'])} | {c['year']} | {c['quartile'] or '?'} | "
                    f"{c['cited_by_count']:,} ({c['cites_per_year']}/yr) | {tag} |")

    md = f"""# Paper candidates — "{a.query}"

> Produced by `discover-papers` via OpenAlex on {stamp}. {quality_note}. Read-only.

## At a glance
{mermaid}

**{len(cands)} candidate(s)** — {n_q1} Q1-journal, {n_imp} high-impact (non-Q1). Ranked Q1 → citations/year. These are *candidates to triage*, not a quality judgment — OpenAlex ranks by text relevance and citation counts lag for recent papers.

## Shortlist
| # | Title | Authors | Venue | Year | Quartile | Citations | Why kept |
|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

## Next step
Pick one and run the `paper-researcher` agent / `digest-paper` skill on its DOI or OpenAlex id to get a structured digest + an HTML mechanism explainer. Machine-readable list: `{os.path.basename(json_path)}`.
"""
    with open(md_path, "w") as f:
        f.write(md)
    with open(json_path, "w") as f:
        json.dump({"query": a.query, "generated": stamp, "source": "openalex",
                   "scimago_used": have_scimago, "require": a.require,
                   "min_cites_per_year": a.min_cites_per_year,
                   "n_candidates": len(cands), "candidates": cands}, f, indent=2)

    print(f"query={a.query!r} | kept {len(cands)} ({n_q1} Q1, {n_imp} high-impact)"
          + ("" if have_scimago else " | NOTE: no Scimago table → quartiles unknown, impact-only"))
    print(f"  written → {md_path}")
    print(f"            {json_path}")


def md_cell(s):
    return str(s or "").replace("|", "\\|").replace("\n", " ").strip()


if __name__ == "__main__":
    main()

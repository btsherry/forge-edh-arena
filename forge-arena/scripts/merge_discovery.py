#!/usr/bin/env python3
"""Merge the FABLE + Gemini whole-deck discovery outputs into the canonical
`discovered-synergies-wholedeck.json` (schema arena.discovered-synergies-wholedeck/1).

Usage:
    python3 scripts/merge_discovery.py <deck-slug>

Reads (from decks/<slug>/dossier/):
    discovered-synergies-fable.json    — the FABLE workflow catalog (primary)
    discovered-synergies-gemini.json   — gemini_wholedeck.py output (cross-check)
Writes:
    discovered-synergies-wholedeck.json

FABLE is primary: its records become `fable_catalog` (deduped by anchor+sorted-
partners, keeping the higher compile_rank, capped). Gemini records whose key is NOT
already in the FABLE set become `gemini_only_candidates`; overlaps are counted.
Env: RECORD_CAP (default 200), TOP_ANCHORS (default 12).
"""
import json, os, sys

DECK = sys.argv[1] if len(sys.argv) > 1 else "selvala-heart-of-the-wilds"
CAP = int(os.environ.get("RECORD_CAP", "200"))
TOP_N = int(os.environ.get("TOP_ANCHORS", "12"))

HERE = os.path.dirname(os.path.abspath(__file__))   # <repo>/forge-arena/scripts
ARENA = os.path.dirname(HERE)                        # <repo>/forge-arena
DOSSIER = f"{ARENA}/decks/{DECK}/dossier"


def records(path):
    """Extract a records list from any of the shapes we emit (list, or an object
    with a records/fable_catalog/catalog/gemini_only_candidates array)."""
    try:
        d = json.load(open(path))
    except FileNotFoundError:
        return []
    if isinstance(d, list):
        return d
    for k in ("records", "fable_catalog", "catalog", "gemini_only_candidates"):
        if isinstance(d.get(k), list):
            return d[k]
    return []


def key(r):
    cs = [r.get("anchor")] + list(r.get("partner_cards") or [])
    return " + ".join(sorted(c.strip() for c in cs if c))


fable = records(f"{DOSSIER}/discovered-synergies-fable.json")
gemini = records(f"{DOSSIER}/discovered-synergies-gemini.json")

# FABLE is primary; dedup within it keeping the higher compile_rank.
seen = {}
for r in fable:
    k = key(r)
    if k not in seen or (r.get("compile_rank") or 0) > (seen[k].get("compile_rank") or 0):
        seen[k] = r
fable_catalog = sorted(seen.values(), key=lambda r: -(r.get("compile_rank") or 0))[:CAP]
fable_keys = {key(r) for r in fable_catalog}

# Gemini records not already covered by FABLE.
gem_seen, overlap = {}, 0
for r in gemini:
    k = key(r)
    if k in fable_keys:
        overlap += 1
        continue
    if k not in gem_seen or (r.get("compile_rank") or 0) > (gem_seen[k].get("compile_rank") or 0):
        gem_seen[k] = r
gemini_only = list(gem_seen.values())

# Richest anchors by summed compile_rank.
by_anchor = {}
for r in fable_catalog:
    by_anchor[r.get("anchor")] = by_anchor.get(r.get("anchor"), 0) + (r.get("compile_rank") or 0)
top_anchors = [a for a, _ in sorted(by_anchor.items(), key=lambda kv: -kv[1])[:TOP_N] if a]

shape_is_new_backlog = [
    {"key": key(r), "program_class": r.get("program_class") or "", "mechanism": r.get("mechanism") or ""}
    for r in fable_catalog if r.get("shape_is_new")
]

out = {
    "schema": "arena.discovered-synergies-wholedeck/1",
    "deck": DECK,
    "note": (f"Merged FABLE ({len(fable_catalog)}) + Gemini cross-check "
             f"({len(gemini)} total, {len(gemini_only)} unique). FABLE = primary. DISCOVERY ONLY."),
    "counts": {
        "fable_valid": len(fable_catalog),
        "gemini_total": len(gemini),
        "gemini_only": len(gemini_only),
        "overlap_fable_gemini": overlap,
        "final_capped": len(fable_catalog),
    },
    "top_anchors": top_anchors,
    "shape_is_new_backlog": shape_is_new_backlog,
    "fable_catalog": fable_catalog,
    "gemini_only_candidates": gemini_only,
}
path = f"{DOSSIER}/discovered-synergies-wholedeck.json"
json.dump(out, open(path, "w"), indent=1)
print(f"merged -> {path}: fable={len(fable_catalog)} gemini_only={len(gemini_only)} "
      f"overlap={overlap} shape_is_new={len(shape_is_new_backlog)}")

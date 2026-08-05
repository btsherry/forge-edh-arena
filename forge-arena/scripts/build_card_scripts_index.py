#!/usr/bin/env python3
"""Build decks/<deck-slug>/dossier/card-scripts-index.json — the name -> absolute
Forge card-script path index (schema arena.card-scripts-index/1) that discovery
shards and the arena-dev compile step read T0 scripts through.

Deterministic and idempotent: exits without writing when the existing index
already resolves every non-basic card in deck-cards.json (--force rebuilds).
Resolution tries the snake_case filename slug first, then falls back to a single
full cardsfolder scan matching exact `Name:` lines — that covers the lossy slugs
(DFC files like bala_ged_recovery_bala_ged_sanctuary.txt, Nylea -> nylea_keeneyed).

Usage:
    python3 scripts/build_card_scripts_index.py <deck-slug> [-o OUT] [--force]

Exit: 0 all resolved (or up-to-date), 1 unresolved cards remain, 2 usage/missing input.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))   # <repo>/forge-arena/scripts
ARENA = os.path.dirname(HERE)                        # <repo>/forge-arena
REPO = os.path.dirname(ARENA)
CARDSFOLDER = os.path.join(REPO, "forge-gui", "res", "cardsfolder")
SCHEMA = "arena.card-scripts-index/1"


def slug(name):
    return re.sub(r"[^a-z0-9_]", "", name.lower().replace(" ", "_"))


def names_in(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return [line[5:].strip() for line in f if line.startswith("Name:")]


def full_scan():
    """One pass over cardsfolder: every Name: line (front and back faces) -> file."""
    m = {}
    for root, _dirs, files in os.walk(CARDSFOLDER):
        for fn in files:
            if fn.endswith(".txt"):
                p = os.path.join(root, fn)
                for n in names_in(p):
                    m.setdefault(n, p)
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("deck", help="deck slug under forge-arena/decks/")
    ap.add_argument("-o", "--out", help="write here instead of the dossier (diff/testing)")
    ap.add_argument("--force", action="store_true", help="rebuild even if the index is healthy")
    a = ap.parse_args()

    deck_path = os.path.join(ARENA, "decks", a.deck, "dossier", "deck-cards.json")
    if not os.path.isfile(deck_path):
        sys.exit(f"usage: no deck-cards.json at {deck_path} — run prep.sh first (exit 2)")
    with open(deck_path) as f:
        deck = json.load(f)

    # Non-basic cards, deduped, in deck-cards order — the same filter as anchors.py.
    wanted, seen = [], set()
    for c in deck["cards"]:
        if "Basic" in (c.get("type_line") or ""):
            continue
        if c["name"] not in seen:
            seen.add(c["name"])
            wanted.append(c["name"])

    out_path = a.out or os.path.join(ARENA, "decks", a.deck, "dossier", "card-scripts-index.json")
    if not a.force and os.path.isfile(out_path):
        try:
            with open(out_path) as f:
                cur = json.load(f)
            if not cur.get("unresolved") and all(n in cur.get("index", {}) for n in wanted):
                print(f"up-to-date: {out_path} ({len(cur['index'])} resolved)")
                return
        except (json.JSONDecodeError, KeyError):
            pass  # corrupt index: rebuild it

    index, unresolved, scan = {}, [], None
    for name in wanted:
        s = slug(name)
        cand = os.path.join(CARDSFOLDER, s[0], s + ".txt") if s else ""
        if cand and os.path.isfile(cand) and name in names_in(cand):
            index[name] = cand
            continue
        if scan is None:
            scan = full_scan()
        if name in scan:
            index[name] = scan[name]
        else:
            unresolved.append(name)

    doc = {
        "schema": SCHEMA,
        "cardsfolder_root": CARDSFOLDER,
        "resolved": len(index),
        "unresolved": unresolved,
        "index": index,
    }
    with open(out_path, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    print(f"wrote {out_path}: {len(index)} resolved, {len(unresolved)} unresolved")
    if unresolved:
        for n in unresolved:
            print(f"  UNRESOLVED: {n}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

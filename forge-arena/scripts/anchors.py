#!/usr/bin/env python3
"""Print a deck's non-basic anchor card names as a JSON array — the value to pass
as the FABLE whole-deck workflow's `args.anchors` (Workflow scripts can't read the
filesystem, so the caller supplies the anchors).

Usage:
    python3 scripts/anchors.py <deck-slug>
    -> ["Allosaurus Shepherd","Ancient Tomb",...]

Basics (including Snow-Covered basics) are excluded via the type line.
"""
import json, os, sys

DECK = sys.argv[1] if len(sys.argv) > 1 else "selvala-heart-of-the-wilds"
HERE = os.path.dirname(os.path.abspath(__file__))   # <repo>/forge-arena/scripts
ARENA = os.path.dirname(HERE)                        # <repo>/forge-arena
deck = json.load(open(f"{ARENA}/decks/{DECK}/dossier/deck-cards.json"))

anchors = sorted({
    c["name"] for c in deck["cards"]
    if "Basic" not in (c.get("type_line") or "")
})
print(json.dumps(anchors))

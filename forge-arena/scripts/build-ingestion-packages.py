#!/usr/bin/env python3
"""Assemble the ingestion packages for the hand-run of the new pattern.

Emits:
  packages/cards/<n>.json   one per unique card: oracle text, script, combos
  packages/deck-package.json  the whole-deck package for Gemini
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path("/Users/toor/Claude/personal/forge-edh-arena")
OUT = Path("/private/tmp/claude-501/-Users-toor-Claude/472653bf-a5b3-4295-8ed3-bc916e689d2e/scratchpad/packages")
DECK = ROOT / "forge-arena/decks/purphoros-god-of-the-forge2.dck"
DOSSIER = ROOT / "forge-arena/decks/purphoros-god-of-the-forge/dossier"
PRIMER = ROOT / "forge-arena/docs/primers/purphoros-god-of-the-forge-deckcheck.md"
CARDS = ROOT / "forge-gui/res/cardsfolder"

sys.path.insert(0, str(Path(__file__).parent))
from capproto import capabilities, script_for as _script_for


def script_for(name):
    """Resolve a card to its Forge script, including split-name cards.

    Subagent finding: 7 of 78 cards had no script because modal
    double-faced and Adventure cards are stored as frontname_backname.txt
    (virtue_of_courage_embereth_blaze.txt). Falling back to a prefix match
    on the normalised front-face name recovers them.
    """
    direct = _script_for(name)
    if direct is not None:
        return direct
    import re as _re
    from pathlib import Path as _P
    key = (name.split("//")[0].strip().lower()
           .replace(",", "").replace("'", "").replace("-", "_")
           .replace(" ", "_").replace(".", "").replace("!", ""))
    root = _P("/Users/toor/Claude/personal/forge-edh-arena/forge-gui/res/cardsfolder")
    hits = sorted(root.glob(f"{key[0]}/{key}_*.txt")) if key else []
    return hits[0] if hits else None


def parse_deck(p):
    """Moxfield-style export: card lines, with a trailing Commander: section."""
    main, commander, in_cmd = [], [], False
    for line in p.read_text().splitlines():
        s = line.strip()
        if not s:
            continue
        if s.lower().startswith("commander"):
            in_cmd = True
            continue
        m = re.match(r"^(\d+)\s+(.+)$", s)
        if m:
            # Subagent finding: quantities were dropped, so "8 Mountain"
            # counted as one card and a 100-card deck read as 80 lines.
            (commander if in_cmd else main).append((m.group(2).strip(), int(m.group(1))))
    return main, commander


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cards").mkdir(exist_ok=True)

    deck_cards, commanders = parse_deck(DECK)
    qty = {}
    for n, q in deck_cards + commanders:
        qty[n] = qty.get(n, 0) + q
    commander_names = [n for n, _ in commanders]
    all_names = list(dict.fromkeys([n for n, _ in deck_cards + commanders]))
    true_size = sum(qty.values())

    # oracle text from the existing dossier (Forge card DB sourced)
    oracle = {}
    dc = json.load(open(DOSSIER / "deck-cards.json"))
    dc = dc if isinstance(dc, list) else dc.get("cards", [])
    for c in dc:
        if isinstance(c, dict) and c.get("name"):
            oracle[c["name"]] = c

    combos = json.load(open(DOSSIER / "combos.json")).get("combos", [])
    combo_by_card = {}
    for x in combos:
        pieces = [(c.get("name") if isinstance(c, dict) else c) for c in (x.get("cards") or [])]
        for p in pieces:
            combo_by_card.setdefault(p, []).append({"id": x.get("id"), "pieces": pieces})

    vocab = sorted({c for n in all_names
                    for c in (capabilities(script_for(n).read_text(errors="replace"))
                              if script_for(n) else set())})

    inventory, missing_script = {}, []
    for name in all_names:
        sp = script_for(name)
        if not sp:
            missing_script.append(name)
            script_text = None
            caps = []
        else:
            script_text = sp.read_text(errors="replace")
            caps = sorted(capabilities(script_text))
        o = oracle.get(name, {})
        pkg = {
            "card": name,
            "mana_cost": o.get("mana_cost"),
            "type_line": o.get("type_line"),
            "oracle_text": o.get("oracle_text"),
            "forge_script": script_text,
            "script_path": str(sp) if sp else None,
            "t0_capabilities": caps,
            "combos_containing_this_card": combo_by_card.get(name, []),
            "quantity": qty.get(name, 1),
            "is_commander": name in commander_names,
        }
        inventory[name] = pkg
        safe = re.sub(r"[^A-Za-z0-9]+", "_", name)[:60]
        (OUT / "cards" / f"{safe}.json").write_text(json.dumps(pkg, indent=1))

    deck_pkg = {
        "deck_id": "purphoros-god-of-the-forge2",
        "commander": commander_names,
        "decklist": all_names,
        "unique_names": len(all_names),
        "true_deck_size": true_size,
        "combos": combos,
        "t0_capability_vocabulary": vocab,
        "strategy_primer": PRIMER.read_text(),
        "primer_status": "UNVERIFIED HINT - human-written, not evidence of card behaviour",
        "cards_without_script": missing_script,
    }
    (OUT / "deck-package.json").write_text(json.dumps(deck_pkg, indent=1))

    print(f"deck: {true_size} cards, {len(all_names)} unique ({len(commander_names)} commander)")
    print(f"card packages written: {len(inventory)}")
    print(f"cards with NO forge script: {len(missing_script)} {missing_script}")
    print(f"T0 vocabulary discovered: {len(vocab)}")
    print(f"  {vocab}")
    print(f"combos: {len(combos)}")
    print(f"primer: {len(PRIMER.read_text())} chars")


if __name__ == "__main__":
    main()

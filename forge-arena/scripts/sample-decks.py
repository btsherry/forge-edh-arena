#!/usr/bin/env python3
"""sample-decks — LOCAL TOOL (do NOT bundle). Draw N random public Commander
decks of a given bracket from Archidekt, gated on what the arena can use, and
print them for approval BEFORE any credit-spending import.

Why Archidekt: its public API filters on the author-tagged bracket
(`edhBracket=`) and needs no key; Moxfield's search is bot-blocked (403).
The bracket tag is self-reported, so the follow-up import through DeckCheck
(`deckcheck-import.py`) is where the bracket gets verified.

Pool: the most-viewed `--pool` decks of that bracket (popularity-filtered so
"random" never means "abandoned draft"), then a seeded random draw subject to:
  - exactly 100 cards in the included categories, exactly one commander
    (or a partner pair), no custom cards, not theorycrafted;
  - the commander is not one of the bundled decks' commanders;
  - pairwise different colour identities among the picks;
  - every card has a Forge script (front face for DFCs); `--max-missing`
    unscripted cards tolerated (default 0 — redraw rather than hand-edit).
Rejected candidates are listed with the reason so the draw is auditable.

Usage:
  sample-decks.py [--bracket 3] [--n 3] [--pool 300] [--seed N]
                  [--max-missing 0] [--spares 2] [--json OUT]
Then, per pick (spends 1 DeckCheck credit each at --tier standard):
  deckcheck-import.py <archidekt-url> --tier standard --drop-sideboard --dck-out decks/<slug>.dck
  arena-add-deck.py decks/<slug>.dck --slug <slug> --deckcheck <deckId> --strict
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARENA = HERE.parent
REPO = ARENA.parent
CARDS = REPO / "forge-gui" / "res" / "cardsfolder"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
API = "https://archidekt.com/api"
COLORS = "WUBRG"


def get(url: str, retries: int = 3) -> dict:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 — retry then surface
            last = e
            time.sleep(1.5 * (i + 1))
    raise SystemExit(f"ERROR: GET {url} failed: {last}")


def forge_script_names() -> set[str]:
    """Every `Name:` in the card-script tree (front faces included; a DFC's
    back face is a second Name: line in the same file, which is fine here)."""
    cache = HERE.parent / "runner" / "logs" / "cache" / "forge-card-names.json"
    try:
        if cache.exists() and time.time() - cache.stat().st_mtime < 7 * 86400:
            return set(json.loads(cache.read_text()))
    except (OSError, ValueError):
        pass
    names: set[str] = set()
    for p in CARDS.rglob("*.txt"):
        try:
            with p.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("Name:"):
                        names.add(line[5:].strip())
        except OSError:
            continue
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(sorted(names)))
    except OSError:
        pass
    return names


def bundled_commanders() -> set[str]:
    out: set[str] = set()
    for d in (ARENA / "decks").glob("*.dck"):
        sec = None
        for line in d.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("["):
                sec = line
                continue
            if sec == "[Commander]" and line:
                out.add(re.sub(r"^\d+\s+", "", line).split(" // ")[0].split("|")[0].strip())
    return out


def pool(bracket: int, size: int) -> list[dict]:
    decks: list[dict] = []
    page = 1
    while len(decks) < size:
        d = get(f"{API}/decks/v3/?formats=3&edhBracket={bracket}&orderBy=-viewCount&pageSize=50&page={page}")
        rs = d.get("results") or []
        if not rs:
            break
        decks.extend(rs)
        if not d.get("next"):
            break
        page += 1
    return decks[:size]


def colour_identity(pips: dict) -> str:
    return "".join(c for c in COLORS if (pips or {}).get(c, 0) > 0) or "C"


def inspect(deck_id: int, scripts: set[str]) -> dict:
    d = get(f"{API}/decks/{deck_id}/")
    # Archidekt's rule: a card is OUT of the deck when any of its categories
    # is excluded (a "Creature" that is also "Maybeboard" is a maybe, not a
    # creature) — the first draw counted those and rejected good decks as
    # "104 cards".
    excluded_cats = {c["name"] for c in d.get("categories", []) if not c.get("includedInDeck", True)}
    premier = {c["name"] for c in d.get("categories", []) if c.get("isPremier")}
    cards, commanders, missing = [], [], []
    for x in d.get("cards", []):
        cats = set(x.get("categories") or [])
        if cats & excluded_cats or x.get("deletedAt"):
            continue  # sideboard / maybeboard / considering / removed
        name = x["card"]["oracleCard"]["name"]
        qty = int(x.get("quantity") or 0)
        front = name.split(" // ")[0].strip()
        if front not in scripts and name not in scripts:
            missing.append(name)
        cards.append((name, qty))
        if cats & premier or "Commander" in cats:
            commanders.append(name)
    total = sum(q for _, q in cards)
    return {
        "id": deck_id, "name": d.get("name"), "commanders": commanders, "total": total,
        "missing": missing, "custom": bool(d.get("customCards")),
        "theorycrafted": bool(d.get("theorycrafted")), "bracket": d.get("edhBracket"),
        "updated": (d.get("updatedAt") or "")[:10], "views": d.get("viewCount"),
        "url": f"https://archidekt.com/decks/{deck_id}",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bracket", type=int, default=3)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--pool", type=int, default=300)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--max-missing", type=int, default=0)
    ap.add_argument("--spares", type=int, default=2)
    ap.add_argument("--json", help="write the picks/spares/rejects report here")
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else int(time.time())
    rng = random.Random(seed)

    print(f"[sample] indexing Forge card scripts under {CARDS.relative_to(REPO)} …", flush=True)
    scripts = forge_script_names()
    excluded = bundled_commanders()
    print(f"[sample] {len(scripts)} script names; bundled commanders excluded: {len(excluded)}")
    print(f"[sample] pool: top {a.pool} most-viewed public Commander decks tagged bracket {a.bracket} (Archidekt)")
    cands = [c for c in pool(a.bracket, a.pool) if c.get("size") == 100]
    print(f"[sample] {len(cands)} candidates at exactly 100 cards; seed={seed}")
    rng.shuffle(cands)

    picks, spares, rejects = [], [], []
    seen_cmd: set[str] = set()
    seen_ci: set[str] = set()
    want = a.n + a.spares
    for c in cands:
        if len(picks) + len(spares) >= want:
            break
        info = inspect(c["id"], scripts)
        info["ci"] = colour_identity(c.get("colors"))
        why = None
        if info["custom"]:
            why = "custom cards"
        elif info["theorycrafted"]:
            why = "theorycrafted"
        elif info["total"] != 100:
            why = f"{info['total']} cards in included categories"
        elif not (1 <= len(info["commanders"]) <= 2):
            why = f"{len(info['commanders'])} commanders"
        elif any(x.split(" // ")[0] in excluded for x in info["commanders"]):
            why = "commander already bundled"
        elif len(info["missing"]) > a.max_missing:
            why = f"{len(info['missing'])} unscripted in Forge: {', '.join(info['missing'][:4])}"
        elif set(info["commanders"]) & seen_cmd:
            why = "duplicate commander"
        elif info["ci"] in seen_ci and len(picks) < a.n:
            why = f"colour identity {info['ci']} already drawn"
        if why:
            rejects.append({**info, "why": why})
            print(f"  reject  {info['name'][:38]:<38} {'/'.join(info['commanders'])[:34]:<34} {info['ci']:<5} {why}")
            continue
        seen_cmd.update(info["commanders"])
        seen_ci.add(info["ci"])
        (picks if len(picks) < a.n else spares).append(info)
        tag = "PICK " if len(picks) <= a.n and info in picks else "spare"
        print(f"  {tag}   {info['name'][:38]:<38} {'/'.join(info['commanders'])[:34]:<34} {info['ci']:<5} "
              f"views={info['views']} upd={info['updated']}")

    print("\n== picks ==")
    for i, p in enumerate(picks, 1):
        print(f"{i}. {p['name']}  —  {' / '.join(p['commanders'])}  [{p['ci']}]  bracket-tag {p['bracket']}  "
              f"views {p['views']}  updated {p['updated']}\n   {p['url']}")
    if spares:
        print("== spares (if a pick fails DeckCheck's bracket or the import) ==")
        for s in spares:
            print(f"-  {s['name']}  —  {' / '.join(s['commanders'])}  [{s['ci']}]  {s['url']}")
    if a.json:
        Path(a.json).write_text(json.dumps({"seed": seed, "bracket": a.bracket, "picks": picks,
                                            "spares": spares, "rejects": rejects}, indent=1))
        print(f"[sample] report -> {a.json}")
    if len(picks) < a.n:
        sys.exit(f"ERROR: only {len(picks)} of {a.n} picks survived the gates — widen --pool or relax --max-missing")


if __name__ == "__main__":
    main()

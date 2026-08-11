#!/usr/bin/env python3
"""arena-add-deck — bare .dck -> playable arena seat (dossier + combos + lint +
primer). See docs/SPEC-arena-add-deck.md. Stdlib only (urllib/json) so the
distributed package needs no pip installs.

Usage:
  arena-add-deck.py path/to/deck.dck [--slug NAME] [--strict]
                    [--primer a|b|skip] [--no-cache] [--verify]

Steps: (1) parse .dck  (2) Scryfall oracle text  (3) CommanderSpellbook combos
(4) implementability lint vs Forge's card DB  (5) primer (DeckCheck paste or
fable/max)  (6) write + summary.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # forge-arena/
REPO = os.path.dirname(ROOT)                                                 # repo root
DECKS = os.path.join(ROOT, "decks")
PRIMERS = os.path.join(ROOT, "docs", "primers")
CARDSFOLDER = os.path.join(REPO, "forge-gui", "res", "cardsfolder")
BASICS = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
          "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
          "Snow-Covered Mountain", "Snow-Covered Forest"}
UA = {"User-Agent": "forge-edh-arena/arena-add-deck (non-commercial fan project)",
      "Accept": "application/json", "Content-Type": "application/json"}


def log(msg): print(msg, flush=True)
def warn(msg): print(f"  ! {msg}", file=sys.stderr, flush=True)


def slugify_deck(name: str) -> str:
    """Deck directory slug: kebab-case (matches the bundled decks)."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "deck"


def slugify_card(name: str) -> str:
    """Forge cardsfolder filename slug. Matches Forge's convention: apostrophes
    dropped (Gaea's -> gaeas), hyphens/slashes are word boundaries (Keen-Eyed ->
    keen_eyed), and DFC faces join with '_' (A // B -> a_b), so pass the FULL
    Scryfall name (both faces) for DFCs, not just the front."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()  # Andúril -> Anduril
    s = s.lower().replace("'", "")                            # drop apostrophes
    s = re.sub(r"[-/]+", " ", s)                               # hyphen/slash -> boundary
    s = re.sub(r"[^a-z0-9 ]+", "", s)                          # drop remaining punctuation
    return re.sub(r"\s+", "_", s.strip())


# ---- step 1: parse .dck ------------------------------------------------------

HEADERS = {"metadata": "meta", "commander": "commander", "commanders": "commander",
           "main": "main", "maindeck": "main", "deck": "main",
           "sideboard": "sideboard", "sb": "sideboard"}


def parse_dck(path: str):
    """Robust to both the Forge sectioned format ([metadata]/[Commander]/[Main])
    and the flatter Archidekt/Moxfield export (a bare card list with a
    'Commander:' marker and no metadata). Unheadered lines default to main."""
    name, commanders, main = None, [], []
    section = "main"
    for raw in open(path, encoding="utf-8", errors="replace"):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        key = line.strip("[]").rstrip(":").strip().lower()   # [Commander] / Commander: / commander
        if key in HEADERS:
            section = HEADERS[key]
            continue
        if section == "meta":
            if line.lower().startswith("name="):
                name = line.split("=", 1)[1].strip()
            continue
        if section == "sideboard":
            continue
        m = re.match(r"(\d+)\s*[xX]?\s+(.+)", line)            # "3 Card" / "3x Card"
        if m:
            qty, card = int(m.group(1)), m.group(2)
        else:
            qty, card = 1, line                                # bare card name -> qty 1
        card = card.split("|")[0].strip()                      # drop |SET|num tags
        if card:
            (commanders if section == "commander" else main).append((card, qty))
    if not commanders:
        raise SystemExit("ERROR: no commander found — is this a Commander .dck? "
                         "(need a [Commander] section or a 'Commander:' marker)")
    if not name:
        name = commanders[0][0]                                # name the deck after its commander
    if name.startswith("Name="):
        name = name[5:].strip()
    total = sum(q for _, q in commanders + main)
    if not (95 <= total <= 105):
        warn(f"deck has {total} cards (expected ~100)")
    return {"name": name, "slug": slugify_deck(name),
            "commanders": commanders, "main": main}


# ---- step 2: Scryfall oracle text -------------------------------------------

def _post(url, payload, cache_path=None, use_cache=True):
    if cache_path and use_cache and os.path.exists(cache_path):
        return json.load(open(cache_path))
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    if cache_path:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        json.dump(data, open(cache_path, "w"))
    return data


def fetch_scryfall(names, cache_dir, use_cache):
    """Return {name_lower: card_json} and a list of not-found names."""
    uniq = sorted({n for n in names})
    found, not_found = {}, []
    for i in range(0, len(uniq), 75):
        batch = uniq[i:i + 75]
        payload = {"identifiers": [{"name": n} for n in batch]}
        cache = os.path.join(cache_dir, f"scryfall-{i//75}.json")
        try:
            data = _post("https://api.scryfall.com/cards/collection", payload,
                         cache, use_cache)
        except urllib.error.URLError as e:
            raise SystemExit(f"ERROR: Scryfall request failed: {e}")
        for c in data.get("data", []):
            found[c["name"].lower()] = c
            for face in c.get("card_faces", []) or []:      # index front-face too
                found.setdefault(face.get("name", "").lower(), c)
        for nf in data.get("not_found", []):
            not_found.append(nf.get("name", "?"))
        time.sleep(0.1)                                     # Scryfall rate limit
    return found, not_found


def _oracle(card):
    if card.get("oracle_text") is not None and "card_faces" not in card:
        return card["oracle_text"]
    faces = card.get("card_faces") or []
    if faces:
        return "\n//\n".join(f"{f.get('name','')}: {f.get('oracle_text','')}"
                             for f in faces)
    return card.get("oracle_text", "")


def build_deck_cards(parsed, scry, slug):
    cards, unresolved = [], []
    for zone, lst in (("commander", parsed["commanders"]), ("main", parsed["main"])):
        for name, qty in lst:
            c = scry.get(name.lower())
            if not c:
                unresolved.append(name)
                continue
            cards.append({
                "name": c["name"], "qty": qty, "zone": zone,
                "mana_cost": c.get("mana_cost")
                or (c.get("card_faces", [{}])[0].get("mana_cost", "")),
                "type_line": c.get("type_line", ""),
                "color_identity": "".join(c.get("color_identity", [])) or "C",
                "oracle_text": _oracle(c),
            })
    return {"schema": "arena.deck-cards/1", "deck_id": slug,
            "cards": cards, "unresolved": unresolved}


# ---- step 3: CommanderSpellbook combos --------------------------------------

def fetch_combos(parsed, slug, cache_dir, use_cache):
    """Included combos (all pieces present in the deck) via find-my-combos."""
    payload = {
        "commanders": [{"card": n, "quantity": q} for n, q in parsed["commanders"]],
        "main": [{"card": n, "quantity": q} for n, q in parsed["main"]],
    }
    cache = os.path.join(cache_dir, "commanderspellbook.json")
    try:
        data = _post("https://backend.commanderspellbook.com/find-my-combos",
                     payload, cache, use_cache)
    except urllib.error.URLError as e:
        warn(f"CommanderSpellbook unavailable ({e}); combos.json will be empty")
        data = {}
    results = (data.get("results") or {})
    included = results.get("included", []) if isinstance(results, dict) else []
    combos = []
    for v in included:
        feats = [f.get("feature", {}).get("name") if isinstance(f, dict) else f
                 for f in (v.get("produces") or [])]
        combos.append({
            "id": v.get("id"),
            "url": f"https://commanderspellbook.com/combo/{v.get('id')}/",
            "cards": [{"name": (u.get("card", {}) or {}).get("name") or u.get("card")}
                      for u in (v.get("uses") or v.get("cards") or [])],
            "mana_needed": v.get("manaNeeded") or v.get("mana_needed"),
            "prerequisites": v.get("easyPrerequisites") or v.get("prerequisites"),
            "steps": v.get("description") or v.get("steps"),
            "produces": [f for f in feats if f],
            "bracket_tag": v.get("bracketTag") or v.get("bracket_tag"),
            "popularity": v.get("popularity"),
        })
    return {"schema": "arena.combos/1", "deck_id": slug,
            "spellbook_snapshot": data.get("count") or len(combos),
            "combos": combos}


# ---- step 4: implementability lint ------------------------------------------

def lint(all_names):
    if not os.path.isdir(CARDSFOLDER):
        warn(f"Forge cardsfolder not found at {CARDSFOLDER}; skipping lint")
        return {"unsupported": [], "checked": 0}
    unsupported = []
    for name in sorted(set(all_names)):
        if name in BASICS:
            continue
        slug = slugify_card(name)
        path = os.path.join(CARDSFOLDER, slug[:1], slug + ".txt")
        if not os.path.exists(path):
            unsupported.append(name)
    return {"unsupported": unsupported, "checked": len(set(all_names))}


# ---- step 5: primer ----------------------------------------------------------

PRIMER_PROMPT = """You are writing a STRATEGY PRIMER for an AI that will pilot \
this Commander (EDH) deck in real games. The primer is read verbatim by the \
pilot, so make it a dense, actionable field guide — NOT marketing copy.

Do live research first: look up this commander on EDHREC and the wider web to \
learn its committed subthemes and how strong pilots actually play it. Then, \
using the full card list (oracle text below) and the deck's real combos (below), \
write a primer that covers:
- The commander's role and the deck's chosen archetype(s)/subthemes.
- Every combo: pieces, the exact execution line, and its mana/timing.
- Synergy PACKAGES beyond named combos: sacrifice loops, tap/untap engines, \
overlapping keyword payoffs, counters-matter, storm, landfall, etc. — the webs \
that dictate sequencing.
- Mulligan heuristics, threat assessment across a pod, and turn sequencing.
- Primary win line(s) and backups, plus what to protect and when.
Be specific and concrete; prefer card names and real lines over generalities.

## DECK COMBOS (CommanderSpellbook)
{combos}

## FULL CARD LIST (oracle text)
{cards}

Write the primer now as Markdown."""


def make_primer(slug, deck_cards, combos, primer_path, mode):
    log("\n" + "=" * 70)
    log(f"STRATEGY PRIMER for {slug} — the pilot plays far better with a good one.")
    log("DeckCheck.co gives the best commander-specific analysis we've seen "
        "(subthemes,\nsac loops, keyword overlaps, synergy lines). Options:")
    log(f"  (A) Paste a DeckCheck review (recommended). Open https://deckcheck.co,")
    log(f"      run this deck, copy the review, save it to:\n        {primer_path}")
    log(f"  (B) Generate locally with the top model (fable, max effort) from your")
    log(f"      dossier + combos + live EDHREC/web research.")
    log(f"  (skip) Play off the dossier + combos only.")
    if mode is None:
        mode = (input("Choose [A/b/skip]: ").strip().lower() or "a")
    if mode in ("a", "A"):
        input(f"  Save the DeckCheck review to {primer_path}, then press ENTER "
              "(or Ctrl-C to skip)... ")
        return os.path.exists(primer_path)
    if mode == "skip":
        return False
    # mode b — fable / max effort, tools enabled so it can research EDHREC.
    log("  Generating with fable/max (this researches EDHREC and can take a "
        "few minutes)...")
    prompt = PRIMER_PROMPT.format(
        combos=json.dumps(combos["combos"], indent=1),
        cards=json.dumps([{k: c[k] for k in ("name", "mana_cost", "type_line",
                                             "oracle_text")}
                          for c in deck_cards["cards"]], indent=1))
    try:
        out = subprocess.run(
            ["claude", "-p", "-", "--model", "fable", "--effort", "max"],
            input=prompt, capture_output=True, text=True, timeout=1200)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        warn(f"fable primer generation failed ({e}); skipping primer")
        return False
    if out.returncode != 0 or not out.stdout.strip():
        warn(f"fable returned nothing (rc={out.returncode}); skipping primer")
        return False
    open(primer_path, "w").write(out.stdout)
    return True


# ---- orchestration -----------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dck")
    ap.add_argument("--slug")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--primer", choices=["a", "b", "skip"])
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    use_cache = not args.no_cache

    parsed = parse_dck(args.dck)
    if args.slug:
        parsed["slug"] = slugify_deck(args.slug)
    slug = parsed["slug"]
    deck_dir = os.path.join(DECKS, slug)
    dossier = os.path.join(deck_dir, "dossier")
    cache_dir = os.path.join(dossier, ".cache")
    os.makedirs(dossier, exist_ok=True)
    os.makedirs(PRIMERS, exist_ok=True)
    log(f"[1/6] parsed '{parsed['name']}' -> slug={slug} "
        f"({len(parsed['commanders'])} commander, {len(parsed['main'])} main entries)")

    all_names = [n for n, _ in parsed["commanders"] + parsed["main"]]
    scry, nf = fetch_scryfall(all_names, cache_dir, use_cache)
    log(f"[2/6] Scryfall: {len(scry)} cards resolved"
        + (f", {len(nf)} NOT FOUND: {nf}" if nf else ""))
    deck_cards = build_deck_cards(parsed, scry, slug)

    combos = fetch_combos(parsed, slug, cache_dir, use_cache)
    log(f"[3/6] CommanderSpellbook: {len(combos['combos'])} included combos")

    # Lint on RESOLVED Scryfall names (full DFC 'A // B' names) so the filename
    # slug matches Forge's front_back convention; raw .dck names are front-only.
    lint_res = lint([c["name"] for c in deck_cards["cards"]])
    if lint_res["unsupported"]:
        warn(f"[4/6] {len(lint_res['unsupported'])} card(s) not in Forge's DB "
             f"(may misbehave in-engine): {lint_res['unsupported']}")
        if args.strict:
            raise SystemExit("ERROR: --strict and unsupported cards present.")
    else:
        log(f"[4/6] lint: all {lint_res['checked']} cards implemented in Forge")

    # write dossier + combos + copy the .dck
    json.dump(deck_cards, open(os.path.join(dossier, "deck-cards.json"), "w"), indent=1)
    json.dump(combos, open(os.path.join(dossier, "combos.json"), "w"), indent=1)
    dst_dck = os.path.join(DECKS, slug + ".dck")
    if os.path.abspath(args.dck) != os.path.abspath(dst_dck):
        open(dst_dck, "w").write(open(args.dck, encoding="utf-8",
                                      errors="replace").read())

    primer_path = os.path.join(PRIMERS, f"{slug}-deckcheck.md")
    have_primer = make_primer(slug, deck_cards, combos, primer_path, args.primer)
    log(f"[5/6] primer: {'written ' + primer_path if have_primer else 'skipped'}")

    log(f"[6/6] done. Deck '{slug}' is ready:")
    log(f"      {dst_dck}")
    log(f"      {os.path.join(dossier, 'deck-cards.json')}  "
        f"({len(deck_cards['cards'])} cards"
        + (f", {len(deck_cards['unresolved'])} unresolved" if deck_cards['unresolved'] else "")
        + ")")
    log(f"      {os.path.join(dossier, 'combos.json')}  ({len(combos['combos'])} combos)")
    log(f"  Play it: swap '{slug}' into run_table.sh / arena-play.sh, or "
        f"ARENA seat --deck {slug}")


if __name__ == "__main__":
    main()

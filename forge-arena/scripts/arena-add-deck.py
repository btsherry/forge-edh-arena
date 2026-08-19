#!/usr/bin/env python3
"""arena-add-deck — bare .dck -> playable arena seat (dossier + combos + lint +
primer). See docs/SPEC-arena-add-deck.md. Stdlib only (urllib/json) so the
distributed package needs no pip installs.

Usage:
  arena-add-deck.py path/to/deck.dck [--slug NAME] [--strict]
                    [--primer a|b|skip] [--deckcheck URL_OR_ID] [--no-cache]

Steps: (1) parse .dck  (2) Scryfall oracle text  (3) CommanderSpellbook combos
(4) implementability lint vs Forge's card DB  (5) primer (DeckCheck auto-fetch
or fable/max)  (6) write + summary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from html.parser import HTMLParser

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


def rel(p):
    """Display paths package-root-relative — echoes must never leak the local
    absolute prefix (hostname/username) into logs, screenshots, or shared runs."""
    return os.path.relpath(p, REPO)


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


def _normname(name):
    """Punctuation/case-insensitive lookup key ("Spider-Punk" == "spider punk")."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _front_face(name):
    """DFC front face for Scryfall lookup ("A // B" -> "A"): Scryfall's collection
    {"name"} can't match the combined name but resolves the whole card from the
    front (canonical name stays "A // B", both faces populate card_faces)."""
    return name.split(" // ")[0].strip() if " // " in name else name


def fetch_scryfall(names, cache_dir, use_cache):
    """Return {name_lower: card_json} and a list of not-found names."""
    uniq = sorted({n for n in names})
    found, not_found = {}, []
    for i in range(0, len(uniq), 75):
        batch = uniq[i:i + 75]
        # Scryfall's collection {"name"} lookup misses a full DFC "Front // Back"
        # name; querying the FRONT face returns the whole card (both faces in
        # card_faces, canonical name unchanged), which _oracle/build_deck_cards
        # already index by full name + face names.
        payload = {"identifiers": [{"name": _front_face(n)} for n in batch]}
        # Content-addressed cache: keyed by the batch's actual names, so editing
        # the deck invalidates stale batches. (An index-keyed cache — scryfall-0,
        # scryfall-1 — silently served the pre-edit cards, dropping swapped-in
        # cards into 'unresolved' on any re-run.) 'v2' busts pre-DFC-fix caches.
        key = hashlib.sha1(("v2\x1f" + "\x1f".join(batch)).encode("utf-8")).hexdigest()[:16]
        cache = os.path.join(cache_dir, f"scryfall-{key}.json")
        try:
            data = _post("https://api.scryfall.com/cards/collection", payload,
                         cache, use_cache)
        except urllib.error.URLError as e:
            raise SystemExit(f"ERROR: Scryfall request failed: {e}")
        for c in data.get("data", []):
            found[c["name"].lower()] = c
            # Punctuation-insensitive index too: Scryfall's identifier lookup
            # accepts "Spider Punk" but returns canonical "Spider-Punk" — an
            # exact-key round trip loses the card (same class as flavor names).
            found.setdefault(_normname(c["name"]), c)
            for face in c.get("card_faces", []) or []:      # index front-face too
                found.setdefault(face.get("name", "").lower(), c)
                found.setdefault(_normname(face.get("name", "")), c)
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
            c = scry.get(name.lower()) or scry.get(_normname(name))
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
    # Content-addressed by the decklist, so an edited deck re-fetches combos
    # instead of serving the pre-edit result (same bug the Scryfall cache had).
    key = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    cache = os.path.join(cache_dir, f"commanderspellbook-{key}.json")
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

# --- 5A: DeckCheck.co structured analysis (keyless public read endpoint) ------
# Anthony (DeckCheck owner) opened /builder/api/public/deck/<id> keyless (~10/s)
# with the AI data (analysis prose + bracket + CRISPI), so mode A fetches and
# renders it as the primer — no copy/paste. See docs/research/DECKCHECK-ACCESS.md.
DECKCHECK_API = "https://deckcheck.co/builder/api/public/deck/{}"


def parse_deckcheck_id(s):
    """Pull the deck id from a DeckCheck URL (builder/deck/app/api forms) or a
    bare id. Ids are >=6 alphanumerics, so 'api'/'app' path words don't match."""
    s = (s or "").strip()
    for pat in (r"/public/deck/([A-Za-z0-9_-]{6,})",
                r"/app/(?:builder|deck)/([A-Za-z0-9_-]{6,})",
                r"/(?:builder|deck)/([A-Za-z0-9_-]{6,})"):
        m = re.search(pat, s)
        if m:
            return m.group(1)
    return s if re.fullmatch(r"[A-Za-z0-9_-]{6,}", s) else None


def _get(url, cache_path=None, use_cache=True):
    if cache_path and use_cache and os.path.exists(cache_path):
        return json.load(open(cache_path))
    req = urllib.request.Request(
        url, method="GET",
        headers={"User-Agent": UA["User-Agent"], "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    if cache_path:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        json.dump(data, open(cache_path, "w"))
    return data


class _HTMLToMarkdown(HTMLParser):
    """Minimal HTML -> Markdown for DeckCheck's analysis prose (h2/p/ul/li/span/
    strong/em). Unknown tags are dropped but their text is kept, so the card-name
    <span> content survives."""
    def __init__(self):
        super().__init__()
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self.out.append("\n\n# ")
        elif tag == "h2":
            self.out.append("\n\n## ")
        elif tag in ("h3", "h4"):
            self.out.append("\n\n### ")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in ("p", "div", "ul", "ol"):
            self.out.append("\n\n")
        elif tag == "br":
            self.out.append("\n")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "p", "li", "div"):
            self.out.append("\n")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")

    def handle_data(self, data):
        self.out.append(data)

    def text(self):
        t = "".join(self.out)
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r" *\n *", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()


def _html_to_md(h):
    p = _HTMLToMarkdown()
    p.feed(h)
    return p.text()


def deckcheck_primer_markdown(d):
    """Render the DeckCheck deck JSON as a primer: a header (commander, bracket,
    CRISPI) + the full analysis prose (HTML converted to Markdown)."""
    md = d.get("metadata") or {}
    ar = d.get("attribute_ratings") or {}
    lines = [f"# {d.get('name') or 'Deck'} — DeckCheck analysis", ""]
    if d.get("commander"):
        c2 = d.get("commander2")
        lines.append(f"- **Commander:** {d['commander']}" + (f" // {c2}" if c2 else ""))
    if md.get("bracketLevel") is not None:
        lines.append(f"- **Bracket:** {md['bracketLevel']}")
    if ar:
        crispi = " · ".join(f"{k} {v}" for k, v in ar.items())
        perf = md.get("performanceIndex")
        lines.append(f"- **CRISPI:** {crispi}"
                     + (f" · performance {perf}" if perf is not None else ""))
    if len(lines) > 2:
        lines.append("")
    body = d.get("full_analysis") or d.get("analysis_preview") or ""
    if "<" in body and ">" in body:
        body = _html_to_md(body)
    lines.append(body.strip())
    lines.append("")
    lines.append(f"*Source: DeckCheck.co — deck `{d.get('id') or d.get('deckview_id')}`.*")
    return "\n".join(lines) + "\n"


def fetch_deckcheck_primer(url_or_id, cache_dir, use_cache):
    """Fetch DeckCheck's structured analysis and render a primer.
    Returns (markdown, deck_name) on success, or (None, reason) on failure."""
    deck_id = parse_deckcheck_id(url_or_id)
    if not deck_id:
        return None, "couldn't read a DeckCheck deck id from that input"
    cache = os.path.join(cache_dir, f"deckcheck-{deck_id}.json")
    try:
        d = _get(DECKCHECK_API.format(deck_id), cache, use_cache)
    except urllib.error.HTTPError as e:
        return None, (f"DeckCheck returned HTTP {e.code} for id {deck_id} "
                      "(is the deck public or unlisted?)")
    except urllib.error.URLError as e:
        return None, f"DeckCheck request failed: {e}"
    except ValueError:
        return None, "DeckCheck returned a non-JSON response"
    if not isinstance(d, dict):
        return None, "unexpected DeckCheck response shape"
    if not (d.get("full_analysis") or d.get("analysis_preview")):
        return None, ("that deck has no analysis yet — run 'Analyze' on DeckCheck "
                      "first, then re-run this")
    return deckcheck_primer_markdown(d), d.get("name", deck_id)


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
State execution lines rules-accurately (timing/priority, and announce finite \
loop counts rather than claiming "infinite" where a loop is bounded). Use the \
MTG RULES REFERENCE below for YOUR reasoning so every line is rules-exact; do \
NOT restate general rules in the primer (the pilot already holds these digests) \
— cite a rule only where a line hinges on it.

## MTG RULES REFERENCE (for your reasoning only — do NOT copy into the primer)
{rules}

## DECK COMBOS (CommanderSpellbook)
{combos}

## FULL CARD LIST (oracle text)
{cards}

Write the primer now as Markdown. Output ONLY the primer itself — no meta
commentary, session/operator notes, apologies, or remarks about tooling; the
file is read verbatim by the pilot and anything else is noise in its context."""


def make_primer(slug, deck_cards, combos, primer_path, mode, deckcheck,
                cache_dir, use_cache, primer_timeout=2700):
    log("\n" + "=" * 70)
    log(f"STRATEGY PRIMER for {slug} — the pilot plays far better with a good one.")
    log("DeckCheck.co gives the best commander-specific analysis we've seen "
        "(subthemes,\nsac loops, keyword overlaps, synergy lines). Options:")
    log("  (A) DeckCheck (recommended). Give your DeckCheck deck URL or id and this")
    log("      fetches the analysis (prose + bracket + CRISPI) automatically — no")
    log("      copy/paste. Create + analyze the deck once at https://deckcheck.co first.")
    log("  (B) Generate locally with the top model (fable, max effort) from your")
    log("      dossier + combos + live EDHREC/web research.")
    log("  (skip) Play off the dossier + combos only.")
    interactive = mode is None
    if interactive:
        mode = input("Choose [A/b/skip]: ").strip().lower() or "a"
    if mode == "skip":
        return False
    if mode == "a":
        url = deckcheck
        if not url and interactive:
            url = input("  DeckCheck deck URL or id (ENTER to skip): ").strip()
        if url:
            log("  Fetching analysis from DeckCheck (keyless public endpoint)...")
            primer, res = fetch_deckcheck_primer(url, cache_dir, use_cache)
            if primer:
                open(primer_path, "w").write(primer)
                log(f"  DeckCheck analysis for '{res}' saved.")
                return True
            warn(f"DeckCheck fetch failed: {res}")
        else:
            warn("no DeckCheck URL/id given")
        if interactive and input(
                "  Fall back to local fable generation? [y/N]: ").strip().lower() == "y":
            mode = "b"
        else:
            return False
    # mode b — fable / max effort, tools enabled so it can research EDHREC.
    log("  Generating with fable/max (this researches EDHREC and can take a "
        "few minutes)...")
    # Rules reference for the generator's reasoning (loop legality, timing,
    # priority) — the same corpus the seat brains load at runtime. Kept out of
    # the primer output; it only makes the stated lines rules-exact.
    rules_parts = []
    for rf in ("mtg-rules-digest-conversion.md", "mtg-rules-summary.md"):
        rp = os.path.join(ROOT, "docs", "research", rf)
        if os.path.exists(rp):
            rules_parts.append(f"### {rf}\n"
                               + open(rp, encoding="utf-8", errors="replace").read())
        else:
            warn(f"rules reference {rf} not found; primer reasoning will lack it")
    rules_text = "\n\n".join(rules_parts) or "(no rules reference available)"
    prompt = PRIMER_PROMPT.format(
        rules=rules_text,
        combos=json.dumps(combos["combos"], indent=1),
        cards=json.dumps([{k: c[k] for k in ("name", "mana_cost", "type_line",
                                             "oracle_text")}
                          for c in deck_cards["cards"]], indent=1))
    try:
        out = subprocess.run(
            # Headless -p auto-denies gated tools, so grant the two read-only
            # research tools explicitly or the EDHREC/web step silently fails
            # and the model burns its budget hunting for an allowed avenue.
            ["claude", "-p", "-", "--model", "fable", "--effort", "max",
             "--allowedTools", "WebSearch,WebFetch"],
            input=prompt, capture_output=True, text=True, timeout=primer_timeout)
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
    ap.add_argument("--deckcheck", metavar="URL_OR_ID",
                    help="DeckCheck deck URL or id; primer mode A fetches its "
                         "analysis automatically (no copy/paste)")
    ap.add_argument("--primer-timeout", type=int, default=2700,
                    help="seconds for fable/max primer generation, mode B "
                         "(default 2700; the rules-context prompt is slow)")
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
    # Passing --deckcheck implies mode A even when --primer wasn't given.
    primer_mode = args.primer or ("a" if args.deckcheck else None)
    have_primer = make_primer(slug, deck_cards, combos, primer_path, primer_mode,
                              args.deckcheck, cache_dir, use_cache,
                              args.primer_timeout)
    log(f"[5/6] primer: {'written ' + rel(primer_path) if have_primer else 'skipped'}")

    log(f"[6/6] done. Deck '{slug}' is ready:")
    log(f"      {rel(dst_dck)}")
    log(f"      {rel(os.path.join(dossier, 'deck-cards.json'))}  "
        f"({len(deck_cards['cards'])} cards"
        + (f", {len(deck_cards['unresolved'])} unresolved" if deck_cards['unresolved'] else "")
        + ")")
    log(f"      {rel(os.path.join(dossier, 'combos.json'))}  ({len(combos['combos'])} combos)")
    log(f"  Play it: arena-play.sh --human {slug}.dck — or put '{slug}' in "
        f"ARENA_SEAT_DECKS for a brain to pilot it")


if __name__ == "__main__":
    main()

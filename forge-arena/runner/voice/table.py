"""The table, for the voice runner (runner/voice_runner.py): which voice library
sits at which seat (voices/<lib>/manifest.json, voices/assign.json, the launcher's
roster or the game log), how a seat is addressed (voices/address.json: commander
slug, else colour identity), each deck's game changers, cards and combos (the
dossier and voices/combos.json), the whole-sentence number lines, and the
table/cards sub-library constants. Split out of voice_runner.py on 2026-09-14
(voicework2 hardening plan, Phase 0a) with no behaviour change; voice_runner
re-exports every public name here."""
from __future__ import annotations

import json
from pathlib import Path

from voice.renderer import ARENA, VOICES_DIR

# The tuning (2026-09-16, hardening plan §2 — "36 environment knobs on the voice path" -> five
# operator knobs): every number the talk runs on that is not an operator's choice lives in
# voices/tuning.json, loaded once here. The path is bound at import so a test that points
# VOICES_DIR at a fake tree still reads the shipped numbers; VoiceRunner(tuning={...}) overrides.
TUNING_FILE = VOICES_DIR / "tuning.json"
TUNING_SCHEMA = "arena.voice-tuning/1"


def load_tuning(path: Path | None = None) -> dict:
    """voices/tuning.json as a dict (schema and note dropped). A missing or unreadable file is a
    packaging fault, not a quiet default: the runner cannot pace itself without the numbers."""
    p = path or TUNING_FILE
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        raise RuntimeError(f"voice tuning unreadable: {p} ({e})") from e
    if not isinstance(data, dict) or data.get("schema") != TUNING_SCHEMA:
        raise RuntimeError(f"voice tuning {p}: expected schema {TUNING_SCHEMA!r}, got {data.get('schema') if isinstance(data, dict) else type(data).__name__!r}")
    return {k: v for k, v in data.items() if k not in ("schema", "note")}


# The table sub-library (round 31, runner/voice/table_lines.py): procedural self-narration,
# whole-sentence numbers and named addressing live in voices/<lib>/table/. Per-line odds
# below are multiplied by tuning.json's table_p; the governor treats them as anchored.
TABLE_LIB = "table"
TABLE_P = {"grudge": 0.6, "again-countered": 0.7, "not-again-sweep": 0.7, "heads-up": 0.8, "early-game": 0.3, "you-promised": 0.7,
           "land-go": 0.6, "pass": 0.5, "mana-up": 0.5, "tapped-out": 0.4, "untap-draw": 0.5, "come-on-land": 0.4, "thinking": 0.3,
           "cast": 0.45, "cast-big": 0.6, "in-response": 0.7, "poke": 0.5, "attack-you": 0.45, "no-blocks": 0.4, "take-it": 0.35,
           "sure": 0.25, "hold-on": 0.4, "life": 0.5, "address": 0.5}
LIFE_STEPS = (45, 50, 60, 80, 100)
# The cards sub-library (round 31, runner/voice/card_lines.py): game changers, commanders
# and combos by name. The generic hooks stay; when the ctx names the card ("card" +
# "card_kind" gc | cmd | combo) and the seat's cards library carries the wording, the
# specific line replaces the generic one — for the opener and for the replies it invites.
CARD_LIB = "cards"
CARD_SWAP = {"game-changer": ("gc", "gc-{card}-cast"), "gc-react": ("gc", "gc-{card}-react"), "gc-gone": ("gc", "gc-{card}-gone"),
             "commander-cast": ("cmd", "cmd-{card}-cast"), "lost-commander": ("cmd", "cmd-{card}-dead"),
             "engine-online": ("combo", "combo-{card}-online")}
CARD_REACTIONS = {"gc": ({"gc-react", "oh-no", "kill-that", "wow", "read-that", "nice-play", "thats-mean"}, "gc-{card}-react"),
                  "cmd": ({"oh-no", "brace", "read-that", "wow", "nice-play"}, "cmd-{card}-react"),
                  "combo": ({"scoff", "brace", "oh-no", "disagree", "wow", "read-that"}, "combo-{card}-react")}


def load_libraries(voices_dir: Path | None = None) -> dict[str, dict]:
    """{library: {"library", "voice", "temperament", "role", "seat"}} from every voices/<name>/manifest.json.
    `role` is "seat" (a table voice) or "advisor" (Joshua's library: it never sits at a table with a human);
    `seat` is the manifest's old default seat, kept only to order the fallback when assign.json names none."""
    out: dict[str, dict] = {}
    d = voices_dir or VOICES_DIR
    try:
        mans = sorted(d.glob("*/manifest.json"))
    except OSError:
        return out
    for mp in mans:
        try:
            m = json.loads(mp.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict):
            continue                                            # a manifest that is not an object is no library (Gemini review, 2026-09-17)
        try:
            seat = int(m.get("seat", 99))
        except (TypeError, ValueError):
            seat = 99
        out[mp.parent.name] = {"library": mp.parent.name, "voice": str(m.get("voice_name") or mp.parent.name).split(" - ")[0],
                               "temperament": str(m.get("temperament") or ""), "role": str(m.get("role") or "seat"), "seat": seat}
    return out


def load_assignments(voices_dir: Path | None = None) -> dict[str, str]:
    """voices/assign.json by_deck: deck slug -> library (Ben's associations); anything but an object is no associations."""
    by = _assign_file(voices_dir).get("by_deck")
    return {str(k): str(v) for k, v in by.items()} if isinstance(by, dict) else {}


def load_fallback(voices_dir: Path | None = None) -> list[str]:
    """voices/assign.json fallback: the order unassociated decks take the free libraries in."""
    fb = _assign_file(voices_dir).get("fallback")
    return [str(x) for x in fb] if isinstance(fb, list) else []


def _assign_file(voices_dir: Path | None) -> dict:
    try:
        d = json.loads(((voices_dir or VOICES_DIR) / "assign.json").read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def assign_voices(libraries: dict[str, dict], seat_decks: dict[int, str] | None, by_deck: dict[str, str] | None,
                  human_seat: int | None = 0, fallback: list[str] | None = None) -> dict[int, dict]:
    """Who speaks as whom — ONE rule, three passes (2026-09-17, replacing the default-seat / late-rebind tangle):

    1. The human's seat is never voiced, and a library with role "advisor" (Joshua) never sits at a table with a
       human — his voice is the advisor's there.
    2. A seat whose deck has an association takes that library; when two seats want the same one, the lower seat
       keeps it and the other falls through.
    3. Every remaining seat, in seat order, takes the next free library in the fallback order (assign.json
       `fallback`, else the manifests' old default seats, else the name). Each library is used once; a table with
       more seats than libraries leaves the last seats voiceless — never two seats in one voice.

    `seat_decks` is the launcher's table ({seat: deck}); with no table at all the seats are 0-3 minus the human's,
    which with three seat libraries and a human at 0 is seats 1-3 — the old default behaviour. Four random decks
    with no associations, or no assign.json at all, seat deterministically through pass 3."""
    if not libraries:
        return {}
    libs = {n: i for n, i in libraries.items() if not (human_seat is not None and i.get("role") == "advisor")}
    by_deck = by_deck or {}
    decks: dict[int, str] = {}
    for k, v in (seat_decks or {}).items():                         # keys may arrive as strings from JSON (Gemini review)
        try:
            decks[int(k)] = str(v)
        except (TypeError, ValueError):
            continue
    order = [n for n in (fallback or []) if n in libs]
    order += [n for n in sorted(libs, key=lambda n: (libs[n].get("seat", 99), n)) if n not in order]
    if decks:
        seats = sorted(s for s in decks if s != human_seat)
    else:
        seats = [s for s in range(4) if s != human_seat][:len(order)]
    out: dict[int, dict] = {}
    used: set[str] = set()
    for seat in seats:                                              # pass 2: the associations, lower seat first
        lib = by_deck.get(decks.get(seat, ""))
        if lib in libs and lib not in used:
            out[seat] = libs[lib]; used.add(lib)
    for seat in seats:                                              # pass 3: the fallback order
        if seat in out:
            continue
        free = next((n for n in order if n not in used), None)
        if free is None:
            break                                                   # more seats than libraries: the rest stay silent
        out[seat] = libs[free]; used.add(free)
    return out


def load_seat_libraries(voices_dir: Path | None = None, seat_decks: dict[int, str] | None = None,
                        human_seat: int | None = 0) -> dict[int, dict]:
    """{seat: {"library", "voice", "temperament", ...}} — the voices at the table (assign_voices). Missing dir -> {}."""
    return assign_voices(load_libraries(voices_dir), seat_decks, load_assignments(voices_dir), human_seat, load_fallback(voices_dir))


DEFAULT_TABLE = "urza-lord-high-artificer giada-font-of-hope purphoros-god-of-the-forge selvala-heart-of-the-wilds"


def table_from_launcher(human_deck: str | None, roster: str | None, all_ai: bool) -> dict[int, str]:
    """The table as the launcher seats it — the ONLY source of who plays what (the game-log rebind is gone,
    2026-09-17): an all-AI table seats roster[i] at seat i; a human table is the roster minus the human's deck,
    in roster order, at seats 1-3. An empty roster is the arena's default table."""
    slugs = (roster or "").split() or DEFAULT_TABLE.split()
    if all_ai:
        return {i: d for i, d in enumerate(slugs[:4])}
    if not human_deck:
        return {}
    rest = list(slugs)
    if human_deck in rest:
        rest.remove(human_deck)                                     # the human's ONE copy; a roster listing a deck twice keeps the other (Gemini review)
    return {i + 1: d for i, d in enumerate(rest[:3])}


def game_changers_of(deck_slug: str, decks_dir: Path | None = None) -> set[str]:
    """Card names Scryfall flags game_changer in this deck's dossier (deck-cards.json,
    written by arena-add-deck since 2026-09-10). Empty when the dossier is missing."""
    try:
        d = json.loads(((decks_dir or (ARENA / "decks")) / deck_slug / "dossier" / "deck-cards.json").read_text())
    except (OSError, ValueError, TypeError):
        return set()
    out: set[str] = set()
    for c in d.get("cards") or []:
        if isinstance(c, dict) and c.get("game_changer") and c.get("name"):
            out.add(str(c["name"])); out.add(str(c["name"]).split(" // ")[0])
    return out


def deck_cards_of(deck_slug: str, decks_dir: Path | None = None) -> dict[str, dict]:
    """name -> card record from the deck's dossier (front-face names too); empty when missing."""
    try:
        d = json.loads(((decks_dir or (ARENA / "decks")) / deck_slug / "dossier" / "deck-cards.json").read_text())
    except (OSError, ValueError, TypeError):
        return {}
    out: dict[str, dict] = {}
    for c in d.get("cards") or []:
        if isinstance(c, dict) and c.get("name"):
            out[str(c["name"])] = c
            out.setdefault(str(c["name"]).split(" // ")[0], c)
    return out


def card_kind(rec: dict | None) -> str:
    """creature | planeswalker | instant | sorcery | artifact | enchantment | land | "" from the type line."""
    t = str((rec or {}).get("type_line") or "").split(" // ")[0].lower()
    for k in ("creature", "planeswalker", "instant", "sorcery", "artifact", "enchantment", "land"):
        if k in t:
            return k
    return ""


def load_address(voices_dir: Path | None = None) -> dict:
    """voices/address.json — who a seat may be addressed as (commander slug, else colour identity)."""
    try:
        return json.loads(((voices_dir or VOICES_DIR) / "address.json").read_text())
    except (OSError, ValueError, TypeError):
        return {}


def who_for_deck(address: dict, deck_slug: str, decks_dir: Path | None = None) -> str:
    """The address slug for a deck: its commander when the table lines carry it, else the
    colour identity of its commander card (Ben's chart), else ""."""
    if not address or not deck_slug:
        return ""
    c = (address.get("commanders") or {}).get(deck_slug)
    if c and c.get("who"):
        return str(c["who"])
    cards = deck_cards_of(deck_slug, decks_dir)
    cmd = next((r for r in cards.values() if r.get("zone") == "commander"), None)
    if not cmd:
        return ""
    ident = cmd.get("color_identity") or ""
    letters = set(ident if isinstance(ident, str) else "".join(ident))
    key = "".join(ch for ch in "WUBRG" if ch in letters) or "C"
    return str((address.get("colors") or {}).get(key, ""))


def card_slug(name: str) -> str:
    """'Tergrid, God of Fright // Tergrid's Lantern' -> 'tergrid-god-of-fright' (same as runner/voice/card_lines.py)."""
    front = str(name or "").split(" // ")[0].lower()
    s = "".join(ch if ch.isalnum() else "-" for ch in front)
    return "-".join(p for p in s.split("-") if p)


def load_combo_index(voices_dir: Path | None = None) -> dict[frozenset, str]:
    """voices/combos.json: frozenset(front-face names) -> combo line key."""
    try:
        data = json.loads(((voices_dir or VOICES_DIR) / "combos.json").read_text()).get("combos") or {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}
    out: dict[frozenset, str] = {}
    for key, sets in data.items():
        for s in sets:
            out[frozenset(str(n).split(" // ")[0] for n in s)] = str(key)
    return out


def deck_combos_of(deck_slug: str, index: dict[frozenset, str], decks_dir: Path | None = None) -> list[tuple[frozenset, str]]:
    """The deck's <=3-piece combos from its dossier, each with its line key ("" when no
    line is written for that shape — the generic engine-online then). The pieces are
    matched against what a seat shows: its battlefield and what its permanents hold
    (an imprinted Dramatic Reversal, a Time Warp under the Mirror), so a piece the
    record places in hand or exile still counts once it is visibly in play."""
    try:
        d = json.loads(((decks_dir or (ARENA / "decks")) / deck_slug / "dossier" / "combos.json").read_text())
    except (OSError, ValueError, TypeError):
        return []
    out: list[tuple[frozenset, str]] = []
    seen: set[frozenset] = set()
    for cb in d.get("combos") or []:
        cards = cb.get("cards") or []
        if not cards or len(cards) > 3:
            continue
        fs = frozenset(str(c.get("name") or "").split(" // ")[0] for c in cards)
        if fs in seen:
            continue
        seen.add(fs)
        out.append((fs, index.get(fs, "")))
    return out


def life_pid(life) -> str:
    """The whole-sentence life line for a total: exact to forty, then the nearest step; none above a hundred or at zero."""
    try:
        n = int(life)
    except (TypeError, ValueError):
        return ""
    if n <= 0 or n > 100:
        return ""
    if n <= 40:
        return f"life-{n}"
    return f"life-{min(LIFE_STEPS, key=lambda s: (abs(s - n), s))}"


def hand_pid(hand) -> str:
    try:
        n = int(hand)
    except (TypeError, ValueError):
        return ""
    return f"hand-{n}" if 0 <= n <= 10 else ""

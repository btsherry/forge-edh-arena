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
    """{library: {"library", "voice", "temperament", "seat"}} from every
    voices/<name>/manifest.json; `seat` is the library's default seat."""
    out: dict[str, dict] = {}
    d = voices_dir or VOICES_DIR
    try:
        mans = sorted(d.glob("*/manifest.json"))
    except OSError:
        return out
    for mp in mans:
        try:
            m = json.loads(mp.read_text())
            seat = int(m["seat"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        out[mp.parent.name] = {"library": mp.parent.name, "voice": str(m.get("voice_name", mp.parent.name)).split(" - ")[0],
                               "temperament": str(m.get("temperament", "")), "seat": seat}
    return out


def load_assignments(voices_dir: Path | None = None) -> dict[str, str]:
    """voices/assign.json by_deck: deck slug -> library (Ben's associations)."""
    try:
        return dict((json.loads(((voices_dir or VOICES_DIR) / "assign.json").read_text()).get("by_deck") or {}))
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def assign_voices(libraries: dict[str, dict], seat_decks: dict[int, str] | None, by_deck: dict[str, str] | None,
                  exclude_seat: int | None = None) -> dict[int, dict]:
    """{seat: library info}. A seat whose deck is in by_deck gets that library
    (lower seat wins a clash); every other seat takes a free library in seat
    order — the library's default seat first, then whatever is left. With no
    seat->deck knowledge every library sits at its default seat."""
    if not libraries:
        return {}
    if exclude_seat is not None:
        # the human's seat is never voiced (2026-09-16: Joshua's library sits at seat 0 for all-AI tables only)
        libraries = {n: i for n, i in libraries.items() if i["seat"] != exclude_seat}
    seat_decks = {s: d for s, d in (seat_decks or {}).items() if s != exclude_seat}
    by_deck = by_deck or {}
    out: dict[int, dict] = {}
    used: set[str] = set()
    for seat in sorted(seat_decks):
        lib = by_deck.get(seat_decks[seat])
        if lib in libraries and lib not in used:
            out[seat] = libraries[lib]; used.add(lib)
    defaults = {info["seat"]: name for name, info in libraries.items()}
    seats = sorted(set(seat_decks) | set(defaults))
    for seat in seats:
        if seat in out:
            continue
        lib = defaults.get(seat)
        if lib is None or lib in used:
            free = [n for n in sorted(libraries, key=lambda n: libraries[n]["seat"]) if n not in used]
            lib = free[0] if free else None
        if lib is not None:
            out[seat] = libraries[lib]; used.add(lib)
    return out


def load_seat_libraries(voices_dir: Path | None = None, seat_decks: dict[int, str] | None = None,
                        exclude_seat: int | None = None) -> dict[int, dict]:
    """{seat: {"library", "voice", "temperament", "seat"}} — the voices at the table,
    by deck when the table is known (voices/assign.json), by default seat otherwise;
    the human's seat (exclude_seat) is never voiced. Missing dir -> {} (barks silently off)."""
    return assign_voices(load_libraries(voices_dir), seat_decks, load_assignments(voices_dir), exclude_seat)


DEFAULT_TABLE = "urza-lord-high-artificer giada-font-of-hope purphoros-god-of-the-forge selvala-heart-of-the-wilds"


def table_from_launcher(human_deck: str | None, roster: str | None, all_ai: bool) -> dict[int, str]:
    """The seats the launcher knows at startup: an all-AI table seats roster[i] at seat i (game 56:
    without it Urza spoke two lines as Joshua before the game log named the decks and the voices
    moved); a human table is the roster minus the human's deck, seats 1-3."""
    if all_ai:
        slugs = (roster or "").split() or DEFAULT_TABLE.split()
        return {i: d for i, d in enumerate(slugs[:4])}
    return seat_decks_from_roster(human_deck, roster)


def seat_decks_from_roster(human_deck: str | None, roster: str | None) -> dict[int, str]:
    """{1..3: deck} the way GuiPilotMatch/run_table.sh/the advisor seat a human
    table: the roster minus the human's deck, in roster order, first three.
    Empty when the human deck is unknown (an all-AI table, or an old launcher)."""
    if not human_deck:
        return {}
    slugs = (roster or "").split() or DEFAULT_TABLE.split()
    return {i + 1: d for i, d in enumerate([d for d in slugs if d != human_deck][:3])}


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


def seat_decks_from_game_log(game_log: Path) -> dict[int, str]:
    """{seat: deck slug} from the runners' shared game log (each record carries
    seat + deck); empty until the first decisions land."""
    out: dict[int, str] = {}
    try:
        with game_log.open("rb") as f:
            for raw in f:
                try:
                    r = json.loads(raw)
                except ValueError:
                    continue
                if r.get("seat") is not None and r.get("deck"):
                    out.setdefault(int(r["seat"]), str(r["deck"]))
                if len(out) >= 4:
                    break
    except OSError:
        pass
    return out

#!/usr/bin/env python3
"""AI Advisor runner — a resident brain that watches the human seat's decision
shadow feed (mailbox/seat-0-advisor/inbox/) and streams teaching commentary
into runner/logs/advisor-0.log, which the GUI's Advisor tab tails.

One-way by construction: this process only READS the feed, so it can never
stall the game. Discipline:
  - ADVICE PREEMPTS COLOR: pending decision requests are answered before any
    turn-digest commentary; queued digests fold into the advice prompt.
  - STALE REQUESTS ARE SKIPPED: if several decision windows queued up, only
    the newest is advised (advising yesterday's window helps nobody).
  - The human's actual choices ride along as context for the next call —
    the brain teaches from divergence but never gets a dedicated call for it.
  - QUESTIONS ARE ANSWERED FIRST, EVEN WHILE PAUSED: the Advisor tab's field
    writes logs/control/ask/ask-<ts>-<n>.json; each is one direct call, answered
    in the stream as [you] / [advisor] lines (Ben, 2026-09-04).

Usage:
  advisor_runner.py --deck <slug> [--model opus] [--effort low]
                    [--base <mailbox-dir>] [--timeout 60]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seatd import backends  # noqa: E402
from seatd.brain import SeatBrain
from seatd.runner import SeatRunner  # noqa: E402

POLL_S = 1.0   # plan §3 (2026-09-14): one inbox listing a second still lands a request within the
               # second; the snapshot is stat-gated below, so an idle table costs nearly nothing
# Table roster convention shared with run_table.sh / GuiPilotMatch: four deck
# slugs in seat order, overridable via ARENA_SEAT_DECKS.
# Item R (Ben, 2026-09-04): the all-AI table is Urza, Giada, Purphoros, Selvala
# in seat order; a human game seats the human's deck at 0 and the first three
# roster decks that are not the human's behind it. GuiPilotMatch.DECKS and
# run_table.sh apply the same rule.
DEFAULT_TABLE = ("urza-lord-high-artificer giada-font-of-hope "
                 "purphoros-god-of-the-forge selvala-heart-of-the-wilds")
CONTEXT_MAX_LINES = 40  # BL-13: bound on lines carried between advice calls
ASK_MAX_CHARS = 500     # a question is one line; the GUI caps at the same value
# The advisor may run exactly this (see advisor-brief.md "Public state tool");
# claude -p's cwd is the package root, so the path is root-relative.
PUBLIC_STATE_CMD = "python3 forge-arena/scripts/arena-public-state.py"
PUBLIC_STATE_TOOL = f"Bash({PUBLIC_STATE_CMD}:*)"
# Voice quips (Ben, 2026-09-07): the advisor may end an advice or commentary
# line with ONE tag from this closed set — [quip:<id>] — and the voice runner
# plays the matching pre-rendered Joshua/W.O.P.R. phrase. The tag is stripped
# from the panel text and recorded as its own `quip` record. Film quotes are
# rare by instruction (the prompt says so); the runner rate-limits everything.
# Three registers since 2026-09-08: WarGames (the original batch), RoboCop
# (1987) one-liners and HK-47 "Statement:/Observation:" lines. Every id here
# has a pre-rendered runner/voice/stock/<id>.wav (tests check the manifest).
QUIP_REACTIONS = (
    # WarGames register
    "good-swing", "good-counter", "rough-counter", "didnt-see-that", "nice-combo", "stick-it-to-them",
    "ouch", "must-have-hurt", "well-played", "interesting", "calculating",
    # RoboCop
    "come-quietly", "can-you-fly", "nice-shooting", "lose-the-gun", "book-them", "theyll-fix-you",
    "good-business", "call-this-a-glitch", "call-a-paramedic",
    # HK-47
    "needs-removing", "did-i-say-that", "enjoy-this-very-much", "harsh-player", "blast-them-now",
    "random-cruelty-generator", "nothing-to-see", "meatbag-hypocrisy", "noble-sacrifice",
    "prospect-of-violence", "organic-life-fragile", "continue-to-surprise", "law-against-emotions",
    "exceedingly-proficient", "do-not-lose-targets")
# Moments in the game rather than plays: the human's turn, an elimination, the end.
QUIP_EVENTS = ("your-move-creep", "twenty-seconds-to-comply", "kill-something-for-you", "calm-before-engagement",
               "dead-or-alive", "youre-fired", "thank-you-cooperation", "sentence-is-death",
               "stay-out-of-trouble", "court-adjourned")
# Film quotes: at most once per game each.
QUIP_QUOTES = ("shall-we-play", "greetings-falken", "strange-game", "nice-game-of-chess", "hello",
               "buy-that-for-a-dollar", "serve-public-trust", "somewhere-a-crime", "i-am-the-law")
QUIPS = QUIP_REACTIONS + QUIP_EVENTS + QUIP_QUOTES
QUIP_RE = re.compile(r"\s*\[quip:([a-z0-9-]+)\]\s*")

# Seat barks (2026-09-10): the three AI seats have static voices (runner/voice/
# stock/voices/<lib>/, one library per seat number). The advisor — which already
# sees each turn's public log and knows the decks — picks the SEAT and the MOMENT;
# the persona is in the pre-rendered wording. Closed vocabulary, shared by every
# voice; unknown ids and seats outside 1-3 are dropped. The voice runner applies
# the knob (ARENA_BARKS), the dice, a per-seat cooldown and the global gap.
BARK_WHEN = {
    "commander-cast": "casts or recasts its commander",
    "big-swing": "declares a large attack",
    "landed-hit": "its attack connects for big damage",
    "removal": "destroys or exiles a key permanent",
    "sweep": "wipes the board",
    "counter": "counters a spell",
    "engine-online": "its engine or combo pieces are visibly assembled",
    "big-mana": "makes an explosive amount of mana",
    "kill": "eliminates another player",
    "win": "wins the game",
    "that-hurt": "takes a big hit",
    "lost-commander": "its commander dies or leaves",
    "got-countered": "its spell is countered",
    "got-swept": "its board is wiped",
    "low-life": "drops to about ten life or less",
    "eliminated": "is out of the game",
    "taunt": "needles whoever is ahead",
    "respect": "acknowledges another player's good play, the human included",
    "archenemy": "calls out the table leader",
    "slow-turn": "its own turn passes with nothing done",
    "my-turn": "opens the turn that is just beginning (the recap arrives as the next seat's turn starts)",
    # reactions (2026-09-10): a bystander's editorial on someone else's play — tag the seat that would say it
    "nice-play": "admires another player's good play",
    "thats-mean": "winces at a removal or an attack on a third party",
    "oh-no": "sees a threat land",
    "wow": "is impressed by anything big",
    "why-me": "is being attacked and objects",
    "attack-them": "deflects an attack onto someone else",
    "read-that": "wants an unfamiliar card read again",
    "play-slower": "is overwhelmed by a flurry of plays",
    "game-changer": "casts one of its game changers (the bracket list; the runner also fires this from the cast itself)",
    "gc-react": "sees another seat cast a game changer",
    "gc-gone": "is glad a game changer left the battlefield",
}
BARKS = tuple(BARK_WHEN)
BARK_RE = re.compile(r"\s*\[bark:\s*(\d)\s*:\s*([a-z0-9-]+)\s*\]\s*")
BARK_SEATS = (1, 2, 3)   # never the human (seat 0)


def split_bark(text: str, log=None) -> tuple[str, tuple[int, str] | None]:
    """Strip the [bark:<seat>:<id>] tag from a reply; return (clean text, (seat, id) or None).
    Unknown ids and seats outside 1-3 are dropped and logged, like quips."""
    m = BARK_RE.search(text or "")
    if not m:
        return (text or "").strip(), None
    seat, bid = int(m.group(1)), m.group(2)
    clean = BARK_RE.sub(" ", text).strip()
    if bid not in BARKS or seat not in BARK_SEATS:
        if log is not None:
            log(f"[advisor] bark tag dropped: [bark:{seat}:{bid}] "
                + ("(unknown id)" if bid not in BARKS else "(seat must be 1-3)"))
        return clean, None
    return clean, (seat, bid)


def game_changers_of(deck_slug: str) -> set:
    """Names Scryfall flags game_changer in the deck's dossier (deck-cards.json)."""
    try:
        from voice_runner import game_changers_of as _gc
        return _gc(deck_slug)
    except Exception:  # noqa: BLE001
        return set()


def bark_guide(seat_voices: dict, mode: str, seat_decks: dict | None = None, owner=None) -> str:
    """The prompt sentence offering the seat-bark tag, or "" when barks are off
    or no seat voice library exists. `seat_voices` is voice_runner.load_seat_libraries();
    `seat_decks` maps seat -> deck slug so the model can name the seat it means.

    `owner` shapes a RECAP's guide (the table-talk design, Ben 2026-09-10):
    an AI seat's turn -> that seat speaks (one tag for it, expected); the
    human's turn (0) -> Joshua's colour line, plus at most one seat reacting;
    None -> an advice window: optional, sparse.

    The VOICE NAMES are deliberately absent (game 38: Joshua called a player
    "Bill"): the model sees each seat's deck and temperament only, and the
    convention — players are their commanders — is spelled out."""
    if mode == "off" or not seat_voices:
        return ""
    decks = seat_decks or {}
    who = "; ".join(f"seat {k} ({decks.get(k, 'AI deck')}): {v['temperament']}"
                    for k, v in sorted(seat_voices.items()) if v.get("temperament"))
    ids = "; ".join(f"{b} when it {w}" for b, w in BARK_WHEN.items())
    gcs = "; ".join(f"seat {k}: " + ", ".join(sorted(game_changers_of(v))[:8]) for k, v in sorted(decks.items()) if game_changers_of(v))
    common = ((" GAME CHANGERS at the table (bracket list): " + gcs + "." if gcs else "")
              + " Tag form [bark:<seat>:<id>]; ids: " + ids + ". Never seat 0. Only public events; never a hidden hand. "
              "A quip and a bark never share one reply. In your own words always call a player by their COMMANDER "
              "(Urza, Giada, Purphoros…), never by a seat number or any other name.")
    if owner is not None and int(owner) in seat_voices:
        return (f"\nSEAT BARK: this recap is seat {int(owner)}'s own turn ({decks.get(int(owner), 'AI deck')}); the seats "
                f"speak in their own voices ({who}). End with exactly ONE tag for seat {int(owner)} that fits the turn it "
                "just had — what it did (commander-cast, big-swing, landed-hit, removal, sweep, counter, engine-online, "
                "big-mana, kill), what it suffered (that-hurt, lost-commander, got-countered, got-swept, low-life), or "
                "slow-turn if nothing happened. Table talk (taunt, respect, archenemy) only when it truly fits." + common)
    if owner is not None and int(owner) == 0:
        return ("\nSEAT BARK (optional): this recap is the human's turn. The seats speak in their own voices (" + who
                + "). If ONE seat was clearly affected by what the human did — hit hard, swept, countered, out-played — "
                "end with exactly one tag for that seat (that-hurt, got-swept, got-countered, respect, taunt…); otherwise "
                "no tag." + common)
    return ("\nSEAT BARK (optional, sparse): the AI seats speak in their own voices (" + who + "). If ONE seat's "
            "situation in what you just saw clearly earns a line, end with exactly one tag naming that seat and the "
            "moment. Most replies carry no tag." + common)
# Two densities (Ben, 2026-09-08): while the voice can render live lines the
# quips stay rare ("if the moment earns it"); when live lines are down — no
# ElevenLabs key (every package user without one), a spent quota, no usable
# voice — the pre-rendered stock quips are all the voice has, so the advisor
# is asked for one on about one line in two. The voice runner publishes its
# state to mailbox/seat-0-voice/state.json; _quip_guide() reads it per prompt.
_QUIP_LIST = ", ".join(f"[quip:{q}]" for q in QUIPS)
_QUOTE_NAMES = ", ".join(QUIP_QUOTES)
_REACTION_NAMES = ", ".join(QUIP_REACTIONS)
_EVENT_NAMES = ", ".join(QUIP_EVENTS)
QUIP_GUIDE_SPARSE = ("\nVOICE QUIP (optional): if the moment earns it, end with exactly one tag from this list and nothing after it: "
                     + _QUIP_LIST
                     + ". Use one at most every other turn; the film quotes (" + _QUOTE_NAMES
                     + ") at most once per game each, when they genuinely fit.")
QUIP_GUIDE_DENSE = ("\nVOICE QUIP: the voice has only its stock phrases right now — end about one line in two with exactly "
                    "one tag from this list and nothing after it: " + _QUIP_LIST
                    + ". The reactions (" + _REACTION_NAMES + ") fit any notable play — a big "
                    "attack, a removal, a counter, a combo piece, a swing in life; the event lines (" + _EVENT_NAMES
                    + ") fit a moment rather than a play — the human's turn or a slow decision (your-move-creep, "
                    "twenty-seconds-to-comply, kill-something-for-you), the quiet before combat (calm-before-engagement), "
                    "a player eliminated (dead-or-alive, youre-fired, thank-you-cooperation, sentence-is-death), the end "
                    "(stay-out-of-trouble, court-adjourned); vary them — do not repeat one you used in the last few turns; "
                    "the film quotes (" + _QUOTE_NAMES + ") at most once per game each, when they genuinely fit.")
QUIP_GUIDE = QUIP_GUIDE_SPARSE   # the default when the voice has published nothing


class TurnClock:
    """Turn labels as players say them (Ben, 2026-09-08): ``r4-t13`` = the
    fourth round, thirteenth turn of the game. A round is one full set of
    turns around the table: it ends when a seat that has already taken a turn
    this round becomes active again — so any starting seat and any
    elimination count correctly. The active seat of each turn is read from the
    public observer snapshot as the game runs (``observe()`` from the advisor's
    poll loop, so the pair is known before the turn's first line is written —
    game 33 showed a one-turn lag when it was only read on demand). Without a
    snapshot, four turns make a round."""

    def __init__(self, observer_state: Path):
        self.path = observer_state
        self.last: dict = {}          # the last snapshot read (danger detection reads its stack)
        self.active_of: dict = {}     # turn -> active seat, as observed
        self.round_of: dict = {}      # turn -> round, computed in turn order
        self._seen: set = set()       # seats active in the round being built
        self._round = 1
        self._last_turn = 0
        self._sig = None              # (mtime_ns, size) of the snapshot last parsed

    def observe(self) -> None:
        """Record the snapshot's (turn, activeSeat) if new; cheap, call often — the
        file is stat-ed first and parsed only when its mtime or size moved (plan §3:
        four full parses a second on an idle table). A partial write leaves the
        signature unset, so the next poll reads again."""
        try:
            st = os.stat(self.path)
            sig = (st.st_mtime_ns, st.st_size)
            if sig == self._sig:
                return
            d = json.loads(Path(self.path).read_text())
        except (OSError, ValueError, TypeError):
            return
        self._sig = sig
        self.last = d if isinstance(d, dict) else {}
        turn, active = d.get("turn"), d.get("activeSeat")
        if not isinstance(turn, int) or isinstance(turn, bool) or active is None or turn in self.active_of:
            return
        self.active_of[turn] = active
        if turn <= self._last_turn:
            return   # out of order (a late snapshot): keep the round already assigned
        if not self.round_of:
            self._round = max(1, (turn - 1) // 4 + 1)   # joined mid-game: best guess, exact from here
        elif active in self._seen:
            self._seen = set()
            self._round += 1
        self._seen.add(active)
        self.round_of[turn] = self._round
        self._last_turn = turn

    def label(self, turn) -> str:
        if not isinstance(turn, int) or isinstance(turn, bool):
            return f"t{turn}"
        if turn not in self.round_of:
            self.observe()
        r = self.round_of.get(turn)
        if r is None:
            r = self._round if (self.round_of and turn >= self._last_turn) else (turn - 1) // 4 + 1
        return f"r{r}-t{turn}"


def danger_targets(snapshot: dict, human_seat: int = 0) -> list[str]:
    """Opponents' stack items aimed at the human: "<spell> targets <your thing>".
    Reads the public snapshot's stackDetail (owner, targets); a target is the
    human's when it names their seat, one of their own stack items, or a card on
    their battlefield. Game 43 (2026-09-10): Jwari Disruption on Sheltering
    Ancient fell to the governor's dice and nobody said "Earthcraft now" —
    a window like this is always advised."""
    if not isinstance(snapshot, dict):
        return []
    detail = snapshot.get("stackDetail") or []
    mine: set[str] = set()
    for item in detail:
        if isinstance(item, dict) and item.get("owner") == human_seat and item.get("name"):
            mine.add(f"{item['name']} (on the stack)")
    for seat in snapshot.get("seats") or []:
        if isinstance(seat, dict) and seat.get("seat") == human_seat:
            for c in seat.get("battlefield") or []:
                if isinstance(c, dict) and c.get("name"):
                    mine.add(c["name"])
    out: list[str] = []
    for item in detail:
        if not isinstance(item, dict) or item.get("owner") in (None, human_seat):
            continue
        hits = [t for t in (item.get("targets") or []) if t == f"seat {human_seat}" or t in mine]
        if hits:
            out.append(f"{item.get('name', '?')} targets " + ", ".join(h.replace(f"seat {human_seat}", "you") for h in hits))
    return out


def quip_guide(state_file, log=None, prev=None) -> tuple[str, bool]:
    """(guidance text, live) from the voice runner's state file; sparse when
    the file is missing or unreadable. `prev` is the last `live` seen, so a
    switch is logged once."""
    live = True
    try:
        st = json.loads(Path(state_file).read_text())
        live = bool(st.get("live", True))
        reason = st.get("reason", "")
    except (OSError, ValueError, TypeError):
        reason = ""
    if log is not None and prev is not None and live != prev:
        log(f"[advisor] voice live lines {'back on — quips rare again' if live else 'off (' + reason + ') — stock quips on about one line in two'}")
    return (QUIP_GUIDE_SPARSE if live else QUIP_GUIDE_DENSE), live


def split_quip(text: str, log=None) -> tuple[str, str | None]:
    """Strip the [quip:<id>] tag from a reply; return (clean text, id or None).
    Unknown ids are dropped — the vocabulary is closed — and logged when a
    logger is given (Gemini review 2026-09-07: silent drops hid prompt drift)."""
    m = QUIP_RE.search(text or "")
    if not m:
        return (text or "").strip(), None
    qid = m.group(1)
    clean = QUIP_RE.sub(" ", text).strip()
    if qid not in QUIPS and log is not None:
        log(f"[advisor] unknown quip tag dropped: [quip:{qid}]")
    return clean, (qid if qid in QUIPS else None)


def table_opponents(own_deck: str, roster: list[str]) -> list[str]:
    """The three AI decks at a human table: roster minus the human's deck, in
    roster order, first three. Mirrors GuiPilotMatch/run_table.sh."""
    return [d for d in roster if d != own_deck][:3]


# ---- table deals (docs/reviews/2026-09-16-table-deals-plan.md §11) ---------------
# The player deals through the Advisor chat: `@urza peace for a turn?` or `deal
# purphoros alliance 2 rounds`. Joshua RELAYS — the message is parsed here, never
# answered by the brain — as a `deal-offer` note in the seat's mailbox; the seat's
# `deal` answer (game.jsonl) and the voice runner's ledger (logs/deals.jsonl) come
# back as panel lines. Three kinds, two durations, one counter per offer.
DEAL_KINDS = ("truce", "no-target", "alliance")
DEAL_ROUNDS_MAX = 3
OFFER_NUDGE_S = 30.0        # an open offer this old earns one panel line saying the seat has had no window yet
DEAL_COLOR_P = 1.0          # Ben (game 50): a deal you struck or had broken is state you act on — Joshua's read is delivered every time, no dice
DEAL_PANEL_MAX = 100        # every deal panel line fits one row
ADDRESS_JSON = Path(__file__).resolve().parent / "voice" / "stock" / "voices" / "address.json"
_DEAL_AT_RE = re.compile(r"^@\s*([A-Za-z0-9][\w'\-]*)[:,]?\s*(.*)$", re.S)
_DEAL_WORD_RE = re.compile(r"^deal\s+(?:with\s+)?([A-Za-z][\w'\-]*)[:,]?\s*(.*)$", re.I | re.S)
_DEAL_ACCEPT_RE = re.compile(r"^(accept(?:ed)?|yes|ok|okay|agreed|deal|take it)[.!]*$", re.I)
_DEAL_REFUSE_RE = re.compile(r"^(no|nope|refuse|decline|reject|pass|no deal)[.!]*$", re.I)
_DEAL_UNTIL_RE = re.compile(r"\buntil\s+(?:the\s+)?(?:end\s+of\s+)?turn\s+(\d+)", re.I)
_DEAL_ROUNDS_RE = re.compile(r"\b(\d+|a|an|one|two|three)\s+(?:more\s+|full\s+)?(?:turns?|rounds?)\b", re.I)
_DEAL_NUMS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}
_DEAL_KIND_RES = (("no-target", re.compile(r"\bno[\s-]?targets?\b|\bdon'?t target\b", re.I)),
                  ("alliance", re.compile(r"\b(alliance|allied|ally|allies|both)\b", re.I)),
                  ("truce", re.compile(r"\b(truce|peace)\b", re.I)))
_ADVISOR_NAMES = ("joshua", "advisor", "wopr")
# Game 54 (Ben): "make me an offer" and "you dirty bastard" both went out as one-turn truces. Words to a seat are an
# OFFER only when they carry deal terms; an invitation asks the seat to propose; anything else is table talk relayed
# to the seat's brain (it may answer with a say). A bare "@urza" stays the one-turn truce it always was.
_DEAL_TERM_RE = re.compile(r"\b(deal|truce|peace|alliance|ally|allies|allied|no[\s-]?targets?|don'?t target|turns?|rounds?|until)\b", re.I)
_DEAL_INVITE_RE = re.compile(r"\b(make (me )?an offer|make me an? (deal|proposal)|what do you want|what would you (take|want)|your terms|name your (price|terms)|offer me|propose (something|a deal)|got an offer)\b", re.I)
DEAL_KINDS_TEXT = ("Terms of a deal: a truce forbids attacks only; a no-target deal forbids targeting the other player or their "
                   "permanents; an alliance forbids both. Nothing else is promised — a truce is not broken by a spell.")
_DEAL_ASK_RE = re.compile(r"\b(deal|truce|alliance|no[\s-]target|counter[\s-]?offer)\b", re.I)


def load_commanders(path: Path = ADDRESS_JSON) -> dict:
    """address.json `commanders`: deck slug -> {who, say, name}; {} when unreadable."""
    try:
        d = json.loads(Path(path).read_text()).get("commanders") or {}
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def deal_table(seat_decks: dict, commanders: dict | None = None) -> tuple[dict, dict, dict]:
    """(aliases, names, handles) for the seats at the table: `aliases` maps every way the
    player may type a seat — commander (`urza`), its said name, the deck slug and
    its first word, `seat1`/`s1`/`1` — to the seat number; `names` maps seat ->
    the commander as the panel says it ("Urza"); `handles` seat -> the one word
    the panel tells the player to type (`@urza accept`). A deck address.json does
    not know is named by its slug's first word, capitalised."""
    cmd = load_commanders() if commanders is None else commanders
    aliases: dict[str, int] = {}
    names: dict[int, str] = {}
    handles: dict[int, str] = {}
    for seat, slug in sorted((int(k), str(v)) for k, v in seat_decks.items()):
        entry = cmd.get(slug) or {}
        first = slug.split("-")[0]
        say = str(entry.get("say") or first.capitalize())
        names[seat] = say
        handles[seat] = str(entry.get("who") or first).lower()
        keys = {slug, first, say, str(entry.get("who") or ""), str(entry.get("name") or "").split(",")[0],
                str(entry.get("name") or "").split("//")[0], f"seat{seat}", f"seat-{seat}", f"s{seat}", str(seat)}
        for k in keys:
            k = " ".join(k.lower().split())
            if k and k not in aliases:
                aliases[k] = seat
    return aliases, names, handles


def parse_deal(text: str, aliases: dict) -> dict | None:
    """The Advisor-chat deal grammar. `@<commander-or-seat> <words>` or `deal
    <commander> <words>`; words -> a kind (truce|peace, no target, alliance|ally|
    both; default truce) and a duration (`N turn(s)|round(s)` -> rounds 1..3;
    `until turn N` -> until_turn; default rounds 1), or `accept`/`yes` / `no` for
    a pending counter. Returns {"to": seat, "action": "offer", "deal": {...},
    "words": ...} | {"to": seat, "action": "accept"|"refuse", ...} | {"to":
    "advisor", "words": ...} for `@joshua …` | None when nothing here names a
    seat — the message is then an ordinary question for the brain."""
    m = _DEAL_AT_RE.match(text or "") or _DEAL_WORD_RE.match(text or "")
    if not m:
        return None
    name = " ".join(m.group(1).lower().rstrip("?!.,:;").split())
    words = " ".join(m.group(2).split())
    if name in _ADVISOR_NAMES:
        return {"to": "advisor", "words": words}
    seat = aliases.get(name)
    if seat is None:
        return None
    if _DEAL_ACCEPT_RE.match(words):
        return {"to": seat, "action": "accept", "words": words}
    if _DEAL_REFUSE_RE.match(words):
        return {"to": seat, "action": "refuse", "words": words}
    if _DEAL_INVITE_RE.search(words):
        return {"to": seat, "action": "invite", "words": words}
    if words and not _DEAL_TERM_RE.search(words):
        return {"to": seat, "action": "talk", "words": words}
    kind = "truce"
    for k, rx in _DEAL_KIND_RES:
        if rx.search(words):
            kind = k
            break
    deal: dict = {"kind": kind}
    mu = _DEAL_UNTIL_RE.search(words)
    if mu:
        deal["until_turn"] = int(mu.group(1))
    else:
        mr = _DEAL_ROUNDS_RE.search(words)
        n = 1
        if mr:
            tok = mr.group(1).lower()
            n = _DEAL_NUMS.get(tok) or int(tok)
        deal["rounds"] = max(1, min(DEAL_ROUNDS_MAX, n))
    return {"to": seat, "action": "offer", "deal": deal, "words": words}


def deal_terms_text(deal: dict, name: str | None = None) -> str:
    """`truce, 1 turn` / `alliance, 2 turns` / `no-target until turn 12`; with a
    name and both durations resolved: `truce until Urza's turn 9 ends`."""
    kind = str((deal or {}).get("kind") or "truce")
    until, rounds = (deal or {}).get("until_turn"), (deal or {}).get("rounds")
    if until is not None and rounds is not None and name:
        return f"{kind} until {name}'s turn {until} ends"
    if until is not None:
        return f"{kind} until turn {until}"
    n = int(rounds or 1)
    return f"{kind}, {n} turn{'s' if n != 1 else ''}"


def opponent_deck_sections(own_deck: str, arena_root: Path) -> list[str]:
    """Full oracle text + combo lists for every OTHER deck at the table.

    The advisor is an observer-teacher: knowing the pod's decks is the
    experienced-friend model (and grounds card facts like indestructible in
    context instead of trusting recall). Seat brains never receive this —
    their fairness contract keeps opponents' lists dark.
    """
    import os
    roster = (os.environ.get("ARENA_SEAT_DECKS", "").split() or DEFAULT_TABLE.split())
    parts: list[str] = []
    for slug in table_opponents(own_deck, roster):
        dossier = arena_root / "decks" / slug / "dossier"
        try:
            cards = json.loads((dossier / "deck-cards.json").read_text()).get("cards", [])
        except (OSError, ValueError):
            parts.append(f"\n## OPPONENT DECK {slug} — dossier missing (not ingested)\n")
            continue
        lines = []
        for c in cards:
            oracle = (c.get("oracle_text") or "").replace("\n", " / ")
            lines.append(f"{c.get('name')} — {c.get('mana_cost', '')} — "
                         f"{c.get('type_line', '')} — {oracle}")
        section = (f"\n## OPPONENT DECK: {slug} (public deck metadata — use for "
                   f"threat forecasting and teaching)\n" + "\n".join(lines))
        try:
            combos = json.loads((dossier / "combos.json").read_text()).get("combos", [])
            if combos:
                section += ("\n### their known combos (CommanderSpellbook)\n"
                            + json.dumps(combos, separators=(",", ":")))
        except (OSError, ValueError):
            pass
        parts.append(section)
    return parts


class AdvisorRunner:
    def __init__(self, deck: str, base: Path, model: str, effort: str, timeout: float,
                 log_dir: Path | None = None):
        self.inbox = base / "seat-0-advisor" / "inbox"
        self._voice_state = base / "seat-0-voice" / "state.json"
        # seat barks: the voices at the table (from the stock libraries) and the knob
        self._barks_mode = os.environ.get("ARENA_BARKS", "some").lower()
        roster = (os.environ.get("ARENA_SEAT_DECKS", "").split() or DEFAULT_TABLE.split())
        self._seat_decks = {i + 1: slug for i, slug in enumerate(table_opponents(deck, roster))}
        try:
            from voice_runner import load_seat_libraries
            self._seat_voices = load_seat_libraries(seat_decks=self._seat_decks)   # by deck (voices/assign.json), same as the voice runner
        except Exception:  # noqa: BLE001 — the voice runner is optional
            self._seat_voices = {}
        self._bark_guide_text = bark_guide(self._seat_voices, self._barks_mode, self._seat_decks)   # advice windows
        self._clock = TurnClock(base / "observer-state.json")
        self._voice_live = None
        self.timeout = timeout
        log_dir = Path(log_dir) if log_dir else Path(__file__).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._stream = log_dir / "advisor-0.log"
        self._jsonl = log_dir / "advisor-0.jsonl"
        self._usage = log_dir / "seat-0.usage.json"
        self._control = log_dir / "control" / "seat-0.json"
        self._control_mtime = 0.0
        self._asks = log_dir / "control" / "ask"   # questions from the Advisor tab
        self._last_turn = None                      # for the [tN · you] label
        arena_root = Path(__file__).resolve().parent.parent
        # Table deals (plan §11): the player's offers by offer_id, the seats as the
        # player may type them, and the cursors into the two files that answer —
        # game.jsonl (a seat's `deal` answer) and logs/deals.jsonl (the voice
        # runner's ledger). Both cursors start at the current end: a restarted
        # advisor never re-prints a finished deal.
        self._offers: dict[str, dict] = {}
        self._deal_seen: set = set()
        self._deal_aliases, self._deal_names, self._deal_handles = deal_table({0: deck, **self._seat_decks})
        self._ledger = log_dir / "deals.jsonl"
        self._deal_control = log_dir / "control" / "deal"
        self._questions = self._deal_control / "questions"     # the offer pane's files (plan 2026-09-16-offer-dialog-plan.md)
        self._clear_questions()                                  # a fresh runner: no pane from a past game
        self._game_pos = self._size_of(log_dir / "game.jsonl")
        self._ledger_pos = self._size_of(self._ledger)
        self.deal_rng = random.Random()              # the 70/30 dice, apart from the governor's seeded stream
        # The advisor's ONE tool (Ben, 2026-09-07): the public-state dump.
        # claude -p runs from the package root, so the pattern is root-relative;
        # ARENA_ADVISOR_TOOLS=off takes it away.
        tools = None
        if os.environ.get("ARENA_ADVISOR_TOOLS", "on").lower() != "off":
            tools = [PUBLIC_STATE_TOOL]
        self.brain = SeatBrain(0, deck, model=model, effort=effort,
                               log=self._say, brief="advisor-brief.md",
                               extra_parts=opponent_deck_sections(deck, arena_root),
                               allowed_tools=tools)
        self.last_seq = 0
        self.game_id: str | None = None   # item 5/8: the game being advised
        # Executive take-over (Ben, 2026-09-07): logs/control/executive.json
        # {"on": true} — written by the Advisor tab's second button. The GUI
        # installs a mailbox controller over the human seat at its next
        # priority; THIS process answers that mailbox with the advisor's own
        # brain through a seat-0 SeatRunner (no second agent, same session).
        self._exec_file = log_dir / "control" / "executive.json"
        self._exec: SeatRunner | None = None
        self._base = Path(base)
        self._log_dir = log_dir
        self._game_log = log_dir / "game.jsonl"
        try:
            self.rotate_at = int(os.environ.get("ARENA_ADVISOR_ROTATE_TOKENS", "400000"))
        except ValueError:
            self.rotate_at = 400000
        self.pending_context: list[str] = []  # chosen/digest lines awaiting a call
        self._context_dropped = 0             # BL-13: lines cut by the bound
        self._init_control(model, effort)
        # ---- frequency governor state (the charm patch) ----------------------
        # Advice is deliberately sparse and humanly random: every in-game window
        # (priority, combat, danger, targets/X) is tied to a per-turn range of
        # 1-3 admitted by seeded dice — no guaranteed main/combat/danger stops.
        # Only the once-a-game mulligan is always answered; a big mid-turn play
        # the dice miss is covered by the always-on end-of-turn digest.
        self.rng = random.Random()
        self.gov_turn = -1
        self.gov_budget = 0
        try:
            own = json.loads((arena_root / "decks" / deck / "dossier"
                              / "deck-cards.json").read_text())
            self.own_card_names = {c.get("name") for c in own.get("cards", [])}
        except (OSError, ValueError):
            self.own_card_names = set()

    # ---- frequency governor ----------------------------------------------------

    RANDOM_ADMIT_P = 0.35

    def _gov_new_turn(self, turn: int) -> None:
        seed = f"{self.brain.session_id or 'warmup'}:{turn}"
        self.rng.seed(seed)
        self.gov_turn = turn
        self.gov_budget = self.rng.randint(1, 3)
        self._record("governor", {"turn": turn, "budget": self.gov_budget,
                                  "seed": seed})

    def _admit(self, req: dict) -> tuple[bool, str]:
        """Governor verdict for one request: (advise?, reason). Every in-game
        window obeys the per-turn range; only the once-a-game mulligan is always
        answered. A big mid-turn play the dice miss is still covered by the
        always-on end-of-turn digest."""
        turn = int(req.get("turn") or 0)
        if turn > self.gov_turn:
            self._gov_new_turn(turn)
        if (req.get("decisionType") or "") == "MULLIGAN":
            return True, "mulligan"
        danger = danger_targets(self._clock.last)
        if danger:
            return True, "danger: " + "; ".join(danger)[:160]
        # Everything else — priority windows, combat declares, danger (opponent
        # spell on the stack), targets/X — is tied to the range: seeded dice
        # while the per-turn budget remains. No guaranteed main/combat/danger.
        if self.gov_budget > 0 and self.rng.random() < self.RANDOM_ADMIT_P:
            self.gov_budget -= 1
            return True, "range"
        return False, "budget"

    # ---- output --------------------------------------------------------------

    def _say(self, msg: str) -> None:
        print(time.strftime("%H:%M:%S"), msg, flush=True)

    def _stream_write(self, text: str) -> None:
        try:
            with self._stream.open("a") as f:
                f.write(text)
        except OSError:
            pass  # BL-26: bookkeeping never ends the advisor

    def _record(self, kind: str, body: dict) -> None:
        body = {"ts": round(time.time(), 3), "kind": kind, **body}
        try:
            with self._jsonl.open("a") as f:
                f.write(json.dumps(body) + "\n")
        except OSError:
            pass  # BL-26
        try:
            self._usage.write_text(json.dumps(self.brain.totals))
        except OSError:
            pass

    def _push_context(self, line: str) -> None:
        """BL-13: the context carried into the next advice call is bounded;
        the oldest lines go first and the drop is stated, never silent."""
        self.pending_context.append(line)
        extra = len(self.pending_context) - CONTEXT_MAX_LINES
        if extra > 0:
            del self.pending_context[:extra]
            self._context_dropped += extra

    # ---- control file (AI-tab steppers re-dial the advisor mid-game) ----------

    def _init_control(self, model: str, effort: str) -> None:
        try:
            self._control.parent.mkdir(parents=True, exist_ok=True)
            # The advisor is Claude-only in v1 (plan F-10): a stale backend
            # model left in the control file by a previous session must not
            # be honored — reset it so the AI panel shows what actually runs.
            stale = False
            if self._control.exists():
                try:
                    cur = json.loads(self._control.read_text())
                    stale = backends.parse_model(cur.get("model"))[0] != "claude"
                except ValueError:
                    stale = True
            if stale:
                self._say("[advisor] control file held a backend model — "
                          "advisor is Claude-only in v1; resetting to defaults")
            if stale or not self._control.exists():
                self._control.write_text(json.dumps({"model": model, "effort": effort}))
            self._control_mtime = self._control.stat().st_mtime
        except OSError:
            pass

    def _apply_control(self) -> None:
        try:
            mtime = self._control.stat().st_mtime
            if mtime == self._control_mtime:
                return
            try:
                desired = json.loads(self._control.read_text())
            except ValueError:
                return  # torn write — mtime not recorded, retried next poll
            self._control_mtime = mtime
            model = desired.get("model")
            effort = desired.get("effort")
            if model and model != self.brain.model:
                if backends.parse_model(model)[0] != "claude":
                    # Claude-only guard, mid-game leg (plan F-10): refuse the
                    # dial, tell the human IN the advisor stream, and write the
                    # control file back so the panel recovers instead of
                    # displaying a model that is not running.
                    self._say(f"[advisor] backend model {model} refused — "
                              f"advisor is Claude-only in v1")
                    self._stream_write(
                        f"\n[advisor] {model} is a backend model — the advisor "
                        f"is Claude-only in v1; staying on {self.brain.model}.\n")
                    self._control.write_text(json.dumps(
                        {"model": self.brain.model, "effort": self.brain.effort}))
                    self._control_mtime = self._control.stat().st_mtime
                else:
                    self.brain.model = model
                    self._say(f"[advisor] model -> {model}")
            if effort and effort != self.brain.effort:
                self.brain.effort = effort
                self._say(f"[advisor] effort -> {effort}")
        except OSError:
            pass

    # ---- executive take-over ---------------------------------------------------

    EXEC_HANDOFF = (
        "EXECUTIVE MODE (the human clicked 'Advisor Executive'): from now until you are told "
        "otherwise you PLAY seat 0 — the deck in your dossier — directly. Requests arrive in the "
        "seat format and each states its exact 'Answer:' shape. Reply with ONLY the JSON answer "
        "object on one line: no prose, no code fences. The request JSON is ground truth; you see "
        "your own hand plus public information. A malformed answer is replaced by a safe default "
        "(CAST_SPELL/REACT pass; MULLIGAN keep; no attackers/blocks; CHOOSE_* the first legal "
        "ids; CHOOSE_NUMBER the maximum for an X cost else the minimum; PAY_UNLESS decline; "
        "CONFIRM yes only when the effect is yours and free). Play to win. Reply exactly: READY")
    EXEC_RELEASE = ("EXECUTIVE MODE ENDED: the human plays seat 0 again. You are advising "
                    "from here on. Reply exactly: OK")

    def _executive_wanted(self) -> bool:
        try:
            body = json.loads(self._exec_file.read_text())
            return bool(body.get("on", False))
        except (OSError, ValueError):
            return False

    def _executive_tick(self) -> bool:
        """Start/stop executive mode from the control file; answer one pending
        seat-0 request when on. Returns True when a request was handled."""
        want = self._executive_wanted()
        if want and self._exec is None:
            self._exec = SeatRunner(0, self.brain.deck, self._base, model=self.brain.model,
                                    effort=self.brain.effort, timeout_s=self.timeout,
                                    log_dir=self._log_dir, brain=self.brain)
            try:
                self._exec.mb.start_heartbeat_thread()
            except Exception:  # noqa: BLE001 — liveness only
                pass
            self.brain.note(self.EXEC_HANDOFF, timeout_s=min(60.0, self.timeout))
            self._say("[advisor] EXECUTIVE ON — playing seat 0 through the mailbox")
            self._clear_questions()                    # the seat-0 runner answers the notes itself; no pane
            self._stream_write("\n[advisor] EXECUTIVE ON — I am playing your seat now. Click again to take it back.\n")
        elif not want and self._exec is not None:
            try:
                self._exec.mb.stop_heartbeat_thread()   # seat-0 must not read as alive now
            except Exception:  # noqa: BLE001
                pass
            self._exec = None
            self.brain.note(self.EXEC_RELEASE, timeout_s=min(60.0, self.timeout))
            self._say("[advisor] EXECUTIVE OFF — advising again")
            self._stream_write("\n[advisor] EXECUTIVE OFF — your seat is yours again from the next priority.\n")
        if self._exec is not None:
            if getattr(self._exec, "_game_id", None):
                self.game_id = self._exec._game_id   # one game id for both views (Gemini P2)
            req = self._exec.mb.pending_request()
            if req is not None:
                self._exec.handle(req)
                return True
        return False

    def _maybe_rotate(self) -> bool:
        """Layer two for the advisor: a fresh session with the same four
        dossiers plus the public game record when the last call re-read more
        than ARENA_ADVISOR_ROTATE_TOKENS (0 disables)."""
        if self._exec is not None:
            return False   # executive: the seat-0 runner rotates with its OWN record (Gemini P1)
        size = getattr(self.brain, "last_prompt_tokens", 0)
        if not self.rotate_at or size < self.rotate_at or not self.brain.session_id:
            return False
        try:
            from seatd import record as _record
            text = _record.render(self._game_log, None, 0, game_id=self.game_id)
        except Exception as e:  # noqa: BLE001
            self._say(f"[advisor] game record failed ({e}) — rotation skipped")
            return False
        return self.brain.rotate(text, timeout_s=min(120.0, self.timeout))

    # ---- auto-pass receipts in the panel (Ben, 2026-09-08: "address the spam") --
    # ARENA_AUTOPASS_RECEIPTS = all (DEFAULT, Ben 2026-09-08: every receipt) |
    # summary (ONE line per turn, written when the next turn's first receipt
    # arrives, with counts by reason) | off (nothing in the panel). "prompt
    # kept" lines always show at once.

    def _show_note(self, body: dict) -> None:
        mode = os.environ.get("ARENA_AUTOPASS_RECEIPTS", "summary").lower()   # Ben 2026-09-08 (game 32): one line per turn by default
        note = str(body.get("note") or "")
        turn = body.get("turn")
        if mode == "off":
            return
        if mode == "all" or "prompt kept" in note or "auto-passed" not in note:
            self._flush_receipts(turn)
            self._stream_write(f"[{self._clock.label(turn)}] ⏭ {note}\n")
            return
        if getattr(self, "_receipt_turn", None) != turn:
            self._flush_receipts(turn)
            self._receipt_turn = turn
            self._receipts = {}
        reason = re.sub(r"^\(auto-passed — ", "", note).rstrip(")")
        self._receipts[reason] = self._receipts.get(reason, 0) + 1

    def _flush_receipts(self, new_turn=None) -> None:
        """Write the pending turn's one-line summary (if any) before anything
        for a later turn is shown, so the panel stays in order."""
        rec = getattr(self, "_receipts", None)
        turn = getattr(self, "_receipt_turn", None)
        if not rec or turn is None or turn == new_turn:
            return
        total = sum(rec.values())
        parts = ", ".join(f"{k} ×{v}" if v > 1 else k for k, v in rec.items())
        self._stream_write(f"[{self._clock.label(turn)}] ⏭ auto-passed {total} stop{'s' if total != 1 else ''} ({parts})\n")
        self._receipts = {}
        self._receipt_turn = None

    def _toggle_enabled(self) -> bool:
        try:
            body = json.loads((self._control.parent / "advisor.json").read_text())
            return bool(body.get("enabled", True))
        except (OSError, ValueError):
            return True  # missing/torn file = enabled (launch default)

    # ---- feed intake -----------------------------------------------------------

    def _scan(self) -> list[tuple[int, str, Path]]:
        """New inbox items as (seq, kind, path), seq-ordered."""
        items = []
        try:
            for p in self.inbox.iterdir():
                name = p.name
                if not name.endswith(".json"):
                    continue
                kind, _, tail = name.partition("-")
                if kind not in ("req", "chosen", "digest", "note"):
                    continue
                try:
                    n = int(tail[:-5])
                except ValueError:
                    continue
                items.append((n, kind, p))
        except OSError:
            return []
        items.sort()
        return items

    @staticmethod
    def _load(path: Path) -> dict | None:
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return None  # partial write — retry next poll

    # ---- prompts ---------------------------------------------------------------

    @staticmethod
    def _fmt_options(req: dict) -> str:
        opts = req.get("options") or []
        if not opts:
            return ""
        lines = [f"  [{o.get('id')}] {o.get('label')}" for o in opts]
        return "OPTIONS OFFERED:\n" + "\n".join(lines) + "\n"

    def _advise(self, req: dict) -> None:
        turn, phase = req.get("turn"), req.get("phase")
        ctx = ""
        if self.pending_context:
            head = (f"- … {self._context_dropped} earlier line(s) dropped\n"
                    if self._context_dropped else "")
            ctx = "SINCE LAST TIME:\n" + head + "\n".join(self.pending_context) + "\n\n"
            self.pending_context = []
            self._context_dropped = 0
        prompt = (f"{ctx}DECISION NOW — {req.get('decisionType')} "
                  f"(turn {turn}, {phase}): {req.get('prompt')}\n"
                  f"{self._fmt_options(req)}"
                  f"STATE: {json.dumps(req.get('state'), separators=(',', ':'))}\n\n"
                  "Advise the human now (1-3 sentences, plain text)." + self._quip_guide() + self._bark_guide_text)
        answer, meta = self.brain.decide(prompt, self.timeout)
        text, quip = split_quip((meta.get("raw") or "").strip(), log=self._say)
        text, bark = split_bark(text, log=self._say)
        if text:
            self._stream_write(f"\n[{self._clock.label(turn)} · {phase}] {text}\n")
        self._record("advice", {"seq": req.get("seq"), "turn": turn, "phase": phase,
                                "decisionType": req.get("decisionType"),
                                "text": text, "latency_s": meta.get("latency_s")})
        if quip:
            self._record("quip", {"id": quip, "turn": turn, "with": "advice", "seq": req.get("seq")})
        if bark:
            self._record("bark", {"seat": bark[0], "id": bark[1], "turn": turn, "with": "advice", "seq": req.get("seq")})

    def _quip_guide(self) -> str:
        text, live = quip_guide(self._voice_state, log=self._say, prev=self._voice_live)
        self._voice_live = live
        return text

    def _commentate(self, digest: dict) -> None:
        turn = digest.get("turn")
        lines = digest.get("digest") or []
        # whose turn was it? the clock observed the active seat as the turn ran
        owner = self._clock.active_of.get(turn) if isinstance(turn, int) else None
        prompt = (f"TURN {turn} COMPLETE. Public log of the turn:\n"
                  + "\n".join(f"  {ln}" for ln in lines[-60:])
                  + "\n\nONE line of color commentary (plain text)." + self._quip_guide()
                  + bark_guide(self._seat_voices, self._barks_mode, self._seat_decks, owner))
        answer, meta = self.brain.decide(prompt, min(self.timeout, 45.0))
        text, quip = split_quip((meta.get("raw") or "").strip(), log=self._say)
        text, bark = split_bark(text, log=self._say)
        if text:
            self._stream_write(f"\n[{self._clock.label(turn)} · color] {text}\n")
        self._record("color", {"seq": digest.get("seq"), "turn": turn, "owner": owner,
                               "text": text, "latency_s": meta.get("latency_s")})
        if quip:
            self._record("quip", {"id": quip, "turn": turn, "with": "color", "seq": digest.get("seq")})
        if bark:
            self._record("bark", {"seat": bark[0], "id": bark[1], "turn": turn, "with": "color", "seq": digest.get("seq")})

    # ---- game identity (plan items 5 + 8) ----------------------------------------

    def _reset_for_new_game(self, why: str) -> None:
        """Fresh session, fresh transcript, fresh governor. The governor used
        to keep the previous game's turn counter, so a second game in one
        process never re-armed and got no advice past the mulligan."""
        self._say(f"[advisor] new game detected ({why}) — resetting session")
        self.brain.reset()
        self.pending_context = []
        self._context_dropped = 0
        self.last_seq = 0
        self.gov_turn = -1
        self.gov_budget = 0

    def _maybe_new_game(self, body: dict, n: int, kind: str) -> bool:
        """Engine-stamped feeds: reset on a gameId CHANGE, never on numbering
        (chosen-<n> reuses its request's number while digests/notes take fresh
        ones, so the file numbers were never monotonic — the old comparison
        fired on ordinary interleaving). Unstamped feeds keep the legacy seq
        check, but only on kinds whose numbers do increase."""
        gid = body.get("gameId")
        if isinstance(gid, str) and gid:
            if self.game_id is None:
                self.game_id = gid
                return False
            if gid != self.game_id:
                old, self.game_id = self.game_id, gid
                self._reset_for_new_game(f"{old} -> {gid}")
                return True
            return False
        if kind in ("req", "digest", "note") and n < self.last_seq:
            self._reset_for_new_game(f"seq {n} < {self.last_seq}, unstamped engine")
            return True
        return False

    def _process(self, items: list[tuple[int, str, Path]], quiet: bool = False) -> int:
        """Consume scanned feed items. `quiet` (resume after a pause): fold
        chosen/digest lines into context, record notes without streaming them,
        skip every backlogged request — then the caller announces once.
        Returns the number of items consumed."""
        reqs, digests, consumed = [], [], 0
        for n, kind, path in items:
            body = self._load(path)
            if body is None:
                continue  # partial write — leave for next poll
            self._maybe_new_game(body, n, kind)
            self.last_seq = max(self.last_seq, n)
            consumed += 1
            if kind in ("req", "digest") and body.get("turn") is not None:
                if body.get("turn") != self._last_turn:
                    self._flush_receipts(body.get("turn"))
                self._last_turn = body.get("turn")
            if kind == "req":
                reqs.append(body)
            elif kind == "digest":
                digests.append(body)
            elif kind == "chosen":
                self._push_context(
                    f"- the human chose {json.dumps(body.get('chosen'))} "
                    f"for {body.get('decisionType')} (seq {body.get('seq')})")
                self._record("chosen", {"seq": body.get("seq"), "decisionType": body.get("decisionType")})
            elif kind == "note":
                if not quiet:
                    self._show_note(body)
                self._record("note", body)   # every receipt is kept for analysis
            try:
                path.unlink()
            except OSError:
                pass
        if quiet:
            for r in reqs:
                self._record("skipped_backlog", {"seq": r.get("seq"),
                                                 "decisionType": r.get("decisionType")})
            for d in digests:
                self._push_context(
                    f"- turn {d.get('turn')} public log: "
                    + " | ".join((d.get("digest") or [])[-25:]))
            return consumed
        # Governor: stale requests die first (advising yesterday's window
        # helps nobody), then the NEWEST request faces the admission rules.
        for stale in reqs[:-1]:
            self._record("skipped", {"seq": stale.get("seq"),
                                     "decisionType": stale.get("decisionType")})
        admitted = None
        if reqs:
            ok, reason = self._admit(reqs[-1])
            if ok:
                admitted = (reqs[-1], reason)
            else:
                self._record("skipped_gov", {"seq": reqs[-1].get("seq"),
                                             "decisionType": reqs[-1].get("decisionType"),
                                             "turn": reqs[-1].get("turn")})
        # digests fold into a pending advice call as context (advice preempts
        # color); with no admitted decision they get their own commentary call.
        if admitted is not None:
            for d in digests:
                self._push_context(
                    f"- turn {d.get('turn')} public log: "
                    + " | ".join((d.get("digest") or [])[-25:]))
            if admitted[1].startswith("danger: "):
                # the window is being advised BECAUSE an opponent aimed at the human: say so
                self._push_context("- DANGER on the stack: " + admitted[1][len("danger: "):]
                                   + " — advise the response now (an ability must be activated in THIS window; nothing can be activated once the spell resolves)")
                self._record("danger", {"seq": admitted[0].get("seq"), "turn": admitted[0].get("turn"), "what": admitted[1][len("danger: "):]})
            self._advise(admitted[0])
        else:
            for d in digests:
                self._commentate(d)
        return consumed

    # ---- questions from the Advisor tab (Ben, 2026-09-04) -------------------------

    def _scan_asks(self) -> list[Path]:
        """logs/control/ask/ask-<millis>-<serial>.json, oldest first (numeric
        order, not lexical). Each file is one question typed into the field."""
        try:
            files = [p for p in self._asks.iterdir()
                     if p.name.startswith("ask-") and p.name.endswith(".json")]
        except OSError:
            return []

        def key(p: Path) -> tuple[int, int, str]:
            parts = p.name[4:-5].split("-")
            try:
                return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0, p.name
            except ValueError:
                return 0, 0, p.name
        return sorted(files, key=key)

    def _handle_asks(self) -> int:
        """Answer every pending question, in order. Called BEFORE the pause
        gate: a typed question is an explicit request, so a paused advisor
        still answers it (and only it). The file is deleted the moment it is
        read — that deletion is the panel's "sent" signal — so a torn write
        is retried next poll and a malformed one is dropped, never re-read."""
        n = 0
        for p in self._scan_asks():
            body = self._load(p)
            if body is None:
                continue  # partial write — next poll
            try:
                p.unlink()
            except OSError:
                pass
            text = body.get("ask") if isinstance(body, dict) else None
            text = " ".join(str(text).split()) if isinstance(text, str) else ""
            if not text:
                self._record("ask_rejected", {"file": p.name})
                continue
            text = text[:ASK_MAX_CHARS]
            # A deal message first (plan §11): `@urza …` / `deal urza …` is relayed
            # to the seat, never answered; `@joshua …` is a question for the brain.
            d = parse_deal(text, self._deal_aliases)
            if d is not None and d.get("to") == "advisor":
                self._answer_ask(d.get("words") or text, deals=True)
            elif d is not None:
                self._handle_deal_message(d, text)
            else:
                self._answer_ask(text)
            n += 1
        return n

    def _answer_ask(self, text: str, deals: bool = False) -> None:
        turn = self._turn_now()          # the snapshot's turn, else the feed's (a question before any feed: "t?")
        turn = turn if turn is not None else "?"
        ctx = ""
        if self.pending_context:
            head = (f"- … {self._context_dropped} earlier line(s) dropped\n"
                    if self._context_dropped else "")
            ctx = "SINCE LAST TIME:\n" + head + "\n".join(self.pending_context) + "\n\n"
            self.pending_context = []
            self._context_dropped = 0
        if deals or _DEAL_ASK_RE.search(text):
            # Ben's decision 4: asked about a deal, Joshua always assesses — with the facts
            ctx += "DEALS AT THE TABLE (the runner's ledger, ground truth): " + self._deal_facts() + " " + DEAL_KINDS_TEXT + "\n\n"
        prompt = (f"{ctx}THE HUMAN AT YOUR SEAT ASKS: {text}\n\n"
                  "Answer them directly (1-4 sentences, plain text). Ground it in the "
                  "most recent board state you were shown; if it needs something you "
                  "have not seen, say so rather than guess.")
        self._stream_write(f"\n[{self._clock.label(turn)} · you] {text}\n")
        answer, meta = self.brain.decide(prompt, self.timeout)
        reply = (meta.get("raw") or "").strip()
        self._stream_write(f"[{self._clock.label(turn)} · advisor] "
                           + (reply or "(no answer — the call timed out or failed; ask again)")
                           + "\n")
        self._record("ask", {"turn": self._last_turn, "text": text, "answer": reply,
                             "latency_s": meta.get("latency_s")})

    # ---- table deals (plan §11, 2026-09-16) -----------------------------------------
    # The relay: a parsed offer becomes a `deal-offer` note in the seat's mailbox;
    # the seat's `deal` answer (game.jsonl, lane A1) and the voice runner's ledger
    # (logs/deals.jsonl, lane A2) come back as one panel line each. Counters are
    # answered through logs/control/deal/<ts>-accept|refuse.json (the voice runner
    # strikes the deal). Joshua never answers a deal message; he may assess a
    # struck or broken deal in one colour line, every time (Ben, game 50: "critical state"), and when asked.

    @staticmethod
    def _size_of(path: Path) -> int:
        try:
            return os.stat(path).st_size
        except OSError:
            return 0

    def _turn_now(self):
        """The table's current turn: the snapshot's, else the last feed turn, else None."""
        t = self._clock.last.get("turn") if isinstance(self._clock.last, dict) else None
        if isinstance(t, int) and not isinstance(t, bool):
            return t
        return self._last_turn if isinstance(self._last_turn, int) else None

    def _deal_name(self, seat) -> str:
        try:
            return self._deal_names.get(int(seat)) or f"seat {seat}"
        except (TypeError, ValueError):
            return f"seat {seat}"

    def _seat_dead(self, seat: int) -> bool:
        seats = self._clock.last.get("seats") if isinstance(self._clock.last, dict) else None
        for s in seats or []:
            if isinstance(s, dict) and s.get("seat") == seat:
                return bool(s.get("eliminated"))
        return False

    def _panel(self, tag: str, body: str, turn=None) -> None:
        """One deal line, `[<clock> · <tag>] <body>`, at most DEAL_PANEL_MAX chars."""
        turn = self._turn_now() if turn is None else turn
        head = f"[{self._clock.label(turn if turn is not None else '?')} · {tag}] "
        room = DEAL_PANEL_MAX - len(head)
        if len(body) > room:
            body = body[:max(0, room - 1)].rstrip() + "…"
        self._stream_write(f"\n{head}{body}\n")

    @staticmethod
    def _write_atomic(path: Path, body: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(body))
        os.replace(tmp, path)

    def _handle_deal_message(self, d: dict, text: str) -> None:
        seat, action, words = int(d["to"]), d.get("action"), d.get("words") or text
        name = self._deal_name(seat)
        turn = self._turn_now()
        if action in ("accept", "refuse"):
            self._answer_counter(seat, action)
            return
        deal = dict(d.get("deal") or {"kind": "truce", "rounds": 1})
        if seat == 0:
            self._panel("table", "you can't deal with yourself — name a seat (@urza, @giada…)", turn)
            self._record("deal_rejected", {"turn": turn, "text": text, "why": "self"})
            return
        if self._seat_dead(seat):
            self._panel("table", f"{name} is out of the game — no deal", turn)
            self._record("deal_rejected", {"turn": turn, "text": text, "why": "dead", "seat": seat})
            return
        if action in ("invite", "talk"):
            self._relay_words(seat, name, action, words, turn)
            return
        pending = [o for o in self._offers.values()
                   if o["seat"] == seat and o["status"] in ("open", "countered") and o["turn"] == turn]
        if pending:
            self._panel("table", f"you already offered {name} a deal this turn — wait for the answer", turn)
            self._record("deal_rejected", {"turn": turn, "text": text, "why": "duplicate", "seat": seat})
            return
        if "until_turn" in deal and turn is not None and deal["until_turn"] <= turn:
            self._panel("table", f"turn {deal['until_turn']} is not ahead of us — say \"until turn {turn + 2}\" or \"2 turns\"", turn)
            self._record("deal_rejected", {"turn": turn, "text": text, "why": "until_turn_past", "seat": seat})
            return
        ts_ms = int(time.time() * 1000)
        offer_id = f"{ts_ms}-0-{seat}"
        note = {"kind": "deal-offer", "from": 0, "to": seat, "deal": deal, "offer_id": offer_id,
                "text": words, "turn": turn}
        try:
            self._write_atomic(self._base / f"seat-{seat}" / "notes" / f"{ts_ms}-deal-offer.json", note)
        except OSError as e:
            self._panel("table", f"could not reach {name}'s mailbox ({e.__class__.__name__}) — offer not sent", turn)
            return
        self._offers[offer_id] = {"seat": seat, "who": name, "turn": turn, "deal": deal, "offered": dict(deal), "text": words,
                                  "status": "open", "counter": None, "until_turn": deal.get("until_turn"),
                                  "ts": time.time(), "nudged": False}
        self._panel(f"you → {name}", f"{deal_terms_text(deal)}: \"{words}\"", turn)
        self._record("deal", {"event": "offer", "offer_id": offer_id, "seat": seat, "turn": turn, "deal": deal, "text": words})

    def _relay_words(self, seat: int, name: str, action: str, words: str, turn) -> None:
        """Game 54: words to a seat that are not an offer. `invite` -> a deal-invite note (the seat may propose on its
        next main window, its cooldown lifted); `talk` -> a table-talk note (the seat's brain hears it and may answer
        with a say). Relayed as the player's own words, Executive or not; Joshua stays out of it."""
        ts_ms = int(time.time() * 1000)
        kind = "deal-invite" if action == "invite" else "table-talk"
        note = {"kind": kind, "from": 0, "to": seat, "text": words[:200], "turn": turn}
        try:
            self._write_atomic(self._base / f"seat-{seat}" / "notes" / f"{ts_ms}-{kind}.json", note)
        except OSError as e:
            self._panel("table", f"could not reach {name}'s mailbox ({e.__class__.__name__}) — not sent", turn)
            return
        if action == "invite":
            self._panel(f"you → {name}", f"make me an offer: \"{words}\"", turn)
        else:
            self._panel(f"you → {name}", f"\"{words}\"", turn)
        self._record("deal", {"event": action, "seat": seat, "turn": turn, "text": words})

    def _answer_counter(self, seat: int, action: str) -> None:
        """`@urza accept` / `@urza no` on a pending counter -> logs/control/deal/<ts>-accept|refuse.json
        {"offer_id", "counter"}; the voice runner strikes or closes the deal (lane A2)."""
        name = self._deal_name(seat)
        turn = self._turn_now()
        open_ = [(oid, o) for oid, o in self._offers.items() if o["seat"] == seat and o["status"] in ("countered", "proposed")]
        if not open_:
            self._panel("table", f"no counter or offer from {name} is pending", turn)
            return
        oid, off = open_[-1]
        proposal = off["status"] == "proposed"
        body = {"offer_id": oid, "counter": off["counter"] or off["deal"]}
        try:
            self._write_atomic(self._deal_control / f"{int(time.time() * 1000)}-{action}.json", body)
        except OSError as e:
            self._panel("table", f"could not record your answer ({e.__class__.__name__}) — try again", turn)
            return
        what = "offer" if proposal else "counter"
        off["status"] = f"{what}-accepted" if action == "accept" else f"{what}-refused"
        self._question_drop(oid)
        if action == "accept":
            off["deal"] = dict(off["counter"] or off["deal"])
            off["until_turn"] = off["deal"].get("until_turn")
            self._panel(f"you → {name}", f"accept the {what}: {deal_terms_text(off['deal'])}", turn)
        else:
            self._panel(f"you → {name}", f"refuse the {what}", turn)
        self._record("deal", {"event": f"{what}-{action}", "offer_id": oid, "seat": seat, "turn": turn, "counter": off["counter"] or off["deal"]})

    def _tail_jsonl(self, path: Path, attr: str) -> list[dict]:
        """New complete JSON lines since the cursor in `attr`; a shrunken file (arena-stop
        archived it) restarts the cursor; a line caught mid-write waits for the next poll."""
        pos = getattr(self, attr, 0)
        size = self._size_of(path)
        if size < pos:
            pos = 0
        if size == pos:
            return []
        try:
            with path.open("rb") as f:
                f.seek(pos)
                data = f.read()
        except OSError:
            return []
        end = data.rfind(b"\n")
        if end < 0:
            return []
        setattr(self, attr, pos + end + 1)
        out = []
        for raw in data[:end].splitlines():
            try:
                r = json.loads(raw)
            except ValueError:
                continue
            if isinstance(r, dict):
                out.append(r)
        return out

    def _deal_tick(self) -> None:
        """Answers and ledger events into panel lines; a counter unanswered by the end
        of its turn lapses. Called every poll, pause or not — a deal is the player's own request."""
        for r in self._tail_jsonl(self._log_dir / "game.jsonl", "_game_pos"):
            deal = r.get("deal")
            if isinstance(deal, dict) and (r.get("type") == "DEAL" or "offer_id" in deal):
                self._on_deal_record(r, deal)
        for r in self._tail_jsonl(self._ledger, "_ledger_pos"):
            self._on_ledger_record(r)
        if isinstance(self._clock.last, dict) and self._clock.last.get("gameOver"):
            self._clear_questions()
        now = self._turn_now()
        if now is None:
            return
        for oid, off in self._offers.items():
            if off["status"] == "open" and not off.get("nudged") and time.time() - float(off.get("ts") or time.time()) > OFFER_NUDGE_S:
                off["nudged"] = True                                     # game 50: a seat answers at its next window, which may be its own turn
                self._panel("table", f"{off['who']} hasn't had a decision yet — the answer comes at the next window", now)
            if off["status"] in ("countered", "proposed") and isinstance(off.get("counter_turn"), int) and off["counter_turn"] < now:
                what = "offer" if off["status"] == "proposed" else "counter"
                off["status"] = f"{what}-lapsed"
                self._question_drop(oid)
                self._panel("table", f"{off['who']}'s {what} lapsed", now)
                self._record("deal", {"event": f"{what}-lapsed", "offer_id": oid, "seat": off["seat"], "turn": now})

    def _on_deal_record(self, r: dict, deal: dict) -> None:
        """A seat's `deal` answer from game.jsonl (lane A1): accept / refuse / counter."""
        seat, turn, oid = r.get("seat"), r.get("turn"), deal.get("offer_id")
        terms = deal.get("terms") if isinstance(deal.get("terms"), dict) else {}
        counter = deal.get("counter") if isinstance(deal.get("counter"), dict) else None
        if deal.get("propose"):
            self._on_seat_offer(r, deal, seat, turn, oid, terms)
            return
        if seat == 0:
            # Executive (Ben's decision 5): the advisor answered a seat's offer on the player's behalf
            other = self._deal_name(deal.get("with"))
            kind = str((counter or terms).get("kind") or "truce")
            if counter:
                body = f"counter {other}: {deal_terms_text(counter)}"
            elif deal.get("accept"):
                body = f"accept {other}'s {kind}"
            else:
                body = f"refuse {other}'s {kind}"
            self._panel("you (Executive)", body, turn)
            self._record("deal", {"event": "executive-answer", "offer_id": oid, "with": deal.get("with"), "turn": turn, "accept": bool(deal.get("accept")), "counter": counter})
            return
        off = self._offers.get(oid)
        if off is None and deal.get("with") != 0:
            return                                  # seat-to-seat: not the player's business
        if (oid, "answer") in self._deal_seen:
            return
        self._deal_seen.add((oid, "answer"))
        name = off["who"] if off else self._deal_name(seat)
        if deal.get("accept"):
            src = dict(off["deal"] if off else {})
            src.update(terms)
            body = "accepts: " + deal_terms_text(src, name)
            if off is not None:
                off["status"] = "accepted"
                off["until_turn"] = src.get("until_turn")
                off["deal"] = src
        elif counter:
            handle = self._deal_handles.get(seat, str(seat))
            body = f"counters: {deal_terms_text(counter)} — type \"@{handle} accept\" or \"@{handle} no\""
            if off is not None:
                off["status"] = "countered"
                off["counter"] = dict(counter)
                off["counter_turn"] = turn if isinstance(turn, int) else self._turn_now()
        else:
            body = "refuses"
            if off is not None:
                off["status"] = "refused"
        self._panel(name, body, turn)
        self._record("deal", {"event": "answer", "offer_id": oid, "seat": seat, "turn": turn,
                              "accept": bool(deal.get("accept")), "counter": counter, "terms": terms})

    # ---- the offer pane's files: one per open offer to the player, gone with the offer ------------------
    def _question_write(self, oid: str, off: dict, assessment: str | None = None) -> None:
        body = {"offer_id": oid, "seat": off["seat"], "who": off["who"], "handle": self._deal_handles.get(off["seat"], str(off["seat"])),
                "terms": deal_terms_text(off["deal"]), "text": off.get("text") or "", "turn": off["turn"],
                "lapses_after_turn": off.get("counter_turn"), "assessment": assessment, "ts": off.get("ts") or time.time()}
        try:
            self._write_atomic(self._questions / f"{oid}.json", body)
        except OSError as e:
            self._say(f"[advisor] offer pane file not written ({e.__class__.__name__})")

    def _question_drop(self, oid) -> None:
        try:
            os.remove(self._questions / f"{oid}.json")
        except OSError:
            pass

    def _clear_questions(self) -> None:
        try:
            for p in self._questions.glob("*.json"):
                p.unlink()
        except OSError:
            pass

    def _on_seat_offer(self, r: dict, deal: dict, seat, turn, oid, terms: dict) -> None:
        """A seat's OWN offer (Ben, 2026-09-16), from its DEAL record. To another seat: one panel line, the table's
        business. To the player: the panel line with the typed answer, remembered like a counter (`@urza accept` /
        `@urza no` -> the control file the voice runner strikes or refuses from), and Joshua's assessment at once —
        it is state, not colour. Executive holding seat 0 answers it itself through the seat-0 runner."""
        try:
            seat, other = int(seat), int(deal.get("with"))
        except (TypeError, ValueError):
            return
        if not isinstance(oid, str) or (oid, "offer") in self._deal_seen:
            return
        self._deal_seen.add((oid, "offer"))
        name = self._deal_name(seat)
        terms = dict(terms or {"kind": "truce", "rounds": 1})
        text = str(deal.get("text") or "").strip()
        said = f' — "{text[:30]}"' if text else ""                                     # the panel line is capped; the words are a flavour
        if other != 0:
            self._panel("table", f"{name} offers {self._deal_name(other)} {deal_terms_text(terms)}{said}", turn)
            self._record("deal", {"event": "seat-offer", "offer_id": oid, "seat": seat, "to": other, "turn": turn, "deal": terms})
            return
        if self._executive_wanted():
            self._panel(name, f"offers you {deal_terms_text(terms)}{said} — the Executive answers for you", turn)
            self._record("deal", {"event": "seat-offer", "offer_id": oid, "seat": seat, "to": 0, "turn": turn, "deal": terms, "executive": True})
            return
        handle = self._deal_handles.get(seat, str(seat))
        t = turn if isinstance(turn, int) else self._turn_now()
        self._offers[oid] = {"seat": seat, "who": name, "from": seat, "turn": t, "deal": terms, "offered": dict(terms), "text": text,
                             "status": "proposed", "counter": None, "counter_turn": (t + 1) if isinstance(t, int) else None,
                             "until_turn": terms.get("until_turn"), "ts": time.time(), "nudged": True}
        self._panel(name, f"offers you {deal_terms_text(terms)}{said} (@{handle} accept/no)", turn)
        self._record("deal", {"event": "seat-offer", "offer_id": oid, "seat": seat, "to": 0, "turn": turn, "deal": terms, "text": text})
        self._question_write(oid, self._offers[oid])
        self._assess_deal(f"{name} OFFERS you {deal_terms_text(terms)} (unanswered — you accept or refuse in the chat)", turn, offer_id=oid)

    def _on_ledger_record(self, r: dict) -> None:
        """The voice runner's ledger (lane A2): struck / refused / expired / lapsed / broken
        between the player and a seat. Answers the DEAL record already showed are not repeated."""
        ev = str(r.get("event") or "")
        between = r.get("between") or []
        try:
            between = [int(b) for b in between]
        except (TypeError, ValueError):
            return
        if 0 not in between or len(between) != 2:
            return
        other = between[0] if between[1] == 0 else between[1]
        oid, turn = r.get("offer_id"), r.get("turn")
        off = self._offers.get(oid) if oid else None
        name = off["who"] if off else self._deal_name(other)
        deal = r.get("deal") if isinstance(r.get("deal"), dict) else {}
        kind = str(deal.get("kind") or (off or {}).get("deal", {}).get("kind") or "truce")
        key = (oid or f"{other}:{turn}", ev)
        if key in self._deal_seen:
            return
        self._deal_seen.add(key)
        if ev == "struck":
            until = deal.get("until_turn")
            if off is not None:
                off["status"] = "struck"
                already = off.get("until_turn")
                off["until_turn"] = until if until is not None else already
                if (oid, "answer") in self._deal_seen and already is not None:
                    pass                            # the accept line already said when it ends
                elif until is not None:
                    self._panel("table", f"your {kind} with {name} is on until turn {until} ends", turn)
                else:
                    self._panel("table", f"your {kind} with {name} is on", turn)
            else:
                self._panel("table", f"{kind} with {name} struck" + (f" — until turn {until} ends" if until is not None else ""), turn)
            self._assess_deal(f"a {kind} between you and {name} was STRUCK" + (f" (until turn {until} ends)" if until is not None else ""), turn)
        elif ev == "broken":
            by, how = r.get("by"), str(r.get("how") or "attack")
            verb = "targeted" if how == "target" else "attacked"
            if by == 0:
                self._panel("table", f"you broke your {kind} with {name}", turn)
            else:
                self._panel("table", f"{name} broke your {kind} ({verb} you)", turn)
            if off is not None:
                off["status"] = "broken"
            self._assess_deal(f"your {kind} with {name} was BROKEN by {'you' if by == 0 else name} ({verb})", turn)
        elif ev == "lapsed":
            self._panel("table", f"your {kind} with {name} has ended", turn)
            if off is not None:
                off["status"] = "lapsed"
        elif ev == "expired":
            if off is None or off.get("from") is None:
                self._panel("table", f"{name} did not answer", turn)          # a seat's own offer lapsing was the tick's line
            if off is not None and off["status"] == "open":
                off["status"] = "expired"
        elif ev == "refused":
            if (oid, "answer") not in self._deal_seen and r.get("by") != 0:     # the player's own refusal was echoed as typed
                self._panel(name, "refuses", turn)
                if off is not None:
                    off["status"] = "refused"
        elif ev == "counter" and (oid, "answer") not in self._deal_seen and deal:
            self._deal_seen.add((oid, "answer"))
            handle = self._deal_handles.get(other, str(other))
            self._panel(name, f"counters: {deal_terms_text(deal)} — type \"@{handle} accept\" or \"@{handle} no\"", turn)
            if off is not None:
                off["status"], off["counter"] = "countered", dict(deal)
                off["counter_turn"] = turn if isinstance(turn, int) else self._turn_now()
        self._record("deal", {"event": f"ledger-{ev}", "offer_id": oid, "seat": other, "turn": turn, "by": r.get("by"), "deal": deal})

    def _deal_facts(self) -> str:
        if not self._offers:
            return "no deals offered or struck so far."
        parts = []
        for oid, off in list(self._offers.items())[-6:]:
            if off.get("from") is not None:
                s = f"{off['who']}'s offer of {deal_terms_text(off.get('offered') or off['deal'])} (turn {off['turn']}): {off['status']}"
            else:
                s = f"{deal_terms_text(off.get('offered') or off['deal'])} with {off['who']} (offered turn {off['turn']}): {off['status']}"
            if off.get("counter") and off["status"] == "countered":
                s += f", their counter {deal_terms_text(off['counter'])}"
            if off.get("until_turn") is not None and off["status"] in ("accepted", "struck"):
                s += f", until turn {off['until_turn']} ends"
            parts.append(s)
        return "; ".join(parts) + "."

    def _board_brief(self) -> str:
        seats = self._clock.last.get("seats") if isinstance(self._clock.last, dict) else None
        out = []
        for s in seats or []:
            if not isinstance(s, dict) or s.get("seat") is None:
                continue
            who = self._deal_name(s["seat"]) if s.get("seat") != 0 else "you"
            out.append(f"{who}: life {s.get('life')}, hand {s.get('handSize')}, {len(s.get('battlefield') or [])} permanents"
                       + (", ELIMINATED" if s.get("eliminated") else ""))
        return "; ".join(out)

    def _assess_deal(self, facts: str, turn, offer_id: str | None = None) -> None:
        """On a deal the player struck or had broken, Joshua adds ONE assessment line through the
        colour path (a `color` record the voice runner speaks) — every time (Ben, game 50: the
        dice made the advisor absent at the moment the player acts on his read; DEAL_COLOR_P is
        1.0 and kept only as the knob). Never for the player's own offer — that is relayed, not answered;
        a SEAT's offer to the player is assessed as it arrives (_on_seat_offer): the player must decide."""
        if DEAL_COLOR_P < 1.0 and self.deal_rng.random() >= DEAL_COLOR_P:
            return
        board = self._board_brief()
        prompt = (f"TABLE DEAL: {facts}. Deals at the table: {self._deal_facts()} {DEAL_KINDS_TEXT}"
                  + (f" BOARD: {board}." if board else "")
                  + "\n\nOne sentence: was this a good deal for the human, and what to watch (plain text).")
        answer, meta = self.brain.decide(prompt, min(self.timeout, 45.0))
        text, quip = split_quip((meta.get("raw") or "").strip(), log=self._say)
        text, _bark = split_bark(text, log=self._say)   # a bark never rides an assessment
        if not text:
            return
        turn = self._turn_now() if turn is None else turn
        self._stream_write(f"\n[{self._clock.label(turn if turn is not None else '?')} · color] {text}\n")
        self._record("color", {"seq": None, "turn": turn, "owner": None, "text": text, "deal": facts,
                               "latency_s": meta.get("latency_s")})
        if quip:
            self._record("quip", {"id": quip, "turn": turn, "with": "color", "seq": None})
        if offer_id and offer_id in self._offers and (self._questions / f"{offer_id}.json").exists():
            self._question_write(offer_id, self._offers[offer_id], assessment=text)   # the pane shows Joshua's read

    # ---- main loop ---------------------------------------------------------------

    def run(self) -> None:
        self._say(f"[advisor] up — deck={self.brain.deck} model={self.brain.model} "
                  f"watching {self.inbox}")
        self.brain.ensure_session()  # pre-warm: dossier loads before turn 0
        self._stream_write("[advisor] session warm — watching your table.\n")
        enabled = True
        catch_up = False
        # item 12: liveness for the dashboard, from a daemon thread so it beats
        # through blocking model calls too
        import threading
        hb = self.inbox.parent / "heartbeat"

        def beat():
            while True:
                try:
                    hb.touch()
                except OSError:
                    pass
                time.sleep(5.0)
        threading.Thread(target=beat, name="advisor-heartbeat", daemon=True).start()
        while True:
            self._apply_control()
            if self._executive_tick():
                continue          # a seat-0 decision was answered; look again at once
            self._maybe_rotate()
            self._clock.observe()   # the turn's active seat, before its first line is written
            self._handle_asks()   # questions first, pause or not (see docstring)
            self._deal_tick()     # the seats' deal answers and the ledger, into the panel
            # In-game on/off toggle (plan 13b): the Advisor tab's button writes
            # logs/control/advisor.json; disabled = no scanning, no model calls
            # (the engine's one-way feed keeps writing, harmlessly). arena-stop
            # clears control/, so every session starts enabled.
            want = self._toggle_enabled()
            if want != enabled:
                enabled = want
                if enabled:
                    self._say("[advisor] resumed by toggle")
                    catch_up = True   # item 5: consume the backlog quietly first
                else:
                    self._say("[advisor] paused by toggle")
                    self._stream_write("\n[advisor] paused — click the button to bring me back.\n")
            if not enabled:
                time.sleep(POLL_S)
                continue
            items = self._scan()
            if catch_up:
                n = self._process(items, quiet=True)
                catch_up = False
                self._stream_write(f"\n[advisor] back — caught up on {n} events while "
                                   f"paused; resuming counsel from here.\n")
                continue
            if not items:
                time.sleep(POLL_S)
                continue
            self._process(items)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True, help="the HUMAN's deck slug")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--base", default=str(Path(__file__).resolve().parent.parent / "mailbox"))
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()
    model = args.model
    if backends.parse_model(model)[0] != "claude":
        # Launch-flag leg of the Claude-only guard (plan F-10): fall back to
        # the default Claude model rather than exiting — the advisor never
        # dies over a model string.
        print(f"[advisor] backend model {model} is not supported for the "
              f"advisor in v1 — falling back to opus", flush=True)
        model = "opus"
    AdvisorRunner(args.deck, Path(args.base), model, args.effort,
                  args.timeout).run()


if __name__ == "__main__":
    main()

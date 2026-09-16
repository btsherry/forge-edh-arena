"""The voice runner's queue and its policy — SchedulerMixin, mixed into VoiceRunner
(runner/voice_runner.py), which supplies the state, say/record, the renderer and
the table. Here: enqueue and eviction by class, the next-item pick and the rate
limit, the duty-cycle governor, the seat guards behind maybe_bark, the named-wording
swaps, the interaction chains' reply planning (after_spoken, proposals), the patter
clock with its silence floor, the chatter dial, and the constants these use. Split
out of voice_runner.py on 2026-09-14 (voicework2 hardening plan, Phase 0a) with no
behaviour change; voice_runner re-exports every public name here. This module never
imports voice_runner."""
from __future__ import annotations

import json
import os

from chains import plan_reply
from voice.table import CARD_LIB, CARD_REACTIONS, CARD_SWAP, TABLE_LIB, hand_pid, life_pid

PRIORITY = {"game_over": 0, "human_out": 0, "startup": 1, "ask": 2, "advice": 3, "quip": 4, "event": 5, "color": 6, "your_move": 7, "bark": 8}
# ("bark": 8 is the fallback for a bare enqueue("bark", ...) with neither prio nor chain — every runner
#  path passes one (maybe_bark: BARK_PRIORITY; the chain hops: CHAIN_HOP_PRIORITY), the test doubles
#  do not; D3 of the 2026-09-14 plan called it unreachable, but the suite reaches it, so it stays.)
# A reply inside an exchange must not be separated from the line it answers: game 44
# (20:43) Joshua's "your move" cut between Harry's jab and Lily's "shut it", so the
# retort landed on Joshua. Hops rank just below advice; if advice or a question
# does interrupt, the pending hop is dropped rather than played orphaned.
CHAIN_HOP_PRIORITY = 3.5
# ONE classification (plan C2, 2026-09-14): a bark is a CHAIN link (a reply inside an
# exchange), ANCHORED to something that happened at the table (a board event, a named
# card, a seat's own procedure, its turn opener, the seat brain's own `say` intent — §4.4:
# "spoken as an anchored line (source brain)") or OPTIONAL (the advisor's afterthoughts,
# the patter clock). Eviction (enqueue), the governor (maybe_bark, after_spoken), the seat
# guard and scripts/arena-hygiene.py's anchored share all read classify()/classify_source();
# before this each kept its own tuple and Ben's steering figure measured something else.
ANCHORED_SOURCES = ("event", "card", "procedural", "opener", "brain")
OPTIONAL_SOURCES = ("recap", "advice", "patter", "chain")     # the complement — kept as a name for the re-export; the rule is classify_source
# The bark ladder (round 31, 2026-09-10): a reaction to something that just happened
# on the board plays ahead of Joshua's colour and the "your move" cue; the advisor's
# tagged afterthoughts and the patter clock come last. Chain hops keep 3.5 (game 44).
# Two optional tiers stay: the optional eviction rule keeps lower-prio peers, so a
# pending recap outlives fresh filler (8.0 < 8.5). The opener's old 5.8 folded into the
# anchored tier (C2): an anchored bark evicts every non-follow-on whatever its prio, and
# no follow-on is ever an opener, so the order between the two never mattered.
ANCHORED_PRIO, RECAP_PRIO, PATTER_PRIO = 5.5, 8.0, 8.5
BARK_PRIORITY = {"chain": CHAIN_HOP_PRIORITY, **{s: ANCHORED_PRIO for s in ANCHORED_SOURCES},
                 "recap": RECAP_PRIO, "advice": RECAP_PRIO, "patter": PATTER_PRIO}


def classify_source(source) -> str:
    """"chain" | "anchored" | "optional" from a bark's source (what a `spoke` record carries)."""
    if source == "chain":
        return "chain"
    return "anchored" if source in ANCHORED_SOURCES else "optional"


def classify(item: dict) -> str:
    """The same three classes from a queue item: a chain link is "chain"; else by its
    priority (below the recap tier = anchored), falling back to its source or kind when
    the item carries no prio (test doubles, a bare event item)."""
    if item.get("chain"):
        return "chain"
    prio = item.get("prio")
    if prio is None:
        return classify_source(item.get("source") or item.get("kind"))
    return "anchored" if prio < BARK_PRIORITY["recap"] else "optional"
# The duty-cycle governor (round 31): five Game Knights tapes run ~190 words/min; game 45
# at rowdy measured 7.8 lines/min, a 31 % speaking duty — the right density with the wrong
# mix (53 % banter, 38 % filler, 4 % about the game). The dial now sets a talk BUDGET —
# the fraction of the last minute someone may be speaking — and every optional line is
# rolled against the headroom left in it; lines anchored to a board event keep priority.
DUTY_BASE = 0.18          # at chatter 1.0; quiet .09, lively .27, rowdy .36
DUTY_WINDOW_S = 60.0
DUTY_HUMAN_MULT = 0.6     # on the human's turn the table aims lower (Ben, game 44: minimal on my turn; game 48: silences are the bigger issue)
# The silence floor (Ben, game 48: "too many long pauses"): nothing has played for this long -> the patter clock speaks
# its best candidate regardless of dice and budget. Divided by the chatter dial.
SILENCE_FLOOR_S = {"ai": 12.0, "human": 24.0}
# Lines that are QUESTIONS get an answer with certainty and are never put to the human (who cannot answer);
# PROPOSALS ("we all hit Selvala") draw a yea or nay from every other player, then the subject may retort.
QUESTION_LINES = {"deal", "whats-your-life", "cards-in-hand", "mull-screw"}
QUESTION_PREFIXES = ("deal-",)
PROPOSAL_LINES = {"kill-that", "youre-the-threat", "archenemy", "someone-wins"}
PROPOSAL_PREFIXES = ("hit-", "threat-")
PROPOSAL_P, PROPOSAL_TARGET_P = 0.85, 0.5
PROPOSAL_REPLIES = ("agree", "disagree")
PROPOSAL_TARGET_REPLIES = ("im-not-the-threat", "clapback", "you-wish", "laugh")
OPTIONAL_FLOOR = 0.15     # an optional line past the taper: nearly silent; an anchored line keeps goal/duty (half at twice the goal), scaled by a quiet dial
GOVERNOR_TAPER_AT = 1.5   # an optional line tapers from 1.0 at the goal to OPTIONAL_FLOOR at this multiple of it (a mean, not a ceiling)
# game 46 (turns 8-13): "come on, land" four times in seven minutes — these lines are said by a seat at most once in RECENT_S
RARE_REPEATS = {"come-on-land", "thinking", "holding-mana", "tapped-out", "mana-up", "land-go", "early-game", "long-game", "loop", "looping"}
# A line a seat says because it just ACTED skips the per-seat guard (game 48: Harry heckled Giada's mulligan
# and one second later his own "seven, keeping" was silenced by his guard). Reactions, patter and banter keep it.
OWN_ACTION_LINES = {"keep-seven", "mull-to-six", "mull-to-five", "mull-to-four", "my-turn", "untap-draw", "early-game", "come-on-land",
                    "land-go", "pass", "mana-up", "tapped-out", "cast-creature", "cast-artifact", "cast-enchantment", "cast-instant",
                    "cast-sorcery", "cast-planeswalker", "cast-big", "in-response", "poke", "attack-you", "big-swing", "landed-hit", "game-changer",
                    "commander-cast", "engine-online", "looping", "counter", "removal", "sweep", "kill", "win", "eliminated"}
# ("landed-hit" is the hitter's own line — events.py speaks it for the seat that hit the human — so its own
#  "big-swing" two seconds earlier must not hold it as anchored-after-anchored; the guard's class rule (A5) is symmetric.)
LIFE_FOLLOWUP = {"that-hurt": 0.6, "take-it": 0.5, "low-life": 0.5}          # the speaker announces its total right after
STATE_ANSWERS = {"whats-your-life": "life", "low-life-jab": "life", "cards-in-hand": "hand", "empty-hand": "hand"}
ADDRESS_SWAP = {"kill-that": ("hit", "target"), "archenemy": ("hit", "target"), "youre-the-threat": ("threat", "target"),
                "deal": ("deal", "target"), "why-me": ("leave-me", "aggressor")}
# Table deals (plan 2026-09-16, §11 — the contract). The voice runner OWNS the deal ledger: the live map
# `_deals: (a, b) -> {"kind", "until_turn", "struck", "offer_id"}` (both directions, checkpointed), the
# append-only logs/deals.jsonl, and the notes files that tell a seat's brain what was agreed
# (mailbox/seat-<n>/notes/<ts_ms>-deal-struck|broken|lapsed.json — the seat runner reads and drops them).
# A deal is struck (i) by a seat brain's DEAL record in game.jsonl accepting the player's offer, (ii) by the
# player's control file accepting a seat's counter, (iii) by the voice chain deal -> promise/take-the-deal
# between two AI seats (the old path: kind truce, one round). It lapses at the roll to until_turn + 1;
# an attack across a truce/alliance or a spell/ability targeting the other party across a no-target/alliance
# breaks it. The runner never enforces a deal — it tells the brains, records what happens, lets the table react.
DEAL_KINDS = ("truce", "no-target", "alliance")
DEAL_ATTACK_KINDS = frozenset({"truce", "alliance"})          # broken by combat (an attack event across it)
DEAL_TARGET_KINDS = frozenset({"no-target", "alliance"})      # broken by a spell or ability targeting the other party
DEAL_MAX_ROUNDS = 3                                           # §2: "for one turn" up to three of the seat's own turns
DEAL_TURNS = 8            # the OLD memory (a truce remembered for two rounds): an int in an old checkpoint upgrades to struck + DEAL_TURNS
DEALS_LEDGER = "deals.jsonl"                                  # logs/deals.jsonl, archived by scripts/arena-stop.sh
DEAL_CONTROL_DIR = "deal"                                     # logs/control/deal/<ts>-accept.json {"offer_id"} — the player accepts a seat's counter (the advisor writes it)
DEAL_NOTE_KINDS = ("deal-struck", "deal-broken", "deal-lapsed")
DEAL_LINES = frozenset({"deal-with-you", "no-deal-with-you", "counter-offer", "deal-over", "you-broke-it", "i-broke-it"})
DEAL_ANSWER_LINE = {"accept": "deal-with-you", "refuse": "no-deal-with-you", "counter": "counter-offer"}      # the seat, to the player (table sub-library)
JOSHUA_DEAL_LINE = {"accept": "joshua-deal-yes", "refuse": "joshua-deal-no", "counter": "joshua-deal-counter"}   # Executive: Joshua is the player at the table
DEAL_OVER_P = 0.5         # a party remarks that the deal has run out
I_BROKE_IT_P = 0.6        # a seat that breaks its own deal by attacking owns it ("I know what I promised. I lied.")
CHAIN_P_OVERRIDE = {"deal-with-you": 0.35}                    # §7: a bystander's jab at the seat that dealt, at 0.35 instead of the table's first hop
LONG_GAME_TURN = 14
LETHAL_POWER = 15
# The floor's pool (plan 4.2, 2026-09-14): the patter candidates ANCHORED to the board — the numbers
# (a life or hand question, the low-life and empty-hand jabs), the threat calls, a slow seat, the big
# board, the long game, "pass already" at the active seat, a deal — speak ahead of filler when the
# silence floor fires; an empty or filler-only pool spends a non-verbal atom instead (4.5), when the
# runner has them. An atom re-arms the floor at its full length and at most FLOOR_ATOM_MAX_RUN play in a
# row: _said_at is table-wide per id and PATTER_REPEAT_S is 300 s, so ~7 lines exhaust the filler pool —
# a sigh every 0.6 × floor until the board re-seeded a candidate was a tic, not presence (critic, 2026-09-14).
# A content line (any spoken line) resets the run.
ANCHORED_PATTER = {"play-faster", "thinking-hard", "youre-the-threat", "whats-your-life", "low-life-jab", "cards-in-hand",
                   "empty-hand", "kill-that", "someone-wins", "board-envy", "long-game", "pass-already", "deal"}
FLOOR_ATOM_MAX_RUN = 2
EXEC_MEMO_S = 1.0         # human_turn() re-reads control/executive.json at most this often (A6; the governor asks several times a step)
IDLE_S = 150.0            # the board unchanged this long (a human away from the keyboard): the patter clock slows to a third
IDLE_SLOWDOWN = 3.0       # Ben (2026-09-11): "a little patter during the human turn, especially if I idle, is okay"
# Mulligans (Ben, 2026-09-11): the seats' keep/mulligan answers land in game.jsonl with the brain's reason;
# the reaction follows the reason — lands/mana -> mull-screw, digging for a piece -> mull-dig, else pity.
MULL_LINE = {1: "mull-to-six", 2: "mull-to-five", 3: "mull-to-four"}
MULL_P = {"own": 1.0, "keep-seven": 0.35, "react": 0.7, "risky": 0.8, "gloat": 0.4}
MULL_SCREW_WORDS = ("land", "mana", "colour", "color", "source")
MULL_DIG_WORDS = ("dig", "tutor", "combo", "engine", "piece", "fast mana", "stronger", "better seven", "fish")
RECENT_S = 240.0          # a line said within this window is stale for the patter pick and for replies
PATTER_REPEAT_S = 300.0   # a patter line said by ANY seat within this window is no candidate at all (game 48: "cards in hand" x4)
# BL-53 (game 49: Purphoros's turn 10 ran nine minutes — by minute four every optional id had been said, the floor found
# `pool 0` four times running and the third proposal drew no reply, "already said this turn" ×71): within ONE turn an
# OPTIONAL line (patter, a chain reply, the advisor's afterthoughts) may be said again by the same seat once this long
# has passed since that seat said it; an ANCHORED id (event, procedural, opener, brain, card) keeps the strict per-turn
# rule — a seat narrates "land, go" once a turn whatever the clock. A turn shorter than this behaves exactly as before.
TURN_REPEAT_S = 180.0
# Seat barks, the table-talk design (Ben, 2026-09-10 — "playing with the AI should
# feel like sitting at the table with people"): every turn boundary has ONE owner.
# The recap of an AI seat's turn belongs to that seat (its retrospective line,
# authored by the advisor, rolled at barks_p); the recap of the human's turn
# belongs to Joshua's colour line (its own dice) plus, optionally, one seat's
# reaction. Instant reactions come from the snapshot's public event ring — an
# attack of barks_swing power, a hit of barks_hit, a countered spell — with no
# LLM in the loop. The numbers are voices/tuning.json's (2026-09-16). Openers ("my turn") fire mechanically at a seat's turn
# start, rarely. A (seat, line) already said this turn is never said again — an anchored line for the whole
# turn, an optional one for TURN_REPEAT_S (BL-53: a nine-minute loop turn must not starve the table).


CHATTER_LEVELS = {"quiet": 0.5, "normal": 1.0, "lively": 1.5, "rowdy": 2.0}


def chatter_level(raw: str | None) -> float:
    """ARENA_CHATTER — one master dial for how much the table talks (Ben,
    2026-09-10: "instead of trying to bake all of this just right anecdotally").
    A name (quiet .5 / normal 1 / lively 1.5 / rowdy 2) or a number; 1 = the
    numbers in voices/tuning.json as written. What the dial scales today
    (VoiceRunner.apply_chatter, round 31): the PACE — the gap between lines
    (min_gap_s / k, floor 3 s), the seat guard (barks_cooldown_s / k, floor
    3 s), the instant-reaction thresholds (barks_swing / k, floor 3 power;
    barks_hit / k, floor 4 damage), the patter clock's gap (patter_gap_s / k,
    floors 2 / 2.5 s), and one more chain hop at lively and above — plus the
    talk BUDGET it derives (DUTY_BASE × k, capped .45), which the governor
    spends at roll time. The probabilities themselves (barks_p, the opener,
    a recap, "your move", the chains' first hop) are NOT pre-scaled any more.
    Advice frequency — model calls — is not chatter and is untouched."""
    v = (raw or "normal").strip().lower()
    if v in CHATTER_LEVELS:
        return CHATTER_LEVELS[v]
    try:
        return max(0.0, min(4.0, float(v)))
    except ValueError:
        return 1.0


def is_question(pid: str) -> bool:
    """A line that asks something of a seat (answered with certainty, never put to the human). The
    "deal-" prefix covers the named offers (deal-urza, deal-azorius); the six deal ids are statements."""
    return pid in QUESTION_LINES or (pid.startswith(QUESTION_PREFIXES) and pid not in DEAL_LINES)


def normalize_deal(v, struck_default=None) -> dict | None:
    """A `_deals` value as the contract's dict, or None for junk. An int (the old shape — the turn the
    truce was struck, remembered for DEAL_TURNS) upgrades to a truce until struck + DEAL_TURNS."""
    if isinstance(v, dict):
        try:
            kind = str(v.get("kind") or "truce")
            struck = int(v.get("struck") if v.get("struck") is not None else (struck_default if struck_default is not None else 0))
            until = int(v.get("until_turn") if v.get("until_turn") is not None else struck + DEAL_TURNS)
        except (TypeError, ValueError):
            return None
        oid = v.get("offer_id")
        return {"kind": kind if kind in DEAL_KINDS else "truce", "until_turn": until, "struck": struck, "offer_id": str(oid) if oid is not None else None}
    try:
        struck = int(v)
    except (TypeError, ValueError):
        return None
    return {"kind": "truce", "until_turn": struck + DEAL_TURNS, "struck": struck, "offer_id": None}


def deal_terms(terms, default_kind: str = "truce") -> dict:
    """The contract's terms — {"kind", "rounds"} | {"kind", "until_turn"} — cleaned: an unknown kind is a
    truce, rounds are clamped to 1..DEAL_MAX_ROUNDS, exactly one duration (until_turn wins when both)."""
    t = terms if isinstance(terms, dict) else {}
    kind = str(t.get("kind") or default_kind)
    out: dict = {"kind": kind if kind in DEAL_KINDS else "truce"}
    if t.get("until_turn") is not None:
        try:
            out["until_turn"] = int(t["until_turn"])
            return out
        except (TypeError, ValueError):
            pass
    try:
        rounds = int(t.get("rounds") or 1)
    except (TypeError, ValueError):
        rounds = 1
    out["rounds"] = max(1, min(DEAL_MAX_ROUNDS, rounds))
    return out


class TurnSaid(dict):
    """The per-turn no-repeat memory (BL-53): (seat, id) -> the clock when the seat last said it this
    turn. To every caller that used the old set it still IS one — `(seat, id) in it` is strict membership
    (the anchored rule), `.add((seat, id))` stamps the clock, iteration yields the pairs (the checkpoint
    writes `sorted(... for s, p in it)`) — and `said()` is the rule itself: an anchored id is said for
    the whole turn, an optional id for TURN_REPEAT_S since that seat said it. `optional` is the set-like
    view chains.plan_reply receives, so chains.py keeps its `(who, reply) in said_this_turn`."""
    __slots__ = ("clock",)

    def __init__(self, clock, seed=()):
        super().__init__()
        self.clock = clock
        if isinstance(seed, dict):
            self.update(seed)
        else:
            now = clock()
            for key in seed:                                     # a plain set (a restored checkpoint, a test): stamped now — the conservative reading
                self[key] = now

    def add(self, key) -> None:
        self[key] = self.clock()

    def said(self, seat, pid: str, optional: bool, now: float | None = None) -> bool:
        t = self.get((seat, pid))
        if t is None:
            return False
        if not optional:
            return True
        return (self.clock() if now is None else now) - t < TURN_REPEAT_S

    @property
    def optional(self) -> "_OptionalSaid":
        return _OptionalSaid(self)


class _OptionalSaid:
    """`(seat, id) in view` applies the optional rule over a TurnSaid — what plan_reply's set-like argument needs."""
    __slots__ = ("_said",)

    def __init__(self, said: TurnSaid):
        self._said = said

    def __contains__(self, key) -> bool:
        seat, pid = key
        return self._said.said(seat, pid, optional=True)


class SchedulerMixin:
    """The queue and its policy; VoiceRunner.__init__ owns every attribute used here."""

    # -- the per-turn no-repeat rule (BL-53)
    def _turn_said(self) -> TurnSaid:
        """The turn's memory as a TurnSaid; a plain set (VoiceRunner.__init__, a restored checkpoint, a
        test that assigned one) is adopted with every entry stamped now."""
        d = self._said_this_turn
        if not isinstance(d, TurnSaid):
            d = self._said_this_turn = TurnSaid(self.clock, d)
        return d

    def said_this_turn(self, seat, pid: str, optional: bool) -> bool:
        """Has `seat` said `pid` this turn, for the purpose of saying it again: always yes for an anchored
        id once said; for an optional id only within TURN_REPEAT_S of the seat saying it."""
        return self._turn_said().said(int(seat), pid, optional)

    def free_to_speak(self, seats: list[int]) -> list[int]:
        """The seats among `seats` outside their own guard (game 47: Bill was asked to
        answer a mulligan one second after his own line and hit the guard); all of them
        when none is free."""
        now = self.clock()
        free = [s for s in seats if now - self._bark_spoken_at.get(int(s), -1e9) >= self.barks_cooldown]
        return free or list(seats)

    def _seat_last_class(self) -> dict:
        """seat -> the guard class of the seat's last spoken line (A5): "anchored" or "optional" —
        a chain reply is banter, so optional. Kept here (after_spoken sees every spoken seat line)
        because speak(), which stamps _bark_spoken_at, lives in the daemon."""
        d = getattr(self, "_last_class", None)
        if d is None:
            d = self._last_class = {}
        return d

    @staticmethod
    def _guard_class(cls: str) -> str:
        return "optional" if cls == "chain" else cls

    # -- the talk budget
    def duty(self, window: float = DUTY_WINDOW_S) -> float:
        """Fraction of the last `window` seconds somebody was speaking."""
        now = self.clock()
        lo = now - window
        self._spoken_log = [(t, sec) for t, sec in self._spoken_log if t + sec > lo]
        return min(1.0, sum(min(sec, t + sec - lo) for t, sec in self._spoken_log) / window) if window > 0 else 0.0

    def human_turn(self) -> bool:
        """The ONE "quieter on your turn" predicate (A6): the active seat is the human's AND
        the Executive is not playing it — game 48 ran 70 seat-0 decisions under the human
        budget (goal 0.14) while Executive held the seat. The budget, the patter gap and
        the silence floor all ask this; executive_on lives on VoiceRunner (control/executive.json)
        and parses the file, so its answer is memoised for EXEC_MEMO_S, dropped when the
        snapshot's turn or active seat changes — the governor asks several times a step."""
        snap = self._last_snapshot
        if snap.get("activeSeat") != self.human_seat:
            return False
        executive = getattr(self, "executive_on", None)
        if not callable(executive):
            return True
        now = self.clock()
        memo = getattr(self, "_exec_memo", None)
        key = (snap.get("turn"), snap.get("activeSeat"))
        if memo is None or memo[1] != key or not (0.0 <= now - memo[0] < EXEC_MEMO_S):
            memo = self._exec_memo = (now, key, bool(executive()))
        return not memo[2]

    def duty_goal(self) -> float:
        return self.duty_target * (self.duty_human if self.human_turn() else 1.0)

    def governor(self, optional: bool) -> float:
        """Multiplier on a line's chance from the table's talk budget — the goal is a MEAN,
        not a ceiling (Ben, 2026-09-14: "rowdy should be rowdy"; the Grower measured the old
        0.15 + 0.85·head factor holding the table at ~60 % of the dial). Below the goal
        every line gets the dial's full boost, 1 + head·(k − 1) at k > 1 (k itself at quiet).
        At and above it an optional line (patter, a banter reply, the advisor's afterthoughts)
        tapers linearly from 1.0 at the goal to OPTIONAL_FLOOR at GOVERNOR_TAPER_AT × the goal,
        while a line anchored to the board keeps max(0.5, goal / duty); both × min(1, k), so
        the quiet dial stays quiet past the goal too (at k = 0.5: 0.5 everywhere below and at
        the goal, 0.2875 / 0.4 at 1.25 × it, 0.075 / 0.333 at 1.5 ×)."""
        goal = self.duty_goal()
        if goal <= 0:
            return 1.0
        d = self.duty()
        k = self.chatter
        if d >= goal:
            # a quiet dial (k < 1) damps this side too, so the curve is continuous at the goal:
            # without min(1, k) quiet went from k below the goal to 1.0 the instant the table crossed it
            if not optional:
                return max(0.5, goal / d) * min(1.0, k)
            over = min(1.0, (d - goal) / ((GOVERNOR_TAPER_AT - 1.0) * goal))   # 0 at the goal, 1 at the taper's end
            return (OPTIONAL_FLOOR + (1.0 - OPTIONAL_FLOOR) * (1.0 - over)) * min(1.0, k)
        head = (goal - d) / goal                                  # 1 in silence, 0 at the goal
        return 1.0 + head * (k - 1.0) if k > 1.0 else k

    # -- queue
    def enqueue(self, kind: str, *, text: str = "", stock: str = "", seq: int | None = None, ttl: float = 25.0,
                library: str = "", seat: int | None = None, ctx: dict | None = None, gap: float | None = None,
                chain: dict | None = None, prio: float | None = None, evict: bool = True, source: str = "") -> None:
        if self.final_locked:
            self.record("dropped", kind=kind, why="game over — nothing after the sign-off", stock=stock, text=text[:60])
            return
        item = {"kind": kind, "text": text, "stock": stock, "seq": seq,
                "prio": prio if prio is not None else (CHAIN_HOP_PRIORITY if chain else PRIORITY.get(kind, 9)),
                "at": self.clock(), "expires": self.clock() + ttl, "library": library, "seat": seat,
                "ctx": ctx or {}, "gap": gap, "chain": chain, "source": source or ("chain" if chain else kind), "follow": not evict}
        before = self.queue
        if kind == "bark" and not evict:
            pass                                                            # a follow-on: it queues behind what is already pending
        elif kind == "bark":
            # one pending bark, newest wins — by class (round 31): a reaction to a board
            # event clears everything pending except a sequenced follow-on (game 47: Purphoros's
            # second mulligan swallowed Lily's answer to Urza's first); a retort clears other
            # retorts and filler, never a reaction; the advisor's afterthoughts and patter clear only their peers
            cls = self._bark_class(item)
            if cls == "anchored":
                self.queue = [q for q in self.queue if q["kind"] != "bark" or q.get("follow")]
            elif cls == "chain":
                self.queue = [q for q in self.queue if q["kind"] != "bark" or self._bark_class(q) == "anchored"]
            else:
                self.queue = [q for q in self.queue if q["kind"] != "bark" or self._bark_class(q) == "anchored"
                              or self._bark_class(q) == "chain" or q["prio"] < item["prio"]]
        elif kind == "event" and evict:
            # Joshua's generic "a player has been eliminated" stands in once for any number of voiceless seats;
            # a seat's own exit line (queued with evict=False) is never displaced (Ben, 2026-09-11)
            self.queue = [q for q in self.queue if q["kind"] != "event" or q.get("follow") or q["stock"] != stock]
        elif kind in ("advice", "your_move", "quip", "color"):
            self.queue = [q for q in self.queue if q["kind"] != kind]       # one pending item per kind: newest wins
        for q in before:
            if q not in self.queue and q["kind"] in ("bark", "event"):     # game 48: Urza's "kill" vanished without a trace
                self.record("dropped", kind=q["kind"], why=f"evicted by {stock or kind}", stock=q["stock"], seat=q.get("seat"))
        self.queue.append(item)

    @staticmethod
    def _bark_class(item: dict) -> str:
        return classify(item)                                              # the eviction class IS the shared classification (C2)

    def next_item(self) -> dict | None:
        now = self.clock()
        live = []
        for q in self.queue:
            if q["expires"] < now:
                self.record("dropped", kind=q["kind"], why="expired", text=q["text"][:80], stock=q["stock"])
                continue
            if q["kind"] == "advice" and q["seq"] is not None and q["seq"] in self.answered:
                self.record("dropped", kind="advice", why="already answered", seq=q["seq"])
                continue
            live.append(q)
        self.queue = live
        if not live:
            return None
        live.sort(key=lambda q: (q["prio"], q["at"]))
        item = live[0]
        if item["kind"] in ("advice", "ask") and any(q.get("chain") for q in live[1:]):
            for q in [q for q in live[1:] if q.get("chain")]:
                self.record("dropped", kind=q["kind"], why="exchange interrupted by the advisor", stock=q["stock"], seat=q.get("seat"))
            live = [q for q in live if not q.get("chain")]
            self.queue = live
        # the rate limit applies to everything but game start / game over; a chain
        # hop brings its own shorter, conversational gap
        gap = item.get("gap") or self.min_gap
        if item["kind"] not in ("startup", "game_over", "human_out") and now - self.last_spoken_at < gap:
            return None
        self.queue.remove(item)
        return item

    # -- interaction chains
    def _respond_to_proposal(self, item: dict, opener_id: str, voiced: dict, turn) -> bool:
        """Ben (game 48): "'Might I suggest we all hit Selvala' should garner nays or assents from the other
        two, and Selvala should complain, laugh it off, say come at me, or not respond." Every other voiced
        player answers yea or nay in seat order, then the subject may retort — all sequenced as follow-ons."""
        if not (opener_id in PROPOSAL_LINES or opener_id.startswith(PROPOSAL_PREFIXES)):
            return False
        if item.get("chain"):
            return False                                          # a proposal made as a reply does not restart the table
        speaker = int(item["seat"])
        targets = [int(t) for t in ((item.get("ctx") or {}).get("targets") or [])]
        others = [s for s in sorted(voiced) if s != speaker and s not in targets]
        for seat in others:
            if self.rng.random() >= PROPOSAL_P:
                continue
            reply = self.rng.choice(PROPOSAL_REPLIES)
            if self.said_this_turn(seat, reply, optional=True):             # a yea or nay is banter: back after TURN_REPEAT_S (BL-53)
                reply = PROPOSAL_REPLIES[1 - PROPOSAL_REPLIES.index(reply)]
            self._turn_said().add((seat, reply))
            link = {"origin": speaker, "hop": 1, "turn": turn, "parent": item.get("stock")}
            self.enqueue("bark", stock=reply, library=self.lib_for(seat, reply), seat=seat, ttl=15.0, gap=0.3,
                         ctx={"targets": [speaker], "aggressor": speaker, "terminal": True}, chain=link, evict=False)
            self.record("queued", kind="bark", stock=reply, seat=seat, source="chain", hop=1, parent=item.get("stock"))
        subject = next((t for t in targets if t in voiced and t != speaker), None)
        if subject is not None and self.rng.random() < PROPOSAL_TARGET_P:
            options = [r for r in PROPOSAL_TARGET_REPLIES if not self.said_this_turn(subject, r, optional=True)]
            if options:
                reply = self.rng.choice(options)
                self._turn_said().add((subject, reply))
                link = {"origin": speaker, "hop": 1, "turn": turn, "parent": item.get("stock")}
                self.enqueue("bark", stock=reply, library=self.lib_for(subject, reply), seat=subject, ttl=15.0, gap=0.3,
                             ctx={"targets": [speaker], "aggressor": speaker, "terminal": True}, chain=link, evict=False)
                self.record("queued", kind="bark", stock=reply, seat=subject, source="chain", hop=1, parent=item.get("stock"))
        self._chain = None                                        # the table has had its say; no third round
        return True

    def leader_of(self, speaker: int):
        """The highest-life seat still in the game, other than the speaker and the human."""
        best, best_life = None, -1
        for s in self._last_snapshot.get("seats") or []:
            sid = s.get("seat")
            if sid is None or sid == speaker or sid == self.human_seat or s.get("eliminated"):
                continue
            if (s.get("life") or 0) > best_life:
                best, best_life = int(sid), s.get("life") or 0
        return best

    def after_spoken(self, item: dict) -> None:
        """A seat's line may invite a reply (chains.py). One reply at most, rolled
        here so the outcome is recorded; a chain dies when the turn changes."""
        if item.get("seat") is not None and item.get("library"):
            self._seat_last_class()[int(item["seat"])] = self._guard_class(classify(item))   # for the seat guard (A5), every spoken seat line
        if (item.get("ctx") or {}).get("terminal"):
            return                                       # a proposal's yea, nay or retort (A3): the table has had its say, no hop follows
        if self.chains is None or self.barks_mode == "off" or self.final_locked:
            return
        if item.get("seat") is None or not item.get("library"):
            return                                       # Joshua spoke: the seats ignore him
        turn = self._said_turn
        chain = item.get("chain") if item.get("chain") and item["chain"].get("turn") == turn else None
        voiced = {int(k): v["library"] for k, v in self.seat_libraries.items() if int(k) not in self.eliminated}
        now = self.clock()
        speaker = int(item["seat"])
        link0 = item.get("chain") or {}
        parent = str(link0.get("parent") or "")
        if item.get("stock") in ("promise", "take-the-deal") and (parent == "deal" or parent.startswith("deal-")) and link0.get("origin") is not None:
            # the seats' own small-talk truce (kind truce, one round — "Deal. For one turn."): struck in the ledger like any
            # other, so both brains are told (§4 source ii); an attack across it earns "you promised!"
            a, b = int(link0["origin"]), speaker
            if a != b:
                self.strike_deal(a, b, "truce", turn if turn is not None else self._last_snapshot.get("turn"), by=speaker, rounds=1, source="voice")
        # a hit is followed by the total ("Take five. I'm at sixteen." — every table does it)
        p_follow = LIFE_FOLLOWUP.get(item.get("stock", ""), 0.0) * self.table_mult
        if p_follow and not (chain and chain.get("followup")):
            pid = life_pid(self._seat_field(speaker, "life"))
            if pid and pid in self.table_ids and not self.said_this_turn(speaker, pid, optional=True) and self.rng.random() < min(1.0, p_follow * self.governor(optional=False)):
                self._turn_said().add((speaker, pid))
                link = {"origin": speaker, "hop": 0, "turn": turn, "parent": item.get("stock"), "followup": True}
                self.enqueue("bark", stock=pid, library=self.lib_for(speaker, pid), seat=speaker, ttl=15.0, gap=0.3, ctx=dict(item.get("ctx") or {}), chain=link)
                self.record("queued", kind="bark", stock=pid, seat=speaker, source="chain", hop=0, parent=item.get("stock"))
                self._chain = link
                return                                       # the table answers the hit after the number
        if chain and chain.get("followup"):
            # the number was the speaker's own follow-up: the table replies to the line before it
            item = dict(item, stock=chain.get("parent") or item["stock"])
            chain = None
        opener_id = (item.get("ctx") or {}).get("generic") or item.get("stock", "")
        question = is_question(opener_id)
        if self._respond_to_proposal(item, opener_id, voiced, turn):
            return
        # a question about a seat's state gets the true number back (whole-sentence lines)
        kind = STATE_ANSWERS.get(item.get("stock", ""))
        if kind:
            tg = [int(t) for t in ((item.get("ctx") or {}).get("targets") or []) if int(t) != speaker and int(t) in voiced]
            if tg:
                who = tg[0]
                pid = life_pid(self._seat_field(who, "life")) if kind == "life" else hand_pid(self._seat_field(who, "handSize"))
                hop = int((chain or {}).get("hop", 0)) + 1
                if pid and pid in self.table_ids and not self.said_this_turn(who, pid, optional=True) and hop <= self.chains.max_hops:
                    # a question gets its number with certainty (game 48: 8 of 17 questions hung); a jab is rolled
                    p = 1.0 if (question and hop == 1) else min(1.0, self.chains.hop_p(hop) * self.governor(optional=True))
                    if self.rng.random() < p:
                        self._turn_said().add((who, pid))
                        link = {"origin": int((chain or {}).get("origin", speaker)), "hop": hop, "turn": turn, "parent": item.get("stock")}
                        self.enqueue("bark", stock=pid, library=self.lib_for(who, pid), seat=who, ttl=15.0, gap=self.chains.gap_s,
                                     ctx={"targets": [speaker], "aggressor": speaker}, chain=link)
                        self.record("queued", kind="bark", stock=pid, seat=who, source="chain", hop=hop, parent=item.get("stock"))
                        self._chain = link
                        return
                    self.record("skipped", kind="bark", why=f"dice (chain hop {hop}, p={p:.2f})", stock=pid, seat=who, source="chain")
        recent = {k for k, t in self._seat_said_at.items() if now - t < RECENT_S}
        generic = (item.get("ctx") or {}).get("generic")
        planned = dict(item, stock=generic) if generic else item          # a named wording invites what its generic line invites
        # the planner's set-like argument is the optional view: a chain reply comes back after TURN_REPEAT_S (BL-53); chains.py is unchanged
        plan = plan_reply(self.chains, planned, chain, voiced, self.human_seat, self.leader_of, self._turn_said().optional, self.rng, turn, recent)
        if plan is None:
            self._chain = None
            return
        # a question to a seat is answered with certainty, outside the budget (game 48: 8 of 17 hung); the rest roll —
        # a few openers set their own first-hop chance (CHAIN_P_OVERRIDE: the jab at a seat that dealt with the player, §7)
        base_p = CHAIN_P_OVERRIDE.get(opener_id, plan["p"]) if plan["hop"] == 1 else plan["p"]
        p = 1.0 if (question and plan["hop"] == 1) else min(1.0, base_p * self.governor(optional=True))
        if self.rng.random() >= p:
            self.record("skipped", kind="bark", why=f"dice (chain hop {plan['hop']}, p={p:.2f})", stock=plan["id"],
                        seat=plan["seat"], source="chain")
            self._chain = None
            return
        link = {"origin": plan["origin"], "hop": plan["hop"], "turn": turn, "parent": item.get("stock")}
        seat = int(plan["seat"])                         # always a seat: Joshua never answers a seat's line (A14, Ben 2026-09-14)
        self._turn_said().add((seat, plan["id"]))
        reply = plan["id"]
        rctx = {"targets": [int(item["seat"])], "aggressor": int(item["seat"])}
        parent_ctx = item.get("ctx") or {}
        if parent_ctx.get("card") and plan["hop"] == 1:
            named = self.card_swap(seat, reply, parent_ctx)                # "Rhystic? I'm not paying all game."
            if named:
                self._turn_said().add((seat, named))
                rctx["generic"] = reply
                reply = named
        self.enqueue("bark", stock=reply, library=self.lib_for(seat, reply), seat=seat, ttl=15.0, gap=self.chains.gap_s, ctx=rctx, chain=link)
        self.record("queued", kind="bark", stock=reply, seat=seat, source="chain", hop=plan["hop"], parent=item.get("stock"))
        self._chain = link

    def maybe_bark(self, seat: int, pid: str, turn=None, source: str = "advice", p: float | None = None, ctx: dict | None = None,
                   gap: float | None = None, evict: bool = True) -> bool:
        """A bark for an AI seat — from the advisor's recap ("recap"), an advice
        window ("advice"), a snapshot event ("event") or a turn start ("opener") —
        subject to the knob, the per-turn no-repeat rule, the short per-seat
        guard and one roll of the dice. Records why when it does not play."""
        if self.barks_mode == "off":
            self.record("skipped", kind="bark", why="barks off (ARENA_BARKS=off)", stock=pid, seat=seat, source=source)
            return False
        if self.final_locked:
            self.record("skipped", kind="bark", why="game over", stock=pid, seat=seat, source=source)
            return False
        lib = self.library_for_seat(seat)
        if not lib:
            self.record("skipped", kind="bark", why=f"no voice library for seat {seat}", stock=pid, seat=seat, source=source)
            return False
        if int(seat) in self.eliminated:
            # Ben (2026-09-10): dead players should not talk — the exit line was their last
            self.record("skipped", kind="bark", why="eliminated", stock=pid, seat=seat, source=source)
            return False
        self._roll_turn(turn)
        # a card's own line is a distinct event (two combos in one turn are two announcements);
        # everything else repeats by its generic id. An anchored id is said once a turn; an optional one
        # (patter, the advisor's afterthoughts) comes back after TURN_REPEAT_S in a long turn (BL-53)
        named = self.card_swap(int(seat), pid, ctx)
        if self.said_this_turn(seat, named or pid, optional=classify_source(source) != "anchored"):
            self.record("skipped", kind="bark", why="already said this turn", stock=named or pid, seat=seat, source=source)
            return False
        if pid in RARE_REPEATS and self.clock() - self._seat_said_at.get((int(seat), pid), -1e9) < RECENT_S:
            self.record("skipped", kind="bark", why=f"said lately ({pid} within {RECENT_S:.0f}s)", stock=pid, seat=seat, source=source)
            return False
        # the seat guard holds only between two lines of the SAME class (A5, game 48 14:14:35: Bill's
        # "nothing happening" silenced his "landed hit" a second later): an anchored line follows the
        # seat's own filler or banter freely; an unknown last class (the guard stamped without a line) holds
        since = self.clock() - self._bark_spoken_at.get(int(seat), -1e9)
        cls = self._guard_class(classify_source(source))
        last = self._seat_last_class().get(int(seat))
        if since < self.barks_cooldown and pid not in OWN_ACTION_LINES and (last is None or last == cls):
            self.record("skipped", kind="bark", why=f"seat guard ({since:.0f}s < {self.barks_cooldown:.0f}s, {cls} after {last or 'a line'})",
                        stock=pid, seat=seat, source=source)
            return False
        # an explicit p (the opener's own number) always applies; otherwise "all" means always, "some" means barks_p (tuning.json)
        chance = p if p is not None else (1.0 if self.barks_mode == "all" else self.barks_p)
        ungoverned = pid in MULL_LINE.values() or (source == "patter" and p == 1.0)   # a mulligan is always worth the breath; so is breaking a silence
        g = 1.0 if ungoverned else self.governor(optional=classify_source(source) != "anchored")   # one rule (C2): chain replies stay optional
        chance = min(1.0, chance * g)
        if self.rng.random() >= chance:
            self.record("skipped", kind="bark", why=f"dice ({source}, p={chance:.2f}, governor {g:.2f})", stock=pid, seat=seat, source=source)
            return False
        self._turn_said().add((int(seat), pid))
        named = named or self.address_swap(int(seat), pid, ctx)
        if named:
            self._turn_said().add((int(seat), named))
            ctx = dict(ctx or {}); ctx["generic"] = pid                    # the chain plans from the generic line
            pid = named
        self.enqueue("bark", stock=pid, library=self.lib_for(int(seat), pid), seat=int(seat), ttl=20.0, ctx=ctx,
                     prio=BARK_PRIORITY.get(source, BARK_PRIORITY["patter"]), gap=gap, evict=evict, source=source)
        self.record("queued", kind="bark", stock=pid, seat=seat, source=source)
        return True

    def card_swap(self, seat: int, pid: str, ctx: dict | None) -> str:
        """A generic card line (game-changer, gc-react, commander-cast, engine-online, the
        reactions they invite) becomes the named wording when the ctx names the card and
        the seat's cards library carries it (round 31)."""
        if not ctx or not ctx.get("card") or not self.card_ids:
            return ""
        kind, card = str(ctx.get("card_kind") or ""), str(ctx["card"])
        named = ""
        if pid in CARD_SWAP and CARD_SWAP[pid][0] == kind:
            named = CARD_SWAP[pid][1].format(card=card)
        elif kind in CARD_REACTIONS and pid in CARD_REACTIONS[kind][0]:
            named = CARD_REACTIONS[kind][1].format(card=card)
        if not named or named not in self.card_ids:
            return ""
        lib = self.library_for_seat(seat)
        if not lib or not self.renderer.variants(named, f"{lib}/{CARD_LIB}"):
            return ""
        return named

    def address_swap(self, seat: int, pid: str, ctx: dict | None) -> str:
        """A generic line with one addressee becomes its named wording (hit-urza,
        threat-mono-red, ...) half the time, when the table library carries it."""
        fam_role = ADDRESS_SWAP.get(pid)
        if not fam_role or not ctx:
            return ""
        fam, role = fam_role
        if role == "target":
            tg = [int(t) for t in (ctx.get("targets") or [])]
            who_seat = tg[0] if len(tg) == 1 else None
        else:
            who_seat = ctx.get("aggressor")
        if who_seat is None or int(who_seat) == seat:
            return ""
        who = self._who.get(int(who_seat), "")
        if not who or self.rng.random() >= self.table_p("address"):
            return ""
        named = f"{fam}-{who}"
        lib = self.library_for_seat(seat)
        if named not in self.table_ids or not lib or not self.renderer.variants(named, f"{lib}/{TABLE_LIB}"):
            return ""
        return named

    # -- the deal ledger (plan 2026-09-16 §11): the live map, logs/deals.jsonl, the notes to the brains
    def _turn_int(self, turn) -> int:
        """`turn` as an int, else the snapshot's, else 0."""
        for v in (turn, self._last_snapshot.get("turn")):
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
        return 0

    def _living_count(self) -> int:
        """Seats still in the game — the length of one round, for a `rounds` deal's until_turn."""
        seats = [x for x in (self._last_snapshot.get("seats") or []) if isinstance(x, dict) and x.get("seat") is not None]
        n = len([x for x in seats if not x.get("eliminated") and int(x["seat"]) not in self.eliminated])
        return n if n >= 2 else max(2, 4 - len(self.eliminated))

    def deal_between(self, a, b) -> dict | None:
        """The live deal between two seats (either direction), normalised, or None."""
        return normalize_deal(self._deals.get((int(a), int(b))))

    def deal_forbids(self, actor, other, how: str) -> bool:
        """Does the deal between `actor` and `other` forbid `how` ("attack" | "target")?"""
        deal = self.deal_between(actor, other)
        if not deal:
            return False
        return deal["kind"] in (DEAL_ATTACK_KINDS if how == "attack" else DEAL_TARGET_KINDS)

    def _deal_counters_map(self) -> dict:
        d = getattr(self, "_deal_counters", None)
        if d is None:
            d = self._deal_counters = {}
        return d

    def _ledger(self, event: str, between, by=None, deal: dict | None = None, offer_id=None, turn=None, **extra) -> dict:
        """One record appended to logs/deals.jsonl: {ts, turn, event, between: [a, b], by, deal: {kind, until_turn,
        rounds?}, offer_id, seq} (+ `how` for a break). Errors are swallowed — the ledger never costs the table a
        line; the same fact goes to voice-0.jsonl as a `noted` deal record, which is what the tests and the
        panel's fallback read."""
        self._deal_seq = int(getattr(self, "_deal_seq", 0) or 0) + 1
        a, b = between
        rec = {"ts": round(self.wall(), 3), "turn": self._turn_int(turn),
               "event": event, "between": [int(a), int(b)], "by": int(by) if by is not None else None,
               "deal": dict(deal) if deal else None, "offer_id": str(offer_id) if offer_id is not None else None, "seq": self._deal_seq, **extra}
        try:
            self.logs.mkdir(parents=True, exist_ok=True)
            with (self.logs / DEALS_LEDGER).open("a") as f:
                f.write(json.dumps(rec) + "\n")
        except (OSError, TypeError, ValueError):
            pass
        self.record("noted", kind="deal", why=f"deal {event}: {a}<->{b}" + (f" by {by}" if by is not None else ""),
                    deal=rec["deal"], between=rec["between"], offer_id=rec["offer_id"], by=rec["by"], seq=self._deal_seq, **extra)
        return rec

    def _deal_note_eligible(self, seat: int) -> bool:
        """A note goes to a seat RUNNER: every AI seat (voiced or not — the brain, not the voice, reads it);
        seat 0 only while the Executive plays it (then the seat-0 runner is a party like any other)."""
        if int(seat) != self.human_seat:
            return True
        executive = getattr(self, "executive_on", None)
        return bool(callable(executive) and executive())

    def _deal_note(self, seat: int, body: dict) -> bool:
        """mailbox/seat-<n>/notes/<ts_ms>-<kind>.json, one JSON object, written atomically (tmp + os.replace);
        the seat runner renders it as one RUNNER NOTE and deletes it. False when the seat gets none."""
        if not self._deal_note_eligible(seat):
            return False
        kind = str(body.get("kind") or "deal")
        try:
            d = self.mailbox / f"seat-{int(seat)}" / "notes"
            d.mkdir(parents=True, exist_ok=True)
            ts_ms = int(float(self.wall()) * 1000)
            path = d / f"{ts_ms}-{kind}.json"
            while path.exists():
                ts_ms += 1                                                        # two notes in one millisecond: the next millisecond
                path = d / f"{ts_ms}-{kind}.json"
            tmp = d / f".{ts_ms}-{kind}.json.tmp"
            tmp.write_text(json.dumps(body))
            os.replace(tmp, path)
            return True
        except (OSError, TypeError, ValueError) as e:
            self.record("noted", kind="deal", why=f"note {kind} for seat {seat} not written ({str(e)[:80]})")
            return False

    def strike_deal(self, a, b, kind: str, turn, by, rounds=None, until_turn=None, offer_id=None, source: str = "") -> dict:
        """A deal struck between `a` and `b`: the live map both ways, a `struck` ledger record and a deal-struck
        note to both parties (the eligible ones). `rounds` N = N of the seat's own turns from the strike, resolved
        here to an absolute until_turn (turn + N x the living seats) so the lapse check is one comparison;
        `until_turn` given wins. Returns the live deal."""
        a, b = int(a), int(b)
        t = self._turn_int(turn)
        kind = kind if kind in DEAL_KINDS else "truce"
        terms: dict = {"kind": kind}
        if until_turn is not None:
            try:
                until = int(until_turn)
            except (TypeError, ValueError):
                until = None
        else:
            until = None
        if until is None:
            try:
                n = max(1, min(DEAL_MAX_ROUNDS, int(rounds or 1)))
            except (TypeError, ValueError):
                n = 1
            until = t + n * self._living_count()
            terms["rounds"] = n
        terms["until_turn"] = until
        deal = {"kind": kind, "until_turn": until, "struck": t, "offer_id": str(offer_id) if offer_id is not None else None}
        self._deals[(a, b)] = self._deals[(b, a)] = deal
        self._ledger("struck", (a, b), by=by, deal=terms, offer_id=offer_id, turn=t, source=source or None)
        for s in (a, b):
            self._deal_note(s, {"kind": "deal-struck", "between": [a, b], "deal": dict(terms), "offer_id": deal["offer_id"], "turn": t})
        return deal

    def break_deal(self, breaker, victim, how: str, turn) -> dict | None:
        """`breaker` attacked or targeted `victim` across their deal: forgotten both ways, a `broken` ledger
        record (by = the breaker, how = attack | target) and a deal-broken note to the wronged party only —
        the breaker chose (§5). None when there was no deal."""
        breaker, victim = int(breaker), int(victim)
        deal = normalize_deal(self._deals.pop((breaker, victim), None))
        self._deals.pop((victim, breaker), None)
        if deal is None:
            return None
        t = self._turn_int(turn)
        self._ledger("broken", (breaker, victim), by=breaker, deal={"kind": deal["kind"], "until_turn": deal["until_turn"]},
                     offer_id=deal["offer_id"], turn=t, how=how)
        self._deal_note(victim, {"kind": "deal-broken", "between": [breaker, victim], "by": breaker, "how": how, "turn": t})
        return deal

    def lapse_deals(self, turn) -> list[tuple[int, int]]:
        """At the roll to until_turn + 1 a deal has run its course: forgotten, a `lapsed` record, a deal-lapsed
        note to both parties, and one party (a voiced AI seat) may say "our truce is done" (DEAL_OVER_P). A
        counter nobody accepted expires at the end of its turn (`expired`). Junk in the map is dropped."""
        try:
            t = int(turn)
        except (TypeError, ValueError):
            return []
        if getattr(self, "_lapsing", False):
            return []                                                # the deal-over line rolls the turn too: no re-entry
        lapsed: list[tuple[int, int]] = []
        for pair, v in list(self._deals.items()):
            if pair not in self._deals:
                continue
            a, b = pair
            deal = normalize_deal(v)
            if deal is None:
                self._deals.pop(pair, None)
                continue
            if t > deal["until_turn"]:
                self._deals.pop((a, b), None)
                self._deals.pop((b, a), None)
                lapsed.append((int(a), int(b)))
                self._ledger("lapsed", (a, b), deal={"kind": deal["kind"], "until_turn": deal["until_turn"]}, offer_id=deal["offer_id"], turn=t)
                for s in (a, b):
                    self._deal_note(s, {"kind": "deal-lapsed", "between": [int(a), int(b)], "turn": t})
        for oid, c in list(self._deal_counters_map().items()):
            try:
                if t > int(c.get("turn", t)):
                    self._deal_counters_map().pop(oid, None)
                    a, b = c.get("between") or (None, None)
                    if a is not None and b is not None:
                        self._ledger("expired", (a, b), by=a, deal=c.get("deal"), offer_id=oid, turn=t)
            except (TypeError, ValueError):
                self._deal_counters_map().pop(oid, None)
        if lapsed and "deal-over" in self.table_ids:
            self._lapsing = True
            try:
                for a, b in lapsed:
                    parties = [s for s in (a, b) if s != self.human_seat and self.library_for_seat(s) and s not in self.eliminated]
                    if parties:
                        who = int(self.rng.choice(parties))
                        other = b if who == a else a
                        self.maybe_bark(who, "deal-over", turn=t, source="event", p=DEAL_OVER_P, ctx={"targets": [other]})
            finally:
                self._lapsing = False
        return lapsed

    def _roll_turn(self, turn) -> None:
        """The no-repeat memory is per game turn: a new turn clears it whole, whatever the clock (BL-53)."""
        if turn is not None and turn != self._said_turn and (self._said_turn is None or turn >= self._said_turn):
            # a turn only rolls FORWARD: a late record from a past turn (an unmute backlog, a null turn) must not
            # wipe the no-repeat set and the loop counters of the turn in progress (critic, 2026-09-16)
            self._said_turn = turn
            self._said_this_turn = TurnSaid(self.clock)
            self._chain = None                           # a new turn ends any exchange
            self._card_events_turn = {}                  # the loop counters are per turn too
        self.lapse_deals(turn)

    # -- the patter clock
    def _patter_gap_s(self, human_turn: bool) -> float:
        """The gap to the next patter line; on the human's turn (human_turn(), so not while the
        Executive plays the seat — A6) it stretches by patter_human (tuning.json, 0.33:
        a third as often), the rate game 48 ran at. §2 promised the same feel and Ben kept the
        floor's numbers, so the gap keeps ITS number; duty_human (0.6) is the budget's alone."""
        g = self.rng.uniform(*self.patter_gap)
        return g / self.patter_human if human_turn and self.patter_human > 0 else g

    def patter_candidates(self, snap: dict, living: list[int]) -> list[tuple[int, str, int | None, float]]:
        """(speaker, line, target, weight) — what the board gives the table to talk
        about. Board lines are addressed to a target (the human included, as a
        target only); filler is always available at low weight."""
        seats = [x for x in (snap.get("seats") or []) if isinstance(x, dict) and not x.get("eliminated")]
        by_id = {int(x["seat"]): x for x in seats if x.get("seat") is not None}
        active = snap.get("activeSeat")
        out: list[tuple[int, str, int | None, float]] = []

        def others(target):
            return [sp for sp in living if sp != target]

        def add(pid, target, w, speakers=None):
            if target == self.human_seat and pid in QUESTION_LINES:
                return                                                # the human cannot answer a question (game 48: awkward)
            for sp in (speakers if speakers is not None else others(target)):
                out.append((sp, pid, target, w / max(1, len(speakers if speakers is not None else others(target)))))

        for slow in self.slow_seats():
            add("play-faster", slow, 3.0); add("thinking-hard", slow, 1.0)
        if len(by_id) >= 2:
            lead = max(by_id.values(), key=lambda x: x.get("life") or 0)
            if [x for x in by_id.values() if (x.get("life") or 0) == (lead.get("life") or 0)] == [lead]:
                add("youre-the-threat", int(lead["seat"]), 2.0); add("whats-your-life", int(lead["seat"]), 1.0)
        for sid, x in by_id.items():
            life, hand = x.get("life") or 0, x.get("handSize") or 0
            if 0 < life <= 10:
                add("low-life-jab", sid, 2.0); add("whats-your-life", sid, 1.0)
            if hand >= 7:
                add("cards-in-hand", sid, 1.0)
            if hand <= 1 and sid != active:
                add("empty-hand", sid, 1.0)
            creatures = [c for c in (x.get("battlefield") or []) if isinstance(c, dict) and c.get("power") is not None]
            if any((c.get("power") or 0) >= 6 for c in creatures):
                add("kill-that", sid, 2.0)
        # the arc (phase D): a lethal board on the table, a game that has run long
        if self.table_ids:
            for sid, x in by_id.items():
                power = sum(int(c.get("power") or 0) for c in (x.get("battlefield") or []) if isinstance(c, dict) and c.get("power") is not None)
                if power >= LETHAL_POWER and "someone-wins" in self.table_ids and any((y.get("life") or 0) <= power for t, y in by_id.items() if t != sid):
                    add("someone-wins", sid, 2.0)
            if (snap.get("turn") or 0) >= LONG_GAME_TURN and "long-game" in self.table_ids:
                for sp in living:
                    out.append((sp, "long-game", None, 1.0 / len(living)))
        boards = {sid: sum(1 for c in (x.get("battlefield") or []) if isinstance(c, dict) and c.get("power") is not None) for sid, x in by_id.items()}
        if boards:
            big = max(boards, key=boards.get)
            if boards[big] >= 3 and list(boards.values()).count(boards[big]) == 1:
                add("board-envy", big, 1.0)
        # filler, always but a quarter of what it was (round 31: game 45 was 38 % filler);
        # a bluff about one's hand is the rarest (game 44)
        for sp in living:
            out.append((sp, "nothing-happening", None, 0.25 / len(living)))
            out.append((sp, "this-is-fine", None, 0.25 / len(living)))
            out.append((sp, "good-hand", None, 0.1 / len(living)))
            out.append((sp, "what-turn", None, 0.15 / len(living)))
            tgt = [t for t in living if t != sp]
            if tgt:
                out.append((sp, "deal", self.rng.choice(tgt), 0.5 / len(living)))
        if active is not None and int(active) in living:
            add("pass-already", int(active), 0.5)
        now = self.clock()
        said = self._turn_said()
        # a line the seat already said this turn is no candidate (game 46: 765 wasted gaps on one jab at turn 0) — for
        # TURN_REPEAT_S, patter being optional (BL-53: a nine-minute turn emptied the pool); a line ANY seat said in
        # the last five minutes is no candidate either (game 48: "cards in hand" x4) — PATTER_REPEAT_S is untouched
        return [(sp, pid, tgt, w)
                for sp, pid, tgt, w in out
                if not said.said(int(sp), pid, True, now) and now - self._said_at.get(pid, -1e9) >= PATTER_REPEAT_S]

    def patter(self) -> None:
        if not self.patter_on or self.barks_mode == "off" or self.queue or self.final_locked:
            return
        now = self.clock()
        snap = self._last_snapshot
        if (snap.get("turn") or 0) < 1 or not snap.get("phase"):
            return                                                # game 46: the table jabbed about "empty hands" at turn 0, before the deal
        idle = now - self._board_changed_at > IDLE_S
        mult = IDLE_SLOWDOWN if idle else 1.0
        if idle and not self._idle_noted:
            self._idle_noted = True
            self.record("skipped", kind="bark", why=f"idle table ({IDLE_S:.0f}s without a change) — the patter clock slows to a third", source="patter")
        human_turn = self.human_turn()                         # the human's turn WITHOUT the Executive playing it (A6)
        if self._patter_anchor != self.last_spoken_at:          # a line just played: rearm from its end
            self._patter_anchor = self.last_spoken_at
            self._patter_due = self.last_spoken_at + self._patter_gap_s(human_turn) * mult
            self._floor_atom_run = 0                            # a content line: the atoms may run again
        floor = SILENCE_FLOOR_S["human" if human_turn else "ai"] / max(0.25, self.chatter) * mult   # an idle table: the floor slows too
        silent_for = now - max(self.last_spoken_at, getattr(self, "_floor_rearmed_at", -1e9))   # an atom re-arms the floor without a line
        breaking = silent_for >= floor and not self.queue
        if not breaking and (now < self._patter_due or now - self._advisor_spoke_at < self.patter_after_advice):
            return
        living = [int(x) for x in self.seat_libraries if int(x) not in self.eliminated]
        cands = self.patter_candidates(snap, living) if living and snap.get("seats") else []
        self._patter_due = now + self._patter_gap_s(human_turn) * mult   # whatever happens, wait another gap
        if breaking:
            # the silence floor (game 48): the best candidate speaks, whatever the dice and the budget say —
            # anchored candidates ahead of filler; an empty or filler-only pool spends an atom when the
            # runner has them (voice/atoms.py, another lane), and the record says what the pool held (4.2)
            anchored = [c for c in cands if c[1] in ANCHORED_PATTER]
            why = f"silence floor ({silent_for:.0f}s quiet >= {floor:.0f}s)"
            if not anchored:
                atom = getattr(self, "floor_atom", None)
                run = getattr(self, "_floor_atom_run", 0)
                if living and callable(atom) and run < FLOOR_ATOM_MAX_RUN and atom(living):
                    self._floor_atom_run = run + 1
                    self._floor_rearmed_at = self.clock()                              # a full floor of quiet AFTER the atom (it plays blocking)
                    self.record("skipped", kind="bark", why=f"{why} — an atom ({run + 1} of {FLOOR_ATOM_MAX_RUN} in a row); "
                                f"the pool is {'empty' if not cands else 'filler only'}",
                                source="patter", pool=len(cands), anchored=0, picked="atom")
                    return
            if not cands:
                return                                            # nothing to say (and the atoms spent, or absent): quiet until the board moves
            self.record("skipped", kind="bark", why=f"{why} — speaking regardless", source="patter",
                        pool=len(cands), anchored=len(anchored), picked="anchored" if anchored else "filler")
            cands = anchored or cands
        else:
            if not cands:
                return
            g = self.governor(optional=True)
            if self.rng.random() >= g:
                self.record("skipped", kind="bark", why=f"governor (duty {self.duty():.2f} vs goal {self.duty_goal():.2f}, p={g:.2f})", source="patter")
                return
        total = sum(w for *_, w in cands)
        pick = self.rng.random() * total
        for speaker, pid, target, w in cands:
            pick -= w
            if pick <= 0:
                break
        said = self.maybe_bark(speaker, pid, turn=snap.get("turn"), source="patter", p=1.0 if breaking else None,
                               ctx={"targets": [target] if target is not None else []})
        if breaking and not said:
            self._floor_rearmed_at = now                              # the pick was guard-held: a full floor before the next try, not every poll

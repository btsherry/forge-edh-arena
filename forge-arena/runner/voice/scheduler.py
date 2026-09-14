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

from chains import plan_reply
from voice.table import CARD_LIB, CARD_REACTIONS, CARD_SWAP, TABLE_LIB, hand_pid, life_pid

PRIORITY = {"game_over": 0, "human_out": 0, "startup": 1, "ask": 2, "advice": 3, "quip": 4, "event": 5, "color": 6, "your_move": 7, "bark": 8}
# A reply inside an exchange must not be separated from the line it answers: game 44
# (20:43) Joshua's "your move" cut between Harry's jab and Lily's "shut it", so the
# retort landed on Joshua. Hops rank just below advice; if advice or a question
# does interrupt, the pending hop is dropped rather than played orphaned.
CHAIN_HOP_PRIORITY = 3.5
# The bark ladder (round 31, 2026-09-10): a reaction to something that just happened
# on the board plays ahead of Joshua's colour and the "your move" cue; the advisor's
# tagged afterthoughts and the patter clock come last. Chain hops keep 3.5 (game 44).
BARK_PRIORITY = {"chain": CHAIN_HOP_PRIORITY, "event": 5.5, "card": 5.5, "procedural": 5.5, "opener": 5.8,
                 "recap": 8.0, "advice": 8.0, "patter": 8.5}
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
OPTIONAL_FLOOR = 0.15     # patter and banter at the goal: nearly silent; an anchored line never drops below half
OPTIONAL_SOURCES = ("patter", "chain")
# game 46 (turns 8-13): "come on, land" four times in seven minutes — these lines are said by a seat at most once in RECENT_S
RARE_REPEATS = {"come-on-land", "thinking", "holding-mana", "tapped-out", "mana-up", "land-go", "early-game", "long-game", "loop", "looping"}
# A line a seat says because it just ACTED skips the per-seat guard (game 48: Harry heckled Giada's mulligan
# and one second later his own "seven, keeping" was silenced by his guard). Reactions, patter and banter keep it.
OWN_ACTION_LINES = {"keep-seven", "mull-to-six", "mull-to-five", "mull-to-four", "my-turn", "untap-draw", "early-game", "come-on-land",
                    "land-go", "pass", "mana-up", "tapped-out", "cast-creature", "cast-artifact", "cast-enchantment", "cast-instant",
                    "cast-sorcery", "cast-planeswalker", "cast-big", "in-response", "poke", "attack-you", "big-swing", "game-changer",
                    "commander-cast", "engine-online", "looping", "counter", "removal", "sweep", "kill", "win", "eliminated"}
LIFE_FOLLOWUP = {"that-hurt": 0.6, "take-it": 0.5, "low-life": 0.5}          # the speaker announces its total right after
STATE_ANSWERS = {"whats-your-life": "life", "low-life-jab": "life", "cards-in-hand": "hand", "empty-hand": "hand"}
ADDRESS_SWAP = {"kill-that": ("hit", "target"), "archenemy": ("hit", "target"), "youre-the-threat": ("threat", "target"),
                "deal": ("deal", "target"), "why-me": ("leave-me", "aggressor")}
DEAL_TURNS = 8            # a truce is remembered for two rounds
LONG_GAME_TURN = 14
LETHAL_POWER = 15
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
RECENT_WEIGHT = 0.15      # its patter weight is multiplied by this
# Seat barks, the table-talk design (Ben, 2026-09-10 — "playing with the AI should
# feel like sitting at the table with people"): every turn boundary has ONE owner.
# The recap of an AI seat's turn belongs to that seat (its retrospective line,
# authored by the advisor, rolled at ARENA_BARKS_P); the recap of the human's turn
# belongs to Joshua's colour line (its own dice) plus, optionally, one seat's
# reaction. Instant reactions come from the snapshot's public event ring — an
# attack of ARENA_BARKS_SWING power, a hit of ARENA_BARKS_HIT, a countered spell —
# with no LLM in the loop. Openers ("my turn") fire mechanically at a seat's turn
# start, rarely. A (seat, line) already said this turn is never said again.


CHATTER_LEVELS = {"quiet": 0.5, "normal": 1.0, "lively": 1.5, "rowdy": 2.0}


def chatter_level(raw: str | None) -> float:
    """ARENA_CHATTER — one master dial for how much the table talks (Ben,
    2026-09-10: "instead of trying to bake all of this just right anecdotally").
    A name (quiet .5 / normal 1 / lively 1.5 / rowdy 2) or a number; 1 = the
    knobs as written. Every frequency knob is multiplied by it (capped at 1),
    the gap between lines divided by it (floor 3 s), the instant-reaction
    thresholds divided by it (floors 3 power / 4 damage). Advice frequency —
    model calls — is not chatter and is untouched."""
    v = (raw or "normal").strip().lower()
    if v in CHATTER_LEVELS:
        return CHATTER_LEVELS[v]
    try:
        return max(0.0, min(4.0, float(v)))
    except ValueError:
        return 1.0



class SchedulerMixin:
    """The queue and its policy; VoiceRunner.__init__ owns every attribute used here."""

    def free_to_speak(self, seats: list[int]) -> list[int]:
        """The seats among `seats` outside their own guard (game 47: Bill was asked to
        answer a mulligan one second after his own line and hit the guard); all of them
        when none is free."""
        now = self.clock()
        free = [s for s in seats if now - self._bark_spoken_at.get(int(s), -1e9) >= self.barks_cooldown]
        return free or list(seats)

    # -- the talk budget
    def duty(self, window: float = DUTY_WINDOW_S) -> float:
        """Fraction of the last `window` seconds somebody was speaking."""
        now = self.clock()
        lo = now - window
        self._spoken_log = [(t, sec) for t, sec in self._spoken_log if t + sec > lo]
        return min(1.0, sum(min(sec, t + sec - lo) for t, sec in self._spoken_log) / window) if window > 0 else 0.0

    def duty_goal(self) -> float:
        human_turn = self._last_snapshot.get("activeSeat") == self.human_seat
        return self.duty_target * (self.duty_human if human_turn else 1.0)

    def governor(self, optional: bool) -> float:
        """Multiplier on a line's chance from the table's talk budget. Silence and a
        lively dial boost (up to the dial, like the old pre-scaling); at the goal an
        optional line (patter, a banter reply) falls to OPTIONAL_FLOOR while a line
        anchored to a board event keeps at least half its chance."""
        goal = self.duty_goal()
        if goal <= 0:
            return 1.0
        d = self.duty()
        if d >= goal:
            return OPTIONAL_FLOOR if optional else max(0.5, goal / d)
        head = (goal - d) / goal                                  # 1 in silence, 0 at the goal
        k = self.chatter
        boost = 1.0 + head * (k - 1.0) if k > 1.0 else k
        return boost * (OPTIONAL_FLOOR + (1.0 - OPTIONAL_FLOOR) * head) if optional else boost

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
        if item.get("chain"):
            return "chain"
        return "anchored" if item["prio"] < BARK_PRIORITY["recap"] else "optional"

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
            if (seat, reply) in self._said_this_turn:
                reply = PROPOSAL_REPLIES[1 - PROPOSAL_REPLIES.index(reply)]
            self._said_this_turn.add((seat, reply))
            link = {"origin": speaker, "hop": 1, "turn": turn, "parent": item.get("stock")}
            self.enqueue("bark", stock=reply, library=self.lib_for(seat, reply), seat=seat, ttl=15.0, gap=0.3,
                         ctx={"targets": [speaker], "aggressor": speaker}, chain=link, evict=False)
            self.record("queued", kind="bark", stock=reply, seat=seat, source="chain", hop=1, parent=item.get("stock"))
        subject = next((t for t in targets if t in voiced and t != speaker), None)
        if subject is not None and self.rng.random() < PROPOSAL_TARGET_P:
            options = [r for r in PROPOSAL_TARGET_REPLIES if (subject, r) not in self._said_this_turn]
            if options:
                reply = self.rng.choice(options)
                self._said_this_turn.add((subject, reply))
                link = {"origin": speaker, "hop": 1, "turn": turn, "parent": item.get("stock")}
                self.enqueue("bark", stock=reply, library=self.lib_for(subject, reply), seat=subject, ttl=15.0, gap=0.3,
                             ctx={"targets": [speaker], "aggressor": speaker}, chain=link, evict=False)
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
            # a truce struck: remembered both ways, for DEAL_TURNS turns; an attack across it earns "you promised!"
            a, b = int(link0["origin"]), speaker
            self._deals[(a, b)] = self._deals[(b, a)] = turn if turn is not None else self._last_snapshot.get("turn")
        # a hit is followed by the total ("Take five. I'm at sixteen." — every table does it)
        p_follow = LIFE_FOLLOWUP.get(item.get("stock", ""), 0.0) * self.table_mult
        if p_follow and not (chain and chain.get("followup")):
            pid = life_pid(self._seat_field(speaker, "life"))
            if pid and pid in self.table_ids and (speaker, pid) not in self._said_this_turn and self.rng.random() < min(1.0, p_follow * self.governor(optional=False)):
                self._said_this_turn.add((speaker, pid))
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
        question = opener_id in QUESTION_LINES or opener_id.startswith(QUESTION_PREFIXES)
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
                if pid and pid in self.table_ids and (who, pid) not in self._said_this_turn and hop <= self.chains.max_hops:
                    # a question gets its number with certainty (game 48: 8 of 17 questions hung); a jab is rolled
                    p = 1.0 if (question and hop == 1) else min(1.0, self.chains.hop_p(hop) * self.governor(optional=True))
                    if self.rng.random() < p:
                        self._said_this_turn.add((who, pid))
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
        plan = plan_reply(self.chains, planned, chain, voiced, self.human_seat, self.leader_of, self._said_this_turn, self.rng, turn, recent)
        if plan is None:
            self._chain = None
            return
        # a question to a seat is answered with certainty, outside the budget (game 48: 8 of 17 hung); the rest roll
        p = 1.0 if (question and plan["hop"] == 1 and plan["seat"] != "joshua") else min(1.0, plan["p"] * self.governor(optional=True))
        if self.rng.random() >= p:
            self.record("skipped", kind="bark", why=f"dice (chain hop {plan['hop']}, p={p:.2f})", stock=plan["id"],
                        seat=plan["seat"], source="chain")
            self._chain = None
            return
        link = {"origin": plan["origin"], "hop": plan["hop"], "turn": turn, "parent": item.get("stock")}
        if plan["seat"] == "joshua":
            self.enqueue("quip", stock=plan["id"], ttl=15.0, gap=self.chains.gap_s)
            self.record("queued", kind="quip", stock=plan["id"], source="chain", hop=plan["hop"], parent=item.get("stock"))
            self._chain = None                           # nobody answers Joshua
            return
        seat = int(plan["seat"])
        self._said_this_turn.add((seat, plan["id"]))
        reply = plan["id"]
        rctx = {"targets": [int(item["seat"])], "aggressor": int(item["seat"])}
        parent_ctx = item.get("ctx") or {}
        if parent_ctx.get("card") and plan["hop"] == 1:
            named = self.card_swap(seat, reply, parent_ctx)                # "Rhystic? I'm not paying all game."
            if named:
                self._said_this_turn.add((seat, named))
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
        # everything else repeats by its generic id
        named = self.card_swap(int(seat), pid, ctx)
        if (int(seat), named or pid) in self._said_this_turn:
            self.record("skipped", kind="bark", why="already said this turn", stock=named or pid, seat=seat, source=source)
            return False
        if pid in RARE_REPEATS and self.clock() - self._seat_said_at.get((int(seat), pid), -1e9) < RECENT_S:
            self.record("skipped", kind="bark", why=f"said lately ({pid} within {RECENT_S:.0f}s)", stock=pid, seat=seat, source=source)
            return False
        since = self.clock() - self._bark_spoken_at.get(int(seat), -1e9)
        if since < self.barks_cooldown and pid not in OWN_ACTION_LINES:
            self.record("skipped", kind="bark", why=f"seat guard ({since:.0f}s < {self.barks_cooldown:.0f}s)", stock=pid, seat=seat, source=source)
            return False
        # an explicit p (the opener's own knob) always applies; otherwise "all" means always, "some" means ARENA_BARKS_P
        chance = p if p is not None else (1.0 if self.barks_mode == "all" else self.barks_p)
        ungoverned = pid in MULL_LINE.values() or (source == "patter" and p == 1.0)   # a mulligan is always worth the breath; so is breaking a silence
        g = 1.0 if ungoverned else self.governor(optional=source in OPTIONAL_SOURCES)
        chance = min(1.0, chance * g)
        if self.rng.random() >= chance:
            self.record("skipped", kind="bark", why=f"dice ({source}, p={chance:.2f}, governor {g:.2f})", stock=pid, seat=seat, source=source)
            return False
        self._said_this_turn.add((int(seat), pid))
        named = named or self.address_swap(int(seat), pid, ctx)
        if named:
            self._said_this_turn.add((int(seat), named))
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

    def _forget_stale_deals(self, turn) -> None:
        try:
            t = int(turn)
        except (TypeError, ValueError):
            return
        for pair, struck in list(self._deals.items()):
            try:
                if t - int(struck) > DEAL_TURNS:
                    self._deals.pop(pair, None)
            except (TypeError, ValueError):
                self._deals.pop(pair, None)

    def _roll_turn(self, turn) -> None:
        """The no-repeat set is per game turn."""
        if turn is not None and turn != self._said_turn:
            self._said_turn = turn
            self._said_this_turn = set()
            self._chain = None                           # a new turn ends any exchange
            self._card_events_turn = {}                  # the loop counters are per turn too
        self._forget_stale_deals(turn)

    # -- the patter clock
    def _patter_gap_s(self, human_turn: bool) -> float:
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
        # a line the seat already said this turn is no candidate (game 46: 765 wasted gaps on one jab at turn 0);
        # a line ANY seat said in the last five minutes is no candidate either (game 48: "cards in hand" x4)
        return [(sp, pid, tgt, w)
                for sp, pid, tgt, w in out
                if (int(sp), pid) not in self._said_this_turn and now - self._said_at.get(pid, -1e9) >= PATTER_REPEAT_S]

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
        human_turn = snap.get("activeSeat") == self.human_seat
        if self._patter_anchor != self.last_spoken_at:          # a line just played: rearm from its end
            self._patter_anchor = self.last_spoken_at
            self._patter_due = self.last_spoken_at + self._patter_gap_s(human_turn) * mult
        floor = SILENCE_FLOOR_S["human" if human_turn else "ai"] / max(0.25, self.chatter) * mult   # an idle table: the floor slows too
        silent_for = now - self.last_spoken_at
        breaking = silent_for >= floor and not self.queue
        if not breaking and (now < self._patter_due or now - self._advisor_spoke_at < self.patter_after_advice):
            return
        living = [int(x) for x in self.seat_libraries if int(x) not in self.eliminated]
        cands = self.patter_candidates(snap, living) if living and snap.get("seats") else []
        self._patter_due = now + self._patter_gap_s(human_turn) * mult   # whatever happens, wait another gap
        if not cands:
            return
        if breaking:
            # the silence floor (game 48): the best candidate speaks, whatever the dice and the budget say
            self.record("skipped", kind="bark", why=f"silence floor ({silent_for:.0f}s quiet >= {floor:.0f}s) — speaking regardless", source="patter")
        else:
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
        self.maybe_bark(speaker, pid, turn=snap.get("turn"), source="patter", p=1.0 if breaking else None,
                        ctx={"targets": [target] if target is not None else []})

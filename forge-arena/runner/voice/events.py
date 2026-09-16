"""The voice runner's sources — EventsMixin, mixed into VoiceRunner
(runner/voice_runner.py), which supplies the state, say/record, the renderer and
the table. Here: the advisor's stream (advice, asks, quips, colour, bark tags), the
observer snapshot (startup, turn boundaries and openers, eliminations, heads-up,
big mana, the final sequence), the snapshot's public event ring (attacks, damage,
casts, removal, counters), the stack, the combos, the seat runners' game log
(mulligans, and the brain's intent: a `cycle` replay or a `say` key), the slow-seat
mutters, the board readers, the state files published for the GUI and the teardown
watcher, and the constants these use. Split out of voice_runner.py on 2026-09-14
(voicework2 hardening plan, Phase 0a); voice_runner re-exports every public name
here. This module never imports voice_runner.

Hardening (plan 2026-09-14, lane E1): the snapshot is stat-ed before it is parsed
and skipped when unchanged (§3); the board fingerprint follows the last ring seq,
not the ring's length (A8); one `_tail` reads both appended logs by complete lines
and restarts on a rotated file (A9); a jump in the ring's seq is recorded as a
`gap` (B2); every consumed ring event goes to logs/events.jsonl and every changed
snapshot, compacted, to logs/observer-tape.jsonl, and a bark queued for a ring
event carries the event's `seq` in its ctx (C1, §4.3); a loop is called three
ways — a game changer recast or self-bounced (LOOP_AT), the same card cast
LOOP_CASTS times in one turn, or the seat brain's own intent from game.jsonl
(`source: cycle`, `say: looping`) — once per turn per seat (A4, §4.4); a valid
`say` id from the brain is spoken as the seat's line with source "brain" (§4.4).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from voice.scheduler import MULL_DIG_WORDS, MULL_LINE, MULL_P, MULL_SCREW_WORDS, PRIORITY
from voice.table import card_kind, card_slug

FIRST_SENTENCE_MAX = 220
ASK_MAX = 300
LOOP_AT = 2               # the second time the same game changer is cast or bounced by its owner in one turn: a loop, not a fresh event
LOOP_CASTS = 4            # ANY card cast this often by one seat in one turn is a loop by mechanics alone (A4: game 48's sixteen Top casts)
INTENT_MAX_AGE_S = 10.0   # a brain's declaration older than this (read after a mute or a restart) is history, not a line
HECKLE_S = 30.0           # the board unchanged this long on the human's turn with no AI seat thinking: "we're waiting on you"
HECKLE_AGAIN_S = 90.0     # ...and this long: "still waiting"
# §4.4: the seat brain's optional "say" key — the seat runner validates it against seatd.rules.SAY_MENU before it lands in
# game.jsonl; this copy is pinned equal by test_events_hardening so the two cannot drift. Three of the ids address someone.
SAY_MENU = ("taunt", "respect", "nice-play", "kill-that", "youre-the-threat", "im-not-the-threat", "deal", "no-deal", "promise",
            "looping", "big-swing", "that-hurt", "gg", "heads-up", "nothing-happening", "this-is-fine")
SAY_TARGETED = ("deal", "kill-that", "youre-the-threat")     # spoken to the life leader among the OTHER seats, else not at all
EVENTS_TAPE = "events.jsonl"                                  # §4.3: every consumed ring event, as-is, plus turn and ts
OBSERVER_TAPE = "observer-tape.jsonl"                         # §4.3: every CHANGED snapshot, compacted
THINK_S = 8.0
NARRATIONS_PER_TURN = 2
GRUDGE_EVERY = 3          # the third hit from the same seat (and every third after) earns "you again?!"
# An AI seat's elimination is voiced ONCE: by the dying seat itself (its `eliminated`
# bark, at once) with this probability, else by Joshua's "A player has been eliminated."
ELIM_SEAT_P = 0.7


def first_sentence(text: str, limit: int = FIRST_SENTENCE_MAX) -> str:
    """The first sentence, cleaned for speech: no markdown, no brackets, no
    card-id noise; cut at a sentence end or the limit."""
    t = re.sub(r"\[[^\]]*\]", " ", text or "")           # [t12 · you], [quip:x], (ids)
    t = re.sub(r"[*_`#>]+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return ""
    m = re.search(r"^(.+?[.!?])(\s|$)", t)
    s = m.group(1) if m else t
    if len(s) > limit:
        cut = s[:limit]
        s = cut[: cut.rfind(" ")] if " " in cut else cut
        s = s.rstrip(",;:") + "."
    return s



class EventsMixin:
    """The sources and what they queue; VoiceRunner.__init__ owns every attribute used here
    except the four below, which the hardening added without touching the daemon."""

    _snap_sig: tuple | None = None        # (st_mtime_ns, st_size) of the last snapshot parsed; None until one is
    _ring_seq: int | None = None          # the ring event being dispatched, stamped on the barks it queues
    _loop_called: dict | None = None      # seat -> the turn its loop was last called (made on first use)
    _tails: dict | None = None            # _tail key -> [inode, pos] (made on first use)

    # -- the module's one door to the scheduler's bark, and its two tapes
    def _bark(self, seat: int, pid: str, **kw) -> bool:
        """maybe_bark, with the ring event's `seq` on the ctx while one is being dispatched
        (C1): the queue item, and so the spoken record, can name the event that caused it."""
        if self._ring_seq is not None:
            ctx = dict(kw.get("ctx") or {})
            ctx.setdefault("seq", self._ring_seq)
            kw["ctx"] = ctx
        return self.maybe_bark(seat, pid, **kw)

    def _atom(self, kind: str, seats: list[int], actor: int | None = None) -> None:
        """An instant reaction on the under channel (voice/atoms.py), when the daemon carries it."""
        react = getattr(self, "react_atom", None)
        if react is not None and seats:
            try:
                react(kind, seats, actor=actor)
            except Exception as e:  # noqa: BLE001 — a gasp never costs the table a line
                self.say(f"[voice] atom failed: {str(e)[:100]}")

    def _human_window_open(self) -> bool:
        """A decision the engine put to the human is still open: the advisor's shadow inbox
        (mailbox/seat-0-advisor/inbox/req-*.json) holds a request older than a moment."""
        try:
            inbox = self.mailbox / "seat-0-advisor" / "inbox"
            now = time.time()
            return any(now - f.stat().st_mtime > 2.0 for f in inbox.glob("req-*.json"))
        except OSError:
            return False

    def heckle_human(self) -> None:
        """Ben (2026-09-14): "heckles are great" — the board has not changed for HECKLE_S on the
        human's turn, Executive is off and no AI seat has a decision pending: a seat says "we're
        waiting on you"; HECKLE_AGAIN_S later "still waiting"; when the board moves again after
        a heckle, "there you are". The advisor never answers (Joshua is outside the game)."""
        if self.barks_mode == "off" or self.final_locked or "waiting-on-you" not in self.table_ids:
            return
        snap = self._last_snapshot
        if not snap.get("phase") and (snap.get("turn") or 0) >= 1:
            return
        quiet = self.clock() - self._board_changed_at
        stage = getattr(self, "_heckled", 0)
        # the wait is the HUMAN's: their turn, or a window put to them on someone else's turn (a block, a
        # target, the opening keep — the advisor's shadow inbox holds the open request); never while
        # Executive plays the seat
        if not (snap.get("activeSeat") == self.human_seat or self._human_window_open()) or self.executive_on():
            if stage:
                self._heckled = 0
            return
        if quiet < HECKLE_S:
            if stage:                                                 # the board moved: the wait is over
                self._heckled = 0
                by = self.free_to_speak([int(x) for x in self.seat_libraries if int(x) not in self.eliminated])
                if by:
                    self._bark(int(self.rng.choice(by)), "there-you-are", turn=snap.get("turn"), source="event", p=0.6, ctx={"targets": [self.human_seat]})
            return
        if self.slow_seats():
            return                                                    # an AI seat is the slow one, not the human
        pid = "waiting-on-you" if stage == 0 else ("still-waiting" if stage == 1 and quiet >= HECKLE_AGAIN_S else None)
        if pid is None:
            return
        by = self.free_to_speak([int(x) for x in self.seat_libraries if int(x) not in self.eliminated])
        if by and self._bark(int(self.rng.choice(by)), pid, turn=snap.get("turn"), source="event", p=1.0, ctx={"targets": [self.human_seat]}):
            self._heckled = stage + 1                                 # only a heckle that was queued counts (a guard-held one tries again next poll)

    def _tape(self, name: str, obj: dict) -> None:
        """One JSON line appended to logs/<name>; opened per call, errors swallowed — a tape
        must never cost the table a line. arena-stop.sh moves both tapes into the archive."""
        try:
            with (self.logs / name).open("a") as f:
                f.write(json.dumps(obj) + "\n")
        except (OSError, TypeError, ValueError):
            pass

    def _tail(self, path: Path, key: str) -> list[str]:
        """The complete lines appended to `path` since the last call for `key` (A9).
        Contract: only whole lines are delivered — the bytes after the last newline
        wait for the next call, so a record caught mid-write is read whole later, never
        lost or torn; the cursor tracks the file's inode and size, so a truncated or
        replaced file (a new game's log, arena-stop's archive) restarts from 0; a
        missing or unreadable file yields nothing and moves nothing. The two cursors
        the daemon seeds at start ("game": logs/game.jsonl from its size at start-up,
        "advisor": logs/advisor-0.jsonl from its size and inode) are adopted on the
        first call, so a (re)started runner never replays old records."""
        if self._tails is None:
            self._tails = {}
        cur = self._tails.get(key)
        if cur is None:
            seeds = {"game": [None, self._game_log_pos], "advisor": [self._adv_inode, self._adv_pos]}
            cur = self._tails[key] = seeds.get(key) or [None, 0]
        try:
            st = path.stat()
        except OSError:
            return []
        if (cur[0] is not None and cur[0] != st.st_ino) or st.st_size < cur[1]:
            cur[1] = 0                                                         # rotated or truncated: a new file (a size-only seed too)
        cur[0] = st.st_ino
        if st.st_size <= cur[1]:
            return []
        try:
            with path.open("rb") as f:
                f.seek(cur[1])
                chunk = f.read()
        except OSError:
            return []
        cut = chunk.rfind(b"\n")
        if cut < 0:
            return []                                                          # a partial line: next time
        chunk = chunk[:cut + 1]
        cur[1] += len(chunk)
        return chunk.decode("utf-8", "replace").splitlines()

    @staticmethod
    def mull_reason(why: str) -> str:
        w = (why or "").lower()
        if any(k in w for k in MULL_DIG_WORDS):
            return "mull-dig"
        if any(k in w for k in MULL_SCREW_WORDS):
            return "mull-screw"
        return "mull-pity"

    def scan_game_log(self) -> None:
        """New records in the seat runners' shared game log, read by complete lines
        (`_tail`): a MULLIGAN is voiced by the seat and answered by the table; any
        other record is read for the brain's intent — a `cycle` replay or a `say`
        key (§4.4). A voiced AI seat's records only; the human has none."""
        if self.barks_mode == "off" or self.final_locked:
            return
        for raw in self._tail(self.logs / "game.jsonl", "game"):
            try:
                r = json.loads(raw)
                seat = int(r["seat"])
            except (ValueError, TypeError, KeyError):
                continue
            if seat == self.human_seat:
                continue
            turn = r.get("turn") or 0
            if not self.library_for_seat(seat):
                if r.get("source") == "cycle":
                    self.brain_intent(r, seat, turn)                  # the table may still react; the staleness gate applies (critic)
                continue
            if r.get("type") == "MULLIGAN":
                if "mull-to-six" in self.table_ids:
                    self._mulligan(r, seat, turn)
            else:
                self.brain_intent(r, seat, turn)

    def _mulligan(self, r: dict, seat: int, turn) -> None:
        """The seat says "mulligan, six" (or five, four) the moment it decides, the table
        answers in the register the reason earns; a keep at seven may be announced; a
        keep at five or fewer is called risky; a seat that kept seven may gloat."""
        keep = bool((r.get("answer") or {}).get("keep", True))
        others = [int(x) for x in self.seat_libraries if int(x) != seat and int(x) not in self.eliminated]
        if not keep:
            k = self._mulls.get(seat, 0) + 1
            self._mulls[seat] = k
            pid = MULL_LINE.get(min(k, 3), "mull-to-four")
            if self._bark(seat, pid, turn=turn, source="event", p=MULL_P["own"], ctx={"targets": []}) and others:
                # the table answers in the register the reason earns, right behind the seat's line — by a seat
                # that has already kept or mulliganed (its own decision is not about to collide), else any free seat
                react = self.mull_reason(str(r.get("why") or ""))
                decided = [o for o in others if o in self._kept_seven or o in self._mulls]
                who = int(self.rng.choice(self.free_to_speak(decided or others)))
                if not self._bark(who, react, turn=turn, source="event", p=MULL_P["react"], ctx={"targets": [seat]}, gap=0.4, evict=False) \
                        and k >= 2 and self._kept_seven:
                    self._bark(int(self.rng.choice(self._kept_seven)), "mull-gloat", turn=turn, source="event", p=MULL_P["gloat"],
                               ctx={"targets": [seat]}, gap=0.4, evict=False)
        else:
            k = self._mulls.get(seat, 0)
            if k == 0:
                self._kept_seven.append(seat)
                self._bark(seat, "keep-seven", turn=turn, source="event", p=MULL_P["keep-seven"], ctx={"targets": []})
            elif k >= 2 and others:
                self._bark(int(self.rng.choice(self.free_to_speak(others))), "mull-risky", turn=turn, source="event", p=MULL_P["risky"], ctx={"targets": [seat]})

    def brain_intent(self, r: dict, seat: int, turn) -> None:
        """§4.4 — what the seat's own brain meant, from its game.jsonl record: a decision
        replayed from an armed cycle (`source: cycle`) or a `say: looping` is the seat
        declaring its loop — the owner's `looping` line at once, once per turn per seat;
        any other valid `say` id is the seat's table line, spoken with certainty under
        its normal guard (source "brain"). The three ids that address someone go to the
        life leader among the other seats, or nowhere. An id off the menu is ignored
        (the seat runner already validated; this is the second lock)."""
        answer = r.get("answer") if isinstance(r.get("answer"), dict) else {}
        say = str(r.get("say") or answer.get("say") or "").strip().lower()
        if not say and r.get("source") != "cycle":
            return
        snap_turn = self._last_snapshot.get("turn")
        age = time.time() - float(r.get("ts") or time.time())
        if (snap_turn is not None and turn and turn < snap_turn) or age > INTENT_MAX_AGE_S:
            # read late (a mute, a restart): a declaration from a past turn or older than a few seconds is history, not a line
            self.record("skipped", kind="bark", why=f"stale intent (turn {turn} vs {snap_turn}, {age:.0f}s old)", stock=say or "cycle", seat=seat, source="brain")
            return
        if r.get("source") == "cycle" or say == "looping":
            self.call_loop(seat, turn, source="brain", why=f"seat {seat} declared its loop ({'cycle replay' if r.get('source') == 'cycle' else 'say'})")
            return
        if not say:
            return
        if say not in SAY_MENU:
            self.record("skipped", kind="bark", why="say id not on the menu", stock=say, seat=seat, source="brain")
            return
        ctx: dict = {"targets": []}
        if say in SAY_TARGETED:
            leader = getattr(self, "leader_of", None)
            target = leader(seat) if callable(leader) else None
            if target is None:
                self.record("skipped", kind="bark", why="say needs a target and no other seat is standing", stock=say, seat=seat, source="brain")
                return
            ctx = {"targets": [int(target)]}
        self._bark(seat, say, turn=turn, source="brain", p=1.0, ctx=ctx)

    def human_mulligans(self, d: dict) -> None:
        """The human's keep is not in the game log; the first snapshot of turn one shows the
        kept hand (public), and a seat remarks on a mulligan once."""
        if self._human_mull_done or (d.get("turn") or 0) != 1 or not d.get("phase") or "mull-pity" not in self.table_ids:
            return
        rec = self._seat_rec(self.human_seat, d)
        if not rec:
            return
        self._human_mull_done = True
        hand = int(rec.get("handSize") or 0)
        phase = str(d.get("phase") or "")
        if d.get("activeSeat") == self.human_seat:
            if phase not in ("UNTAP", "UPKEEP", "DRAW"):
                return                                                     # the hand may already have been played from
            if phase == "DRAW":
                hand -= 1
        mulls = 7 - hand
        if mulls < 1 or mulls > 4:
            return
        by = [int(x) for x in self.seat_libraries if int(x) not in self.eliminated]
        if by:
            line = "mull-dig" if mulls >= 2 else self.rng.choice(["mull-pity", "mull-screw"])
            self._bark(int(self.rng.choice(by)), line, turn=1, source="event", p=self.barks_human_p,
                            ctx={"targets": [self.human_seat], "aggressor": self.human_seat, "human_cause": True})

    def _winner_seat(self, d: dict, seats: list):
        for e in reversed(d.get("events") or []):
            if e.get("kind") == "gameover" and e.get("winner") is not None:
                return int(e["winner"])
        name = d.get("winner")
        for s in seats:
            if name and s.get("name") == name:
                return int(s["seat"])
        alive = [s for s in seats if not s.get("eliminated")]
        return int(alive[0]["seat"]) if len(alive) == 1 else None

    # -- loops (A4): three triggers, one call per turn per seat
    def _loop_was_called(self, seat: int, turn) -> bool:
        """Has this seat's loop been called this turn (by any trigger)? Marks it if not."""
        if self._loop_called is None:
            self._loop_called = {}
        if seat in self._loop_called and self._loop_called[seat] == turn:
            return True
        self._loop_called[seat] = turn
        return False

    def loop_tick(self, seat: int, card: str, turn) -> bool:
        """One more cast or self-bounce of game changer `card` by `seat` this turn. At
        LOOP_AT the table calls the loop (a bystander, then the owner may relish it).
        True when this event is part of a loop and the card's own lines should stay quiet."""
        self._roll_turn(turn)                                   # the turn's counters roll before this event counts
        key = (int(seat), card)
        n = self._card_events_turn.get(key, 0) + 1
        self._card_events_turn[key] = n
        if n < LOOP_AT:
            return False
        if n == LOOP_AT and "loop" in self.table_ids and not self._loop_was_called(int(seat), turn):
            by = [int(x) for x in self.seat_libraries if int(x) != int(seat) and int(x) not in self.eliminated]
            if by:
                said = self._bark(int(self.rng.choice(self.free_to_speak(by))), "loop", turn=turn, source="event", ctx={"targets": [int(seat)]})
                if said and self.library_for_seat(int(seat)):
                    self._bark(int(seat), "looping", turn=turn, source="event", p=0.5, ctx={"targets": []}, gap=0.4, evict=False)
        return True

    def cast_tick(self, seat: int, card: str, turn) -> None:
        """One more cast of any other card by `seat` this turn, in the same per-turn count
        the game changers use; at LOOP_CASTS the loop is called by mechanics alone (game
        48: sixteen Top casts drew no line because Top is not a game changer)."""
        self._roll_turn(turn)
        key = (int(seat), card)
        n = self._card_events_turn.get(key, 0) + 1
        self._card_events_turn[key] = n
        if n == LOOP_CASTS:
            self.call_loop(int(seat), turn, source="event", why=f"{card} cast {n} times this turn by seat {seat}")

    def call_loop(self, seat: int, turn, source: str = "event", why: str = "") -> bool:
        """The loop is called — the owner's `looping` line at once (with certainty, its own
        guard still applies), the table's `loop` reaction behind it — once per turn per
        seat, whichever trigger fires first. False when it was already called this turn."""
        self._roll_turn(turn)
        seat = int(seat)
        if self._loop_was_called(seat, turn):
            return False
        self.record("noted", kind="event", why=f"loop called: {why}", seat=seat, turn=turn, source=source)
        said = False
        if seat != self.human_seat and self.library_for_seat(seat):
            said = self._bark(seat, "looping", turn=turn, source="event", p=1.0, ctx={"targets": []})   # anchored whoever noticed (critic: "brain" was optional)
        if "loop" in self.table_ids:
            by = [int(x) for x in self.seat_libraries if int(x) != seat and int(x) not in self.eliminated]
            if by:
                self._bark(int(self.rng.choice(self.free_to_speak(by))), "loop", turn=turn, source="event", ctx={"targets": [seat]},
                           gap=0.4 if said else None, evict=not said)
        return True

    # -- colour: Joshua speaks after the human's turn
    def _voice_color(self, r: dict) -> None:
        """Joshua's colour line. A recap of an AI seat's turn belongs to that seat
        (the advisor stamps `owner`); the human's turn is Joshua's, under his dice."""
        owner = r.get("owner")
        if self.barks_mode != "off" and owner is not None and int(owner) != self.human_seat and self.library_for_seat(int(owner)):
            self.record("skipped", kind="color", why=f"seat {owner}'s turn — the seat speaks", text=r["text"][:80], seq=r.get("seq"))
            return
        if self.color_mode == "all" or self.rng.random() < min(1.0, self.color_p * self.governor(optional=False)):
            self.enqueue("color", text=first_sentence(r["text"]), ttl=40.0)
        else:
            self.record("skipped", kind="color", why="dice (color_mode=some)", text=r["text"][:80])

    def slow_seats(self) -> list[int]:
        """AI seats with a decision pending in their mailbox longer than barks_slow (tuning.json barks_slow_s)."""
        out = []
        now = time.time()
        for seat in self.seat_libraries:
            if int(seat) in self.eliminated:
                continue
            try:
                inbox = self.mailbox / f"seat-{seat}" / "inbox"
                ages = [now - f.stat().st_mtime for f in inbox.glob("req-*.json")]
            except OSError:
                ages = []
            if ages and max(ages) >= self.barks_slow:
                out.append(int(seat))
        return out

    # -- the board, as the table sees it
    def _seat_field(self, seat: int, key: str, snap: dict | None = None):
        for x in (snap or self._last_snapshot).get("seats") or []:
            if x.get("seat") == seat:
                return x.get(key)
        return None

    @staticmethod
    def _lands(seat_rec: dict | None) -> tuple[int, int]:
        """(lands, untapped lands) on a seat's battlefield."""
        n = up = 0
        for c in (seat_rec or {}).get("battlefield") or []:
            if isinstance(c, dict) and "land" in str(c.get("types") or "").lower():
                n += 1
                up += 0 if c.get("tapped") else 1
        return n, up

    @staticmethod
    def _open_to_attack(seat_rec: dict | None) -> bool:
        """No untapped creature: an attack on this seat goes unblocked."""
        return not any(isinstance(c, dict) and c.get("power") is not None and not c.get("tapped") for c in (seat_rec or {}).get("battlefield") or [])

    def _seat_rec(self, seat, snap: dict | None = None) -> dict | None:
        return next((x for x in (snap or self._last_snapshot).get("seats") or [] if x.get("seat") == seat), None)

    def narrate_cast(self, seat: int, spell: str, cmc: int, turn) -> bool:
        """The caster says what kind of thing it just cast (a type, "a big one", "in
        response") — at most NARRATIONS_PER_TURN a turn. Game changers and the
        commander have their own lines and never come here."""
        st = self._turn_start.get(int(seat)) or {"narrations": 0}
        if st["narrations"] >= NARRATIONS_PER_TURN or not self.table_ids:
            return False
        kind = card_kind(self.cards_of(seat).get(spell))
        active = self._last_snapshot.get("activeSeat")
        if cmc >= 6:
            pid, p, ctx = "cast-big", self.table_p("cast-big"), {"targets": []}
        elif kind == "instant" and active is not None and int(active) != int(seat):
            tg = [int(active)] if int(active) != self.human_seat and self.library_for_seat(int(active)) else []
            pid, p, ctx = "in-response", self.table_p("in-response"), {"targets": tg}
        elif kind in ("creature", "artifact", "enchantment", "instant", "sorcery", "planeswalker"):
            pid, p, ctx = f"cast-{kind}", self.table_p("cast"), {"targets": []}
        else:
            return False
        if self._bark(int(seat), pid, turn=turn, source="procedural", p=p, ctx=ctx):
            st["narrations"] += 1
            return True
        return False

    def turn_boundary(self, d: dict, turn, active) -> bool:
        """The seat whose turn just ended sums it up ("land, go" / "pass" / "pass with
        mana up" / "tapped out"). Returns whether a line was queued, so the next
        seat's opener can follow it instead of evicting it ("Land, go." "My turn.")."""
        queued = False
        ended = self.seen_active
        prev = self._prev_snapshot or {}
        if ended is not None and ended != self.human_seat and self.library_for_seat(int(ended)) and int(ended) not in self.eliminated and self.table_ids:
            st = self._turn_start.get(int(ended))
            rec = self._seat_rec(ended, prev)
            lands, up = self._lands(rec)
            hand = int((rec or {}).get("handSize") or 0)
            nxt = [int(active)] if active is not None and active != self.human_seat and self.library_for_seat(int(active)) else []
            if st is not None:
                if st["casts"] == 0 and lands > st["lands"]:
                    queued = self._bark(int(ended), "land-go", turn=turn, source="procedural", p=self.table_p("land-go"), ctx={"targets": nxt})
                elif st["casts"] > 0:
                    if up >= 3 and hand >= 2:
                        pid = "mana-up"
                    elif up == 0 and hand >= 1:
                        pid = "tapped-out"
                    else:
                        pid = "pass"
                    queued = self._bark(int(ended), pid, turn=turn, source="procedural", p=self.table_p(pid), ctx={"targets": nxt})
            self._turn_start.pop(int(ended), None)
        if active is not None and active != self.human_seat and self.library_for_seat(int(active)):
            lands, _ = self._lands(self._seat_rec(active, d))
            self._turn_start[int(active)] = {"lands": lands, "casts": 0, "narrations": 0}
        return queued

    def opener(self, d: dict, turn, active, follow: bool = False) -> None:
        """Option A (2026-09-10): an opener at a seat's turn start — my-turn or its
        table twin untap-draw, or a mutter for lands when the seat is short of them.
        `follow`: the previous seat just summed its turn up — queue behind it, close."""
        gap, evict = (0.4, False) if follow else (None, True)
        lands, _ = self._lands(self._seat_rec(active, d))
        own_turn = max(1, (int(turn) + 3) // 4)
        if self.table_ids and "come-on-land" in self.table_ids and lands < min(4, own_turn - 1):
            if self._bark(int(active), "come-on-land", turn=turn, source="opener", p=self.table_p("come-on-land"), gap=gap, evict=evict):
                return
        if int(turn) <= 4 and "early-game" in self.table_ids and self.rng.random() < self.table_p("early-game"):
            if self._bark(int(active), "early-game", turn=turn, source="opener", p=self.barks_opener_p, gap=gap, evict=evict):
                return
        pid = "untap-draw" if self.table_ids and "untap-draw" in self.table_ids and self.rng.random() < self.table_p("untap-draw") else "my-turn"
        self._bark(int(active), pid, turn=turn, source="opener", p=self.barks_opener_p, gap=gap, evict=evict)

    def scan_stack(self, d: dict) -> None:
        """Something new on the stack that targets a voiced seat's permanent (or the
        seat itself): "hold on, which one?" — once per turn per seat."""
        detail = d.get("stackDetail") or []
        if not detail:
            self._stack_seen.clear()
            return
        if not self.table_ids or "hold-on" not in self.table_ids:
            return
        turn = d.get("turn")
        for si in detail:
            if not isinstance(si, dict):
                continue
            targets = [str(t) for t in (si.get("targets") or [])]
            key = (si.get("name"), si.get("owner"), tuple(targets))
            if key in self._stack_seen or not targets:
                continue
            self._stack_seen.add(key)
            owner = si.get("owner")
            for t in targets:
                victim = None
                if t.startswith("seat "):
                    try:
                        victim = int(t[5:])
                    except ValueError:
                        victim = None
                else:
                    name = t.replace(" (on the stack)", "")
                    for x in d.get("seats") or []:
                        if any(isinstance(c, dict) and c.get("name") == name for c in x.get("battlefield") or []):
                            victim = x.get("seat")
                            break
                if victim is None or victim == owner or victim == self.human_seat or not self.library_for_seat(int(victim)):
                    continue
                self._bark(int(victim), "hold-on", turn=turn, source="procedural", p=self.table_p("hold-on"),
                                ctx={"targets": [], "aggressor": owner, "human_cause": owner == self.human_seat})
                break

    def scan_combos(self, d: dict) -> None:
        """The last piece of a known combo landed on a seat's battlefield: the owner crows
        (engine-online -> combo-<key>-online) and the table alarms; for the human's
        board a bystander raises it. Once per combo per game."""
        for s in d.get("seats") or []:
            seat = s.get("seat")
            if seat is None or s.get("eliminated"):
                continue
            combos = self.combos_of(int(seat))
            if not combos:
                continue
            names: set[str] = set()
            for c in s.get("battlefield") or []:
                if isinstance(c, dict):
                    names.add(str(c.get("name") or "").split(" // ")[0])
                    names |= {str(n).split(" // ")[0] for n in (c.get("imprinted") or [])}      # Scepter + Dramatic Reversal, Mirror + Time Warp
            done = self._combos_done.setdefault(int(seat), set())
            for pieces, key in combos:
                if pieces in done or not pieces <= names:
                    continue
                done.add(pieces)
                ctx = {"card": key, "card_kind": "combo"} if key else {}
                if int(seat) != self.human_seat and self.library_for_seat(int(seat)):
                    # the announcement queues behind whatever is pending and survives the flood of piece events that
                    # follows (game 47: Urza's Hullbreaker alarm was queued at 20:36:27 and evicted by the Vault lines)
                    self._bark(int(seat), "engine-online", turn=d.get("turn"), source="event", ctx={"targets": [], **ctx}, gap=0.5, evict=False)
                    self._atom("combo", [int(x) for x in self.seat_libraries if int(x) != int(seat)], actor=int(seat))
                elif int(seat) == self.human_seat:
                    by = [x for x in self.seat_libraries if int(x) not in self.eliminated]
                    if by:
                        self._bark(int(self.rng.choice(by)), "oh-no", turn=d.get("turn"), source="event", p=self.barks_human_p,
                                        ctx={"targets": [int(seat)], "aggressor": int(seat), "human_cause": True, **ctx})

    def mutter(self) -> None:
        """A seat whose own decision has been pending THINK_S thinks aloud, once per request."""
        if not self.table_ids or "thinking" not in self.table_ids or self.barks_mode == "off" or self.final_locked:
            return
        now = time.time()
        for seat in self.seat_libraries:
            if int(seat) in self.eliminated:
                continue
            try:
                files = list((self.mailbox / f"seat-{seat}" / "inbox").glob("req-*.json"))
            except OSError:
                files = []
            for f in files:
                key = f"{seat}/{f.name}"
                try:
                    age = now - f.stat().st_mtime
                except OSError:
                    continue
                if age >= THINK_S and key not in self._thought:
                    self._thought.add(key)
                    self._bark(int(seat), "thinking", turn=self._last_snapshot.get("turn"), source="procedural", p=self.table_p("thinking"))
        if len(self._thought) > 500:
            self._thought = set(list(self._thought)[-100:])

    # -- instant reactions from the snapshot's public event ring
    def scan_events(self, d: dict) -> None:
        events = d.get("events") or []
        if self._event_seq is None:
            # first read (fresh start or restart): never replay history
            self._event_seq = max((int(e.get("seq", 0)) for e in events), default=0)
            return
        for e in events:
            try:
                seq = int(e.get("seq", 0))
            except (TypeError, ValueError):
                continue
            if seq <= self._event_seq:
                continue
            if seq > self._event_seq + 1:
                # B2: the 30-entry ring rolled past us between two polls — say so, once per gap
                self.record("gap", kind="event", missed=seq - self._event_seq - 1, seq=seq)
            self._event_seq = seq
            self._tape(EVENTS_TAPE, {**e, "turn": e.get("turn", d.get("turn")), "ts": round(time.time(), 3), "clock": round(self.clock(), 3)})
            if self.barks_mode == "off" or self.final_locked:
                continue
            kind, turn = e.get("kind"), e.get("turn")
            self._ring_seq = seq                                             # C1: the barks below carry it
            try:
                if kind == "attack":
                    seat = int(e.get("seat"))
                    big = int(e.get("power", 0)) >= self.barks_swing or int(e.get("attackers", 0)) >= 3
                    defenders = [int(x) for x in (e.get("defenders") or [])]
                    open_ = [x for x in defenders if x != self.human_seat and self.library_for_seat(x) and self._open_to_attack(self._seat_rec(x, d))]
                    power = int(e.get("power", 0))
                    betrayed = [x for x in defenders if (seat, x) in self._deals and x != self.human_seat and self.library_for_seat(x)]
                    if betrayed and "you-promised" in self.table_ids:
                        # a truce broken: the promised seat objects (and the deal is forgotten)
                        who = int(self.rng.choice(betrayed))
                        for pair in ((seat, who), (who, seat)):
                            self._deals.pop(pair, None)
                        self._bark(who, "you-promised", turn=turn, source="event", p=self.table_p("you-promised"),
                                        ctx={"targets": [], "aggressor": seat, "human_cause": seat == self.human_seat})
                    elif seat != self.human_seat and big:
                        self._bark(seat, "big-swing", turn=turn, source="event",
                                        ctx={"targets": defenders, "aggressor": None, "open": open_})
                        self._atom("swing", [int(x) for x in self.seat_libraries if int(x) != seat], actor=seat)
                    elif seat != self.human_seat and self.library_for_seat(seat) and power > 0:
                        # a smaller attack: "just a poke" / "you take this one" (the defender may answer "no blocks")
                        pid = "attack-you" if power * 2 >= self.barks_swing and len(defenders) == 1 else "poke"
                        self._bark(seat, pid, turn=turn, source="procedural", p=self.table_p(pid),
                                        ctx={"targets": defenders, "aggressor": None, "open": open_})
                    elif seat == self.human_seat:
                        # the human swings: a defender braces, complains, or admits it has no blocks (round 31)
                        voiced_def = [x for x in defenders if x != self.human_seat and self.library_for_seat(x) and x not in self.eliminated]
                        if voiced_def and (big or open_):
                            who = int(self.rng.choice(open_ or voiced_def))
                            line = "no-blocks" if who in open_ and "no-blocks" in self.table_ids else self.rng.choice(["brace", "why-me"])
                            self._bark(who, line, turn=turn, source="event", p=self.barks_human_p,
                                            ctx={"targets": [], "aggressor": seat, "human_cause": True})
                elif kind == "damage":
                    victim = int(e.get("seat"))
                    froms = [int(x) for x in (e.get("from") or [])]
                    if froms:
                        self._last_hit_by[victim] = (froms, turn)
                    amount = int(e.get("amount", 0))
                    if len(froms) == 1 and froms[0] != victim and amount > 0:
                        n = self._hits_from.setdefault(victim, {}).get(froms[0], 0) + 1
                        self._hits_from[victim][froms[0]] = n
                        if n % GRUDGE_EVERY == 0 and victim != self.human_seat and self.library_for_seat(victim) and "grudge" in self.table_ids:
                            if self._bark(victim, "grudge", turn=turn, source="event", p=self.table_p("grudge"),
                                               ctx={"targets": [], "aggressor": froms[0], "human_cause": froms[0] == self.human_seat}):
                                continue                                # "you again?!" stands in for that-hurt / take-it this time
                    if amount < self.barks_hit:
                        if e.get("combat") and amount > 0 and victim != self.human_seat and self.library_for_seat(victim) and "take-it" in self.table_ids:
                            self._bark(victim, "take-it", turn=turn, source="procedural", p=self.table_p("take-it"),
                                            ctx={"targets": [], "aggressor": froms[0] if froms else None, "human_cause": self.human_seat in froms})
                        continue
                    if victim != self.human_seat:
                        self._bark(victim, "that-hurt", turn=turn, source="event",
                                        ctx={"targets": [], "aggressor": froms[0] if froms else None, "human_cause": self.human_seat in froms})
                    else:
                        hitters = [x for x in froms if x != self.human_seat and self.library_for_seat(x)]
                        if hitters:
                            self._bark(hitters[0], "landed-hit", turn=turn, source="event",
                                            ctx={"targets": [self.human_seat], "aggressor": None})
                            self._atom("swing", [int(x) for x in self.seat_libraries if int(x) not in hitters], actor=hitters[0])
                elif kind == "cast":
                    seat = int(e.get("seat"))
                    spell = str(e.get("spell") or "")
                    if seat == self.human_seat:
                        # the human's play: the table reacts to HIM (round 31 — until now the seats
                        # ignored every card the human cast): a game changer alarms, the commander
                        # or a big spell draws a bystander's line
                        by = [x for x in self.seat_libraries if int(x) not in self.eliminated]
                        cmc = int(e.get("cmc", 0))
                        card: dict = {}
                        if spell in self.game_changers.get(seat, set()):
                            if self.loop_tick(seat, spell, turn) or (seat, spell) in self._gc_cast_seen:
                                line = ""                                          # a recast: the table has met this card
                            else:
                                line = "gc-react"
                            self._gc_cast_seen.add((seat, spell))
                            card = {"card": card_slug(spell), "card_kind": "gc"}
                        elif e.get("commander"):
                            line = self.rng.choice(["oh-no", "brace", "read-that"])
                            card = {"card": self._who.get(seat, ""), "card_kind": "cmd"}
                        elif cmc >= 7:
                            line = "wow"
                        elif cmc >= 5:
                            line = self.rng.choice(["nice-play", "read-that", "oh-no"])
                        elif cmc >= 3 and "sure" in self.table_ids:
                            line = "sure"                            # "resolves." — the table acknowledges the play
                        else:
                            line = ""
                        if by and line:
                            self._bark(int(self.rng.choice(by)), line, turn=turn, source="event",
                                            p=self.table_p("sure") if line == "sure" else self.barks_human_p,
                                            ctx={"targets": [seat], "aggressor": seat, "human_cause": True, **card})
                    elif self.library_for_seat(seat):
                        if seat in self._turn_start:
                            self._turn_start[seat]["casts"] += 1        # the turn summary: not a "land, go" turn
                        if spell in self.game_changers.get(seat, set()):
                            # one of the bracket's game changers: the caster crows ONCE a game, the table reacts (chain);
                            # a recast is quiet, and the second cast in a turn is a loop (game 47: Urza's Mana Vault, six times a turn)
                            looping = self.loop_tick(seat, spell, turn)
                            if not looping and (seat, spell) not in self._gc_cast_seen:
                                self._bark(seat, "game-changer", turn=turn, source="event",
                                                ctx={"targets": [], "card": card_slug(spell), "card_kind": "gc"})
                            self._gc_cast_seen.add((seat, spell))
                        elif e.get("commander"):
                            self._bark(seat, "commander-cast", turn=turn, source="event",
                                            ctx={"targets": [], "card": self._who.get(seat, ""), "card_kind": "cmd"})
                        elif not self.narrate_cast(seat, spell, int(e.get("cmc", 0)), turn) and int(e.get("cmc", 0)) >= 5:
                            # no narration: a big spell still draws a bystander's reaction — wow at seven-plus, else admiration / read that / oh no
                            # (when the caster narrates, the reaction comes as the chain's reply to that line)
                            by = [x for x in self.seat_libraries if int(x) != seat and int(x) not in self.eliminated]
                            if by:
                                line = "wow" if int(e.get("cmc", 0)) >= 7 else self.rng.choice(["nice-play", "read-that", "oh-no"])
                                self._bark(int(self.rng.choice(by)), line, turn=turn, source="event", ctx={"targets": [seat]})
                    # a flurry — three spells inside thirty seconds — earns "slow down" from someone else
                    now_t = time.time()
                    recent = [t for t in self._casts.get(seat, []) if now_t - t < 30] + [now_t]
                    self._casts[seat] = recent
                    if len(recent) >= 3 and seat != self.human_seat:
                        by = [x for x in self.seat_libraries if int(x) != seat and int(x) not in self.eliminated]
                        if by:
                            self._bark(int(self.rng.choice(by)), "play-slower", turn=turn, source="event", ctx={"targets": [seat]})
                    # A4: the same card again and again — a game changer's casts were counted by loop_tick above;
                    # every other card counts here, and the fourth cast in a turn calls the loop (after the flurry
                    # line, so the more specific call evicts the generic "slow down", not the other way round)
                    if spell and spell not in self.game_changers.get(seat, set()):
                        self.cast_tick(seat, spell, turn)
                elif kind == "left":
                    by = e.get("by"); owners = [int(x) for x in (e.get("seats") or [])]
                    n, tokens = int(e.get("n", 0)), int(e.get("tokens", 0))
                    commanders = e.get("commanders") or []
                    ai_owners = [o for o in owners if o != self.human_seat and self.library_for_seat(o)]
                    gone_gc = [c for c in (e.get("cards") or []) if any(c in self.game_changers.get(o, set()) for o in owners)]
                    said_gone = False
                    if gone_gc and by is not None and int(by) in owners:
                        # the owner bounced or sacrificed its own game changer: no relief — an engine turning (game 47)
                        for c in gone_gc:
                            self.loop_tick(int(by), c, turn)
                        gone_gc = []
                    if gone_gc and n < 3:
                        # a game changer left the board: someone other than its owner is glad
                        others = [x for x in self.seat_libraries if int(x) not in owners and int(x) not in self.eliminated]
                        if others:
                            said_gone = self._bark(int(self.rng.choice(others)), "gc-gone", turn=turn, source="event",
                                                        ctx={"targets": owners, "card": card_slug(gone_gc[0]), "card_kind": "gc"})
                    if n >= 3 and len(set(owners)) >= 2:
                        self._sweeps += 1
                        swept = "not-again-sweep" if self._sweeps >= 2 and "not-again-sweep" in self.table_ids else "got-swept"
                        if by is not None and int(by) != self.human_seat and self.library_for_seat(int(by)):
                            self._bark(int(by), "sweep", turn=turn, source="event", ctx={"targets": [o for o in owners if o != int(by)]})
                        self._atom("sweep", [int(x) for x in self.seat_libraries if by is None or int(x) != int(by)], actor=int(by) if by is not None else None)
                        for o in ai_owners:
                            if by is None or o != int(by):
                                self._bark(o, swept, turn=turn, source="event", p=self.table_p(swept) if swept != "got-swept" else None,
                                                ctx={"aggressor": int(by) if by is not None else None, "human_cause": by is not None and int(by) == self.human_seat})
                    elif commanders:
                        for o in ai_owners:
                            self._bark(o, "lost-commander", turn=turn, source="event",
                                            ctx={"aggressor": int(by) if by is not None and int(by) != o else None,
                                                 "human_cause": by is not None and int(by) == self.human_seat,
                                                 "card": self._who.get(o, ""), "card_kind": "cmd"})
                    elif by is not None and n > tokens and all(int(by) != o for o in owners) and not said_gone:
                        if int(by) != self.human_seat and self.library_for_seat(int(by)):
                            self._bark(int(by), "removal", turn=turn, source="event", ctx={"targets": owners})
                        elif int(by) == self.human_seat and ai_owners:
                            # the human's spot removal: the owner objects (round 31)
                            self._bark(ai_owners[0], "oh-no", turn=turn, source="event", p=self.barks_human_p,
                                            ctx={"targets": [], "aggressor": int(by), "human_cause": True})
                elif kind == "gameover":
                    pass   # the final sequence in scan_observer plays the winner's line, then Joshua, then locks
                elif kind == "countered":
                    by, victim = e.get("by"), e.get("seat")
                    n = self._countered_n.get(int(victim), 0) + 1 if victim is not None else 0
                    if victim is not None:
                        self._countered_n[int(victim)] = n
                    if (victim is not None and int(victim) != self.human_seat and self.library_for_seat(int(victim)) and n and n % 3 == 0
                            and "again-countered" in self.table_ids):
                        self._bark(int(victim), "again-countered", turn=turn, source="event", p=self.table_p("again-countered"),
                                        ctx={"targets": [], "aggressor": int(by) if by is not None else None,
                                             "human_cause": by is not None and int(by) == self.human_seat})
                    elif by is not None and int(by) != self.human_seat and self.library_for_seat(int(by)):
                        self._bark(int(by), "counter", turn=turn, source="event",
                                        ctx={"targets": [int(victim)] if victim is not None else [], "aggressor": None})
                    elif victim is not None and int(victim) != self.human_seat:
                        self._bark(int(victim), "got-countered", turn=turn, source="event",
                                        ctx={"targets": [], "aggressor": int(by) if by is not None else None,
                                             "human_cause": by is not None and int(by) == self.human_seat})
            except (TypeError, ValueError):
                continue
            finally:
                self._ring_seq = None

    # -- sources
    def scan_advisor(self) -> None:
        """The advisor's stream, by complete lines (`_tail`: a line caught mid-write is read
        whole next scan, never lost — Gemini P1; a new session file restarts the cursor)."""
        for raw in self._tail(self.logs / "advisor-0.jsonl", "advisor"):
            try:
                r = json.loads(raw)
            except ValueError:
                continue
            k = r.get("kind")
            if k == "advice" and r.get("text"):
                self.enqueue("advice", text=first_sentence(r["text"]), seq=r.get("seq"), ttl=25.0)
            elif k == "ask" and r.get("answer"):
                self.enqueue("ask", text=first_sentence(r["answer"], ASK_MAX), ttl=60.0)
            elif k == "color" and r.get("text") and self.color_mode != "off":
                self._voice_color(r)
            elif k == "quip" and r.get("id"):
                self.enqueue("quip", stock=str(r["id"]), ttl=20.0)
            elif k == "bark" and r.get("id") and r.get("seat") is not None:
                try:
                    seat, pid = int(r["seat"]), str(r["id"])
                except (TypeError, ValueError):
                    continue
                # the advisor's tag names no card; a commander tag can still take the seat's own commander line
                ctx = {"targets": [], "card": self._who.get(int(seat), ""), "card_kind": "cmd"} if pid in ("commander-cast", "lost-commander") else None
                self._bark(seat, pid, turn=r.get("turn"), source="recap" if r.get("with") == "color" else "advice", ctx=ctx)
            elif k == "chosen" and r.get("seq") is not None:
                self.answered.add(int(r["seq"]))

    @staticmethod
    def _compact_card(c: dict) -> dict:
        """A battlefield card for the observer tape: its name, and power / toughness /
        tapped only when the snapshot carries them (absent = untapped, no body)."""
        out = {"name": c.get("name")}
        for k in ("power", "toughness", "types"):                # types: the replay's `_lands` needs to know a land (seam critic)
            if c.get(k) is not None:
                out[k] = c[k]
        if c.get("tapped"):
            out["tapped"] = True
        return out

    def scan_observer(self, d: dict | None = None) -> None:
        """The observer snapshot. Live: stat first, and parse only when (mtime_ns, size)
        moved since the last successful parse — an idle table costs a stat a poll (§3);
        a torn read leaves the signature as it was, so the next poll re-reads. Replay
        (E2): the snapshot is handed in as `d` and the file is not touched."""
        if d is None:
            path = self.mailbox / "observer-state.json"
            try:
                st = path.stat()
            except OSError:
                return
            sig = (st.st_mtime_ns, st.st_size)
            if sig == self._snap_sig:
                return
            try:
                d = json.loads(path.read_text())
            except (OSError, ValueError):
                return
            self._snap_sig = sig
        gid = d.get("gameId") or d.get("timestamp") and "live"
        if not self.started_said:
            self.started_said = True
            if (d.get("turn") or 0) <= 1 and not d.get("gameOver"):
                self.enqueue("startup", stock="startup", ttl=30.0)
            # a restart mid-game (supervisor, code reload) says nothing until the next event
        turn, active = d.get("turn"), d.get("activeSeat")
        self._prev_snapshot = self._last_snapshot
        self._last_snapshot = d
        events = d.get("events") or []
        last_seq = events[-1].get("seq") if events and isinstance(events[-1], dict) else None    # A8: the ring's length saturates at 30; its seq does not
        seat_recs = [x for x in d.get("seats") or [] if isinstance(x, dict)]
        fp = (turn, d.get("phase"), active, last_seq, tuple(d.get("stack") or []),
              tuple((x.get("seat"), x.get("life"), x.get("handSize"), len(x.get("battlefield") or [])) for x in seat_recs))
        if fp != self._board_fp:
            self._board_fp, self._board_changed_at, self._idle_noted = fp, self.clock(), False
            self._tape(OBSERVER_TAPE, {
                "ts": round(time.time(), 3), "clock": round(self.clock(), 3), "gameId": d.get("gameId"), "turn": turn, "phase": d.get("phase"), "activeSeat": active,
                "gameOver": bool(d.get("gameOver")), "stack": d.get("stack") or [], "stackDetail": d.get("stackDetail") or [], "seq": last_seq,
                "seats": [{"seat": x.get("seat"), "life": x.get("life"), "handSize": x.get("handSize"), "pool": x.get("pool"),
                           "eliminated": bool(x.get("eliminated")),
                           "battlefield": [self._compact_card(c) for c in x.get("battlefield") or [] if isinstance(c, dict)]} for x in seat_recs]})
        self.scan_events(d)
        if self.barks_mode != "off" and not self.final_locked and not d.get("gameOver"):
            self.scan_stack(d)
            self.scan_combos(d)
            self.human_mulligans(d)
        seats = [s for s in (d.get("seats") or []) if isinstance(s, dict) and s.get("seat") is not None]
        if seats and (turn or 0) >= 1:
            # Forge drops a loser from its in-game list once the leaving-the-game cleanup is done; the
            # observer's `eliminated` flag shows only when a poll lands inside that window (game 48: the
            # human and Purphoros vanished unflagged, Giada was caught — one exit line of three). A seat
            # the snapshot listed before and lists no more has left the game.
            present = {int(s["seat"]) for s in seats}
            vanished = sorted(sid for sid in self._seen_seats if sid not in present and sid not in self.eliminated)
            self._seen_seats |= present
            for sid in vanished:
                self.record("noted", kind="event", why="seat gone from the snapshot: eliminated", seat=sid)
            seats = seats + [{"seat": sid, "eliminated": True, "vanished": True} for sid in vanished]
        for s in seats:
            if s.get("eliminated") and s.get("seat") not in self.eliminated:
                self.eliminated.add(s.get("seat"))
                if d.get("gameOver") and s.get("seat") == self.human_seat:
                    continue  # the game-over pair covers the human's own last stand; the AI seats still get their exit lines
                if s.get("seat") == self.human_seat:
                    # the human's own death (Ben, 2026-09-07): one line from the
                    # rotation, straight away, ahead of the rate limit
                    rotation = self.renderer.manifest.get("human_out") or ["winner-none"]
                    self.enqueue("human_out", stock=self.rng.choice(rotation), ttl=60.0)
                else:
                    # one line, at once: the dying seat's own exit bark (ELIM_SEAT_P) or Joshua's
                    # Ben (2026-09-11): when several die at once, every one of them gets its exit line —
                    # these queue without evicting each other (and Joshua's stands in for a voiceless seat)
                    lib = self.library_for_seat(s.get("seat")) if self.barks_mode != "off" else ""
                    if lib and (d.get("gameOver") or self.rng.random() < ELIM_SEAT_P):
                        self.enqueue("event", stock="eliminated", library=lib, seat=int(s.get("seat")), ttl=30.0, ctx={"targets": []}, evict=False)
                    else:
                        self.enqueue("event", stock="player-eliminated", ttl=30.0)
                    # who finished them? the last seat to hit them this turn gets the kill line
                    hit = self._last_hit_by.get(int(s.get("seat")))
                    if hit and hit[1] == turn:
                        killers = [h for h in hit[0] if h != self.human_seat and self.library_for_seat(h) and h not in self.eliminated]
                        if killers:
                            self._bark(killers[-1], "kill", turn=turn, source="event", ctx={"targets": []})
                            self._atom("kill", [int(x) for x in self.seat_libraries if int(x) != killers[-1]], actor=killers[-1])
        living = [s.get("seat") for s in seats if s.get("seat") is not None and not s.get("eliminated")]
        if len(living) == 2 and not self._heads_up_said and not d.get("gameOver") and self.barks_mode != "off" and "heads-up" in self.table_ids:
            self._heads_up_said = True
            for sid in living:
                if sid != self.human_seat and self.library_for_seat(int(sid)):
                    other = [x for x in living if x != sid]
                    self._bark(int(sid), "heads-up", turn=turn, source="event", p=self.table_p("heads-up"),
                                    ctx={"targets": other}, gap=0.6, evict=False)
                    break
        for s in seats:
            sid, pool = s.get("seat"), s.get("pool") or 0
            if sid is None or sid == self.human_seat:
                continue
            if pool >= self.barks_mana and sid not in self._pool_high:
                self._pool_high.add(sid)
                if self.library_for_seat(sid):
                    self._bark(int(sid), "big-mana", turn=turn, source="event", ctx={"targets": []})
            elif pool < self.barks_mana:
                self._pool_high.discard(sid)
        if turn is not None and (turn, active) != (self.seen_turn, self.seen_active):
            if active == self.human_seat and self.your_move_mode != "off" and self.seen_turn is not None and not self.executive_on():
                if self.your_move_mode == "on" or self.rng.random() < self.your_move_p:
                    self.enqueue("your_move", stock="your-move", ttl=12.0)   # not while the advisor plays the seat
                else:
                    self.record("skipped", kind="your_move", why="dice (ARENA_VOICE_YOUR_MOVE=some)", stock="your-move")
            follow = False
            if self.seen_turn is not None and self.barks_mode != "off" and not d.get("gameOver"):
                follow = self.turn_boundary(d, turn, active)
            if (active is not None and active != self.human_seat and self.seen_turn is not None
                    and self.barks_opener_p > 0 and self.barks_mode != "off" and self.library_for_seat(int(active))):
                # option A: an opener at a seat's turn start — rare, like a person who sometimes says "right, me"
                self.opener(d, turn, active, follow=follow)
            self.seen_turn, self.seen_active = turn, active
        if d.get("gameOver") and not self.game_over_said:
            self.game_over_said = True
            human = next((s for s in seats if s.get("seat") == self.human_seat), None)
            won = human is not None and not human.get("eliminated")
            # everything pending is moot now — except the exit lines of seats that died in this last
            # moment, which play first (Ben, 2026-09-11); then the winning seat's own line (if a
            # voiced AI won), Joshua's verdict, Joshua's sign-off — then silence
            exits = [q for q in self.queue if q["kind"] == "event" and q["stock"] in ("eliminated", "player-eliminated")]
            for q in self.queue:
                if q not in exits:
                    self.record("dropped", kind=q["kind"], why="game over", stock=q["stock"])
            for q in exits:
                q["prio"], q["expires"], q["gap"] = -1.0, self.clock() + 120.0, 0.6
            self.queue = exits
            winner = self._winner_seat(d, seats)
            t = self.clock()
            if winner is not None and winner != self.human_seat and self.library_for_seat(winner) and self.barks_mode != "off":
                self.queue.append({"kind": "game_over", "text": "", "stock": "win", "seq": None, "prio": PRIORITY["game_over"],
                                   "at": t, "expires": t + 120.0, "library": self.library_for_seat(winner), "seat": winner,
                                   "ctx": {}, "gap": None, "chain": None})
            self.queue.append({"kind": "game_over", "text": "", "stock": "you-win" if won else "strange-game", "seq": None,
                               "prio": PRIORITY["game_over"], "at": t + 0.001, "expires": t + 120.0,
                               "library": "", "seat": None, "ctx": {}, "gap": None, "chain": None})
            self.queue.append({"kind": "game_over", "text": "", "stock": "game-over-gg", "seq": None,
                               "prio": PRIORITY["game_over"], "at": t + 0.002, "expires": t + 120.0,
                               "library": "", "seat": None, "ctx": {}, "gap": None, "chain": None})
            self.final_locked = True
            stop = getattr(self, "stop_atoms", None)
            if stop is not None:
                stop()                                    # the under channel and any pending murmur die with the lock
            self.say("[voice] game over — final sequence queued, everything else is silenced")

    def publish_speaking(self, item: dict | None, seconds: float) -> None:
        """logs/voice-speaking.json — {"seat": N, "until": epoch_ms} while one of
        the SEATS is talking, {} otherwise. The match screen (VAdvisor) brings
        that seat's field tab forward for the line and puts the old tab back
        (Ben, 2026-09-10). Joshua and the human never move the tabs."""
        try:
            f = self.logs / "voice-speaking.json"
            if item is not None and item.get("seat") is not None and item.get("library"):
                body = {"seat": int(item["seat"]), "library": item["library"], "stock": item.get("stock", ""),
                        "until": int((time.time() + seconds) * 1000)}
            else:
                body = {}
            tmp = f.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(body))
            tmp.replace(f)
        except OSError:
            pass

    def publish_state(self) -> None:
        """mailbox/seat-0-voice/state.json {"live": bool, "reason": str,
        "enabled": bool} — rewritten only when it changes."""
        live, reason = self.renderer.state()
        cur = {"live": live, "reason": reason, "enabled": self.enabled()}
        if cur == self._state_published:
            return
        self._state_published = cur
        try:
            d = self.mailbox / "seat-0-voice"
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / "state.json.tmp"
            tmp.write_text(json.dumps(cur))
            tmp.replace(d / "state.json")
        except OSError:
            pass
        # log LIVE transitions only — a mute/unmute also changes the state file
        # (game 32: "live lines back on" printed on a mute click)
        if self._live_published is None or live != self._live_published:
            if not live:
                self.say(f"[voice] live lines off ({reason}) — stock phrases only; the advisor will quip more often")
            elif self._live_published is not None:
                self.say("[voice] live lines back on")
        self._live_published = live

    def publish_final(self) -> None:
        """mailbox/seat-0-voice/final.json once the final sequence has played:
        the teardown watcher (arena-autostop) stops the table a few seconds after
        the last line instead of a fixed linger (Ben, game 44)."""
        try:
            d = self.mailbox / "seat-0-voice"
            d.mkdir(parents=True, exist_ok=True)
            f = d / "final.json"
            if not f.exists():
                f.write_text(json.dumps({"done": round(time.time(), 3)}))
                self.say("[voice] final sequence done — the table may be torn down")
        except OSError:
            pass

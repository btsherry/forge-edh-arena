"""The voice runner's sources — EventsMixin, mixed into VoiceRunner
(runner/voice_runner.py), which supplies the state, say/record, the renderer and
the table. Here: the advisor's stream (advice, asks, quips, colour, bark tags), the
observer snapshot (startup, turn boundaries and openers, eliminations, heads-up,
big mana, the final sequence), the snapshot's public event ring (attacks, damage,
casts, removal, counters), the stack, the combos, the seat runners' game log
(mulligans), the slow-seat mutters, the board readers, the state files published
for the GUI and the teardown watcher, and the constants these use. Split out of
voice_runner.py on 2026-09-14 (voicework2 hardening plan, Phase 0a) with no
behaviour change; voice_runner re-exports every public name here. This module
never imports voice_runner."""
from __future__ import annotations

import json
import re
import time

from voice.scheduler import MULL_DIG_WORDS, MULL_LINE, MULL_P, MULL_SCREW_WORDS, PRIORITY
from voice.table import card_kind, card_slug

FIRST_SENTENCE_MAX = 220
ASK_MAX = 300
LOOP_AT = 2               # the second time the same card is cast or bounced by its owner in one turn: a loop, not a fresh event
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
    """The sources and what they queue; VoiceRunner.__init__ owns every attribute used here."""

    @staticmethod
    def mull_reason(why: str) -> str:
        w = (why or "").lower()
        if any(k in w for k in MULL_DIG_WORDS):
            return "mull-dig"
        if any(k in w for k in MULL_SCREW_WORDS):
            return "mull-screw"
        return "mull-pity"

    def scan_game_log(self) -> None:
        """New MULLIGAN records in the seat runners' shared game log: the seat says
        "mulligan, six" (or five, four) the moment it decides, the table answers in
        the register the reason earns; a keep at seven may be announced; a keep at
        five or fewer is called risky; a seat that kept seven may gloat."""
        if self.barks_mode == "off" or self.final_locked or "mull-to-six" not in self.table_ids:
            return
        path = self.logs / "game.jsonl"
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size <= self._game_log_pos:
            if size < self._game_log_pos:
                self._game_log_pos = 0                                         # a new game's log
            return
        try:
            with path.open("rb") as f:
                f.seek(self._game_log_pos)
                chunk = f.read(size - self._game_log_pos)
        except OSError:
            return
        self._game_log_pos = size
        for raw in chunk.splitlines():
            try:
                r = json.loads(raw)
            except ValueError:
                continue
            if r.get("type") != "MULLIGAN" or r.get("seat") is None:
                continue
            seat = int(r["seat"])
            if seat == self.human_seat or not self.library_for_seat(seat):
                continue
            keep = bool((r.get("answer") or {}).get("keep", True))
            turn = r.get("turn") or 0
            others = [int(x) for x in self.seat_libraries if int(x) != seat and int(x) not in self.eliminated]
            if not keep:
                k = self._mulls.get(seat, 0) + 1
                self._mulls[seat] = k
                pid = MULL_LINE.get(min(k, 3), "mull-to-four")
                if self.maybe_bark(seat, pid, turn=turn, source="event", p=MULL_P["own"], ctx={"targets": []}) and others:
                    # the table answers in the register the reason earns, right behind the seat's line — by a seat
                    # that has already kept or mulliganed (its own decision is not about to collide), else any free seat
                    react = self.mull_reason(str(r.get("why") or ""))
                    decided = [o for o in others if o in self._kept_seven or o in self._mulls]
                    who = int(self.rng.choice(self.free_to_speak(decided or others)))
                    if not self.maybe_bark(who, react, turn=turn, source="event", p=MULL_P["react"], ctx={"targets": [seat]}, gap=0.4, evict=False) \
                            and k >= 2 and self._kept_seven:
                        self.maybe_bark(int(self.rng.choice(self._kept_seven)), "mull-gloat", turn=turn, source="event", p=MULL_P["gloat"],
                                        ctx={"targets": [seat]}, gap=0.4, evict=False)
            else:
                k = self._mulls.get(seat, 0)
                if k == 0:
                    self._kept_seven.append(seat)
                    self.maybe_bark(seat, "keep-seven", turn=turn, source="event", p=MULL_P["keep-seven"], ctx={"targets": []})
                elif k >= 2 and others:
                    self.maybe_bark(int(self.rng.choice(self.free_to_speak(others))), "mull-risky", turn=turn, source="event", p=MULL_P["risky"], ctx={"targets": [seat]})

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
            self.maybe_bark(int(self.rng.choice(by)), line, turn=1, source="event", p=self.barks_human_p,
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

    def loop_tick(self, seat: int, card: str, turn) -> bool:
        """One more cast or self-bounce of `card` by `seat` this turn. At LOOP_AT the
        table calls the loop (a bystander, then the owner may relish it). True when
        this event is part of a loop and the card's own lines should stay quiet."""
        self._roll_turn(turn)                                   # the turn's counters roll before this event counts
        key = (int(seat), card)
        n = self._card_events_turn.get(key, 0) + 1
        self._card_events_turn[key] = n
        if n < LOOP_AT:
            return False
        if n == LOOP_AT and "loop" in self.table_ids:
            by = [int(x) for x in self.seat_libraries if int(x) != int(seat) and int(x) not in self.eliminated]
            if by:
                said = self.maybe_bark(int(self.rng.choice(self.free_to_speak(by))), "loop", turn=turn, source="event", ctx={"targets": [int(seat)]})
                if said and self.library_for_seat(int(seat)):
                    self.maybe_bark(int(seat), "looping", turn=turn, source="event", p=0.5, ctx={"targets": []}, gap=0.4, evict=False)
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
            self.record("skipped", kind="color", why="dice (ARENA_VOICE_COLOR=some)", text=r["text"][:80])

    def slow_seats(self) -> list[int]:
        """AI seats with a decision pending in their mailbox longer than ARENA_BARKS_SLOW."""
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
        if self.maybe_bark(int(seat), pid, turn=turn, source="procedural", p=p, ctx=ctx):
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
                    queued = self.maybe_bark(int(ended), "land-go", turn=self.seen_turn, source="procedural", p=self.table_p("land-go"), ctx={"targets": nxt})
                elif st["casts"] > 0:
                    if up >= 3 and hand >= 2:
                        pid = "mana-up"
                    elif up == 0 and hand >= 1:
                        pid = "tapped-out"
                    else:
                        pid = "pass"
                    queued = self.maybe_bark(int(ended), pid, turn=self.seen_turn, source="procedural", p=self.table_p(pid), ctx={"targets": nxt})
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
            if self.maybe_bark(int(active), "come-on-land", turn=turn, source="opener", p=self.table_p("come-on-land"), gap=gap, evict=evict):
                return
        if int(turn) <= 4 and "early-game" in self.table_ids and self.rng.random() < self.table_p("early-game"):
            if self.maybe_bark(int(active), "early-game", turn=turn, source="opener", p=self.barks_opener_p, gap=gap, evict=evict):
                return
        pid = "untap-draw" if self.table_ids and "untap-draw" in self.table_ids and self.rng.random() < self.table_p("untap-draw") else "my-turn"
        self.maybe_bark(int(active), pid, turn=turn, source="opener", p=self.barks_opener_p, gap=gap, evict=evict)

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
                self.maybe_bark(int(victim), "hold-on", turn=turn, source="procedural", p=self.table_p("hold-on"),
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
                    self.maybe_bark(int(seat), "engine-online", turn=d.get("turn"), source="event", ctx={"targets": [], **ctx}, gap=0.5, evict=False)
                elif int(seat) == self.human_seat:
                    by = [x for x in self.seat_libraries if int(x) not in self.eliminated]
                    if by:
                        self.maybe_bark(int(self.rng.choice(by)), "oh-no", turn=d.get("turn"), source="event", p=self.barks_human_p,
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
                    self.maybe_bark(int(seat), "thinking", turn=self._last_snapshot.get("turn"), source="procedural", p=self.table_p("thinking"))
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
            self._event_seq = seq
            if self.barks_mode == "off" or self.final_locked:
                continue
            kind, turn = e.get("kind"), e.get("turn")
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
                        self.maybe_bark(who, "you-promised", turn=turn, source="event", p=self.table_p("you-promised"),
                                        ctx={"targets": [], "aggressor": seat, "human_cause": seat == self.human_seat})
                    elif seat != self.human_seat and big:
                        self.maybe_bark(seat, "big-swing", turn=turn, source="event",
                                        ctx={"targets": defenders, "aggressor": None, "open": open_})
                    elif seat != self.human_seat and self.library_for_seat(seat) and power > 0:
                        # a smaller attack: "just a poke" / "you take this one" (the defender may answer "no blocks")
                        pid = "attack-you" if power * 2 >= self.barks_swing and len(defenders) == 1 else "poke"
                        self.maybe_bark(seat, pid, turn=turn, source="procedural", p=self.table_p(pid),
                                        ctx={"targets": defenders, "aggressor": None, "open": open_})
                    elif seat == self.human_seat:
                        # the human swings: a defender braces, complains, or admits it has no blocks (round 31)
                        voiced_def = [x for x in defenders if x != self.human_seat and self.library_for_seat(x) and x not in self.eliminated]
                        if voiced_def and (big or open_):
                            who = int(self.rng.choice(open_ or voiced_def))
                            line = "no-blocks" if who in open_ and "no-blocks" in self.table_ids else self.rng.choice(["brace", "why-me"])
                            self.maybe_bark(who, line, turn=turn, source="event", p=self.barks_human_p,
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
                            if self.maybe_bark(victim, "grudge", turn=turn, source="event", p=self.table_p("grudge"),
                                               ctx={"targets": [], "aggressor": froms[0], "human_cause": froms[0] == self.human_seat}):
                                continue                                # "you again?!" stands in for that-hurt / take-it this time
                    if amount < self.barks_hit:
                        if e.get("combat") and amount > 0 and victim != self.human_seat and self.library_for_seat(victim) and "take-it" in self.table_ids:
                            self.maybe_bark(victim, "take-it", turn=turn, source="procedural", p=self.table_p("take-it"),
                                            ctx={"targets": [], "aggressor": froms[0] if froms else None, "human_cause": self.human_seat in froms})
                        continue
                    if victim != self.human_seat:
                        self.maybe_bark(victim, "that-hurt", turn=turn, source="event",
                                        ctx={"targets": [], "aggressor": froms[0] if froms else None, "human_cause": self.human_seat in froms})
                    else:
                        hitters = [x for x in froms if x != self.human_seat and self.library_for_seat(x)]
                        if hitters:
                            self.maybe_bark(hitters[0], "landed-hit", turn=turn, source="event",
                                            ctx={"targets": [self.human_seat], "aggressor": None})
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
                            self.maybe_bark(int(self.rng.choice(by)), line, turn=turn, source="event",
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
                                self.maybe_bark(seat, "game-changer", turn=turn, source="event",
                                                ctx={"targets": [], "card": card_slug(spell), "card_kind": "gc"})
                            self._gc_cast_seen.add((seat, spell))
                        elif e.get("commander"):
                            self.maybe_bark(seat, "commander-cast", turn=turn, source="event",
                                            ctx={"targets": [], "card": self._who.get(seat, ""), "card_kind": "cmd"})
                        elif not self.narrate_cast(seat, spell, int(e.get("cmc", 0)), turn) and int(e.get("cmc", 0)) >= 5:
                            # no narration: a big spell still draws a bystander's reaction — wow at seven-plus, else admiration / read that / oh no
                            # (when the caster narrates, the reaction comes as the chain's reply to that line)
                            by = [x for x in self.seat_libraries if int(x) != seat and int(x) not in self.eliminated]
                            if by:
                                line = "wow" if int(e.get("cmc", 0)) >= 7 else self.rng.choice(["nice-play", "read-that", "oh-no"])
                                self.maybe_bark(int(self.rng.choice(by)), line, turn=turn, source="event", ctx={"targets": [seat]})
                    # a flurry — three spells inside thirty seconds — earns "slow down" from someone else
                    now_t = time.time()
                    recent = [t for t in self._casts.get(seat, []) if now_t - t < 30] + [now_t]
                    self._casts[seat] = recent
                    if len(recent) >= 3 and seat != self.human_seat:
                        by = [x for x in self.seat_libraries if int(x) != seat and int(x) not in self.eliminated]
                        if by:
                            self.maybe_bark(int(self.rng.choice(by)), "play-slower", turn=turn, source="event", ctx={"targets": [seat]})
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
                            said_gone = self.maybe_bark(int(self.rng.choice(others)), "gc-gone", turn=turn, source="event",
                                                        ctx={"targets": owners, "card": card_slug(gone_gc[0]), "card_kind": "gc"})
                    if n >= 3 and len(set(owners)) >= 2:
                        self._sweeps += 1
                        swept = "not-again-sweep" if self._sweeps >= 2 and "not-again-sweep" in self.table_ids else "got-swept"
                        if by is not None and int(by) != self.human_seat and self.library_for_seat(int(by)):
                            self.maybe_bark(int(by), "sweep", turn=turn, source="event", ctx={"targets": [o for o in owners if o != int(by)]})
                        for o in ai_owners:
                            if by is None or o != int(by):
                                self.maybe_bark(o, swept, turn=turn, source="event", p=self.table_p(swept) if swept != "got-swept" else None,
                                                ctx={"aggressor": int(by) if by is not None else None, "human_cause": by is not None and int(by) == self.human_seat})
                    elif commanders:
                        for o in ai_owners:
                            self.maybe_bark(o, "lost-commander", turn=turn, source="event",
                                            ctx={"aggressor": int(by) if by is not None and int(by) != o else None,
                                                 "human_cause": by is not None and int(by) == self.human_seat,
                                                 "card": self._who.get(o, ""), "card_kind": "cmd"})
                    elif by is not None and n > tokens and all(int(by) != o for o in owners) and not said_gone:
                        if int(by) != self.human_seat and self.library_for_seat(int(by)):
                            self.maybe_bark(int(by), "removal", turn=turn, source="event", ctx={"targets": owners})
                        elif int(by) == self.human_seat and ai_owners:
                            # the human's spot removal: the owner objects (round 31)
                            self.maybe_bark(ai_owners[0], "oh-no", turn=turn, source="event", p=self.barks_human_p,
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
                        self.maybe_bark(int(victim), "again-countered", turn=turn, source="event", p=self.table_p("again-countered"),
                                        ctx={"targets": [], "aggressor": int(by) if by is not None else None,
                                             "human_cause": by is not None and int(by) == self.human_seat})
                    elif by is not None and int(by) != self.human_seat and self.library_for_seat(int(by)):
                        self.maybe_bark(int(by), "counter", turn=turn, source="event",
                                        ctx={"targets": [int(victim)] if victim is not None else [], "aggressor": None})
                    elif victim is not None and int(victim) != self.human_seat:
                        self.maybe_bark(int(victim), "got-countered", turn=turn, source="event",
                                        ctx={"targets": [], "aggressor": int(by) if by is not None else None,
                                             "human_cause": by is not None and int(by) == self.human_seat})
            except (TypeError, ValueError):
                continue

    # -- sources
    def scan_advisor(self) -> None:
        path = self.logs / "advisor-0.jsonl"
        try:
            st = path.stat()
        except OSError:
            return
        if self._adv_inode != st.st_ino or st.st_size < self._adv_pos:
            self._adv_inode, self._adv_pos = st.st_ino, 0     # new session file (arena-stop archived the old one)
        with path.open("rb") as f:
            f.seek(self._adv_pos)
            chunk = f.read()
            # only complete lines advance the cursor: a line caught mid-write
            # is re-read whole next scan instead of being lost (Gemini P1)
            cut = chunk.rfind(b"\n")
            if cut < 0:
                return
            chunk = chunk[:cut + 1]
            self._adv_pos += len(chunk)
        for raw in chunk.decode("utf-8", "replace").splitlines():
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
                self.maybe_bark(seat, pid, turn=r.get("turn"), source="recap" if r.get("with") == "color" else "advice", ctx=ctx)
            elif k == "chosen" and r.get("seq") is not None:
                self.answered.add(int(r["seq"]))

    def scan_observer(self) -> None:
        path = self.mailbox / "observer-state.json"
        try:
            d = json.loads(path.read_text())
        except (OSError, ValueError):
            return
        gid = d.get("gameId") or d.get("timestamp") and "live"
        if not self.started_said:
            self.started_said = True
            if (d.get("turn") or 0) <= 1 and not d.get("gameOver"):
                self.enqueue("startup", stock="startup", ttl=30.0)
            # a restart mid-game (supervisor, code reload) says nothing until the next event
        turn, active = d.get("turn"), d.get("activeSeat")
        self._prev_snapshot = self._last_snapshot
        self._last_snapshot = d
        fp = (turn, d.get("phase"), active, len(d.get("events") or []), tuple(d.get("stack") or []),
              tuple((x.get("seat"), x.get("life"), x.get("handSize"), len(x.get("battlefield") or [])) for x in d.get("seats") or [] if isinstance(x, dict)))
        if fp != self._board_fp:
            self._board_fp, self._board_changed_at, self._idle_noted = fp, self.clock(), False
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
                            self.maybe_bark(killers[-1], "kill", turn=turn, source="event", ctx={"targets": []})
        living = [s.get("seat") for s in seats if s.get("seat") is not None and not s.get("eliminated")]
        if len(living) == 2 and not self._heads_up_said and not d.get("gameOver") and self.barks_mode != "off" and "heads-up" in self.table_ids:
            self._heads_up_said = True
            for sid in living:
                if sid != self.human_seat and self.library_for_seat(int(sid)):
                    other = [x for x in living if x != sid]
                    self.maybe_bark(int(sid), "heads-up", turn=turn, source="event", p=self.table_p("heads-up"),
                                    ctx={"targets": other}, gap=0.6, evict=False)
                    break
        for s in seats:
            sid, pool = s.get("seat"), s.get("pool") or 0
            if sid is None or sid == self.human_seat:
                continue
            if pool >= self.barks_mana and sid not in self._pool_high:
                self._pool_high.add(sid)
                if self.library_for_seat(sid):
                    self.maybe_bark(int(sid), "big-mana", turn=turn, source="event", ctx={"targets": []})
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

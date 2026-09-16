"""Lane E1 of the voicework2 hardening plan (2026-09-14) — the voice runner's sources:
stat before parse (§3), the board fingerprint on the ring's seq (A8), one `_tail` for
both appended logs (A9), a `gap` record when the ring rolls past a poll (B2), the
event seq on ring barks and the two tapes (C1, §4.3), the three loop triggers (A4)
and the seat brain's intent from game.jsonl — `cycle` and the `say` key (§4.4).

Everything runs against the synthetic tree of test_table_lines (the REAL table ids,
silent takes; Giada is the human at seat 0, Urza/Harry seat 1, Purphoros/Bill seat 2,
Selvala voiceless at seat 3; the dice always pass). Run: python3 -m unittest discover -s tests
"""
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voice import events as ev_mod  # noqa: E402
from seatd import rules as seat_rules  # noqa: E402
from test_table_lines import _TableCase  # noqa: E402


def cast(seq, seat, spell, turn, cmc=1):
    return {"seq": seq, "kind": "cast", "turn": turn, "seat": seat, "spell": spell, "commander": False, "cmc": cmc}


class _EventsCase(_TableCase):
    def _board(self, turn, active, seats=None, events=(), **kw):
        return {"turn": turn, "phase": "MAIN1", "activeSeat": active, "gameOver": False,
                "seats": seats or [self._seat(i) for i in range(4)], "events": list(events), **kw}

    def _write(self, d):
        (self.mailbox / "observer-state.json").write_text(json.dumps(d))

    def _tape(self, name):
        f = self.logs / name
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

    def _prime(self):
        """The first read learns the ring's seq (history is never replayed); then seat 1's turn begins."""
        self._snap(4, 0, events=[cast(1, 3, "x", 3)]); self.r.queue.clear()
        self._snap(5, 1); self.r.queue.clear()

    def _assert_wall_ts(self, rec):
        """Both tapes carry the wall clock as `ts` (so a tape lines up with game.jsonl and voice-0.jsonl)
        and the runner's clock as `clock` (so a replay with a fake clock can follow the timing)."""
        self.assertIsInstance(rec["ts"], float)
        self.assertLess(abs(time.time() - rec["ts"]), 60.0, "ts is the wall clock, not the runner's")

    def _log(self, **rec):
        """One seat-runner record in game.jsonl, shaped like seatd.runner._record's shared line — stamped
        now (a record older than INTENT_MAX_AGE_S is history, not a line; see StaleIntent)."""
        with (self.logs / "game.jsonl").open("a") as f:
            f.write(json.dumps({"ts": time.time(), "deck": "x", "phase": "MAIN1", "type": "CAST_SPELL", "seq": 9, "source": "model",
                                "answer": {"chosenId": 1}, "why": "", **rec}) + "\n")


class Observer(_EventsCase):
    def test_stat_first_the_snapshot_is_parsed_once_per_change_and_a_torn_read_is_retried(self):
        parsed = []
        self.r.scan_events = lambda d: parsed.append(d.get("turn"))
        self._write(self._board(3, 1)); self.r.scan_observer()
        self.assertEqual(parsed, [3])
        for _ in range(3):
            self.r.scan_observer()
        self.assertEqual(parsed, [3], "the same mtime and size: a stat, no read, no parse")
        self._write(self._board(4, 2)); self.r.scan_observer()
        self.assertEqual(parsed, [3, 4])
        sig = self.r._snap_sig
        (self.mailbox / "observer-state.json").write_text('{"turn": 5, "activeSe')            # caught mid-write
        self.r.scan_observer()
        self.assertEqual(parsed, [3, 4]); self.assertEqual(self.r._snap_sig, sig, "a torn read leaves the signature as it was: the next poll re-reads")
        self._write(self._board(5, 3)); self.r.scan_observer()
        self.assertEqual(parsed, [3, 4, 5])
        sig = self.r._snap_sig
        self.r.scan_observer(self._board(6, 0))                                                  # replay: handed in, the file untouched
        self.assertEqual(parsed, [3, 4, 5, 6]); self.assertEqual(self.r._snap_sig, sig)
        self.assertEqual(self.r._last_snapshot["turn"], 6)

    def test_the_board_fingerprint_follows_the_ring_seq_when_the_ring_is_full(self):
        ring = [cast(i, 3, f"c{i}", 3) for i in range(1, 31)]                                   # EVENT_RING = 30: a full ring
        self._write(self._board(3, 1, events=ring)); self.r.scan_observer()
        self.assertEqual(self.r._board_changed_at, self.clock.t); self.assertEqual(self.r._board_fp[3], 30)
        self.clock.t += 50
        ring = ring[1:] + [cast(31, 3, "c31", 3)]                                                # the ring rolled by one: same length, same seats
        self._write(self._board(3, 1, events=ring)); self.r.scan_observer()
        self.assertEqual(self.r._board_changed_at, self.clock.t, "the table is not idle: the fingerprint saw the seq move (A8)")
        self.assertEqual(self.r._board_fp[3], 31)
        self.assertEqual([(t["seq"], t["turn"]) for t in self._tape("events.jsonl")], [(31, 3)], "one event consumed; the primed history was not taped")

    def test_a_jump_in_the_ring_seq_is_recorded_as_a_gap_once(self):
        self._write(self._board(3, 1, events=[cast(1, 3, "a", 3)])); self.r.scan_observer()
        ev = [cast(5, 3, "e", 3), cast(6, 3, "f", 3)]
        self._write(self._board(3, 1, events=ev)); self.r.scan_observer()
        self.assertEqual([(g["missed"], g["seq"], g["kind"]) for g in self._records("gap")], [(3, 5, "event")], "seqs 2-4 rolled out of the ring between two polls")
        ev.append(cast(7, 3, "g", 3))
        self._write(self._board(3, 1, events=ev)); self.r.scan_observer()
        self.assertEqual(len(self._records("gap")), 1, "contiguous again: no new gap")
        self.assertEqual([t["seq"] for t in self._tape("events.jsonl")], [5, 6, 7])

    def test_ring_barks_carry_the_event_seq_and_both_tapes_are_written(self):
        seats = [self._seat(0), self._seat(1, lands=(True, False), creatures=(("Bear", False),)), self._seat(2), self._seat(3)]
        self._write(self._board(3, 1, seats=seats, events=[cast(1, 3, "x", 3)])); self.r.scan_observer(); self.r.queue.clear()
        self.assertEqual(self._tape("events.jsonl"), [], "the first read primes the seq: nothing consumed, nothing taped")
        self.assertEqual(len(self._tape("observer-tape.jsonl")), 1, "the first snapshot is a change")
        ev = [cast(1, 3, "x", 3), {"seq": 2, "kind": "attack", "turn": 3, "seat": 1, "attackers": 1, "power": 9, "defenders": [0]}]
        self._write(self._board(3, 1, seats=seats, events=ev)); self.r.scan_observer()
        barks = [q for q in self.r.queue if q["kind"] == "bark"]
        self.assertEqual([(q["stock"], q["seat"], q["ctx"].get("seq")) for q in barks], [("big-swing", 1, 2)], "the queue item names the ring event (C1)")
        self.assertEqual(self._records("queued", "bark")[-1]["stock"], "big-swing")
        tape = self._tape("events.jsonl")
        self.assertEqual([(t["seq"], t["kind"], t["turn"], t["clock"], t["power"]) for t in tape], [(2, "attack", 3, self.clock.t, 9)], "the event as-is, plus turn, the runner's clock and the wall time")
        self._assert_wall_ts(tape[0])
        obs = self._tape("observer-tape.jsonl")
        self.assertEqual(len(obs), 2)
        last = obs[-1]
        self.assertEqual((last["turn"], last["phase"], last["activeSeat"], last["gameOver"], last["seq"], last["stack"], last["clock"]), (3, "MAIN1", 1, False, 2, [], self.clock.t))
        self._assert_wall_ts(last)
        s1 = next(s for s in last["seats"] if s["seat"] == 1)
        self.assertEqual((s1["life"], s1["handSize"], s1["eliminated"]), (40, 3, False))
        self.assertEqual(s1["battlefield"], [{"name": "Land 0", "types": "Land — Island", "tapped": True}, {"name": "Land 1", "types": "Land — Island"},
                                             {"name": "Bear", "types": "Creature — Thing", "power": 3, "toughness": 3}],
                         "names and types (a replay must know a land), plus power/toughness/tapped only when they say something")
        self.assertIn("stackDetail", last, "a replay sees the stack's targets too")
        self.assertNotIn("graveyard", s1); self.assertNotIn("exile", s1)                     # zone lists stay off the tape
        self.r.scan_observer(self._board(3, 1, seats=seats, events=ev))
        self.assertEqual(len(self._tape("observer-tape.jsonl")), 2, "the same board again: no change, no tape line")


class Tail(_EventsCase):
    def test_tail_delivers_complete_lines_only_and_restarts_on_a_rotated_or_truncated_file(self):
        p = self.logs / "t.jsonl"
        self.assertEqual(self.r._tail(p, "t"), [], "no file: nothing, and nothing moves")
        p.write_bytes(b"a\nb")
        self.assertEqual(self.r._tail(p, "t"), ["a"], "the half-written last line waits for the next call")
        self.assertEqual(self.r._tail(p, "t"), [])
        with p.open("ab") as f:
            f.write(b"\nc\n")
        self.assertEqual(self.r._tail(p, "t"), ["b", "c"], "delivered whole, once")
        ino = p.stat().st_ino
        p.unlink(); p.write_bytes(b"a longer first line of a new file\n")                      # replaced: larger than the old cursor
        self.assertNotEqual(p.stat().st_ino, ino)
        self.assertEqual(self.r._tail(p, "t"), ["a longer first line of a new file"], "a new inode restarts from 0")
        p.write_bytes(b"w\n")                                                                  # truncated in place: smaller than the cursor
        self.assertEqual(self.r._tail(p, "t"), ["w"], "a shrunken file restarts from 0")
        self.assertEqual(self.r._tails["t"], [p.stat().st_ino, 2])

    def test_a_mulligan_record_caught_mid_write_is_voiced_on_the_next_scan_not_lost(self):
        self._snap(0, None); self.r.queue.clear()
        rec = json.dumps({"ts": 1.0, "seat": 1, "deck": "x", "turn": 0, "phase": "", "type": "MULLIGAN", "seq": 1, "answer": {"keep": False}, "why": "Only one land"})
        with (self.logs / "game.jsonl").open("a") as f:
            f.write(rec[:40])
        self.r.scan_game_log()
        self.assertEqual(self.r.queue, [], "half a record: nothing yet, and the cursor did not move past it")
        with (self.logs / "game.jsonl").open("a") as f:
            f.write(rec[40:] + "\n")
        self.r.scan_game_log()
        self.assertEqual([(x["stock"], x["seat"]) for x in self.r.queue if x["kind"] == "bark"], [("mull-to-six", 1), ("mull-screw", 2)])

    def test_a_game_log_smaller_than_the_daemons_seed_restarts_from_zero(self):
        """The daemon seeds the game cursor from the file's size at start-up, inode unknown; a
        log replaced by a shorter one before the first scan (a new game after a hot swap) must
        not leave the runner waiting for the old length."""
        self._snap(0, None); self.r.queue.clear()
        self.r._game_log_pos = 10 ** 6
        with (self.logs / "game.jsonl").open("a") as f:
            f.write(json.dumps({"ts": 1.0, "seat": 1, "deck": "x", "turn": 0, "phase": "", "type": "MULLIGAN", "seq": 1, "answer": {"keep": False}, "why": "Meh."}) + "\n")
        self.r.scan_game_log()
        self.assertEqual([(x["stock"], x["seat"]) for x in self.r.queue if x["kind"] == "bark"][:1], [("mull-to-six", 1)])

    def test_the_advisor_stream_is_read_by_the_same_tail(self):
        line = json.dumps({"ts": 1.0, "kind": "quip", "id": "nice-combo"})
        with (self.logs / "advisor-0.jsonl").open("a") as f:
            f.write(line[:12])
        self.r.scan_advisor()
        self.assertEqual(self.r.queue, [])
        with (self.logs / "advisor-0.jsonl").open("a") as f:
            f.write(line[12:] + "\n")
        self.r.scan_advisor()
        self.assertEqual([q["stock"] for q in self.r.queue], ["nice-combo"])
        self.assertEqual(self.r._tails["advisor"], [(self.logs / "advisor-0.jsonl").stat().st_ino, len(line) + 1])


class Loops(_EventsCase):
    def test_four_casts_of_one_card_in_a_turn_call_the_loop_once(self):
        self._prime()
        ev = [cast(1, 3, "x", 3)] + [cast(1 + i, 1, "Spinning Top", 5) for i in range(1, 5)]
        self._snap(5, 1, events=ev)
        queued = self._queued_stocks()
        self.assertEqual((queued.count("looping"), queued.count("loop")), (1, 1))
        looping = [r for r in self._records("queued", "bark") if r["stock"] == "looping"]
        self.assertEqual((looping[0]["seat"], looping[0]["source"]), (1, "event"))
        q = [(x["stock"], x["seat"], x.get("gap"), x["follow"], x["ctx"].get("seq")) for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual(q, [("looping", 1, None, False, 5), ("loop", 2, 0.4, True, 5)],
                         "the owner at once, the table's reaction sequenced behind it, both stamped with the fourth cast's seq; the 'slow down' of the flurry was evicted by the call")
        self.assertEqual(self.r._card_events_turn[(1, "Spinning Top")], 4, "the game changers' per-turn count, generalised")
        self.assertEqual(len([r for r in self._records("noted") if r["why"].startswith("loop called")]), 1)
        self.r.queue.clear()
        ev += [cast(6, 1, "Spinning Top", 5), cast(7, 1, "Spinning Top", 5)]
        self._snap(5, 1, events=ev)
        self.assertEqual(self._queued_stocks().count("looping"), 1, "casts five and six: the loop was called once this turn")
        self._snap(9, 1, events=ev); self.r.queue.clear()                                       # the next turn begins (one poll)…
        ev += [cast(8 + i, 1, "Spinning Top", 9) for i in range(4)]
        self._snap(9, 1, events=ev)                                                             # …its casts arrive (the next)
        self.assertEqual(self._queued_stocks().count("looping"), 2, "a new turn: the count rolled, four more casts call it again")
        self.assertEqual(self.r._card_events_turn[(1, "Spinning Top")], 4)

    def test_a_cycle_replay_in_the_game_log_is_the_seat_declaring_its_loop(self):
        self._prime()
        self._log(seat=1, turn=5, source="cycle", why="cycle replay 3/16")
        self._log(seat=1, turn=5, source="cycle", why="cycle replay 4/16")
        self.r.scan_game_log()
        looping = [r for r in self._records("queued", "bark") if r["stock"] == "looping"]
        self.assertEqual([(r["seat"], r["source"]) for r in looping], [(1, "event")], "at once, once per turn per seat — however many decisions the cycle replays; anchored (source event) whoever noticed, since 'brain' would be an optional class")
        self.assertTrue([r for r in self._records("noted") if "cycle replay" in r["why"] and r["source"] == "brain"], "the note remembers that the brain declared it")
        self.assertEqual([(x["stock"], x["seat"], x["follow"]) for x in self.r.queue if x["kind"] == "bark"], [("looping", 1, False), ("loop", 2, True)])
        self.assertNotIn("seq", self.r.queue[0]["ctx"], "no ring event caused this line")
        self.r.queue.clear()
        self._snap(5, 1, events=[cast(1, 3, "x", 3)] + [cast(1 + i, 1, "Spinning Top", 5) for i in range(1, 5)])
        self.assertEqual(self._queued_stocks().count("looping"), 1, "the mechanic trigger in the same turn: already called")
        self._log(seat=1, turn=9, source="cycle", why="cycle replay 1/8")
        self.r.scan_game_log()
        self.assertEqual(self._queued_stocks().count("looping"), 2, "the next turn's cycle calls it again")

    def test_say_looping_is_the_same_declaration_from_the_other_seat(self):
        self._prime()
        self._log(seat=2, turn=5, say="looping")
        self.r.scan_game_log()
        self.assertEqual([(x["stock"], x["seat"], x["source"]) for x in self.r.queue if x["kind"] == "bark"], [("looping", 2, "event"), ("loop", 1, "event")], "the declaration is anchored like any other loop call")

    def test_the_game_changer_trigger_marks_the_call_so_the_brain_cannot_double_it(self):
        self._prime()
        ticks = [self.r.loop_tick(1, "Mana Vault", 5) for _ in range(ev_mod.LOOP_AT)]           # cast, then the self-bounce
        self.assertEqual(ticks, [False, True])
        self.assertEqual(self._queued_stocks().count("loop"), 1)
        self._log(seat=1, turn=5, source="cycle")
        self.r.scan_game_log()
        self.assertEqual(self._queued_stocks().count("looping"), 1, "loop_tick already called it this turn: the cycle record adds nothing")


class SayKey(_EventsCase):
    def test_the_menu_matches_the_seat_runners(self):
        self.assertEqual(ev_mod.SAY_MENU, seat_rules.SAY_MENU, "the voice runner's copy of the menu drifted from seatd.rules")
        self.assertTrue(set(ev_mod.SAY_TARGETED) <= set(ev_mod.SAY_MENU))

    def test_a_valid_say_id_is_the_seats_line_with_source_brain_under_its_guard(self):
        self._prime()
        self._log(seat=2, turn=5, say="taunt")
        self.r.scan_game_log()
        self.assertEqual([(x["stock"], x["seat"], x["source"], x["ctx"]) for x in self.r.queue if x["kind"] == "bark"], [("taunt", 2, "brain", {"targets": []})])
        self._log(seat=2, turn=5, say="taunt")
        self.r.scan_game_log()
        self.assertEqual(self._queued_stocks().count("taunt"), 1, "the seat's normal guard: a line is said once a turn")
        self.assertIn("already said this turn", [r["why"] for r in self._records("skipped", "bark") if r["stock"] == "taunt"])

    def test_a_targeted_say_goes_to_the_life_leader_among_the_other_seats_or_nowhere(self):
        self._prime()
        self.r._last_snapshot = self._board(5, 1, seats=[self._seat(0, life=40), self._seat(1, life=20), self._seat(2, life=30), self._seat(3, life=35)])
        self._log(seat=1, turn=5, say="kill-that")
        self.r.scan_game_log()
        q = [x for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual(len(q), 1)
        self.assertEqual((q[0]["ctx"].get("generic", q[0]["stock"]), q[0]["seat"], q[0]["source"], q[0]["ctx"]["targets"]), ("kill-that", 1, "brain", [3]),
                         "Selvala leads on life among the others; the human is never the pick")
        self.r.queue.clear()
        self.r._last_snapshot = self._board(5, 1, seats=[self._seat(0), self._seat(1), dict(self._seat(2), eliminated=True), dict(self._seat(3), eliminated=True)])
        self._log(seat=1, turn=5, say="deal")
        self.r.scan_game_log()
        self.assertEqual([x for x in self.r.queue if x["kind"] == "bark"], [])
        self.assertEqual([r["stock"] for r in self._records("skipped", "bark") if r["why"].startswith("say needs a target")], ["deal"])

    def test_an_unknown_say_id_and_the_humans_records_are_ignored(self):
        self._prime()
        self._log(seat=1, turn=5, say="dance")
        self._log(seat=0, turn=5, say="taunt")
        self._log(seat=3, turn=5, say="taunt")
        self.r.scan_game_log()
        self.assertEqual([x for x in self.r.queue if x["kind"] == "bark"], [], "off the menu / the human / a voiceless seat: nothing")
        self.assertEqual([r["stock"] for r in self._records("skipped", "bark") if r["why"] == "say id not on the menu"], ["dance"])


class StaleIntent(_EventsCase):
    """A brain's declaration read late — after a mute, a restart, a rotated log — is history, not a line."""

    def test_a_say_record_older_than_the_intent_window_is_skipped_as_stale(self):
        self._prime()
        self._log(seat=2, turn=5, say="taunt", ts=time.time() - 60)
        self.r.scan_game_log()
        self.assertEqual([x for x in self.r.queue if x["kind"] == "bark"], [])
        skipped = [r for r in self._records("skipped", "bark") if r["why"].startswith("stale intent")]
        self.assertEqual([(r["stock"], r["seat"], r["source"]) for r in skipped], [("taunt", 2, "brain")])
        self.assertIn("60s old", skipped[0]["why"])

    def test_a_record_from_an_earlier_turn_than_the_snapshots_is_skipped(self):
        self._prime()                                                                           # the snapshot is at turn 5
        self._log(seat=2, turn=4, say="taunt")
        self._log(seat=1, turn=4, source="cycle", why="cycle replay 2/9")
        self.r.scan_game_log()
        self.assertEqual([x for x in self.r.queue if x["kind"] == "bark"], [], "turn 4 is over: neither the say nor the cycle is a line")
        self.assertEqual([(r["stock"], r["why"][:25]) for r in self._records("skipped", "bark") if r["why"].startswith("stale intent")],
                         [("taunt", "stale intent (turn 4 vs 5"), ("cycle", "stale intent (turn 4 vs 5")])
        self.assertEqual([r for r in self._records("noted") if r["why"].startswith("loop called")], [], "a stale cycle does not call the loop either")

    def test_a_fresh_record_on_the_snapshots_turn_is_the_line(self):
        self._prime()
        self._log(seat=2, turn=5, say="taunt", ts=time.time() - ev_mod.INTENT_MAX_AGE_S / 2)
        self.r.scan_game_log()
        self.assertEqual([(x["stock"], x["seat"], x["source"]) for x in self.r.queue if x["kind"] == "bark"], [("taunt", 2, "brain")])
        self.assertEqual([r for r in self._records("skipped", "bark") if r["why"].startswith("stale intent")], [])


class Heckle(_EventsCase):
    """§5.3 (Ben: "heckles are great"): the board unchanged HECKLE_S on the human's turn, Executive
    off and no AI seat thinking — a free seat says "we're waiting on you"; HECKLE_AGAIN_S "still
    waiting", never a third; when the board moves, "there you are". The advisor never answers (A14)."""

    def _human_turn(self):
        self._prime()                                                                           # turn 5 is seat 1's
        self._snap(6, 0); self.r.queue.clear()                                                  # turn 6: the human's; the board changed now
        self.r.rng.choice = lambda xs: xs[0]
        self.assertEqual(self.r._board_changed_at, self.clock.t)

    HECKLES = ("waiting-on-you", "still-waiting", "there-you-are")

    def _heckles(self):
        return [(x["stock"], x["seat"], x["source"], x["ctx"].get("targets")) for x in self.r.queue if x["kind"] == "bark"]

    def _heckled(self):
        """The heckles queued so far, from the record — a queued line expires out of the queue after its ttl."""
        return [r["stock"] for r in self._records("queued", "bark") if r["stock"] in self.HECKLES]

    def test_the_human_idle_thirty_seconds_draws_one_heckle_then_still_waiting_and_never_a_third(self):
        self._human_turn()
        self.clock.t += ev_mod.HECKLE_S - 1; self.r.heckle_human()
        self.assertEqual(self._heckles(), [], "29 s: the player is still thinking")
        self.clock.t += 1; self.r.heckle_human()
        self.assertEqual(self._heckles(), [("waiting-on-you", 1, "event", [0])], "30 s: one heckle from a free seat, aimed at the human")
        self.assertEqual([(r["seat"], r["source"]) for r in self._records("queued", "bark") if r["stock"] == "waiting-on-you"], [(1, "event")])
        self.assertEqual(self.r._heckled, 1)
        for _ in range(5):
            self.clock.t += 10; self.r.heckle_human()
        self.assertEqual(self._heckled(), ["waiting-on-you"], "80 s: nothing more yet")
        self.clock.t += 10; self.r.heckle_human()
        self.assertEqual(self._heckled(), ["waiting-on-you", "still-waiting"], "90 s: still waiting")
        self.assertEqual(self._heckles(), [("still-waiting", 1, "event", [0])], "the first heckle has expired out of the queue by now")
        self.assertEqual(self.r._heckled, 2)
        for _ in range(20):
            self.clock.t += 30; self.r.heckle_human()
        self.assertEqual(self._heckled(), ["waiting-on-you", "still-waiting"], "ten minutes: never a third")
        self.assertEqual([r for r in self._records("queued") if r.get("kind") != "bark"], [], "the seats speak; Joshua (quip/color) never")

    def test_the_board_moving_after_a_heckle_earns_there_you_are_and_resets_the_stage(self):
        self._human_turn()
        self.clock.t += ev_mod.HECKLE_S; self.r.heckle_human()
        self.assertEqual([h[0] for h in self._heckles()], ["waiting-on-you"])
        self.r.queue.clear()
        self.clock.t += 5
        self._snap(6, 0, seats=[self._seat(0, lands=(False,)), self._seat(1), self._seat(2), self._seat(3)])   # the human plays a land
        self.assertEqual(self.r._board_changed_at, self.clock.t)
        self.r.rng.random = lambda: 0.59                                                       # p = 0.6: just under
        self.r.heckle_human()
        self.assertEqual(self._heckles(), [("there-you-are", 1, "event", [0])])
        self.assertEqual(self.r._heckled, 0, "the stage resets: the next long wait starts again at 'waiting on you'")
        self.r.rng.random = lambda: 0.0
        self.r.heckle_human()
        self.assertEqual([h[0] for h in self._heckles()], ["there-you-are"], "said once")
        self.clock.t += ev_mod.HECKLE_S; self.r.heckle_human()
        self.assertEqual([h[0] for h in self._heckles()], ["there-you-are"], "the wait restarted from the board's last move — but Harry already said it this turn: his normal guard")
        self.assertIn("already said this turn", [r["why"] for r in self._records("skipped", "bark") if r["stock"] == "waiting-on-you"])
        self.assertEqual(self.r._heckled, 0, "a heckle nobody heard does not count: the stage waits for one that was queued (critic, 2026-09-16)")
        self.r.queue.clear(); self.r.rng.choice = lambda xs: xs[-1]
        self.r.heckle_human()
        self.assertEqual(self._heckles(), [("waiting-on-you", 2, "event", [0])], "next poll, another free seat says it")
        self.assertEqual(self.r._heckled, 1)
        self.r.queue.clear()
        self.clock.t += ev_mod.HECKLE_AGAIN_S - ev_mod.HECKLE_S; self.r.heckle_human()
        self.assertEqual(self._heckles(), [("still-waiting", 2, "event", [0])], "the same stall, a minute on")

    def test_there_you_are_is_a_roll_of_the_dice(self):
        self._human_turn()
        self.clock.t += ev_mod.HECKLE_S; self.r.heckle_human(); self.r.queue.clear()
        self._snap(6, 0, seats=[self._seat(0, lands=(False,)), self._seat(1), self._seat(2), self._seat(3)])
        self.r.rng.random = lambda: 0.6                                                        # p = 0.6: the dice say no
        self.r.heckle_human()
        self.assertEqual(self._heckles(), [])
        self.assertEqual(self.r._heckled, 0, "the stage resets whether or not the line is said")

    def test_the_advisor_never_answers_a_heckle(self):
        self._human_turn()
        self.clock.t += ev_mod.HECKLE_S; self.r.heckle_human()
        item = next(x for x in self.r.queue if x["stock"] == "waiting-on-you"); self.r.queue.clear()
        self._spoken(item["seat"], "waiting-on-you", ctx=item["ctx"])                          # the line plays; the chain planner runs
        self.assertEqual([x for x in self.r.queue if x["kind"] != "bark" or x["seat"] not in (1, 2)], [], "no quip, no colour, no Joshua item: a line aimed at the human gets no reply (A14)")

    def test_executive_on_means_nobody_to_heckle(self):
        self._human_turn()
        (self.logs / "control").mkdir(exist_ok=True)
        (self.logs / "control" / "executive.json").write_text(json.dumps({"on": True}))
        self.clock.t += ev_mod.HECKLE_AGAIN_S; self.r.heckle_human()
        self.assertEqual(self._heckles(), [], "the advisor is playing the seat: 'waiting on you' would be addressed to nobody")
        self.assertEqual(getattr(self.r, "_heckled", 0), 0)

    def test_not_the_humans_turn_means_no_heckle(self):
        self._prime()                                                                           # turn 5 is seat 1's
        self.clock.t += ev_mod.HECKLE_AGAIN_S; self.r.heckle_human()
        self.assertEqual(self._heckles(), [])

    def test_an_ai_seat_still_thinking_is_the_slow_one_not_the_human(self):
        import os
        self._human_turn()
        inbox = self.mailbox / "seat-2" / "inbox"; inbox.mkdir(parents=True)
        f = inbox / "req-9.json"; f.write_text("{}")
        old = time.time() - self.r.barks_slow - 5; os.utime(f, (old, old))
        self.assertEqual(self.r.slow_seats(), [2])
        self.clock.t += ev_mod.HECKLE_AGAIN_S; self.r.heckle_human()
        self.assertEqual(self._heckles(), [], "Bill has a decision pending: the table is waiting on him, not the player")
        f.unlink()
        self.r.heckle_human()
        self.assertEqual([h[0] for h in self._heckles()], ["waiting-on-you"], "his answer landed and the board still has not moved: now it is the player")

    def test_barks_off_or_the_final_lock_silence_the_heckle(self):
        self._human_turn()
        self.r.final_locked = True
        self.clock.t += ev_mod.HECKLE_S; self.r.heckle_human()
        self.assertEqual(self._heckles(), [])
        self.r.final_locked = False; self.r.barks_mode = "off"
        self.r.heckle_human()
        self.assertEqual(self._heckles(), [])

    # -- BL-54: the opening keep (game 49: 292 s of silence while the human chose; activeSeat None, turn 0, no shadow request)
    def _opening(self, hands=(7, 7, 7, 7)):
        """The table as the observer shows it during the mulligans: turn 0, no phase, no active seat, the hands dealt."""
        self._write({"turn": 0, "phase": "", "activeSeat": None, "gameOver": False, "events": [],
                     "seats": [self._seat(i, hand=h) for i, h in enumerate(hands)]})
        self.r.scan_observer(); self.r.queue.clear()
        self.r.rng.choice = lambda xs: xs[0]
        self.assertEqual(self.r._board_changed_at, self.clock.t)

    def _mull_decided(self, *seats, keep=True):
        for s in seats:
            self._log(seat=s, turn=0, phase="", type="MULLIGAN", seq=1, answer={"keep": keep})
        self.r.scan_game_log(); self.r.queue.clear()                                            # the keep-seven lines are not under test

    def _ai_request(self, seat, seq=1):
        inbox = self.mailbox / f"seat-{seat}" / "inbox"; inbox.mkdir(parents=True, exist_ok=True)
        f = inbox / f"req-{seq}.json"; f.write_text(json.dumps({"seq": seq, "type": "MULLIGAN"}))
        return f

    def test_the_opening_keep_is_the_humans_window_once_every_ai_seat_has_decided(self):
        self._opening()
        self._mull_decided(1, 2, 3)
        self.clock.t += ev_mod.HECKLE_S - 1; self.r.heckle_human()
        self.assertEqual(self._heckles(), [], "29 s into the keep: nothing yet")
        self.clock.t += 1; self.r.heckle_human()
        self.assertEqual(self._heckles(), [("waiting-on-you", 1, "event", [0])], "30 s at turn 0 with no AI seat deciding: the wait is the human's")
        self.assertEqual(self.r._heckled, 1)
        self.clock.t += ev_mod.HECKLE_AGAIN_S - ev_mod.HECKLE_S; self.r.heckle_human()
        self.assertEqual(self._heckled(), ["waiting-on-you", "still-waiting"])
        for _ in range(10):
            self.clock.t += 30; self.r.heckle_human()
        self.assertEqual(self._heckled(), ["waiting-on-you", "still-waiting"], "never a third")
        self.assertEqual([r for r in self._records("queued") if r.get("kind") not in ("bark", "startup")], [], "the seats speak; Joshua never")

    def test_an_ai_seat_still_deciding_its_keep_owns_the_wait(self):
        self._opening()
        self._mull_decided(2, 3)
        f = self._ai_request(1)                                                                 # Urza's mulligan request is open: the table waits on him
        self.clock.t += ev_mod.HECKLE_AGAIN_S; self.r.heckle_human()
        self.assertEqual(self._heckles(), [], "an AI seat has the decision, whatever its age")
        f.unlink()
        self.r.heckle_human()
        self.assertEqual(self._heckles(), [("waiting-on-you", 1, "event", [0])], "his answer landed and the board still has not moved: now it is the player")

    def test_game_49s_shape_the_seats_after_the_human_are_not_even_asked_until_the_human_keeps(self):
        """Forge asks the mulligans one player at a time in turn order (2 -> 3 -> 0 -> 1 in game 49): Urza's
        request came five seconds before turn 1. Two seats decided, one not yet asked, no request open: the human's."""
        self._opening()
        self._mull_decided(2, keep=False); self._mull_decided(3)
        self.clock.t += ev_mod.HECKLE_S; self.r.heckle_human()
        self.assertEqual(self._heckles(), [("waiting-on-you", 1, "event", [0])])

    def test_executive_on_means_nobody_to_heckle_in_the_opening_window_either(self):
        self._opening()
        self._mull_decided(1, 2, 3)
        (self.logs / "control").mkdir(exist_ok=True)
        (self.logs / "control" / "executive.json").write_text(json.dumps({"on": True}))
        self.clock.t += ev_mod.HECKLE_AGAIN_S; self.r.heckle_human()
        self.assertEqual(self._heckles(), [])
        self.assertEqual(getattr(self.r, "_heckled", 0), 0)

    def test_turn_one_arriving_after_an_opening_heckle_earns_there_you_are(self):
        self._opening()
        self._mull_decided(1, 2, 3)
        self.clock.t += ev_mod.HECKLE_S; self.r.heckle_human()
        self.assertEqual([h[0] for h in self._heckles()], ["waiting-on-you"]); self.r.queue.clear()
        self.clock.t += 20
        self._snap(1, 2)                                                                         # turn 1: Giada's — the human kept
        self.assertEqual(self.r._board_changed_at, self.clock.t)
        self.r.heckle_human()
        self.assertEqual(self._heckles(), [("there-you-are", 1, "event", [0])], "turn 1 arriving is the board moving: the wait is over")
        self.assertEqual(self.r._heckled, 0)
        self.clock.t += ev_mod.HECKLE_AGAIN_S; self.r.heckle_human()
        self.assertEqual([h[0] for h in self._heckles()], ["there-you-are"], "turn 1 is an AI seat's: no heckle, however long it takes")

    def test_before_the_deal_and_under_thirty_seconds_the_opening_is_quiet(self):
        self._opening(hands=(0, 7, 7, 7))                                                        # a hand still empty: Forge is setting the table
        self._mull_decided(1, 2, 3)
        self.clock.t += ev_mod.HECKLE_AGAIN_S; self.r.heckle_human()
        self.assertEqual(self._heckles(), [], "not dealt yet")
        self._opening()
        self.clock.t += ev_mod.HECKLE_S - 1; self.r.heckle_human()
        self.assertEqual(self._heckles(), [], "dealt, 29 s: still thinking")
        self.assertEqual(getattr(self.r, "_heckled", 0), 0)


class AtomsHook(_EventsCase):
    """§4.5 trigger 3: the ring's big moments reach the under channel through _atom, which never
    costs the table a line; the game-over lock stops the channel."""

    def test_a_big_swing_asks_the_listeners_for_a_gasp_with_the_attacker_excluded(self):
        calls = []
        self.r.react_atom = lambda kind, seats, actor=None, p=None: calls.append((kind, sorted(seats), actor))
        self._prime()
        ev = [cast(1, 3, "x", 3), {"seq": 2, "kind": "attack", "turn": 5, "seat": 1, "attackers": 1, "power": 9, "defenders": [0]}]
        self._snap(5, 1, events=ev)
        self.assertEqual(len(calls), 1)
        kind, seats, actor = calls[0]
        self.assertEqual((kind, actor), ("swing", 1))
        self.assertNotIn(1, seats, "the attacker does not gasp at his own swing")
        self.assertTrue(seats and set(seats) <= {int(s) for s in self.r.seat_libraries})
        self.assertIn("big-swing", self._queued_stocks(), "the main-channel line is queued as before")

    def test_an_atom_that_fails_never_costs_the_table_its_line(self):
        def boom(kind, seats, actor=None, p=None):
            raise RuntimeError("no player")
        self.r.react_atom = boom
        self._prime()
        ev = [cast(1, 3, "x", 3), {"seq": 2, "kind": "attack", "turn": 5, "seat": 1, "attackers": 1, "power": 9, "defenders": [0]}]
        self._snap(5, 1, events=ev)
        self.assertIn("big-swing", self._queued_stocks())

    def test_the_game_over_lock_stops_the_under_channel(self):
        stopped = []
        self.r.stop_atoms = lambda: stopped.append(True)
        self._prime()
        self._write(self._board(5, 1, gameOver=True)); self.r.scan_observer()
        self.assertTrue(self.r.final_locked)
        self.assertEqual(stopped, [True])
        self.r.scan_observer(self._board(5, 1, gameOver=True, events=[cast(1, 3, "x", 3)]))
        self.assertEqual(stopped, [True], "the lock is taken once")


if __name__ == "__main__":
    unittest.main()

"""Scheduler hardening (experimental/voicework2, 2026-09-14 — plan Lane C, items C2, §5.1, A6,
§4.2, A5, A3, A14). One classification shared by eviction, the governor, the seat guard and the
hygiene script; the governor as a mean, not a ceiling; one human_turn() predicate switched off
while the Executive plays the seat; the silence floor's pool on its record, anchored first and an
atom when the pool is empty or filler-only; the seat guard holds only between two lines of the
same class; a proposal's replies are terminal; Joshua never answers a seat.
Run: python3 -m unittest discover -s tests"""
import importlib.util
import json
import os
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import voice_runner as vr  # noqa: E402
from chains import ChainTable, plan_reply  # noqa: E402
from voice import scheduler as sch  # noqa: E402
from test_barks_runtime import FakePlayer  # noqa: E402
from test_table_lines import _TableCase  # noqa: E402

RUNNER = Path(__file__).resolve().parents[1]
SOURCES = ("event", "card", "procedural", "opener", "brain", "recap", "advice", "patter", "chain")
FILLER = ("nothing-happening", "this-is-fine", "good-hand", "what-turn")


def _load_hygiene():
    spec = importlib.util.spec_from_file_location("arena_hygiene", RUNNER.parent / "scripts" / "arena-hygiene.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OneClassification(_TableCase):
    """C2: classify() / classify_source() are THE rule — the eviction class, the governor's
    optional decision and arena-hygiene.py's anchored share all read it."""

    def test_the_two_classifiers_agree_with_the_ladder_and_each_other(self):
        self.assertEqual({s for s in SOURCES if sch.classify_source(s) == "anchored"}, {"event", "card", "procedural", "opener", "brain"})
        self.assertEqual({s for s in SOURCES if sch.classify_source(s) == "optional"}, {"recap", "advice", "patter"})
        self.assertEqual(sch.classify_source("chain"), "chain")
        self.assertEqual(sch.classify_source("floor"), "optional"); self.assertEqual(sch.classify_source(None), "optional")
        for s, prio in sch.BARK_PRIORITY.items():
            item = {"prio": prio, "chain": {"hop": 1} if s == "chain" else None, "source": s}
            self.assertEqual(sch.classify(item), sch.classify_source(s), f"{s}: by prio and by source must agree")
            self.assertEqual(vr.VoiceRunner._bark_class(item), sch.classify(item), f"{s}: the eviction class is classify()")
        self.assertEqual(sch.BARK_PRIORITY["opener"], sch.BARK_PRIORITY["event"], "the opener's own tier folded into the anchored one")
        self.assertLess(sch.BARK_PRIORITY["recap"], sch.BARK_PRIORITY["patter"], "a pending recap still outlives fresh filler")
        self.assertEqual(sch.classify({"kind": "event", "seat": 2, "library": "bill"}), "anchored", "no prio: the kind decides (a seat's exit line)")
        self.assertEqual(sch.classify({"kind": "bark", "source": "patter"}), "optional", "no prio: the source decides")
        self.assertEqual(sch.classify({"kind": "bark", "prio": 3.5, "chain": {"hop": 2}}), "chain")

    def test_hygiene_reads_the_same_rule(self):
        hy = _load_hygiene()
        self.assertIs(hy.classify_source, sch.classify_source, "the script imports the runner's rule, not a copy")
        for s in SOURCES + ("floor", None):
            self.assertEqual(hy.anchored({"source": s}), sch.classify_source(s) == "anchored", s)
        self.assertFalse(hy.anchored({"source": "recap"}), "the advisor's afterthoughts no longer count as anchored (they did in the old tuple)")
        self.assertEqual(tuple(hy.ANCHORED_SOURCES), sch.ANCHORED_SOURCES)
        # the script's fallback (a package without the runner beside it) mirrors the same tuple, brain included
        saved = sys.modules.get("voice.scheduler")
        sys.modules["voice.scheduler"] = None                              # "import voice.scheduler" now raises ImportError
        try:
            fb = _load_hygiene()
        finally:
            sys.modules["voice.scheduler"] = saved
        self.assertIsNot(fb.classify_source, sch.classify_source, "the fallback ran")
        self.assertEqual(tuple(fb.ANCHORED_SOURCES), sch.ANCHORED_SOURCES, "the mirrored tuple drifted from the runner's")
        for s in SOURCES + ("floor", None):
            self.assertEqual(fb.classify_source(s), sch.classify_source(s), s)
        self.assertTrue(fb.anchored({"source": "brain"}))

    def test_a_brain_line_is_anchored_and_survives_the_advisors_afterthoughts(self):
        """§4.4: the seat brain's `say` is spoken as an anchored line (source "brain") — the critic found it
        classed optional, priced 8.5 by the .get fallback, evicted by a recap, tapered past the goal and
        held by the guard after the seat's own filler."""
        r = self.r
        self.assertEqual(sch.classify_source("brain"), "anchored")
        self.assertEqual(sch.BARK_PRIORITY["brain"], sch.BARK_PRIORITY["event"], "the event tier, 5.5 — not the patter fallback")
        self._snap(3, 1); r.queue.clear(); r._roll_turn(3)
        self.assertTrue(r.maybe_bark(1, "taunt", turn=3, source="brain", p=1.0, ctx={"targets": [2]}))
        brain = [q for q in r.queue if q["kind"] == "bark"][0]
        self.assertEqual((brain["prio"], brain["source"], sch.classify(brain)), (5.5, "brain", "anchored"))
        self.assertTrue(r.maybe_bark(2, "slow-turn", turn=3, source="recap"))                       # the advisor's afterthought
        self.assertIn(brain, r.queue, "a recap evicts only its optional peers; the brain's line stands")
        r.enqueue("bark", stock="clapback", library=r.lib_for(2, "clapback"), seat=2, ttl=15.0, gap=0.3,
                  chain={"origin": 1, "hop": 1, "turn": 3}, ctx={"targets": [1]})
        self.assertIn(brain, r.queue, "a chain reply clears retorts and filler, never an anchored line")
        self.assertEqual([x["stock"] for x in self._records("dropped", "bark")], ["slow-turn"], "only the recap went")
        # the governor: anchored past the goal keeps max(0.5, goal / duty), not the optional taper's floor
        r.queue.clear(); r.duty = lambda window=vr.DUTY_WINDOW_S: 1.0; r.rng.random = lambda: 0.4
        self.assertTrue(r.maybe_bark(1, "respect", turn=3, source="brain", ctx={"targets": [2]}), "0.5 > 0.4: heard")
        self.assertFalse(r.maybe_bark(2, "nice-play", turn=3, source="recap", ctx={"targets": [1]}), "0.15 < 0.4: the recap is not")
        # the guard: an anchored line follows the seat's own filler freely (A5)
        r.rng.random = lambda: 0.0; r.duty = lambda window=vr.DUTY_WINDOW_S: 0.0
        r._bark_spoken_at[1] = self.clock.t; r._seat_last_class()[1] = "optional"
        self.assertTrue(r.maybe_bark(1, "gg", turn=3, source="brain", ctx={"targets": []}), "brain after the seat's own filler: not guard-held")

    def test_the_governor_governs_the_advisors_afterthoughts_as_optional(self):
        r = self.r
        r.duty = lambda window=vr.DUTY_WINDOW_S: 1.0                       # the table has been talking non-stop
        r.rng.random = lambda: 0.2
        self.assertFalse(r.maybe_bark(1, "slow-turn", turn=3, source="recap"))
        self.assertIn("governor 0.15", self._records("skipped", "bark")[-1]["why"], "a recap is optional: the floor of the taper")
        self.assertFalse(r.maybe_bark(1, "respect", turn=3, source="advice"))
        self.assertIn("governor 0.15", self._records("skipped", "bark")[-1]["why"])
        self.assertTrue(r.maybe_bark(1, "that-hurt", turn=3, source="event"), "anchored: max(0.5, goal/duty) = 0.5 > 0.2")
        self.assertEqual(sch.classify(r.queue[-1]), "anchored")


class GovernorIsAMean(_TableCase):
    """§5.1 (Ben: rowdy should rowdy): full chance below the goal (the dial's boost), a linear
    taper from 1.0 at the goal to OPTIONAL_FLOOR at 1.5 × the goal for optional lines; anchored
    lines keep max(0.5, goal / duty) above it."""

    def _curve(self, optional, goal, points):
        out = []
        for m in points:
            self.r.duty = lambda window=vr.DUTY_WINDOW_S, d=goal * m: d
            out.append(round(self.r.governor(optional=optional), 4))
        return out

    def test_normal_dial(self):
        r = self.r
        self.assertAlmostEqual(r.duty_goal(), 0.18)
        pts = (0.0, 0.5, 1.0, 1.25, 1.5, 2.0)
        self.assertEqual(self._curve(True, 0.18, pts), [1.0, 1.0, 1.0, 0.575, 0.15, 0.15], "optional: nothing held back until the goal, then the taper")
        self.assertEqual(self._curve(False, 0.18, pts), [1.0, 1.0, 1.0, 0.8, 0.6667, 0.5], "anchored: goal/duty, never below half")

    def test_rowdy_dial_boosts_below_the_goal_undamped(self):
        r = self.r
        r.chatter = 2.0; r.duty_target = 0.36
        pts = (0.0, 0.5, 1.0, 1.25, 1.5)
        self.assertEqual(self._curve(True, 0.36, pts), [2.0, 1.5, 1.0, 0.575, 0.15], "the old 0.15 + 0.85·head factor is gone")
        self.assertEqual(self._curve(False, 0.36, pts), [2.0, 1.5, 1.0, 0.8, 0.6667])
        r.duty_target = 0.0
        self.assertEqual(r.governor(True), 1.0, "no goal: no governor")

    def test_quiet_dial_stays_quiet_past_the_goal(self):
        """The critic: at k < 1 the multiplier was k below the goal and 1.0 AT it — quiet doubled its chance
        the instant the table crossed the goal. Both branches above the goal now carry min(1, k)."""
        r = self.r
        r.chatter = 0.5; r.duty_target = 0.09
        pts = (0.0, 0.5, 1.0, 1.25, 1.5)
        self.assertEqual(self._curve(True, 0.09, pts), [0.5, 0.5, 0.5, 0.2875, 0.075], "optional at quiet: k, then k × the taper")
        self.assertEqual(self._curve(False, 0.09, pts), [0.5, 0.5, 0.5, 0.4, 0.3333], "anchored at quiet: k, then k × max(0.5, goal/duty)")
        r.chatter = 1.0; r.duty_target = 0.18
        self.assertEqual(self._curve(True, 0.18, (1.0, 1.25)), [1.0, 0.575], "normal is untouched: min(1, k) = 1")

    def test_constants(self):
        self.assertEqual((sch.OPTIONAL_FLOOR, sch.GOVERNOR_TAPER_AT), (0.15, 1.5))


class HumanTurnPredicate(_TableCase):
    """A6 + §2: one human_turn() — the human is active AND the Executive is not playing the seat —
    behind the budget, the patter gap and the floor. The gap keeps its own rate (PATTER_HUMAN 0.33,
    game 48's feel — Ben: the floor's numbers stay); the budget's 0.6 is the budget's alone."""

    def _executive(self, on: bool):
        (self.logs / "control").mkdir(parents=True, exist_ok=True)
        (self.logs / "control" / "executive.json").write_text(json.dumps({"on": on}))

    def test_budget_and_gap_follow_one_predicate_and_the_executive_switches_it_off(self):
        r = self.r
        r.rng.uniform = lambda a, b: a; r.patter_gap = (5.0, 7.0)
        r._last_snapshot = {"turn": 4, "phase": "MAIN1", "activeSeat": 1}
        self.assertFalse(r.human_turn()); self.assertAlmostEqual(r.duty_goal(), 0.18); self.assertAlmostEqual(r._patter_gap_s(r.human_turn()), 5.0)
        r._last_snapshot = {"turn": 4, "phase": "MAIN1", "activeSeat": 0}
        self.assertTrue(r.human_turn(), "the human is active, nobody plays for him")
        self.assertAlmostEqual(r.duty_goal(), 0.18 * 0.6)
        self.assertAlmostEqual(r._patter_gap_s(r.human_turn()), 5.0 / 0.33, msg="the gap is three times longer — game 48's rate, not the budget's 0.6 (1.8× faster)")
        r.duty_human = 0.01
        self.assertAlmostEqual(r._patter_gap_s(True), 5.0 / 0.33, msg="the budget's multiplier does not touch the gap")
        r.patter_human = 0.5
        self.assertAlmostEqual(r._patter_gap_s(True), 10.0, msg="patter_human (tuning.json) is the gap's own number")
        r.duty_human = 0.6
        self.clock.t += 1; self._executive(True)                            # a second on: the memo re-reads the file
        self.assertFalse(r.human_turn(), "Executive on: an AI is playing the seat — an AI turn")
        self.assertAlmostEqual(r.duty_goal(), 0.18); self.assertAlmostEqual(r._patter_gap_s(r.human_turn()), 5.0)
        self.clock.t += 1; self._executive(False)
        self.assertTrue(r.human_turn())

    def test_the_executive_file_is_read_once_a_second_and_again_when_the_turn_moves(self):
        """The critic: human_turn() → executive_on() parsed control/executive.json on every governor call
        (several a step). A one-second memo keyed on the clock, dropped when the snapshot's turn or
        active seat changes."""
        reads = []

        class Double(sch.SchedulerMixin):
            human_seat = 0
            _last_snapshot = {"turn": 4, "activeSeat": 0}
            on = False
            duty_target, duty_human, chatter = 0.18, 0.6, 1.0                 # what governor()/duty_goal() read

            def __init__(self, clock):
                self.clock = clock

            def duty(self, window=vr.DUTY_WINDOW_S):
                return 0.0

            def executive_on(self):
                reads.append(self.clock())
                return self.on
        clock = self.clock
        d = Double(clock)
        self.assertTrue(d.human_turn()); self.assertTrue(d.human_turn()); d.governor(True); d.duty_goal()
        self.assertEqual(len(reads), 1, "four asks inside a second: one read")
        d.on = True
        self.assertTrue(d.human_turn(), "the memo answers until it ages out")
        clock.t += 0.99; self.assertEqual(len(reads), 1); self.assertTrue(d.human_turn())
        clock.t += 0.01
        self.assertFalse(d.human_turn(), "a second on: read again, the Executive is seen"); self.assertEqual(len(reads), 2)
        d._last_snapshot = {"turn": 5, "activeSeat": 0}; d.on = False
        self.assertTrue(d.human_turn(), "a new turn drops the memo at once"); self.assertEqual(len(reads), 3)
        d._last_snapshot = {"turn": 5, "activeSeat": 1}
        self.assertFalse(d.human_turn()); self.assertEqual(len(reads), 3, "an AI seat is active: the file is not consulted at all")
        d._last_snapshot = {"turn": 5, "activeSeat": 0}
        self.assertTrue(d.human_turn()); self.assertEqual(len(reads), 3, "back to the human's seat inside the same second and turn: the memo still answers")
        d._last_snapshot = {"turn": 5, "activeSeat": 2}; d.human_turn()
        d._last_snapshot = {"turn": 6, "activeSeat": 0}
        self.assertTrue(d.human_turn()); self.assertEqual(len(reads), 4, "a new turn on the human's seat: read again")
        clock.t -= 5; d.human_turn()
        self.assertEqual(len(reads), 5, "a clock that went backwards (a replay) is not trusted")
        self.assertEqual(sch.EXEC_MEMO_S, 1.0)

    def test_the_floor_is_the_ai_floor_while_the_executive_plays_the_humans_turn(self):
        r = self.r
        r.patter_on = True; r.patter_gap = (3.0, 3.0); r.rng.uniform = lambda a, b: a
        r.duty = lambda window=vr.DUTY_WINDOW_S: 1.0                       # the governor holds every optional roll
        r.rng.random = lambda: 0.99                                        # and the dice fail: only the floor can speak
        self._executive(True)
        self._snap(5, 0); r.queue.clear(); r.last_spoken_at = self.clock.t; r._patter_anchor = None
        self.clock.t += 13; r.patter()
        self.assertEqual(len(r.queue), 1, "13 s quiet with Executive on the human's seat: the 12 s AI floor speaks")
        r.queue.clear()
        self._executive(False)
        r.last_spoken_at = self.clock.t
        self.clock.t += 13; r.patter()
        self.assertEqual(r.queue, [], "the human really playing: the floor is 24 s")
        self.clock.t += 12; r.patter()
        self.assertEqual(len(r.queue), 1)

    def test_a_test_double_without_executive_on_is_a_plain_human_turn(self):
        class Bare(sch.SchedulerMixin):
            human_seat = 0
            _last_snapshot = {"activeSeat": 0}
        self.assertTrue(Bare().human_turn())


class FloorPool(_TableCase):
    """§4.2: the silence floor's record carries pool / anchored / picked; anchored candidates
    speak first; an empty or filler-only pool spends an atom (voice/atoms.py, another lane) when
    the runner has floor_atom(); an atom re-arms the floor at its full length and at most two play in a
    row (the critic: ~7 lines exhaust the filler pool for 300 s, and a sigh every 0.6 × floor until the
    board re-seeded a candidate was a tic, not presence)."""

    def _quiet_table(self, leader_life=40):
        r = self.r
        r.patter_on = True; r.patter_gap = (3.0, 3.0); r.rng.uniform = lambda a, b: a
        r.duty = lambda window=vr.DUTY_WINDOW_S: 1.0                       # the ordinary clock is held by the governor...
        r.rng.random = lambda: 0.99                                        # ...and the dice, so only the floor speaks
        seats = [self._seat(0), self._seat(1), self._seat(2, life=leader_life), self._seat(3)]
        self._snap(5, 1, seats); r.queue.clear(); r.last_spoken_at = self.clock.t; r._patter_anchor = None
        return r

    def _floor_records(self):
        return [x for x in self._records("skipped", "bark") if "silence floor" in (x.get("why") or "")]

    def test_anchored_candidates_speak_first_and_the_record_says_what_the_pool_held(self):
        r = self._quiet_table(leader_life=45)                             # seat 2 leads: threat calls exist
        r.rng.random = lambda: 0.0                                        # the weighted pick takes the first anchored candidate
        self.clock.t += 12; r.patter()
        rec = self._floor_records()[-1]
        self.assertEqual(rec["picked"], "anchored"); self.assertGreaterEqual(rec["anchored"], 3); self.assertGreater(rec["pool"], rec["anchored"])
        q = [x for x in r.queue if x["kind"] == "bark"]
        self.assertEqual(len(q), 1)
        self.assertIn(q[0]["ctx"].get("generic") or q[0]["stock"], sch.ANCHORED_PATTER, "not filler")
        self.assertEqual(q[0]["stock"], "youre-the-threat" if not q[0]["ctx"].get("generic") else q[0]["stock"])

    def test_a_filler_only_pool_spends_an_atom_and_the_floor_rearms_at_its_full_length(self):
        r = self._quiet_table()
        r._said_at["deal"] = r._said_at["pass-already"] = self.clock.t       # the anchored filler-adjacent lines are stale
        calls = []
        r.floor_atom = lambda living: calls.append(list(living)) or True
        self.clock.t += 12; r.patter()
        self.assertEqual(r.queue, [], "no content line: the atom stood in")
        self.assertEqual(calls, [[1, 2]])
        rec = self._floor_records()[-1]
        self.assertEqual((rec["pool"], rec["anchored"], rec["picked"]), (8, 0, "atom")); self.assertIn("filler only", rec["why"])
        self.assertIn("1 of 2 in a row", rec["why"])
        self.clock.t += 7.5; r.patter()                                   # 60 % of the floor (the old re-arm): not any more
        self.assertEqual((len(calls), r.queue), (1, []))
        self.assertIn("governor", self._records("skipped", "bark")[-1]["why"], "the ordinary clock ran and was held")
        self.clock.t += 4; r.patter()                                     # 11.5 s since the atom: not yet
        self.assertEqual(len(calls), 1)
        self.clock.t += 0.5; r.patter()
        self.assertEqual(len(calls), 2, "the floor tripped again after a FULL floor of quiet")
        self.assertIn("2 of 2 in a row", self._floor_records()[-1]["why"])

    def test_at_most_two_atoms_in_a_row_then_filler_or_silence_until_a_line_plays(self):
        r = self._quiet_table()
        r._said_at["deal"] = r._said_at["pass-already"] = self.clock.t
        calls = []
        r.floor_atom = lambda living: calls.append(self.clock.t) or True
        for _ in range(2):
            self.clock.t += 12; r.patter()
        self.assertEqual((len(calls), r.queue), (2, []))
        self.clock.t += 12; r.patter()
        self.assertEqual(len(calls), 2, "the third floor spends no atom")
        q = [x for x in r.queue if x["kind"] == "bark"]
        self.assertEqual(len(q), 1); self.assertIn(q[0]["stock"], FILLER, "a filler-only pool: filler speaks instead — words, not a third sigh")
        self.assertEqual(self._floor_records()[-1]["picked"], "filler")
        # the pool empties (every filler id said lately): no third atom, no record — quiet until the board moves
        for pid in FILLER:
            r._said_at[pid] = self.clock.t
        r.queue.clear(); n = len(self._floor_records())
        for _ in range(3):
            self.clock.t += 12; r.patter()
        self.assertEqual((len(calls), r.queue, len(self._floor_records())), (2, [], n), "silence, not a tic")
        # a content line plays: the run resets and the atoms may stand in again
        r.last_spoken_at = self.clock.t
        self.clock.t += 12; r.patter()
        self.assertEqual(len(calls), 3, "after a spoken line the atoms run again")
        self.assertEqual(sch.FLOOR_ATOM_MAX_RUN, 2)
        self.assertFalse(hasattr(sch, "FLOOR_ATOM_REARM"), "the 60 % re-arm is gone")

    def test_when_the_atom_declines_or_is_absent_filler_speaks_as_before(self):
        r = self._quiet_table()
        r._said_at["deal"] = r._said_at["pass-already"] = self.clock.t
        r.floor_atom = lambda living: False
        self.clock.t += 12; r.patter()
        q = [x for x in r.queue if x["kind"] == "bark"]
        self.assertEqual(len(q), 1); self.assertIn(q[0]["stock"], FILLER)
        rec = self._floor_records()[-1]
        self.assertEqual((rec["pool"], rec["anchored"], rec["picked"]), (8, 0, "filler"))
        del r.floor_atom
        r.queue.clear(); r.last_spoken_at = self.clock.t
        self.clock.t += 12; r.patter()
        self.assertEqual(len([x for x in r.queue if x["kind"] == "bark"]), 1, "no atoms on this runner: filler, as built")
        self.assertEqual(self._floor_records()[-1]["picked"], "filler")

    def test_an_empty_pool_spends_an_atom_or_stays_silent(self):
        r = self._quiet_table()
        for pid in ("deal", "pass-already") + FILLER:
            r._said_at[pid] = self.clock.t                                 # everything the board offers was said lately
        r.floor_atom = lambda living: True
        self.clock.t += 12; r.patter()
        rec = self._floor_records()[-1]
        self.assertEqual((rec["pool"], rec["anchored"], rec["picked"]), (0, 0, "atom")); self.assertIn("empty", rec["why"])
        self.assertEqual(r.queue, [])
        del r.floor_atom
        n = len(self._floor_records()); r.last_spoken_at = self.clock.t
        self.clock.t += 12; r.patter()
        self.assertEqual((r.queue, len(self._floor_records())), ([], n), "nothing to say and no atoms: silence, no record")

    def test_the_anchored_set(self):
        self.assertTrue({"whats-your-life", "cards-in-hand", "low-life-jab", "empty-hand", "youre-the-threat", "kill-that", "someone-wins",
                         "pass-already", "deal"} <= sch.ANCHORED_PATTER)
        self.assertFalse(set(FILLER) & sch.ANCHORED_PATTER)


class SeatGuardByClass(_TableCase):
    """A5 (game 48, 14:14:35-36): Bill's `nothing-happening` blocked his `landed-hit` a second later.
    The guard holds only between two lines of the same class; a chain reply counts as optional."""

    def _spoke(self, seat, stock, source, prio, chain=None):
        self.r._bark_spoken_at[seat] = self.clock.t
        self.r.after_spoken({"kind": "bark", "stock": stock, "text": "", "seat": seat, "library": self.r.lib_for(seat, stock),
                             "ctx": {"targets": [1 if seat == 2 else 2]}, "chain": chain, "prio": prio, "source": source})
        self.r.queue.clear()

    def setUp(self):
        super().setUp()
        self._snap(3, 1); self.r.queue.clear(); self.r._roll_turn(3)
        self.r.rng.random = lambda: 0.0

    def test_an_anchored_line_follows_the_seats_own_filler_freely(self):
        self._spoke(2, "nothing-happening", "patter", 8.5)
        self.assertEqual(self.r._last_class[2], "optional")
        self.clock.t += 1
        self.assertTrue(self.r.maybe_bark(2, "landed-hit", turn=3, source="event", ctx={"targets": [1]}), "game 48: the hit is heard")
        self.assertFalse(self.r.maybe_bark(2, "this-is-fine", turn=3, source="patter"), "filler on filler: held")
        self.assertIn("seat guard (1s < 10s, optional after optional)", self._records("skipped", "bark")[-1]["why"])

    def test_two_anchored_lines_still_hold_and_optional_after_anchored_passes(self):
        self._spoke(2, "landed-hit", "event", 5.5)
        self.assertEqual(self.r._last_class[2], "anchored")
        self.clock.t += 2
        self.assertFalse(self.r.maybe_bark(2, "respect", turn=3, source="event"), "a reaction on a reaction: held, as before")
        self.assertIn("anchored after anchored", self._records("skipped", "bark")[-1]["why"])
        self.assertTrue(self.r.maybe_bark(2, "nothing-happening", turn=3, source="patter"), "a different class passes (the rule is symmetric)")

    def test_a_chain_reply_is_banter_for_the_guard(self):
        self._spoke(2, "clapback", "chain", 3.5, chain={"origin": 1, "hop": 1, "turn": 3})
        self.assertEqual(self.r._last_class[2], "optional", "chain folds into optional for the guard")
        self.clock.t += 1
        self.assertFalse(self.r.maybe_bark(2, "what-turn", turn=3, source="patter"), "filler on a retort: held")
        self.assertTrue(self.r.maybe_bark(2, "big-swing", turn=3, source="event"), "a board event after a retort: heard")

    def test_landed_hit_is_the_hitters_own_line_and_follows_its_own_big_swing(self):
        """events.py speaks `landed-hit` for the seat that hit the human, two seconds after that seat's own
        `big-swing`; both anchored, so the class rule alone would hold it — it is an own-action line (critic)."""
        self.assertIn("landed-hit", sch.OWN_ACTION_LINES)
        self._spoke(2, "big-swing", "event", 5.5)
        self.assertEqual(self.r._last_class[2], "anchored")
        self.clock.t += 2
        self.assertTrue(self.r.maybe_bark(2, "landed-hit", turn=3, source="event", ctx={"targets": [0], "aggressor": None}), "the hit lands, 2 s after the swing")
        self.assertFalse(self.r.maybe_bark(2, "respect", turn=3, source="event"), "a reaction that is not the seat's own act is still held")
        self.assertIn("anchored after anchored", self._records("skipped", "bark")[-1]["why"])

    def test_a_stamp_without_a_line_holds_and_own_actions_still_skip_the_guard(self):
        self.r._bark_spoken_at[1] = self.clock.t                            # the guard stamped, no class known (a test double, a restart)
        self.assertFalse(self.r.maybe_bark(1, "respect", turn=3, source="event"))
        self.assertIn("after a line", self._records("skipped", "bark")[-1]["why"])
        self.assertTrue(self.r.maybe_bark(1, "counter", turn=3, source="event"), "a seat's own action is never guarded")


class ProposalRepliesAreTerminal(_TableCase):
    """A3: the yea / nay and the subject's retort end the exchange — after_spoken plans no hop from
    them (game 48 had disagree → laugh 8 and disagree → clapback 7 as ordinary chains)."""

    def _three_voices(self):
        d = vr.VOICES_DIR / "lily"; d.mkdir()
        (d / "manifest.json").write_text(json.dumps({"schema": "arena.voice-stock/1", "library": "lily", "seat": 3, "voice_name": "Lily - Velvety Actress",
                                                     "temperament": "warm", "phrases": {}}))
        for f in (vr.VOICES_DIR / "bill").glob("*.wav"):
            (d / f.name).write_bytes(f.read_bytes())
        os.environ["ARENA_SEAT_DECKS"] = "urza-lord-high-artificer purphoros-god-of-the-forge sythis-harvests-hand giada-font-of-hope"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock, tuning=self.tuning)
        r.rng.random = lambda: 0.0; r.rng.shuffle = lambda x: None
        r.rng.choice = lambda xs: xs[1] if "agree" in xs else xs[0]        # "disagree" (invites clapback) and "im-not-the-threat" (invites disagree)
        r._last_snapshot = {"turn": 4, "phase": "MAIN1", "activeSeat": 1, "seats": [self._seat(i) for i in range(4)]}
        r._roll_turn(4)
        return r

    def test_replies_carry_terminal_and_nothing_follows_them(self):
        r = self._three_voices()
        r.after_spoken({"kind": "bark", "stock": "kill-that", "text": "", "seat": 1, "library": "harry", "ctx": {"targets": [3]}, "chain": None})
        replies = [q for q in r.queue if q["kind"] == "bark"]
        self.assertEqual([(q["stock"], q["seat"]) for q in replies], [("disagree", 2), ("im-not-the-threat", 3)])
        self.assertTrue(all(q["ctx"].get("terminal") and q.get("follow") for q in replies))
        self.assertIsNone(r._chain)
        before = len(self._records("queued", "bark"))
        for q in replies:                                                  # each is "spoken"
            r.after_spoken(q)
            self.assertEqual(len(r.queue), 2, f"{q['stock']}: no hop planned")
            self.assertIsNone(r._chain)
        self.assertEqual(len(self._records("queued", "bark")), before)
        self.assertEqual([x for x in self._records("skipped", "bark") if x.get("source") == "chain"], [], "not even a rolled-and-lost hop")
        # the control: the same item without the flag would have invited its clapback
        plain = dict(replies[0], ctx={k: v for k, v in replies[0]["ctx"].items() if k != "terminal"})
        r.after_spoken(plain)
        self.assertEqual([q["stock"] for q in r.queue if q["kind"] == "bark"][-1], "clapback", "the flag is what stops the hop")


class JoshuaNeverAnswersASeat(_TableCase):
    """A14 (Ben): the advisor is a ghost outside the game — a seat's line aimed at the human gets no
    reply from him; the planner moves to its next option. Joshua's own channels are untouched."""

    def test_plan_reply_skips_the_human_and_the_table_has_no_joshua_map(self):
        table = ChainTable({"invites": {"landed-hit": [{"role": "target", "reply": "scoff"}]}, "joshua_replies": {"landed-hit": "ouch"}})
        self.assertFalse(hasattr(table, "joshua"), "an old file's key is tolerated and ignored")
        spoken = {"seat": 1, "stock": "landed-hit", "ctx": {"targets": [0]}}
        self.assertIsNone(plan_reply(table, spoken, None, {1: "harry", 2: "bill"}, 0, lambda s: None, set(), random.Random(0), 3))
        table = ChainTable({"invites": {"landed-hit": [{"role": "target", "reply": "scoff"}, {"role": "bystander", "reply": "pile-on"}]}})
        rng = random.Random(0); rng.shuffle = lambda x: None
        plan = plan_reply(table, spoken, None, {1: "harry", 2: "bill"}, 0, lambda s: None, set(), rng, 3)
        self.assertEqual((plan["seat"], plan["id"]), (2, "pile-on"), "the human's slot yields nothing; the bystander is next")
        shipped = json.loads((RUNNER / "voice" / "stock" / "voices" / "chains.json").read_text())
        self.assertNotIn("joshua_replies", shipped)

    def test_the_scheduler_queues_no_quip_for_a_line_at_the_human(self):
        r = self.r
        self._snap(3, 1); r.queue.clear()
        for opener in ("landed-hit", "counter", "big-swing", "kill"):     # the four lines the old map answered
            r._roll_turn(3); r._said_this_turn = set()
            self._spoken(1, opener, ctx={"targets": [0], "aggressor": None})
            self.assertEqual([q for q in r.queue if q["kind"] == "quip"], [], opener)
            r.queue.clear()
        self.assertEqual([x for x in self._records("queued") if x.get("kind") == "quip"], [])
        r.enqueue("quip", stock="ouch", ttl=15.0)                          # Joshua's OWN channel still works
        self.assertEqual([(q["kind"], q["stock"]) for q in r.queue], [("quip", "ouch")])


def _sixty_second_turn(case) -> list:
    """One 60 s turn, the same calls whatever the scheduler: a seat's filler twice, a seat's own "land, go"
    twice, three "kill that" proposals at the other seat, the advisor's afterthought twice, the filler once
    more at 59 s, then the pool's size — every result, the queue and the skip/drop records in one trace.
    LongTurnRelief.test_a_short_turn_is_exactly_as_before runs it and compares with HEAD_TRACE_60S."""
    r, clock = case.r, case.clock
    case._snap(3, 1); r.queue.clear(); r._roll_turn(3)
    r.rng.random = lambda: 0.0; r.rng.shuffle = lambda x: None; r.rng.choice = lambda xs: xs[0]
    r.duty = lambda window=vr.DUTY_WINDOW_S: 0.0
    t0 = clock.t
    kill = {"kind": "bark", "stock": "kill-that", "text": "", "seat": 1, "library": r.lib_for(1, "kill-that"), "ctx": {"targets": [2]}, "chain": None}
    steps = [
        (0, lambda: r.maybe_bark(1, "nothing-happening", turn=3, source="patter")),
        (0, lambda: r.maybe_bark(1, "nothing-happening", turn=3, source="patter")),
        (5, lambda: r.maybe_bark(2, "land-go", turn=3, source="procedural")),
        (5, lambda: r.maybe_bark(2, "land-go", turn=3, source="procedural")),
        (15, lambda: r.after_spoken(dict(kill))),
        (30, lambda: r.after_spoken(dict(kill))),
        (30, lambda: r.after_spoken(dict(kill))),
        (45, lambda: r.maybe_bark(2, "slow-turn", turn=3, source="recap", ctx={"targets": [1]})),
        (45, lambda: r.maybe_bark(2, "slow-turn", turn=3, source="recap", ctx={"targets": [1]})),
        (59, lambda: r.maybe_bark(1, "nothing-happening", turn=3, source="patter")),
        (60, lambda: len(r.patter_candidates(r._last_snapshot, [1, 2]))),
    ]
    trace = []
    for dt, step in steps:
        clock.t = t0 + dt
        trace.append(step())
    trace.append([(q["stock"], q["seat"]) for q in r.queue if q["kind"] == "bark"])
    trace.append([(x.get("stock"), x.get("seat"), (x.get("why") or "").split(" (")[0])
                  for x in case._records() if x.get("event") in ("skipped", "dropped", "queued") and x.get("kind") == "bark"])
    return trace


# What HEAD (844e5ba24f8, the per-turn SET) produced for _sixty_second_turn — captured by running the same
# function with HEAD's SchedulerMixin mixed in ahead of VoiceRunner (git show HEAD:… into a scratch module).
HEAD_TRACE_60S = [
    True, False,                                                           # the filler, then "already said this turn"
    True, False,                                                           # "land, go", then the same
    None, None, None,                                                      # three proposals: three different retorts from the subject
    True, False,                                                           # the afterthought, then the same
    False,                                                                 # 59 s: the filler is still spent
    10,                                                                    # the pool at 60 s
    [("land-go", 2), ("im-not-the-threat", 2), ("clapback", 2), ("you-wish", 2), ("slow-turn", 2)],
    [("nothing-happening", 1, ""), ("nothing-happening", 1, "already said this turn"), ("nothing-happening", 1, "evicted by land-go"),
     ("land-go", 2, ""), ("land-go", 2, "already said this turn"),
     ("im-not-the-threat", 2, ""), ("clapback", 2, ""), ("you-wish", 2, ""),
     ("slow-turn", 2, ""), ("slow-turn", 2, "already said this turn"),
     ("nothing-happening", 1, "already said this turn")],
]


class LongTurnRelief(_TableCase):
    """BL-53 (game 49: Purphoros's turn 10 ran nine minutes — by minute four the floor found `pool 0` and the
    third proposal drew no reply because every retort was in the per-turn set): within one turn an OPTIONAL
    id (patter, a chain reply, the advisor's afterthoughts) comes back for the same seat TURN_REPEAT_S after
    it said it; an ANCHORED id (event, procedural, opener, brain, card) is said once a turn whatever the clock.
    A short turn — Ben: "the patter is sounding good" — behaves exactly as before."""

    def setUp(self):
        super().setUp()
        self._snap(3, 1); self.r.queue.clear(); self.r._roll_turn(3)
        self.r.duty = lambda window=vr.DUTY_WINDOW_S: 0.0                 # the budget is not what these tests are about

    def _why(self):
        return self._records("skipped", "bark")[-1]["why"]

    def test_an_optional_id_is_refused_at_a_minute_and_back_after_three(self):
        r = self.r
        self.assertTrue(r.maybe_bark(1, "nothing-happening", turn=3, source="patter")); r.queue.clear()
        self.clock.t += 60
        self.assertFalse(r.maybe_bark(1, "nothing-happening", turn=3, source="patter")); self.assertEqual(self._why(), "already said this turn")
        self.assertTrue(r.said_this_turn(1, "nothing-happening", optional=True))
        self.clock.t += 119                                                # 179 s
        self.assertFalse(r.maybe_bark(1, "nothing-happening", turn=3, source="patter"), "one second short")
        self.clock.t += 2                                                  # 181 s
        self.assertFalse(r.said_this_turn(1, "nothing-happening", optional=True))
        self.assertIn((1, "nothing-happening"), r._said_this_turn, "strict membership still says so (the checkpoint lists it)")
        self.assertNotIn((1, "nothing-happening"), r._turn_said().optional, "the planner's view applies the rule")
        self.assertTrue(r.maybe_bark(1, "nothing-happening", turn=3, source="patter"), "the same seat, the same turn, three minutes on")
        self.assertEqual(r._said_this_turn[(1, "nothing-happening")], self.clock.t, "re-stamped: the next three minutes start now")
        r.queue.clear()
        self.assertTrue(r.maybe_bark(2, "slow-turn", turn=3, source="recap", ctx={"targets": [1]})); r.queue.clear()
        self.clock.t += 179
        self.assertFalse(r.maybe_bark(2, "slow-turn", turn=3, source="recap", ctx={"targets": [1]}), "the advisor's afterthought is optional too")
        self.clock.t += 2
        self.assertTrue(r.maybe_bark(2, "slow-turn", turn=3, source="recap", ctx={"targets": [1]}))

    def test_an_anchored_id_stays_refused_for_the_whole_turn(self):
        r = self.r
        self.assertTrue(r.maybe_bark(2, "land-go", turn=3, source="procedural")); r.queue.clear()
        self.assertTrue(r.maybe_bark(1, "big-swing", turn=3, source="event", ctx={"targets": [2]})); r.queue.clear()
        for dt in (60, 121, 600, 1800):                                    # 1 min, 3 min 1 s, 13 min, 43 min
            self.clock.t += dt
            self.assertFalse(r.maybe_bark(2, "land-go", turn=3, source="procedural"), f"{dt}: a seat narrates 'land, go' once a turn")
            self.assertEqual(self._why(), "already said this turn", "the per-turn rule, not RARE_REPEATS (nothing was spoken)")
            self.assertFalse(r.maybe_bark(1, "big-swing", turn=3, source="event", ctx={"targets": [2]}))
            self.assertEqual(self._why(), "already said this turn")
            self.assertTrue(r.said_this_turn(2, "land-go", optional=False))
        self.assertEqual(r.queue, [])

    def test_the_floors_pool_refills_in_a_long_turn(self):
        r = FloorPool._quiet_table(self)
        living = [1, 2]
        cands = r.patter_candidates(r._last_snapshot, living)
        self.assertGreater(len(cands), 0)
        for sp, pid, _, _ in cands:
            r._turn_said().add((sp, pid))                                  # minute four of a loop turn: every seat has said everything it could
        t0 = self.clock.t
        r.floor_atom = lambda living: True
        self.clock.t += 12; r.patter()
        rec = [x for x in self._records("skipped", "bark") if "silence floor" in (x.get("why") or "")][-1]
        self.assertEqual((rec["pool"], rec["picked"]), (0, "atom"), "game 49: the floor found the pool empty and spent an atom")
        self.clock.t = t0 + 60
        self.assertEqual(r.patter_candidates(r._last_snapshot, living), [], "a minute on: still empty")
        self.clock.t = t0 + 181
        pool = r.patter_candidates(r._last_snapshot, living)
        self.assertGreater(len(pool), 0, "three minutes on: the pool is back")
        del r.floor_atom
        r.patter()
        self.assertEqual(len([q for q in r.queue if q["kind"] == "bark"]), 1, "the floor speaks a line again")
        rec = [x for x in self._records("skipped", "bark") if "silence floor" in (x.get("why") or "")][-1]
        self.assertGreater(rec["pool"], 0); self.assertEqual(rec["picked"], "anchored")
        # Ben's table-wide window is untouched: a line that was SPOKEN by anyone is no candidate for 300 s whatever the turn rule says
        r.queue.clear(); t1 = self.clock.t
        for _, pid, _, _ in pool:
            r._said_at[pid] = t1
        self.clock.t = t1 + 181
        self.assertEqual(r.patter_candidates(r._last_snapshot, living), [], "PATTER_REPEAT_S still holds at 181 s")
        self.clock.t = t1 + 301
        self.assertGreater(len(r.patter_candidates(r._last_snapshot, living)), 0)
        self.assertEqual(sch.PATTER_REPEAT_S, 300.0)

    def test_a_proposal_at_minute_four_draws_a_reply_again(self):
        """Game 49, 11:16:01: seat 2 was eliminated, so 'someone wins' from seat 1 at seat 3 could only draw the
        subject's retort — all four were in the per-turn set, and the responder left without a word or a record."""
        r = self.r
        r.rng.choice = lambda xs: xs[0]

        def propose():
            r.after_spoken({"kind": "bark", "stock": "someone-wins", "text": "", "seat": 1, "library": r.lib_for(1, "someone-wins"),
                            "ctx": {"targets": [2]}, "chain": None})
            out = [(q["stock"], q["seat"]) for q in r.queue if q["kind"] == "bark"]
            r.queue.clear()
            return out
        self.assertEqual([propose() for _ in range(5)],
                         [[("im-not-the-threat", 2)], [("clapback", 2)], [("you-wish", 2)], [("laugh", 2)], []], "four retorts, then the well is dry")
        self.clock.t += 60
        self.assertEqual(propose(), [], "a minute on: dry, as before")
        self.clock.t += 121
        self.assertEqual(propose(), [("im-not-the-threat", 2)], "three minutes on: the subject answers again")
        self.assertEqual(len([x for x in self._records("queued", "bark") if x.get("source") == "chain"]), 5)

    def test_a_new_turn_still_clears_everything_at_once(self):
        r = self.r
        self.assertTrue(r.maybe_bark(1, "nothing-happening", turn=3, source="patter"))
        self.assertTrue(r.maybe_bark(2, "land-go", turn=3, source="procedural")); r.queue.clear()
        self.clock.t += 5
        r._roll_turn(4)
        self.assertIsInstance(r._said_this_turn, sch.TurnSaid); self.assertEqual(r._said_this_turn, {})
        self.assertTrue(r.maybe_bark(1, "nothing-happening", turn=4, source="patter"), "five seconds on, a new turn: said again")
        self.assertTrue(r.maybe_bark(2, "land-go", turn=4, source="procedural"), "the anchored id too")
        self.assertEqual(sorted([int(s), str(p)] for s, p in r._said_this_turn), [[1, "nothing-happening"], [2, "land-go"]], "the checkpoint's shape still reads it")
        # a restored checkpoint (or a test) hands the runner a plain set: adopted, every entry stamped now — the conservative reading
        r._said_this_turn = {(1, "nothing-happening"), (2, "land-go")}
        self.assertTrue(r.said_this_turn(1, "nothing-happening", optional=True)); self.assertTrue(r.said_this_turn(2, "land-go", optional=False))
        self.assertIsInstance(r._said_this_turn, sch.TurnSaid)
        self.clock.t += 181
        self.assertFalse(r.said_this_turn(1, "nothing-happening", optional=True)); self.assertTrue(r.said_this_turn(2, "land-go", optional=False))
        self.assertEqual(sch.TURN_REPEAT_S, 180.0)
        self.assertEqual((sch.RECENT_S, sch.PATTER_REPEAT_S, sch.SILENCE_FLOOR_S), (240.0, 300.0, {"ai": 12.0, "human": 24.0}), "Ben's numbers stay")
        self.assertEqual(sch.RARE_REPEATS, {"come-on-land", "thinking", "holding-mana", "tapped-out", "mana-up", "land-go", "early-game", "long-game", "loop", "looping"})

    def test_a_short_turn_is_exactly_as_before(self):
        self.assertEqual(_sixty_second_turn(self), HEAD_TRACE_60S, "a 60 s turn: the same results, queue and records as HEAD's set")


if __name__ == "__main__":
    unittest.main()

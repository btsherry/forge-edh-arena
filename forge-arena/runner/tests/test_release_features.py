"""The experimental-release features batch (docs/reviews/2026-09-16-release-features-plan.md, steps 1-8):
deals polish (offer delivery at the seat's next window, the panel nudge, deal-over certain for the
player), procedural narration ungoverned, grudges every second hit, the runner's up/summary records,
hygiene's grounding score, the named -> generic fallback, the kill-shot family, threat memory.
Run: python3 -m unittest discover -s tests"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voice import scheduler as sch  # noqa: E402
from voice import events as ev  # noqa: E402
from test_deals_seat import make_runner, offer, react, deal_rows  # noqa: E402
from test_table_lines import _TableCase  # noqa: E402


# ---- step 1a: a pending offer holds the window for the model
class OfferDelivery(unittest.TestCase):
    def test_a_pending_offer_makes_a_fastpath_window_the_models(self):
        r = make_runner()
        r._fastpath = lambda req: ({"chosenId": 0}, "memo")             # a memo would answer this REACT without the brain
        r.brain.script = [{"chosenId": 0}, {"chosenId": 0}]
        r.handle(react(1))
        self.assertEqual(r.brain.calls, 0, "no offer pending: the memo answers")
        oid = offer(r, 1005, "1005-0-3")
        r.brain.script = [{"chosenId": 0, "deal": {"offer_id": oid, "accept": True}, "say": "take-the-deal"}]
        r.handle(react(2))
        self.assertEqual(r.brain.calls, 1, "game 50: the offer is answered at the seat's NEXT window, not its own turn")
        self.assertIn("DEAL PENDING", r.brain.last_prompt)
        self.assertTrue(any("held for the model: an offer is waiting" in l for l in r.log_lines))
        self.assertEqual(deal_rows(r)[-1]["deal"]["accept"], True)
        r.handle(react(3))
        self.assertEqual(r.brain.calls, 1, "answered: the memo may answer again")


# ---- steps 1c, 2, 6 (fallback), 8 (threat memory), 7 (kill-shot): the table
class TableBatch(_TableCase):
    def test_deal_over_is_certain_for_the_players_deal_and_rolled_for_the_seats(self):
        r = self.r
        self._snap(4, 1); r.queue.clear()
        r.rng.random = lambda: 0.99                                       # the dice miss everything optional
        r.duty = lambda window=sch.DUTY_WINDOW_S: 1.0                     # and the table is over budget (game 51: p=0.93 lost the lapse)
        r.strike_deal(0, 1, "truce", 4, by=1, until_turn=5)
        r.strike_deal(2, 3, "truce", 4, by=3, until_turn=5)
        r.lapse_deals(6)
        said = [q["stock"] for q in r.queue if q["kind"] == "bark"]
        self.assertEqual(said.count("deal-over"), 1, "the player's deal ending is spoken; the seats' may pass unremarked (Ben, game 50)")
        self.assertEqual([q["ctx"]["targets"] for q in r.queue if q["stock"] == "deal-over"], [[0]])

    def test_procedural_narration_is_not_governed(self):
        r = self.r
        self._snap(4, 1); r.queue.clear()
        r.duty = lambda window=sch.DUTY_WINDOW_S: 1.0                     # far over budget
        r.rng.random = lambda: 0.2                                        # passes a certain line, fails a governed 0.9 x 0.15
        self.assertTrue(r.maybe_bark(1, "land-go", turn=4, source="procedural", p=1.0, ctx={"targets": []}),
                        "a seat narrating its own turn is always worth the breath (game 48: thirty died to the budget)")
        r.queue.clear()
        self.assertFalse(r.maybe_bark(2, "nothing-happening", turn=4, source="patter", p=0.9, ctx={"targets": []}),
                         "filler still answers to the governor")

    def test_a_seats_answer_to_a_deal_is_never_rolled(self):
        r = self.r
        self._snap(6, 2); r.queue.clear()
        r.duty = lambda window=sch.DUTY_WINDOW_S: 1.0                     # far over budget
        r.rng.random = lambda: 0.97                                       # game 51: "dice (brain, p=0.96)" lost Giada's "Deal, Player One"
        for pid in ("deal-with-you", "no-deal-with-you", "counter-offer"):
            r.queue.clear()
            self.assertTrue(r.maybe_bark(2, pid, turn=6, source="brain", p=1.0, ctx={"targets": [0]}), pid)

    def test_a_named_line_heard_lately_falls_back_to_its_generic(self):
        r = self.r
        self._snap(4, 1); r.queue.clear()
        r.rng.random = lambda: 0.0                                        # the address swap always wants the named take
        named = r.address_swap(1, "deal", {"targets": [2]})
        if not named:
            self.skipTest("no named wording for seat 2's commander in this fixture")
        r._said_at[named] = self.clock.t - 60                             # heard a minute ago
        self.assertEqual(r.address_swap(1, "deal", {"targets": [2]}), "", "the generic, with its several takes, speaks instead")
        r._said_at[named] = self.clock.t - sch.PATTER_REPEAT_S - 1
        self.assertEqual(r.address_swap(1, "deal", {"targets": [2]}), named, "five minutes on, the named take is back")

    def test_threat_memory_names_the_real_threat_and_decays(self):
        r = self.r
        seats = [self._seat(0, life=40), self._seat(1, life=45), self._seat(2, life=30), self._seat(3, life=20)]
        self._snap(6, 1, seats=seats); r.queue.clear()
        self.assertEqual(r.leader_of(2), 1, "no pin: the life leader")
        r.raise_threat(3, 3.0, "combo online")
        self.assertEqual(r.leader_of(2), 3, "a pin above THREAT_MIN outranks life")
        cands = {(pid, tgt) for _, pid, tgt, _ in r.patter_candidates(r._last_snapshot, [1, 2, 3])}
        self.assertIn(("youre-the-threat", 3), cands); self.assertIn(("kill-that", 3), cands)
        self.assertNotIn(("youre-the-threat", 1), cands, "the life leader is not the threat while a pin is raised")
        r.raise_threat(3, 4.0, "a loop called")
        cands = {(pid, tgt) for _, pid, tgt, _ in r.patter_candidates(r._last_snapshot, [1, 2, 3])}
        self.assertIn(("someone-wins", 3), cands, "at THREAT_WINNING the table says so")
        r.decay_threat(); r.decay_threat()
        self.assertAlmostEqual(r._threat[3], 1.75)
        self.assertEqual(r.leader_of(2), 1, "decayed under THREAT_MIN: back to life")
        self.assertIn("3", r._recency_state()["threat"], "the pin travels in the checkpoint")
        levels = [x for x in self._records("noted", "threat")]
        self.assertEqual(len(levels), 2)

    def test_two_seats_falling_at_once_is_the_kill_shot(self):
        r = self.r
        self._snap(9, 1); r.queue.clear()
        r.rng.random = lambda: 0.0
        r._last_hit_by = {2: ([1], 9), 3: ([1], 9)}                       # seat 1 (voiced) finished both; seat 3 has no voice in this fixture
        seats = [self._seat(0), self._seat(1)]                            # seats 2 and 3 vanished from the snapshot together
        (self.mailbox / "observer-state.json").write_text(json.dumps({"turn": 9, "phase": "COMBAT_DAMAGE", "activeSeat": 1, "gameOver": False,
                                                                        "seats": seats, "events": [], "stackDetail": []}))
        r.scan_observer()
        stocks = [q["stock"] for q in r.queue if q["kind"] == "event"]
        self.assertIn("table-kill", stocks, "the killer: 'and that's the table'")
        self.assertIn("all-of-us", stocks, "a dying seat: 'all of us? at once?'")
        self.assertEqual(stocks.count("table-kill"), 1)
        self.assertNotIn("kill", [q["stock"] for q in r.queue if q["kind"] == "bark"], "the plain kill line yields to the kill-shot")
        self.assertEqual(r.eliminated, {2, 3})
        self.assertEqual([q["seat"] for q in r.queue if q["stock"] == "all-of-us"], [2], "the dying seat with a voice says it")

    def test_a_single_death_is_not_a_kill_shot(self):
        r = self.r
        self._snap(9, 1); r.queue.clear()
        r.rng.random = lambda: 0.0
        r._last_hit_by = {2: ([1], 9)}
        seats = [self._seat(0), self._seat(1), self._seat(3)]             # seat 2 alone vanished
        (self.mailbox / "observer-state.json").write_text(json.dumps({"turn": 9, "phase": "COMBAT_DAMAGE", "activeSeat": 1, "gameOver": False,
                                                                        "seats": seats, "events": [], "stackDetail": []}))
        r.scan_observer()
        stocks = [q["stock"] for q in r.queue]
        self.assertNotIn("table-kill", stocks); self.assertNotIn("all-of-us", stocks)
        self.assertIn("kill", stocks)


# ---- step 3: grudges
class Grudges(unittest.TestCase):
    def test_the_second_hit_earns_the_grudge(self):
        self.assertEqual(ev.GRUDGE_EVERY, 2, "the memory layer pays out (2026-09-16)")


# ---- step 4: the runner's records
class RunnerRecords(_TableCase):
    def test_up_and_summary_records_and_the_spoke_target(self):
        r = self.r
        r.record_up()
        ups = [x for x in self._records("up")]
        self.assertEqual((ups[-1]["restart"], ups[-1]["kind"]), (0, "runner"))
        r.record_up()
        self.assertEqual(self._records("up")[-1]["restart"], 1, "the second start counts the first")
        self._snap(4, 1); r.queue.clear()
        r.rng.random = lambda: 0.0
        r.maybe_bark(1, "kill-that", turn=4, source="patter", p=1.0, ctx={"targets": [2]})
        self.clock.t += 10
        item = r.next_item()
        self.assertIsNotNone(item)
        r.speak(item)
        sp = self._records("spoke", "bark")[-1]
        self.assertEqual(sp["target"], 2, "who the line was aimed at, for hygiene's grounding score")
        r.record_summary()
        sm = self._records("summary")[-1]
        self.assertGreaterEqual(sm["spoke"], 1); self.assertIn("patter", sm["by_source"]); self.assertEqual(sm["atoms"], 0)


# ---- step 5: hygiene's grounding line
class Grounding(unittest.TestCase):
    def test_the_grounding_score_from_a_synthetic_archive(self):
        import importlib.util, tempfile
        spec = importlib.util.spec_from_file_location("hy", Path(__file__).resolve().parents[2] / "scripts" / "arena-hygiene.py")
        hy = importlib.util.module_from_spec(spec); spec.loader.exec_module(hy)
        d = Path(tempfile.mkdtemp())
        (d / "game-1.json.rated").write_text(json.dumps({"placementGroups": [[3], [1], [0, 2]]}))
        (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in [
            {"kind": "cast", "turn": 5, "seat": 1}, {"kind": "cast", "turn": 5, "seat": 1}, {"kind": "cast", "turn": 6, "seat": 3}]))
        voice = [{"event": "spoke", "kind": "bark", "stock": "kill-that", "target": 3, "turn": 5, "ts": 1.0},     # the winner
                 {"event": "spoke", "kind": "bark", "stock": "youre-the-threat", "target": 1, "turn": 5, "ts": 2.0},  # the turn's busiest seat
                 {"event": "spoke", "kind": "bark", "stock": "hit-giada", "target": 2, "turn": 6, "ts": 3.0},          # neither
                 {"event": "spoke", "kind": "bark", "stock": "nothing-happening", "turn": 6, "ts": 4.0}]              # not addressed
        lines = hy.grounding(str(d), voice)
        self.assertEqual(len(lines), 1)
        self.assertIn("grounding: 67% of 3 addressed lines named the winner or the turn's busiest seat (winner seat 3)", lines[0])
        self.assertEqual(hy.grounding(str(d), [{"event": "spoke", "kind": "bark", "stock": "taunt"}]), [], "no addressed lines: silent")


if __name__ == "__main__":
    unittest.main()

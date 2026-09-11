"""Round 31 (experimental/voicework2, 2026-09-10) — the table's talk budget and the
mix of what gets said. Five Game Knights tapes: ~190 words/min, mostly procedural
self-narration and reactions to plays. Game 45 at rowdy: 7.8 lines/min at a 31 %
speaking duty — the right density, the wrong mix (53 % banter replies, 38 % filler,
4 % about the game). So: (1) the chatter dial sets a duty-cycle GOAL the governor
spends — optional lines (patter, banter replies) fall to a floor at the goal, lines
anchored to a board event keep at least half their chance, silence and a lively
dial boost; (2) a fresh reaction outranks Joshua's colour and the "your move" cue,
and filler never evicts it; (3) the seats react to the HUMAN's plays — a big swing,
a game changer, the commander, a big spell, spot removal — which they ignored
before; (4) filler weights are a quarter and the chain table is pruned to 90 invites.
Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import voice_runner as vr  # noqa: E402
from test_barks_runtime import _TreeCase, FakePlayer  # noqa: E402


class TalkBudget(_TreeCase):
    def test_duty_is_the_speaking_fraction_of_the_last_minute(self):
        r = self.r; t = self.clock.t
        self.assertEqual(r.duty(), 0.0)
        r._spoken_log = [(t - 100, 5.0), (t - 65, 10.0), (t - 20, 3.0)]
        self.assertAlmostEqual(r.duty(), (5.0 + 3.0) / 60, msg="an old line is gone, a straddling line counts its tail")
        self.assertEqual(len(r._spoken_log), 2, "the log is trimmed as it is read")

    def test_goal_follows_the_dial_the_override_and_the_humans_turn(self):
        os.environ["ARENA_CHATTER"] = "lively"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertAlmostEqual(r.duty_target, 0.27); self.assertAlmostEqual(r.duty_goal(), 0.27)
        r._last_snapshot = {"activeSeat": 0}
        self.assertAlmostEqual(r.duty_goal(), 0.27 * 0.4, msg="the human's turn: well under half")
        os.environ["ARENA_VOICE_DUTY"] = "0.25"; os.environ["ARENA_VOICE_DUTY_HUMAN"] = "0.5"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual((r.duty_target, r.duty_human), (0.25, 0.5), "the override beats the dial")
        os.environ["ARENA_VOICE_DUTY"] = "bogus"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertAlmostEqual(r.duty_target, 0.27, msg="a bad override falls back to the dial")

    def test_governor_boosts_in_silence_and_throttles_at_the_goal(self):
        r = self.r; t = self.clock.t                                   # normal: goal 0.18
        self.assertEqual((r.governor(False), r.governor(True)), (1.0, 1.0), "silence at normal: the knobs as written")
        r._spoken_log = [(t - 30, 5.4)]                                # half the budget spent
        self.assertAlmostEqual(r.governor(False), 1.0); self.assertAlmostEqual(r.governor(True), 0.15 + 0.85 * 0.5)
        r._spoken_log = [(t - 30, 11.0)]                               # at the goal
        self.assertEqual(r.governor(True), 0.15, "patter and banter go nearly silent")
        self.assertTrue(0.5 <= r.governor(False) <= 1.0, "an anchored line keeps at least half")
        r._spoken_log = [(t - 40, 30.0)]                               # far over it
        self.assertEqual(r.governor(False), 0.5); self.assertEqual(r.governor(True), 0.15)
        os.environ["ARENA_CHATTER"] = "rowdy"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual((r.governor(False), r.governor(True)), (2.0, 2.0), "silence at rowdy: the dial's full boost")
        r._spoken_log = [(t - 30, 60 * 0.18)]                          # half of rowdy's 0.36 spent
        self.assertAlmostEqual(r.governor(False), 1.5); self.assertAlmostEqual(r.governor(True), 1.5 * (0.15 + 0.85 * 0.5))
        r.duty_target = 0.0
        self.assertEqual(r.governor(True), 1.0, "no goal: no governor")

    def test_every_optional_roll_goes_through_the_governor_and_anchored_lines_survive(self):
        r = self.r
        r.duty = lambda window=vr.DUTY_WINDOW_S: 1.0                   # the table has been talking non-stop
        r.rng.random = lambda: 0.2
        self.assertFalse(r.maybe_bark(1, "deal", turn=3, source="patter", ctx={"targets": [2]}))
        self.assertIn("governor 0.15", self._records("skipped", "bark")[-1]["why"])
        self.assertTrue(r.maybe_bark(1, "that-hurt", turn=3, source="event"), "1.0 × max(0.5, goal/duty) = 0.5 > 0.2")
        self.assertEqual(r.queue[-1]["prio"], vr.BARK_PRIORITY["event"])
        # colour through the governor too (anchored: halves, never below)
        r.color_mode = "some"; r.color_p = 0.9
        r._voice_color({"text": "Recap.", "owner": 0, "seq": 1})
        self.assertEqual([q["kind"] for q in r.queue if q["kind"] == "color"], ["color"], "0.9 × 0.5 = 0.45 > 0.2")
        # and the patter clock
        r.patter_on = True; r.patter_gap = (1.0, 1.0); r.rng.uniform = lambda a, b: a
        r._last_snapshot = {"turn": 3, "phase": "MAIN1", "activeSeat": 1, "seats": [{"seat": i, "life": 40, "handSize": 3, "battlefield": []} for i in range(4)]}
        r.queue.clear(); r.last_spoken_at = self.clock.t; r._patter_anchor = None
        self.clock.t += 2; r.patter()
        self.assertEqual(r.queue, [])
        self.assertIn("governor (duty 1.00", self._records("skipped", "bark")[-1]["why"])

    def test_the_spoke_record_carries_the_duty(self):
        self._advisor(kind="bark", seat=1, id="big-swing", turn=4)
        self._step()
        rec = self._records("spoke")[-1]
        self.assertIn("duty", rec); self.assertIn("goal", rec); self.assertEqual(rec["goal"], 0.18)
        self.assertEqual(len(self.r._spoken_log), 1)


class BarkLadder(_TreeCase):
    def test_a_reaction_outranks_colour_and_your_move_and_filler_never_evicts_it(self):
        r = self.r
        r.enqueue("color", text="Joshua's recap.", ttl=40.0)
        r.enqueue("your_move", stock="your-move", ttl=12.0)
        self.assertTrue(r.maybe_bark(1, "that-hurt", turn=3, source="event"))
        order = [q["kind"] for q in sorted(r.queue, key=lambda q: (q["prio"], q["at"]))]
        self.assertEqual(order, ["bark", "color", "your_move"], "the reaction plays first")
        self.assertTrue(r.maybe_bark(2, "nothing-happening", turn=3, source="patter"))
        barks = [(q["stock"], q["prio"]) for q in r.queue if q["kind"] == "bark"]
        self.assertEqual(barks, [("that-hurt", 5.5), ("nothing-happening", 8.5)], "filler queues behind the reaction, never over it")
        self.assertTrue(r.maybe_bark(1, "big-swing", turn=3, source="event"))
        self.assertEqual([q["stock"] for q in r.queue if q["kind"] == "bark"], ["big-swing"], "a fresh reaction clears everything pending")
        r.enqueue("bark", stock="laugh", library="bill", seat=2, ttl=15.0, gap=0.25, chain={"origin": 1, "hop": 1, "turn": 3})
        self.assertEqual([q["stock"] for q in r.queue if q["kind"] == "bark"], ["big-swing", "laugh"], "a retort never evicts a reaction")
        self.assertTrue(r.maybe_bark(2, "deal", turn=3, source="patter", ctx={"targets": [1]}))
        self.assertTrue(r.maybe_bark(1, "slow-turn", turn=3, source="recap"))
        stocks = [q["stock"] for q in r.queue if q["kind"] == "bark"]
        self.assertEqual(stocks, ["big-swing", "laugh", "slow-turn"], "the advisor's afterthought evicts the filler, keeps the reaction and the retort")
        self.assertEqual([q["stock"] for q in sorted(r.queue, key=lambda q: (q["prio"], q["at"])) if q["kind"] == "bark"], ["laugh", "big-swing", "slow-turn"])
        self.assertTrue(r.maybe_bark(2, "my-turn", turn=3, source="opener", p=1.0))
        self.assertEqual([q["stock"] for q in r.queue if q["kind"] == "bark"], ["my-turn"], "an opener is anchored: newest wins")

    def test_the_ladder_and_the_classes(self):
        self.assertEqual(vr.BARK_PRIORITY["chain"], vr.CHAIN_HOP_PRIORITY)
        self.assertLess(vr.PRIORITY["quip"], vr.BARK_PRIORITY["event"]); self.assertLess(vr.BARK_PRIORITY["event"], vr.PRIORITY["color"])
        self.assertLess(vr.PRIORITY["your_move"], vr.BARK_PRIORITY["recap"], "the advisor's tagged afterthoughts stay behind the cue (game 44)")
        self.assertEqual(vr.VoiceRunner._bark_class({"prio": 5.5, "chain": None}), "anchored")
        self.assertEqual(vr.VoiceRunner._bark_class({"prio": 8.0, "chain": None}), "optional")
        self.assertEqual(vr.VoiceRunner._bark_class({"prio": 3.5, "chain": {"hop": 1}}), "chain")


class ReactToTheHuman(_TreeCase):
    def _events(self, turn, *evs):
        self._observer(turn, 0, events=list(evs)); self.r.scan_observer()
        got = [q for q in self._queued() if q[0] == "bark"]
        self.r.queue.clear()
        return got

    def test_the_table_reacts_to_the_humans_swing_game_changer_commander_big_spell_and_removal(self):
        self.r.rng.random = lambda: 0.0
        self.r.game_changers[0] = {"Rhystic Study"}
        self._observer(3, 0, events=[{"seq": 1, "kind": "cast", "turn": 2, "seat": 0, "spell": "old", "cmc": 9}]); self.r.scan_observer(); self.r.queue.clear()
        ev = [{"seq": 1, "kind": "cast", "turn": 2, "seat": 0, "spell": "old", "cmc": 9}]
        ev.append({"seq": 2, "kind": "attack", "turn": 3, "seat": 0, "attackers": 1, "power": 9, "defenders": [2]})
        got = self._events(3, *ev)
        self.assertEqual((len(got), got[0][3], got[0][1] in ("brace", "why-me")), (1, 2, True), got)
        q = self._records("queued", "bark")[-1]; self.assertEqual((q["source"], q["seat"]), ("event", 2))
        ev.append({"seq": 3, "kind": "cast", "turn": 4, "seat": 0, "spell": "Rhystic Study", "commander": False, "cmc": 3})
        got = self._events(4, *ev)
        self.assertEqual([g[1] for g in got], ["gc-react"], "the human's game changer alarms the table")
        self.assertIn(got[0][3], (1, 2))
        ev.append({"seq": 4, "kind": "cast", "turn": 5, "seat": 0, "spell": "Giada, Font of Hope", "commander": True, "cmc": 2})
        got = self._events(5, *ev)
        self.assertEqual(len(got), 1); self.assertIn(got[0][1], ("oh-no", "brace", "read-that"))
        ev.append({"seq": 5, "kind": "cast", "turn": 6, "seat": 0, "spell": "Big", "commander": False, "cmc": 8})
        self.assertEqual([g[1] for g in self._events(6, *ev)], ["wow"])
        ev.append({"seq": 6, "kind": "cast", "turn": 7, "seat": 0, "spell": "Mid", "commander": False, "cmc": 5})
        got = self._events(7, *ev); self.assertEqual(len(got), 1); self.assertIn(got[0][1], ("nice-play", "read-that", "oh-no"))
        n = len(self._records("queued", "bark"))
        ev.append({"seq": 7, "kind": "cast", "turn": 8, "seat": 0, "spell": "Small", "commander": False, "cmc": 2})
        self.assertEqual(self._events(8, *ev), [], "a two-drop is nothing to remark on")
        self.assertEqual(len(self._records("queued", "bark")), n)
        ev.append({"seq": 8, "kind": "left", "turn": 9, "by": 0, "cards": ["Sol Ring"], "seats": [2], "commanders": [], "n": 1, "tokens": 0})
        got = self._events(9, *ev)
        self.assertEqual(got, [("bark", "oh-no", "bill", 2)], "the human's spot removal: the owner objects")
        last = [r for r in self._records("queued", "bark")][-1]
        self.assertEqual((last["source"], last["seat"], last["stock"]), ("event", 2, "oh-no"))

    def test_human_reaction_probability_is_its_own_knob(self):
        os.environ["ARENA_BARKS_HUMAN_P"] = "0.4"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual(r.barks_human_p, 0.4)
        self.assertEqual(self.r.barks_human_p, 0.7, "default")
        self.r.rng.random = lambda: 0.75                                # >= 0.7: no reaction
        self._observer(3, 0, events=[{"seq": 1, "kind": "cast", "turn": 2, "seat": 0, "spell": "x", "cmc": 1}]); self.r.scan_observer(); self.r.queue.clear()
        self._observer(3, 0, events=[{"seq": 1, "kind": "cast", "turn": 2, "seat": 0, "spell": "x", "cmc": 1},
                                     {"seq": 2, "kind": "attack", "turn": 3, "seat": 0, "attackers": 3, "power": 3, "defenders": [1]}]); self.r.scan_observer()
        self.assertEqual([q for q in self._queued() if q[0] == "bark"], [])
        self.assertIn("p=0.70", self._records("skipped", "bark")[-1]["why"])

    def test_the_humans_game_changers_come_from_the_launcher_and_the_game_log(self):
        os.environ["ARENA_HUMAN_DECK"] = "giada-font-of-hope"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertIn("Smothering Tithe", r.game_changers[0], "the human's deck from the launcher")
        self.assertNotIn(0, self.r.game_changers, "no launcher env: nothing known about the human")
        with (self.logs / "game.jsonl").open("w") as f:
            for seat, deck in ((0, "giada-font-of-hope"), (1, "urza-lord-high-artificer"), (2, "purphoros-god-of-the-forge"), (3, "selvala-heart-of-the-wilds")):
                f.write(json.dumps({"seat": seat, "deck": deck}) + "\n")
        self.r.learn_table()
        self.assertIn("The One Ring", self.r.game_changers[0], "the game log names the human's deck too")
        self.assertIn("Rhystic Study", self.r.game_changers[1])


class LeanerBags(_TreeCase):
    def test_filler_is_a_quarter_of_what_it_was(self):
        seats = [{"seat": i, "life": 40, "handSize": 3, "battlefield": []} for i in range(4)]
        cands = self.r.patter_candidates({"turn": 3, "activeSeat": 1, "seats": seats}, [1, 2])
        w = {pid: wgt for _, pid, _, wgt in cands}
        self.assertAlmostEqual(w["nothing-happening"], 0.125); self.assertAlmostEqual(w["this-is-fine"], 0.125)
        self.assertAlmostEqual(w["good-hand"], 0.05); self.assertAlmostEqual(w["what-turn"], 0.075)
        self.assertAlmostEqual(w["deal"], 0.25); self.assertAlmostEqual(w["pass-already"], 0.5)

    def test_the_chain_table_is_pruned_but_the_anchored_openers_keep_their_replies(self):
        table = json.loads((Path(__file__).resolve().parents[1] / "voice" / "stock" / "voices" / "chains.json").read_text())
        inv = table["invites"]
        table_ids = set(json.loads((Path(__file__).resolve().parents[1] / "voice" / "stock" / "voices" / "harry" / "table" / "manifest.json").read_text())["phrases"])
        self.assertEqual(sum(len(v) for k, v in inv.items() if k not in table_ids), 93, "140 invites before round 31 (the generic lines: 90 pruned + big-swing's 'open' row + deal's two arc replies)")
        self.assertEqual(sum(len(v) for v in inv.values()), 152, "plus the table openers' and the arc lines' invites")
        for opener in ("big-swing", "landed-hit", "that-hurt", "counter", "got-countered", "removal", "sweep", "got-swept", "kill", "game-changer", "commander-cast", "lost-commander"):
            self.assertGreaterEqual(len(inv[opener]), 2, f"{opener} is anchored to a board event: it keeps its replies")
        for reply in ("agree", "clapback", "sympathy", "gg", "last-word", "nerd", "wow", "read-that", "thinking-hard", "what-turn"):
            self.assertEqual(inv[reply], [], f"{reply} ends an exchange")
        for k, v in inv.items():
            if k in ("agree", "disagree", "scoff", "clapback", "brace", "pile-on", "sympathy", "laugh", "you-suck", "you-wish", "shut-it", "bite-me", "not-sorry"):
                self.assertLessEqual(len(v), 1, f"a reply invites at most one more reply: {k}")
        self.assertNotIn("you-cheat", [o["reply"] for k in ("good-hand", "promise") for o in inv[k]], "fewer cheating accusations (game 45)")


if __name__ == "__main__":
    unittest.main()

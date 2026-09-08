"""Regression tests for the accepted findings of the 2026-09-07 Gemini review
(docs/reviews/2026-09-07-gemini-review.md). Each test names the finding.
Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import advisor_runner as ar  # noqa: E402
from seatd import record  # noqa: E402
from seatd.protocol import SeatMailbox  # noqa: E402
from seatd.runner import SeatRunner  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "engine"
PASS = {"chosenId": 0}


def runner():
    tmp = Path(tempfile.mkdtemp(prefix="rev-"))
    return SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))


def react(*options, stack=("Staff of Domination",), kinds=("ability",), owners=(0,), targets=None,
          life=21, pool=0, untapped=0, avail=None, turn=23):
    r = json.loads((FIX / "react.json").read_text())
    r["turn"] = turn
    st = r["state"]
    st["seat"] = 2; st["life"] = life; st["manaPool"] = pool; st["untappedManaSourceCount"] = untapped
    st["manaAvailableNow"] = avail if avail is not None else pool + untapped
    st.pop("manaReach", None)   # the fixture carries the engine's reach; tests set the sum explicitly
    st["stack"] = list(stack); st["stackKinds"] = list(kinds); st["stackOwners"] = list(owners)
    st["stackTargets"] = targets if targets is not None else [[] for _ in stack]
    st["battlefield"] = [{"id": 77, "name": "Gilded Lotus"}]
    r["options"] = [{"id": 0, "label": "Pass (do nothing)", "cost": None, "type": "PASS"}] + [
        {"id": i + 1, "label": lab, "cost": cost, "type": "Ability"} for i, (lab, cost) in enumerate(options)]
    return r


class ReactorAndThreatGuards(unittest.TestCase):
    def test_stifle_class_counters_are_not_dead_on_an_all_abilities_stack(self):   # finding R1 (P0)
        r = runner()
        stifle = ("Stifle  {U} — Counter target activated or triggered ability.", "{U}")
        self.assertIsNone(r._fastpath(react(stifle, untapped=1)), "Stifle answers an ability: the model decides")
        negate = ("Negate  {1}{U} — Counter target noncreature spell.", "{1}{U}")
        ans, src = r._fastpath(react(negate, untapped=2))
        self.assertEqual((ans, src), (PASS, "affordability"), "a pure spell counter is dead vs abilities")

    def test_mana_only_options_stay_live_when_our_source_is_targeted(self):   # finding R4 (P1)
        r = runner()
        lotus = ("Gilded Lotus  {T} — Add three mana of any one color.", "{T}")
        ans, src = r._fastpath(react(lotus, untapped=1))
        self.assertEqual(src, "affordability", "no threat: mana-only is dead")
        self.assertIsNone(r._fastpath(react(lotus, untapped=1, stack=("Beast Within",), kinds=("spell",), owners=(3,),
                                            targets=[["Gilded Lotus (77)"]])), "Beast Within on the Lotus: float it first")

    def test_repeat_rule_needs_an_all_abilities_stack(self):   # finding R5 (P1)
        r = runner()
        ring = ("The One Ring  {T} — draw a card for each burden counter.", "{T}")
        first = react(ring)
        r._note_tap_pass(first, PASS)
        self.assertEqual(r._fastpath(react(ring))[1], "repeat")
        self.assertIsNone(r._fastpath(react(ring, stack=("Peer into the Abyss",), kinds=("spell",), owners=(3,))),
                          "a spell on the stack: dig with the Ring is a live question")

    def test_game_reset_clears_the_per_turn_memories(self):   # finding R7 (P2)
        r = runner()
        r._tap_pass = (1, ("x",), 40); r._yielded = {(1, "a", 0, "ability", ()): (40, 0, 0)}
        req = react(stack=(), kinds=(), owners=()); req["seq"] = 1; req["turn"] = 1
        req["decisionType"] = "CAST_SPELL"   # an own-main window: nothing to yield on after the reset
        r.mb.game_reset = True
        r.brain.decide = lambda *a, **k: (PASS, {"latency_s": 0.1, "usage": None, "cache_read": None, "raw": "{}"})
        r.brain.session_id = "s"; r.brain.ensure_session = lambda *a, **k: True
        r.mb.respond = lambda req, ans: True
        r.handle(req)
        self.assertIsNone(r._tap_pass); self.assertEqual(r._yielded, {})


class RecordAndHeartbeat(unittest.TestCase):
    def test_record_drops_the_oldest_turns_never_the_newest(self):   # finding R9 (P2)
        d = Path(tempfile.mkdtemp(prefix="rec-"))
        rows = [{"seat": 2, "gameId": "g", "turn": t, "seq": t, "type": "CAST_SPELL", "source": "model",
                 "answer": {"chosenId": 1}, "why": "reason " * 30,
                 "board": {"lives": {"0": 40 - t, "2": 40}, "stack": ["Card %d" % t]}} for t in range(1, 60)]
        (d / "game.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        text = record.render(d / "game.jsonl", None, 2, max_chars=3000)
        self.assertLessEqual(len(text), 3000, "the newest FULL_TURNS blocks always fit a 3k budget")
        self.assertIn("Turn 59", text, "the newest turn survives")
        self.assertIn("earlier turn", text, "the omission is announced")
        self.assertNotIn("…\n", text[-3:], "no tail truncation")
        tiny = record.render(d / "game.jsonl", None, 2, max_chars=600)
        self.assertLessEqual(len(tiny), 600, "the hard cap holds")
        self.assertIn("Turn 59", tiny, "and it keeps the newest text, cutting from the front")

    def test_record_labels_survive_dict_shaped_options(self):   # finding R2 (P1)
        self.assertEqual(record._label({"answer": {"chosenId": 1}, "options": ["Pass", {"id": 1, "label": "Chrome Mox  {0}"}]}),
                         "Chrome Mox")

    def test_heartbeat_thread_stops(self):   # finding R6 (P2)
        tmp = Path(tempfile.mkdtemp(prefix="hb-"))
        mb = SeatMailbox(0, str(tmp))
        mb.HEARTBEAT_S = 0.05
        mb.start_heartbeat_thread()
        time.sleep(0.15)
        hb = tmp / "seat-0" / "heartbeat"
        self.assertTrue(hb.exists())
        mb.stop_heartbeat_thread()
        time.sleep(0.15)
        m1 = hb.stat().st_mtime_ns
        time.sleep(0.2)
        self.assertEqual(hb.stat().st_mtime_ns, m1, "no beats after stop")
        self.assertFalse(any(t.name == "seat-0-heartbeat" and t.is_alive() for t in threading.enumerate()))


class AdvisorExecutiveGuards(unittest.TestCase):
    def test_advisor_never_rotates_while_executive_and_tracks_the_seat_game_id(self):   # findings R3, R8
        tmp = Path(tempfile.mkdtemp(prefix="exec-"))

        class FakeBrain:
            deck = "selvala-heart-of-the-wilds"; model = "opus"; effort = "low"; session_id = "s1"
            last_prompt_tokens = 10_000_000; totals = {"calls": 0}; backend = None; wedges = 0; calls = 0
            rotated = 0

            def ensure_session(self, *a, **k): return True
            def reset(self): pass
            def note(self, text, timeout_s=60.0): return True
            def rotate(self, text, timeout_s=120.0): self.rotated += 1; return True
        orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain, ar.opponent_deck_sections = (lambda *a, **k: FakeBrain()), (lambda *a, **k: [])
        try:
            adv = ar.AdvisorRunner("selvala-heart-of-the-wilds", tmp, "opus", "low", 30.0, log_dir=tmp / "logs")
        finally:
            ar.SeatBrain, ar.opponent_deck_sections = orig
        (tmp / "logs" / "control").mkdir(parents=True, exist_ok=True)
        (tmp / "logs" / "control" / "executive.json").write_text('{"on": true}')
        adv._executive_tick()
        self.assertIsNotNone(adv._exec)
        adv._exec._game_id = "g-77"
        adv._executive_tick()
        self.assertEqual(adv.game_id, "g-77")
        self.assertFalse(adv._maybe_rotate(), "the seat runner owns rotation while executive")
        self.assertEqual(adv.brain.rotated, 0)
        (tmp / "logs" / "control" / "executive.json").write_text('{"on": false}')
        adv._executive_tick()
        self.assertIsNone(adv._exec)

    def test_unknown_quip_is_logged_and_dropped(self):   # finding R10 (P3)
        logs = []
        text, quip = ar.split_quip("Nice line. [quip:nice-swingg]", log=logs.append)
        self.assertEqual((text, quip), ("Nice line.", None))
        self.assertTrue(logs and "nice-swingg" in logs[0])


if __name__ == "__main__":
    unittest.main()


class ReceiptSummaryTests(unittest.TestCase):
    """Ben, 2026-09-08: auto-pass receipts collapse to one line per turn in the panel."""
    def _adv(self):
        tmp = Path(tempfile.mkdtemp(prefix="rcpt-"))

        class FakeBrain:
            deck = "selvala-heart-of-the-wilds"; model = "opus"; effort = "low"; session_id = "s1"
            last_prompt_tokens = 0; totals = {"calls": 0}; backend = None; wedges = 0; calls = 0
            def ensure_session(self, *a, **k): return True
            def reset(self): pass
        orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain, ar.opponent_deck_sections = (lambda *a, **k: FakeBrain()), (lambda *a, **k: [])
        try:
            adv = ar.AdvisorRunner("selvala-heart-of-the-wilds", tmp, "opus", "low", 30.0, log_dir=tmp / "logs")
        finally:
            ar.SeatBrain, ar.opponent_deck_sections = orig
        out = []
        adv._stream_write = out.append
        import os as _os
        _os.environ["ARENA_AUTOPASS_RECEIPTS"] = "summary"   # explicit (the default since game 32)
        self.addCleanup(lambda: _os.environ.pop("ARENA_AUTOPASS_RECEIPTS", None))
        return adv, out

    def test_one_line_per_turn_with_counts(self):
        adv, out = self._adv()
        for _ in range(3):
            adv._show_note({"turn": 8, "note": "(auto-passed — nothing available)"})
        adv._show_note({"turn": 8, "note": "(auto-passed — only utility activations available: Arbor Elf)"})
        self.assertEqual(out, [], "nothing shown until the turn moves on")
        adv._show_note({"turn": 9, "note": "(auto-passed — nothing available)"})
        self.assertEqual(len(out), 1)
        self.assertIn("[r2-t8] ⏭ auto-passed 4 stops (nothing available ×3, only utility activations available: Arbor Elf)", out[0])

    def test_kept_prompts_show_at_once_and_flush_first(self):
        adv, out = self._adv()
        adv._show_note({"turn": 8, "note": "(auto-passed — nothing available)"})
        adv._show_note({"turn": 8, "note": "(prompt kept — castable: Khalni Ambush)"})
        self.assertEqual(len(out), 1); self.assertIn("prompt kept", out[0])
        adv._show_note({"turn": 9, "note": "(auto-passed — nothing available)"})
        self.assertIn("[r2-t8] ⏭ auto-passed 1 stop (nothing available)", out[1])

    def test_modes_all_and_off(self):
        adv, out = self._adv()
        import os as _os
        _os.environ["ARENA_AUTOPASS_RECEIPTS"] = "all"
        try:
            adv._show_note({"turn": 1, "note": "(auto-passed — nothing available)"})
            self.assertEqual(len(out), 1)
            _os.environ["ARENA_AUTOPASS_RECEIPTS"] = "off"
            adv._show_note({"turn": 1, "note": "(auto-passed — nothing available)"})
            self.assertEqual(len(out), 1)
        finally:
            _os.environ.pop("ARENA_AUTOPASS_RECEIPTS", None)

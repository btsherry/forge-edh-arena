"""Game 25 (2026-09-07) seat rules — cut the REPEAT offers, never the first:
- a counterspell / spell-copier is dead when the stack holds only abilities;
- a resourceless, tap-only REACT window is passed without a model call once
  the MODEL passed the same option set this turn and own life has not dropped;
- the same-turn memo buckets OPPONENTS' life above 10 (own life exact).
Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd.runner import SeatRunner  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "engine"
PASS = {"chosenId": 0}
RING = ("The One Ring  {T} — The One Ring (256) - seat puts a burden counter and draws a card for each.", "{T}")
FLARE = ("Flare of Duplication  {0}, Sacrifice a nontoken red creature — Copy target instant or sorcery spell.", "{0}")
BOLT = ("Lightning Bolt  {R} — Lightning Bolt deals 3 damage to any target.", "{R}")


def runner():
    tmp = Path(tempfile.mkdtemp(prefix="repeat-"))
    return SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))


def react(*options, stack=("Staff of Domination",), kinds=("ability",), owners=(0,), life=21, pool=0, untapped=0,
          turn=23, opp_life=(34, 4, 40), targets=None):
    r = json.loads((FIX / "react.json").read_text())
    r["turn"] = turn
    st = r["state"]
    st["seat"] = 2
    st["life"] = life
    st["manaPool"] = pool
    st["untappedManaSourceCount"] = untapped
    st["manaAvailableNow"] = pool + untapped
    st["stack"] = list(stack)
    st["stackKinds"] = list(kinds) if kinds is not None else None
    st["stackOwners"] = list(owners)
    st["stackTargets"] = targets if targets is not None else [[] for _ in stack]
    st["opponents"] = [{"seat": i, "life": l} for i, l in zip((0, 1, 3), opp_life)]
    r["options"] = [{"id": 0, "label": "Pass (do nothing)", "cost": None, "type": "PASS"}] + [
        {"id": i + 1, "label": lab, "cost": cost, "type": "Ability"} for i, (lab, cost) in enumerate(options)]
    return r


class SpellReactorRuleTests(unittest.TestCase):
    def test_copy_spell_with_only_abilities_on_the_stack_is_dead(self):
        r = runner()
        ans, src = r._fastpath(react(FLARE, stack=("Staff of Domination", "Selvala, Heart of the Wilds"),
                                     kinds=("ability", "ability"), owners=(0, 0)))
        self.assertEqual((ans, src), (PASS, "affordability"))
        self.assertIn("no spell on the stack", r._fast_why)

    def test_a_spell_on_the_stack_goes_to_the_model(self):
        r = runner()
        self.assertIsNone(r._fastpath(react(FLARE, stack=("Genesis Wave",), kinds=("spell",), owners=(0,))))

    def test_missing_stack_kinds_fails_open(self):
        r = runner()
        self.assertIsNone(r._fastpath(react(FLARE, kinds=None)))
        self.assertIsNone(r._fastpath(react(FLARE, stack=("A", "B"), kinds=("ability",), owners=(0, 0))), "length mismatch")

    def test_a_non_reactor_option_keeps_the_window(self):
        r = runner()
        self.assertIsNone(r._fastpath(react(FLARE, BOLT, untapped=1)))


class RepeatTapPassTests(unittest.TestCase):
    def test_tap_only_helper(self):
        t = SeatRunner._tap_only_utility
        self.assertTrue(t({"label": RING[0]}))
        self.assertFalse(t({"label": "Maze of Ith  {T} — Untap target attacking creature; prevent all combat damage."}))
        self.assertFalse(t({"label": "Viscera Seer  Sacrifice a creature — Scry 1."}))
        self.assertFalse(t({"label": "Staff of Domination  {5}, {T} — Draw a card."}), "mana cost is not tap-only")
        self.assertFalse(t({"label": "Pass (do nothing)"}))

    def test_first_window_goes_to_the_model_then_repeats_are_passed(self):
        r = runner()
        first = react(RING)
        self.assertIsNone(r._fastpath(first), "the first offer is always the model's")
        r._note_tap_pass(first, PASS)                       # the model passed it
        again = react(RING, stack=("Selvala, Heart of the Wilds",), opp_life=(36, 4, 40))
        ans, src = r._fastpath(again)
        self.assertEqual((ans, src), (PASS, "repeat"))
        self.assertIn("repeat", r._fast_why)

    def test_life_drop_threat_mana_or_new_option_reopen_the_window(self):
        r = runner()
        r._note_tap_pass(react(RING), PASS)
        self.assertIsNone(r._fastpath(react(RING, life=19)), "own life dropped: the desperation draw stays live")
        self.assertIsNone(r._fastpath(react(RING, untapped=1)), "mana up: not resourceless")
        self.assertIsNone(r._fastpath(react(RING, targets=[["seat 2"]])), "an item aimed at us")
        self.assertIsNone(r._fastpath(react(RING, BOLT)), "a new option")
        self.assertIsNone(r._fastpath(react(RING, stack=(), kinds=())), "empty stack is a tactical window")
        self.assertIsNone(r._fastpath(react(RING, turn=24)), "next turn")

    def test_a_punt_never_arms_the_repeat_and_acting_clears_it(self):
        r = runner()
        # punts go through _record only; _note_tap_pass is called for MODEL passes alone
        r._note_tap_pass(react(RING), {"chosenId": 1})
        self.assertIsNone(r._tap_pass)
        r._note_tap_pass(react(RING), PASS)
        self.assertIsNotNone(r._tap_pass)


class LifeBucketMemoTests(unittest.TestCase):
    def test_opponent_life_above_ten_is_bucketed_own_life_exact(self):
        r = runner()
        a = r._react_signature(react(RING, opp_life=(34, 4, 40)))
        b = r._react_signature(react(RING, opp_life=(32, 4, 40)))
        self.assertEqual(a, b, "Ben's Staff life swing does not break the memo")
        c = r._react_signature(react(RING, opp_life=(34, 3, 40)))
        self.assertNotEqual(a, c, "an opponent at 4 -> 3 is exact (kill range)")
        d = r._react_signature(react(RING, opp_life=(34, 4, 40), life=20))
        self.assertNotEqual(a, d, "own life is exact")
        e = r._react_signature(react(RING, opp_life=(29, 4, 40)))
        self.assertNotEqual(a, e, "crossing a bucket boundary re-opens the window")


if __name__ == "__main__":
    unittest.main()

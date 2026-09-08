"""Affordability fastpath (2026-09-07): a REACT window where every non-pass
option costs more mana than the engine says is available now is passed
without a model call. Anything that could be a real play — a free or X or
Phyrexian cost, an unknown cost, a free-cast marker, a missing mana figure —
falls through to the model (the 2026-08-13 "325th window" lesson).
Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd.runner import SeatRunner  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "engine"


def runner():
    tmp = Path(tempfile.mkdtemp(prefix="afford-"))
    return SeatRunner(0, "purphoros-god-of-the-forge", str(tmp), log_dir=str(tmp / "logs"))


def react(avail, *options):
    r = json.loads((FIX / "react.json").read_text())
    r["state"]["manaAvailableNow"] = avail
    r["state"].pop("manaReach", None)   # the fixture carries the engine's reach; tests set the sum explicitly
    r["state"]["stack"] = ["Craterhoof Behemoth"]; r["state"]["stackOwners"] = [2]; r["state"]["stackKinds"] = ["spell"]
    r["options"] = [{"id": 0, "label": "Pass (do nothing)", "cost": None, "type": "PASS"}] + [
        {"id": i + 1, "label": lab, "cost": cost, "type": "Instant"} for i, (lab, cost) in enumerate(options)]
    return r


class AffordabilityFastpathTests(unittest.TestCase):
    def test_mana_value_parses_costs(self):
        mv = SeatRunner._mana_value
        self.assertEqual(mv("{2}{U}{U}"), 4)
        self.assertEqual(mv("{B}"), 1)
        self.assertEqual(mv("{0}"), 0)
        self.assertEqual(mv("{T}"), 0)
        self.assertEqual(mv("{1}, {T}, Sacrifice a creature"), 1)
        self.assertEqual(mv("{W/U}{2/R}"), 3, "hybrid takes the cheapest half")
        self.assertIsNone(mv("{X}{R}"), "X is unknowable")
        self.assertIsNone(mv("{G/P}"), "Phyrexian can be paid with life")
        self.assertIsNone(mv(None)); self.assertIsNone(mv("free"))

    def test_all_unaffordable_passes_without_a_model_call(self):
        r = runner()
        req = react(1, ("Heroic Intervention  {1}{G}", "{1}{G}"), ("Finale of Devastation  {X}{G}{G}", "{2}{G}{G}"))
        ans, src = r._fastpath(req)
        self.assertEqual((ans, src), ({"chosenId": 0}, "affordability"))
        self.assertIn("cheapest option costs 2, 1 mana available now", r._fast_why)

    def test_an_affordable_option_goes_to_the_model(self):
        r = runner()
        self.assertIsNone(r._fastpath(react(2, ("Heroic Intervention  {1}{G}", "{1}{G}"))))

    def test_free_x_phyrexian_unknown_and_marked_options_go_to_the_model(self):
        r = runner()
        self.assertIsNone(r._fastpath(react(0, ("Pact of Negation  {0}", "{0}"))), "free spell")
        self.assertIsNone(r._fastpath(react(0, ("Finale  {X}{G}{G}", "{X}{G}{G}"))), "X")
        self.assertIsNone(r._fastpath(react(0, ("Dismember  {1}{B/P}{B/P}", "{1}{B/P}{B/P}"))), "Phyrexian")
        self.assertIsNone(r._fastpath(react(0, ("Mystery", None))), "unknown cost")
        self.assertIsNone(r._fastpath(react(0, ("Force of Will  {3}{U}{U} — you may cast without paying", "{3}{U}{U}"))), "free-cast marker")
        self.assertIsNone(r._fastpath(react(0, ("Ancient Stirrings (convoke)  {3}{G}", "{3}{G}"))), "convoke marker")

    def test_missing_mana_figure_goes_to_the_model(self):
        r = runner()
        req = react(9, ("Counterspell  {U}{U}", "{U}{U}"))
        del req["state"]["manaAvailableNow"]
        self.assertIsNone(r._fastpath(req))

    def test_utility_tap_ability_is_affordable_so_the_model_decides(self):
        r = runner()
        req = react(0, ("Maze of Ith  {T}: untap target attacking creature", "{T}"))
        req["options"][1]["type"] = "Ability"
        self.assertIsNone(r._fastpath(req))

    def test_plain_mana_abilities_alone_are_a_dead_window(self):
        r = runner()
        req = react(3, ("Chrome Mox  {T} — Chrome Mox (221) - {T}: Add one mana of any of the exiled card's colors.", "{T}"),
                    ("Giada, Font of Hope  {T} — {T}: Add {W}.", "{T}"))
        ans, src = r._fastpath(req)
        self.assertEqual((ans, src), ({"chosenId": 0}, "affordability"))
        self.assertIn("only mana abilities", r._fast_why)
        # a mana ability with a sacrifice cost is a real play (Lion's Eye Diamond class)
        led = react(3, ("Lion's Eye Diamond  Sacrifice, discard your hand — Add three mana of any one color.", "Sac<1/CARDNAME>"))
        self.assertIsNone(r._fastpath(led))

    def test_counterspells_with_an_empty_stack_are_a_dead_window(self):
        r = runner()
        req = react(4, ("Pact of Negation  {0} — Counter target spell. At the beginning of your next upkeep, pay {3}{U}{U}.", "{0}"))
        req["state"]["stack"] = []; req["state"]["stackOwners"] = []; req["state"]["stackKinds"] = []
        ans, src = r._fastpath(req)
        self.assertEqual((ans, src), ({"chosenId": 0}, "affordability"))
        self.assertIn("stack is empty", r._fast_why)
        # with a spell on the stack the same option goes to the model
        self.assertIsNone(r._fastpath(react(4, ("Pact of Negation  {0} — Counter target spell.", "{0}"))))

    def test_only_a_pass_option_is_left_alone(self):
        r = runner()
        self.assertIsNone(r._unaffordable_react(react(0)))


if __name__ == "__main__":
    unittest.main()

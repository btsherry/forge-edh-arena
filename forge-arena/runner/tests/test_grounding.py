"""2026-08-10 grounding fixes: X-cancel sentinel, gated feature prompt text,
mana ground truth, and the deck-agnostic COMBO STATUS matcher. Run:
python3 -m unittest discover -s tests"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd import rules  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def num_req(lo, hi, cancelable=False):
    r = json.loads((FIX / "choose_number.json").read_text())
    r["state"]["min"], r["state"]["max"] = lo, hi
    if cancelable:
        r["state"]["cancelable"] = True
    return r


class CancelSentinelTests(unittest.TestCase):
    def test_cancel_accepted_when_cancelable(self):
        self.assertEqual(rules.validate(num_req(0, 0, cancelable=True),
                                        {"chosen": -1}), {"chosen": -1})

    def test_cancel_rejected_when_not_cancelable(self):
        self.assertIsNone(rules.validate(num_req(0, 5), {"chosen": -1}))

    def test_bounds_still_enforced(self):
        self.assertIsNone(rules.validate(num_req(0, 5, cancelable=True),
                                         {"chosen": 6}))
        self.assertEqual(rules.validate(num_req(0, 5, cancelable=True),
                                        {"chosen": 5}), {"chosen": 5})

    def test_safe_default_never_cancels(self):
        # punts must stay engine-legal, never -1. Wave-3 (F3): real mana-X
        # requests carry puntHigh (max is affordability-capped) and punt max;
        # un-flagged number requests (bids) punt LOW — still never -1.
        x_req = num_req(0, 4, cancelable=True)
        x_req["state"]["puntHigh"] = True
        self.assertEqual(rules.safe_default(x_req), {"chosen": 4})
        self.assertEqual(rules.safe_default(num_req(0, 4, cancelable=True)),
                         {"chosen": 0})


class PromptGatingTests(unittest.TestCase):
    def _cast_req(self):
        return json.loads((FIX / "cast_spell.json").read_text())

    def _react_req(self):
        return json.loads((FIX / "react.json").read_text())

    def test_plan_text_gated_on_speculative(self):
        req = self._cast_req()
        req["phase"] = "MAIN1"
        off = rules.build_user_prompt(req)
        on = rules.build_user_prompt(req, speculative=True)
        self.assertNotIn('"plan" key', off)
        self.assertIn('"plan" key', on)

    def test_hold_hint_gated_on_react_hold(self):
        req = self._react_req()
        off = rules.build_user_prompt(req)
        on = rules.build_user_prompt(req, react_hold=True)
        self.assertNotIn("hold_turn", off)
        self.assertIn("hold_turn", on)

    def test_mana_ground_truth_on_cast_windows(self):
        self.assertIn("MANA GROUND TRUTH",
                      rules.build_user_prompt(self._cast_req()))
        self.assertNotIn("MANA GROUND TRUTH",
                         rules.build_user_prompt(self._react_req()))


COMBOS = [
    {"id": "a", "cards": [{"name": "Umbral Mantle"},
                          {"name": "Selvala, Heart of the Wilds"}],
     "mana_needed": "{2}{G} at most"},
    {"id": "b", "cards": [{"name": "Staff of Domination"},
                          {"name": "Selvala, Heart of the Wilds"}]},
    {"id": "c", "cards": [{"name": "Card Nowhere"}, {"name": "Other Gone"}]},
]


def combo_req(bf=(), hand=(), command=(), grave=()):
    return {"decisionType": "CAST_SPELL",
            "state": {"battlefield": [{"name": n} for n in bf],
                      "hand": [{"name": n} for n in hand],
                      "command": list(command),
                      "graveyard": list(grave)}}


class ComboStatusTests(unittest.TestCase):
    def test_executable_now_flagged(self):
        line = rules.combo_status_line(COMBOS, combo_req(
            bf=("Umbral Mantle", "Selvala, Heart of the Wilds")))
        self.assertIn("EXECUTE THIS TURN", line)
        self.assertIn("needs {2}{G} at most", line)

    def test_one_step_away_in_hand(self):
        line = rules.combo_status_line(COMBOS, combo_req(
            bf=("Selvala, Heart of the Wilds",), hand=("Umbral Mantle",)))
        self.assertIn("Umbral Mantle IN HAND", line)
        self.assertIn("1 step(s) from live", line)

    def test_command_zone_counts_as_castable(self):
        line = rules.combo_status_line(COMBOS, combo_req(
            bf=("Staff of Domination",),
            command=("Selvala, Heart of the Wilds",)))
        self.assertIn("IN COMMAND ZONE", line)

    def test_quiet_when_nothing_in_reach(self):
        self.assertIsNone(rules.combo_status_line(
            [COMBOS[2]], combo_req(bf=("Forest",))))

    def test_quiet_off_main_windows_and_empty(self):
        req = combo_req(bf=("Umbral Mantle",))
        req["decisionType"] = "REACT"
        self.assertIsNone(rules.combo_status_line(COMBOS, req))
        self.assertIsNone(rules.combo_status_line([], combo_req()))


if __name__ == "__main__":
    unittest.main()

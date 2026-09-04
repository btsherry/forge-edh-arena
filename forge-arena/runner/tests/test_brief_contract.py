"""Interactive plan item 14 (2026-09-03): the seat brief's failure model must
be the code's. It told the model that a bad answer became a pass; the runner
actually substitutes rules.safe_default, which keeps hands, takes first
options, and spends the whole affordable X. This pins the brief's table to
the function: change one, and this test makes you change the other.
Run: python3 -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seatd import rules  # noqa: E402

BRIEF = (Path(__file__).resolve().parents[1] / "seatd" / "seat-brief.md").read_text()


def req(dtype, options, state=None):
    return {"decisionType": dtype, "prompt": "x", "state": state or {},
            "options": [{"id": i, "label": f"o{i}"} for i in options]}


class BriefMatchesSafeDefault(unittest.TestCase):
    def test_brief_says_defaults_are_not_a_pass(self):
        self.assertNotIn("a pass is played for you", BRIEF)
        self.assertIn("SAFE\n   DEFAULT", BRIEF.replace("SAFE DEFAULT", "SAFE\n   DEFAULT"))

    def test_table_rows_match_the_function(self):
        # (brief phrase that must be present, request, expected default)
        cases = [
            ("| CAST_SPELL, REACT | pass |", req("REACT", [0, 1]), {"chosenId": 0}),
            ("| MULLIGAN | keep the hand |", req("MULLIGAN", [0, 1]), {"keep": True}),
            ("no attackers / no blocks", req("DECLARE_ATTACKERS", [5]), {"attackers": []}),
            ("no attackers / no blocks", req("DECLARE_BLOCKERS", [5]), {"blocks": []}),
            ("the first `min` modes", req("CHOOSE_MODE", [0, 1, 2], {"min": 2, "max": 2}),
             {"chosen": [0, 1]}),
            ("the first `min` legal ids", req("CHOOSE_CARDS", [11, 12, 13], {"min": 1, "max": 2}),
             {"chosen": [11]}),
            ("nothing when min is 0", req("CHOOSE_ENTITIES", [11, 12], {"min": 0, "max": 2}),
             {"chosen": []}),
            ('"none" when offered', req("CHOOSE_ENTITY", [0, 11, 12], {"min": 0, "max": 1}),
             {"chosenId": 0}),
            ("else the FIRST legal option", req("CHOOSE_CARD", [11, 12], {"min": 1, "max": 1}),
             {"chosenId": 11}),
            ("the MAXIMUM when the request is an X cost",
             req("CHOOSE_NUMBER", [], {"min": 0, "max": 7, "puntHigh": True}), {"chosen": 7}),
            ("else the minimum", req("CHOOSE_NUMBER", [], {"min": 2, "max": 7}), {"chosen": 2}),
            ("| PAY_UNLESS | decline (never pays) |", req("PAY_UNLESS", [0, 1]), {"chosenId": 0}),
            ("yes ONLY when the effect is yours and free",
             req("CONFIRM", [0, 1], {"confirmMode": "OptionalChoose", "hasCost": False, "isMine": True}),
             {"chosenId": 1}),
            ("otherwise no",
             req("CONFIRM", [0, 1], {"confirmMode": "OptionalChoose", "hasCost": True, "isMine": True}),
             {"chosenId": 0}),
        ]
        for phrase, r, expected in cases:
            with self.subTest(dtype=r["decisionType"], phrase=phrase):
                self.assertIn(phrase, BRIEF, "the brief must state this default")
                self.assertEqual(rules.safe_default(r), expected)


if __name__ == "__main__":
    unittest.main()

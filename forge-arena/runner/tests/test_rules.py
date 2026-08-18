"""Contract tests (H2 checkpoint): for every fixture — the known-good response
is accepted, every documented trap is rejected, and safe_default(req) itself
validates. Run: python3 -m unittest discover -s tests"""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd import rules  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


class SafeDefaultAlwaysLegal(unittest.TestCase):
    def test_every_fixture(self):
        for f in sorted(FIX.glob("*.json")):
            req = json.loads(f.read_text())
            with self.subTest(fixture=f.stem):
                d = rules.safe_default(req)
                self.assertIsNotNone(rules.validate(req, d),
                                     f"safe_default not legal for {f.stem}: {d}")


class TableDrivenContract(unittest.TestCase):
    # (fixture, good responses, trap responses)
    CASES = [
        ("cast_spell",
         [{"chosenId": 0}, {"chosenId": 1}, {"chosenId": 3},
          {"chosenId": 2, "reasoning": "x", "turn_plan": "y"}],  # extras stripped
         [{"chosenId": "1"}, {"chosenId": 1.0}, {"chosenId": 99},
          {"chosenId": True}, {"keep": True}, {}, None, [], "pass"]),
        ("react",
         [{"chosenId": 0}, {"chosenId": 1}],
         [{"chosenId": 2}, {"chosen": [1]}]),
        ("mulligan",
         [{"keep": True}, {"keep": False}],
         [{"chosenId": 1}, {"keep": "yes"}, {"keep": 1}, {}]),
        ("declare_attackers",
         [{"attackers": []},
          {"attackers": [{"attacker": 302, "defender": 0}]},
          {"attackers": [{"attacker": 302, "defender": 3}]}],
         [{"attackers": [{"attacker": 302}]},                     # defender omitted
          {"attackers": [{"attacker": 999, "defender": 0}]},      # unknown attacker
          {"attackers": [{"attacker": 302, "defender": 2}]},      # unknown defender
          {"attackers": [{"attacker": 0, "defender": 0}]},        # pass id as attacker
          {"blocks": []}]),
        ("declare_blockers",
         [{"blocks": []},
          {"blocks": [{"blocker": 302, "attacker": 78}]},
          {"blocks": [{"blocker": 302, "attacker": 161}]}],
         [{"blocks": [{"blocker": 302, "attacker": 999}]},        # unknown attacker
          {"blocks": [{"blocker": 999, "attacker": 78}]},         # unknown blocker
          {"attackers": []}]),
        ("choose_entity",
         [{"chosenId": 0}, {"chosenId": 78}, {"chosenId": 302}],
         [{"chosenId": 999}, {"chosen": [78]}, {"chosenId": "78"}]),
        ("choose_entities",
         [{"chosen": []}, {"chosen": [78]}, {"chosen": [78, 302]}],
         [{"chosen": [78, 78]},                                   # dupes
          {"chosen": [78, 302, 161]},                             # count > max (2)
          {"chosen": [999]}, {"chosen": "78"}]),
        ("choose_mode",
         [{"chosen": [0]}, {"chosen": [1]}, {"chosen": [2]}],     # 0 is a REAL mode
         [{"chosen": []},                                         # below min (1)
          {"chosen": [0, 1]},                                     # above max (1)
          {"chosen": [3]},                                        # unknown index
          {"chosenId": 1}]),
        ("choose_card",
         [{"chosenId": 0}, {"chosenId": 258}, {"chosenId": 259}],
         [{"chosenId": 260}, {"chosenId": None}]),
        ("choose_number",
         [{"chosen": 0}, {"chosen": 2}, {"chosen": 4}],
         [{"chosen": 5}, {"chosen": -1}, {"chosen": "4"}, {"chosen": 4.0},
          {"chosen": True}, {"chosenId": 4}, {}]),
    ]

    def test_good_accepted_and_cleaned(self):
        for fixture, goods, _ in self.CASES:
            req = load(fixture)
            for g in goods:
                with self.subTest(fixture=fixture, resp=g):
                    clean = rules.validate(req, g)
                    self.assertIsNotNone(clean)
                    # wire payload holds contract keys only
                    self.assertNotIn("reasoning", clean)
                    self.assertNotIn("turn_plan", clean)

    def test_traps_rejected(self):
        for fixture, _, traps in self.CASES:
            req = load(fixture)
            for t in traps:
                with self.subTest(fixture=fixture, resp=t):
                    self.assertIsNone(rules.validate(req, t))

    def test_mandatory_choose_without_none_option(self):
        req = load("choose_entity")
        req = copy.deepcopy(req)
        req["options"] = [o for o in req["options"] if o["id"] != 0]
        self.assertIsNone(rules.validate(req, {"chosenId": 0}))   # 0 not offered
        self.assertIsNotNone(rules.validate(req, {"chosenId": 78}))
        d = rules.safe_default(req)                               # first legal id
        self.assertEqual(d, {"chosenId": 78})
        self.assertIsNotNone(rules.validate(req, d))

    def test_combat_tolerates_leaked_why_noise(self):
        # Observed live: model leaked a stray "why" string into the blocks array
        # alongside a valid block. Salvage the valid pair, drop the noise.
        req = load("declare_blockers")
        clean = rules.validate(req, {"blocks": [{"blocker": 302, "attacker": 78}, "why"],
                                     "why": "kills it for free"})
        self.assertEqual(clean, {"blocks": [{"blocker": 302, "attacker": 78}]})
        # attackers array likewise
        reqa = load("declare_attackers")
        cleana = rules.validate(reqa, {"attackers": ["why", {"attacker": 302, "defender": 0}]})
        self.assertEqual(cleana, {"attackers": [{"attacker": 302, "defender": 0}]})
        # pure-noise array degrades to the safe empty declaration, still legal
        self.assertEqual(rules.validate(req, {"blocks": ["why"]}), {"blocks": []})
        # DICT-shaped noise ({"why":...}) alongside a valid block — salvage the block
        self.assertEqual(
            rules.validate(req, {"blocks": [{"blocker": 302, "attacker": 78},
                                            {"why": "x"}], "why": "placeholder"}),
            {"blocks": [{"blocker": 302, "attacker": 78}]})
        reqa = load("declare_attackers")
        self.assertEqual(
            rules.validate(reqa, {"attackers": [{"attacker": 302, "defender": 0},
                                                {"why": "noise"}]}),
            {"attackers": [{"attacker": 302, "defender": 0}]})
        # a real-but-illegal id still hard-rejects (not noise)
        self.assertIsNone(rules.validate(req, {"blocks": [{"blocker": 999, "attacker": 78}]}))

    def test_combat_salvages_duplicate_entries(self):
        # Observed live: model listed the same attacker twice (+ "why":"Placeholder").
        # A creature attacks once; keep the first pairing, drop the repeat.
        reqa = load("declare_attackers")
        self.assertEqual(
            rules.validate(reqa, {"attackers": [{"attacker": 302, "defender": 3},
                                                {"attacker": 302, "defender": 3}]}),
            {"attackers": [{"attacker": 302, "defender": 3}]})
        # blockers likewise: first block for a creature wins, dupe dropped
        reqb = load("declare_blockers")
        self.assertEqual(
            rules.validate(reqb, {"blocks": [{"blocker": 302, "attacker": 78},
                                             {"blocker": 302, "attacker": 161}]}),
            {"blocks": [{"blocker": 302, "attacker": 78}]})
        # a still-unknown id in the array remains a hard reject (not mere noise)
        self.assertIsNone(rules.validate(reqa, {"attackers": [{"attacker": 999, "defender": 3}]}))

    def test_choose_mode_allow_repeat(self):
        req = copy.deepcopy(load("choose_mode"))
        req["state"]["min"], req["state"]["max"] = 2, 2
        req["state"]["allowRepeat"] = True
        self.assertIsNotNone(rules.validate(req, {"chosen": [1, 1]}))
        req["state"]["allowRepeat"] = False
        self.assertIsNone(rules.validate(req, {"chosen": [1, 1]}))
        self.assertIsNotNone(rules.validate(req, {"chosen": [0, 2]}))

    def test_unknown_decision_type_never_guesses(self):
        req = copy.deepcopy(load("cast_spell"))
        req["decisionType"] = "SOMETHING_NEW"
        self.assertIsNone(rules.validate(req, {"chosenId": 0}))
        # but safe_default still emits the universal pass shape
        self.assertEqual(rules.safe_default(req), {"chosenId": 0})


class PromptBuilder(unittest.TestCase):
    def test_prompt_carries_contract_state_and_plan(self):
        req = load("cast_spell")
        obs = {"seats": [{"seat": 0, "life": 35}, {"seat": 2, "life": 38}],
               "stack": []}
        p = rules.build_user_prompt(req, plan="develop then hold up Gift",
                                    observer=obs)
        self.assertIn('"chosenId"', p)
        self.assertIn("REQUEST (ground truth", p)
        self.assertIn("advisory", p)
        self.assertIn("seat 0: 35 life", p)
        self.assertIn(json.dumps(req, separators=(",", ":"))[:60], p)


class ConfirmDefaultShapeTests(unittest.TestCase):
    """CONFIRM punts are shape-aware (game 7): own free play/copy -> yes;
    trigger yes-costs and sacrifice/pay-life confirms -> no."""
    def _req(self, prompt, mode, **st):
        state = {"confirmMode": mode, "min": 1, "max": 1}
        state.update(st)
        return {"decisionType": "CONFIRM", "prompt": prompt, "state": state,
                "options": [{"id": 0, "label": "No"}, {"id": 1, "label": "Yes"}]}

    def test_free_copy_play_defaults_yes(self):
        r = self._req("Do you want to play Dramatic Reversal (copy) without paying?", "untyped")
        self.assertEqual(rules.safe_default(r), {"chosenId": 1})

    def test_trigger_with_cost_defaults_no(self):
        r = self._req("OPTIONAL TRIGGER: Rings ... Saying YES pays {2}", "TRIGGER", yesCost="{2}")
        self.assertEqual(rules.safe_default(r), {"chosenId": 0})

    def test_free_trigger_defaults_yes(self):
        r = self._req("OPTIONAL TRIGGER: you may draw a card", "TRIGGER", yesCost="none")
        self.assertEqual(rules.safe_default(r), {"chosenId": 1})

    def test_sacrifice_confirm_defaults_no(self):
        r = self._req("Do you want to sacrifice a creature to play X?", "untyped")
        self.assertEqual(rules.safe_default(r), {"chosenId": 0})

    def test_defaults_stay_legal(self):
        for r in (self._req("play it?", "untyped"), self._req("t", "TRIGGER", yesCost="{1}")):
            self.assertIsNotNone(rules.validate(r, rules.safe_default(r)))


if __name__ == "__main__":
    unittest.main()

"""Contract tests for seatd/rules.py: for every fixture the known-good response is accepted, every documented
trap is rejected and safe_default(req) itself validates; the shape-aware punt table (CONFIRM by engine facts,
TARGETS with the punt marker, TRIGGER_ORDER / COLOR hand-backs, a single legal defender filled in); the
X-cancel sentinel; the gated prompt text and the deck-agnostic COMBO STATUS line (2026-08-10); and the seat
brief's failure table pinned to the function (plan item 14). Run: python3 -m unittest discover -s tests"""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seatd import rules  # noqa: E402


FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


def num_req(lo, hi, cancelable=False):
    r = json.loads((FIX / "choose_number.json").read_text())
    r["state"]["min"], r["state"]["max"] = lo, hi
    if cancelable:
        r["state"]["cancelable"] = True
    return r


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


BRIEF = (Path(__file__).resolve().parents[1] / "seatd" / "seat-brief.md").read_text()


def brief_req(dtype, options, state=None):
    return {"decisionType": dtype, "prompt": "x", "state": state or {},
            "options": [{"id": i, "label": f"o{i}"} for i in options]}


class SafeDefaultAlwaysLegal(unittest.TestCase):
    """For every fixture — the hand-written ones and the ENGINE-EMITTED ones `ProtocolContractTest`
    (Java) writes to fixtures/engine/ — the runner knows the decision type and the punt answer it would
    send is a legal answer for what the engine actually asked."""

    def test_every_fixture(self):
        files = sorted(FIX.glob("*.json")) + sorted((FIX / "engine").glob("*.json"))
        self.assertTrue(any(f.parent.name == "engine" for f in files), "no engine fixtures — run the Java suite")
        for f in files:
            req = json.loads(f.read_text())
            with self.subTest(fixture=f"{f.parent.name}/{f.stem}"):
                self.assertIn(req["decisionType"], rules.ANSWER_CONTRACT, "a decision type the runner does not know")
                d = rules.safe_default(req)
                self.assertIsNotNone(rules.validate(req, d), f"safe_default not legal for {f.stem}: {d}")


class EngineFixtures(unittest.TestCase):
    def setUp(self):
        self.files = sorted((FIX / "engine").glob("*.json")) if (FIX / "engine").is_dir() else []
        if not self.files:
            self.skipTest("no engine fixtures — run the Java suite (ProtocolContractTest writes them)")

    def test_engine_requests_carry_identity_and_budget(self):
        for f in self.files:
            req = json.loads(f.read_text())
            with self.subTest(fixture=f.stem):
                self.assertRegex(req["gameId"], r"^\d+-\d+$")
                self.assertGreater(req["timeoutSec"], 0)
                self.assertIn("manaSources", req["state"])
                self.assertIn("manaAvailableNow", req["state"])


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
         [{"attackers": [{"attacker": 302}]},                     # defender omitted with SEVERAL legal
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

    def test_free_own_effect_defaults_yes(self):
        # engine facts (item 10): free AND mine -> yes, whatever the words say
        r = self._req("Return it to your hand?", "untyped", hasCost=False, isMine=True)
        self.assertEqual(rules.safe_default(r), {"chosenId": 1})

    def test_player_in_prompt_no_longer_means_yes(self):
        # "play" ⊂ "player" used to default-ACCEPT an opponent's effect
        r = self._req("Each player may draw a card?", "OptionalChoose",
                      hasCost=False, isMine=False)
        self.assertEqual(rules.safe_default(r), {"chosenId": 0})

    def test_own_but_costed_defaults_no(self):
        # a punt never spends new mana, however much is in the pool
        r = self._req("Pay {2} to copy it?", "OptionalChoose", hasCost=True, isMine=True)
        self.assertEqual(rules.safe_default(r), {"chosenId": 0})

    def test_legacy_engine_without_facts_defaults_no(self):
        # no hasCost/isMine (pre-item-10 engine): the word heuristic is GONE
        r = self._req("Do you want to play Dramatic Reversal (copy) without paying?", "untyped")
        self.assertEqual(rules.safe_default(r), {"chosenId": 0})

    def test_play_from_effect_free_still_yes(self):
        r = self._req("PLAY FROM EFFECT: cast Dramatic Reversal WITHOUT paying", "PLAY_FROM_EFFECT",
                      free=True)
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


class TargetWindowPunt(unittest.TestCase):
    def _req(self, purpose, lo):
        return {"decisionType": "CHOOSE_ENTITIES", "seq": 1, "turn": 5,
                "state": {"min": lo, "max": 2, **({"purpose": purpose} if purpose else {})},
                "options": [{"id": 1, "label": "Sol Ring [Urza-S0]"}, {"id": 2, "label": "Grim Monolith [Urza-S0]"}, {"id": 3, "label": "Mox Amber [Urza-S0]"}]}

    def test_a_punt_on_a_target_window_is_marked_and_still_valid(self):
        for lo in (0, 1, 2):
            req = self._req("TARGETS", lo)
            out = rules.safe_default(req)
            self.assertEqual(out, {"chosen": [1, 2][:lo], "punt": True})
            self.assertIsNotNone(rules.validate(req, out), "the invariant: a safe default validates")

    def test_other_multi_pick_windows_punt_as_before(self):
        self.assertEqual(rules.safe_default(self._req(None, 1)), {"chosen": [1]})
        self.assertEqual(rules.safe_default(self._req("SACRIFICE", 0)), {"chosen": []})

    def test_the_seat_may_choose_no_targets_when_the_minimum_is_zero(self):
        req = self._req("TARGETS", 0)
        self.assertEqual(rules.validate(req, {"chosen": []}), {"chosen": []})
        self.assertEqual(rules.validate(req, {"chosen": [3, 1]}), {"chosen": [3, 1]}, "the order is kept: the split follows it")
        self.assertIsNone(rules.validate(req, {"chosen": [1, 1]}))
        self.assertIsNone(rules.validate(req, {"chosen": [1, 2, 3]}), "over state.max")

    def test_a_declinable_window_accepts_an_empty_pick_or_the_real_range(self):
        req = self._req("TARGETS", 2)
        req["state"]["declinable"] = True
        self.assertEqual(rules.validate(req, {"chosen": []}), {"chosen": []}, "[] declines the seat's own optional trigger")
        self.assertIsNone(rules.validate(req, {"chosen": [1]}), "one pick is under the real minimum of two")
        self.assertEqual(rules.validate(req, {"chosen": [1, 2]}), {"chosen": [1, 2]})


class SingleLegalDefender(unittest.TestCase):
    """BL-23: a missing defender is filled in when exactly one is legal (the
    engine's chooseDefender rule); with several legal it is still rejected."""

    def _req(self, defenders):
        return {"decisionType": "DECLARE_ATTACKERS", "prompt": "x",
                "state": {"defenders": [{"id": d, "label": f"seat {d}", "type": "PLAYER"}
                                        for d in defenders]},
                "options": [{"id": 0, "label": "no attack"}, {"id": 302, "label": "Bear"}]}

    def test_one_legal_defender_is_filled_in(self):
        from seatd import rules
        out = rules.validate(self._req([2]), {"attackers": [{"attacker": 302}]})
        self.assertEqual(out, {"attackers": [{"attacker": 302, "defender": 2}]})

    def test_several_legal_defenders_still_require_it(self):
        from seatd import rules
        self.assertIsNone(rules.validate(self._req([1, 2]), {"attackers": [{"attacker": 302}]}))
        # explicit stays explicit
        out = rules.validate(self._req([1, 2]), {"attackers": [{"attacker": 302, "defender": 1}]})
        self.assertEqual(out, {"attackers": [{"attacker": 302, "defender": 1}]})


class PurposeWindowPunts(unittest.TestCase):
    """BL-02/03 windows: a punt hands the pick back to the engine's stock
    logic via the documented empty list; a model may say the same."""

    def test_safe_default_and_validate(self):
        from seatd import rules
        order = {"decisionType": "CHOOSE_MODE", "prompt": "x",
                 "state": {"min": 2, "max": 2, "purpose": "TRIGGER_ORDER"},
                 "options": [{"id": 0, "label": "a"}, {"id": 1, "label": "b"}]}
        color = {"decisionType": "CHOOSE_MODE", "prompt": "x",
                 "state": {"min": 1, "max": 1, "purpose": "COLOR"},
                 "options": [{"id": 0, "label": "white"}, {"id": 1, "label": "green"}]}
        plain = {"decisionType": "CHOOSE_MODE", "prompt": "x", "state": {"min": 1, "max": 1},
                 "options": [{"id": 0, "label": "a"}, {"id": 1, "label": "b"}]}
        self.assertEqual(rules.safe_default(order), {"chosen": []})
        self.assertEqual(rules.safe_default(color), {"chosen": []})
        self.assertEqual(rules.safe_default(plain), {"chosen": [0]}, "ordinary modes keep the first-min rule")
        self.assertEqual(rules.validate(order, {"chosen": []}), {"chosen": []})
        self.assertEqual(rules.validate(color, {"chosen": []}), {"chosen": []})
        self.assertIsNone(rules.validate(plain, {"chosen": []}), "an empty list is not legal for a real mode choice")
        self.assertEqual(rules.validate(order, {"chosen": [1, 0]}), {"chosen": [1, 0]})
        self.assertIsNone(rules.validate(order, {"chosen": [1]}), "a partial order is not a permutation")


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


class BriefMatchesSafeDefault(unittest.TestCase):
    def test_brief_says_defaults_are_not_a_pass(self):
        self.assertNotIn("a pass is played for you", BRIEF)
        self.assertIn("SAFE\n   DEFAULT", BRIEF.replace("SAFE DEFAULT", "SAFE\n   DEFAULT"))

    def test_table_rows_match_the_function(self):
        # (brief phrase that must be present, request, expected default)
        cases = [
            ("| CAST_SPELL, REACT | pass |", brief_req("REACT", [0, 1]), {"chosenId": 0}),
            ("| MULLIGAN | keep the hand |", brief_req("MULLIGAN", [0, 1]), {"keep": True}),
            ("no attackers / no blocks", brief_req("DECLARE_ATTACKERS", [5]), {"attackers": []}),
            ("no attackers / no blocks", brief_req("DECLARE_BLOCKERS", [5]), {"blocks": []}),
            ("the first `min` modes", brief_req("CHOOSE_MODE", [0, 1, 2], {"min": 2, "max": 2}),
             {"chosen": [0, 1]}),
            ("the first `min` legal ids", brief_req("CHOOSE_CARDS", [11, 12, 13], {"min": 1, "max": 2}),
             {"chosen": [11]}),
            ("nothing when min is 0", brief_req("CHOOSE_ENTITIES", [11, 12], {"min": 0, "max": 2}),
             {"chosen": []}),
            ("the engine's stock aim — a punt never aims your spell",
             brief_req("CHOOSE_ENTITIES", [1, 2, 3], {"min": 1, "max": 2, "purpose": "TARGETS"}), {"chosen": [1], "punt": True}),
            ('"none" when offered', brief_req("CHOOSE_ENTITY", [0, 11, 12], {"min": 0, "max": 1}),
             {"chosenId": 0}),
            ("else the FIRST legal option", brief_req("CHOOSE_CARD", [11, 12], {"min": 1, "max": 1}),
             {"chosenId": 11}),
            ("the MAXIMUM when the request is an X cost",
             brief_req("CHOOSE_NUMBER", [], {"min": 0, "max": 7, "puntHigh": True}), {"chosen": 7}),
            ("else the minimum", brief_req("CHOOSE_NUMBER", [], {"min": 2, "max": 7}), {"chosen": 2}),
            ("| PAY_UNLESS | decline (never pays) |", brief_req("PAY_UNLESS", [0, 1]), {"chosenId": 0}),
            ("yes ONLY when the effect is yours and free",
             brief_req("CONFIRM", [0, 1], {"confirmMode": "OptionalChoose", "hasCost": False, "isMine": True}),
             {"chosenId": 1}),
            ("otherwise no",
             brief_req("CONFIRM", [0, 1], {"confirmMode": "OptionalChoose", "hasCost": True, "isMine": True}),
             {"chosenId": 0}),
        ]
        for phrase, r, expected in cases:
            with self.subTest(dtype=r["decisionType"], phrase=phrase):
                self.assertIn(phrase, BRIEF, "the brief must state this default")
                self.assertEqual(rules.safe_default(r), expected)

"""The seat's fastpaths — the answers the runner gives without a model call (seatd/runner.py `_fastpath`
and its memories), each earned by a game:
- affordability (2026-09-07): every non-pass option costs more than the mana available now → pass; a free,
  X, Phyrexian, unknown or marked cost, or a missing mana figure, falls through; BL-43: the engine's
  manaReach is the ceiling when published; BL-44: a mono-colour deck answers a mana-colour CHOOSE_MODE itself;
- the spell-reactor rule, the REPEAT tap-pass and the auto-yield (game 25), with the 2026-09-07 review's
  guards (Stifle-class counters stay live on an all-abilities stack; mana-only options stay live when our
  source is targeted; the repeat rule needs an all-abilities stack; a game reset clears the memories);
- the autopass allowlist's threat clause (wave 2): never eat a window whose stack targets OUR stuff;
- the reactive hold posture (SEAT_REACT_HOLD, experimental): a NEW stack object or an empty stack escalates;
- low effort for REACT windows holding only other players' unthreatening abilities; the yield mirror.
Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seatd.runner import SeatRunner  # noqa: E402
from test_react_memo import react_w2, runner_p  # noqa: E402  — the fixtures/react.json builder, seat 0 Purphoros

FIX = Path(__file__).parent / "fixtures"
FIX_ENGINE = FIX / "engine"


PASS = {"chosenId": 0}


RING = ("The One Ring  {T} — The One Ring (256) - seat puts a burden counter and draws a card for each.", "{T}")


FLARE = ("Flare of Duplication  {0}, Sacrifice a nontoken red creature — Copy target instant or sorcery spell.", "{0}")


BOLT = ("Lightning Bolt  {R} — Lightning Bolt deals 3 damage to any target.", "{R}")


def runner_g():
    tmp = Path(tempfile.mkdtemp(prefix="repeat-"))
    return SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))


def react_avail(avail, *options):
    r = json.loads((FIX_ENGINE / "react.json").read_text())
    r["state"]["manaAvailableNow"] = avail
    r["state"].pop("manaReach", None)   # the fixture carries the engine's reach; tests set the sum explicitly
    r["state"]["stack"] = ["Craterhoof Behemoth"]; r["state"]["stackOwners"] = [2]; r["state"]["stackKinds"] = ["spell"]
    r["options"] = [{"id": 0, "label": "Pass (do nothing)", "cost": None, "type": "PASS"}] + [
        {"id": i + 1, "label": lab, "cost": cost, "type": "Instant"} for i, (lab, cost) in enumerate(options)]
    return r


def react_rep(*options, stack=("Staff of Domination",), kinds=("ability",), owners=(0,), life=21, pool=0, untapped=0,
          turn=23, opp_life=(34, 4, 40), targets=None):
    r = json.loads((FIX_ENGINE / "react.json").read_text())
    r["turn"] = turn
    st = r["state"]
    st["seat"] = 2
    st["life"] = life
    st["manaPool"] = pool
    st["untappedManaSourceCount"] = untapped
    st["manaAvailableNow"] = pool + untapped
    st.pop("manaReach", None)   # the fixture carries the engine's reach; tests set the sum explicitly
    st["stack"] = list(stack)
    st["stackKinds"] = list(kinds) if kinds is not None else None
    st["stackOwners"] = list(owners)
    st["stackTargets"] = targets if targets is not None else [[] for _ in stack]
    st["opponents"] = [{"seat": i, "life": l} for i, l in zip((0, 1, 3), opp_life)]
    r["options"] = [{"id": 0, "label": "Pass (do nothing)", "cost": None, "type": "PASS"}] + [
        {"id": i + 1, "label": lab, "cost": cost, "type": "Ability"} for i, (lab, cost) in enumerate(options)]
    return r


def react_rev(*options, stack=("Staff of Domination",), kinds=("ability",), owners=(0,), targets=None,
          life=21, pool=0, untapped=0, avail=None, turn=23):
    r = json.loads((FIX_ENGINE / "react.json").read_text())
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


def react_eff(**kw):
    r = json.loads((FIX_ENGINE / "react.json").read_text())
    st = r["state"]
    st["seat"] = 2; st["stack"] = list(kw.get("stack", ("Staff of Domination",)))
    kinds = kw.get("kinds", ("ability",)); owners = kw.get("owners", (0,))
    st["stackKinds"] = list(kinds) if kinds is not None else None
    st["stackOwners"] = list(owners) if owners is not None else None
    st["stackTargets"] = kw.get("targets", [[] for _ in st["stack"]])
    return r


def react_req(seq, stack, turn=7):
    r = json.loads((FIX / "react.json").read_text())
    r["seq"] = seq
    r["turn"] = turn
    r["state"]["stack"] = list(stack)
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
        r = runner_p()
        req = react_avail(1, ("Heroic Intervention  {1}{G}", "{1}{G}"), ("Finale of Devastation  {X}{G}{G}", "{2}{G}{G}"))
        ans, src = r._fastpath(req)
        self.assertEqual((ans, src), ({"chosenId": 0}, "affordability"))
        self.assertIn("cheapest option costs 2, 1 mana available now", r._fast_why)

    def test_an_affordable_option_goes_to_the_model(self):
        r = runner_p()
        self.assertIsNone(r._fastpath(react_avail(2, ("Heroic Intervention  {1}{G}", "{1}{G}"))))

    def test_free_x_phyrexian_unknown_and_marked_options_go_to_the_model(self):
        r = runner_p()
        self.assertIsNone(r._fastpath(react_avail(0, ("Pact of Negation  {0}", "{0}"))), "free spell")
        self.assertIsNone(r._fastpath(react_avail(0, ("Finale  {X}{G}{G}", "{X}{G}{G}"))), "X")
        self.assertIsNone(r._fastpath(react_avail(0, ("Dismember  {1}{B/P}{B/P}", "{1}{B/P}{B/P}"))), "Phyrexian")
        self.assertIsNone(r._fastpath(react_avail(0, ("Mystery", None))), "unknown cost")
        self.assertIsNone(r._fastpath(react_avail(0, ("Force of Will  {3}{U}{U} — you may cast without paying", "{3}{U}{U}"))), "free-cast marker")
        self.assertIsNone(r._fastpath(react_avail(0, ("Ancient Stirrings (convoke)  {3}{G}", "{3}{G}"))), "convoke marker")

    def test_missing_mana_figure_goes_to_the_model(self):
        r = runner_p()
        req = react_avail(9, ("Counterspell  {U}{U}", "{U}{U}"))
        del req["state"]["manaAvailableNow"]
        self.assertIsNone(r._fastpath(req))

    def test_utility_tap_ability_is_affordable_so_the_model_decides(self):
        r = runner_p()
        req = react_avail(0, ("Maze of Ith  {T}: untap target attacking creature", "{T}"))
        req["options"][1]["type"] = "Ability"
        self.assertIsNone(r._fastpath(req))

    def test_plain_mana_abilities_alone_are_a_dead_window(self):
        r = runner_p()
        req = react_avail(3, ("Chrome Mox  {T} — Chrome Mox (221) - {T}: Add one mana of any of the exiled card's colors.", "{T}"),
                    ("Giada, Font of Hope  {T} — {T}: Add {W}.", "{T}"))
        ans, src = r._fastpath(req)
        self.assertEqual((ans, src), ({"chosenId": 0}, "affordability"))
        self.assertIn("only mana abilities", r._fast_why)
        # a mana ability with a sacrifice cost is a real play (Lion's Eye Diamond class)
        led = react_avail(3, ("Lion's Eye Diamond  Sacrifice, discard your hand — Add three mana of any one color.", "Sac<1/CARDNAME>"))
        self.assertIsNone(r._fastpath(led))

    def test_counterspells_with_an_empty_stack_are_a_dead_window(self):
        r = runner_p()
        req = react_avail(4, ("Pact of Negation  {0} — Counter target spell. At the beginning of your next upkeep, pay {3}{U}{U}.", "{0}"))
        req["state"]["stack"] = []; req["state"]["stackOwners"] = []; req["state"]["stackKinds"] = []
        ans, src = r._fastpath(req)
        self.assertEqual((ans, src), ({"chosenId": 0}, "affordability"))
        self.assertIn("stack is empty", r._fast_why)
        # with a spell on the stack the same option goes to the model
        self.assertIsNone(r._fastpath(react_avail(4, ("Pact of Negation  {0} — Counter target spell.", "{0}"))))

    def test_only_a_pass_option_is_left_alone(self):
        r = runner_p()
        self.assertIsNone(r._unaffordable_react(react_avail(0)))


class ManaReachCeiling(unittest.TestCase):
    """BL-43: the affordability fastpath must not pass a window the payer could
    fund through a costed source (Selvala) — the engine's manaReach is the
    ceiling when published."""
    def _react(self, avail, reach=None):
        r = json.loads((FIX_ENGINE / "react.json").read_text())
        st = r["state"]
        st["seat"] = 2; st["life"] = 18; st["manaPool"] = 0; st["untappedManaSourceCount"] = 3
        st["manaAvailableNow"] = avail
        st.pop("manaReach", None)   # the fixture carries the engine's reach; tests set the sum explicitly
        if reach is not None:
            st["manaReach"] = reach
        st["stack"] = []; st["stackKinds"] = []; st["stackOwners"] = []; st["stackTargets"] = []
        r["options"] = [{"id": 0, "label": "Pass (do nothing)", "cost": None, "type": "PASS"},
                        {"id": 1, "label": "Rhonas the Indomitable  {2}{G} — Another target creature gets +2/+0 and gains trample", "cost": "{2}{G}", "type": "Ability"}]
        return r

    def test_reach_keeps_the_window_open(self):
        r = runner_g()
        self.assertEqual(r._fastpath(self._react(2))[1], "affordability", "2 mana, {2}{G} pump: dead without a reach")
        self.assertIsNone(r._fastpath(self._react(2, reach=9)), "Selvala can be tapped by the payer: the model decides")
        self.assertEqual(r._fastpath(self._react(2, reach=2))[1], "affordability", "reach equal to the sum changes nothing")
        self.assertEqual(r._fastpath(self._react(2, reach=True))[1], "affordability", "a malformed reach is ignored")


class MonoColorPick(unittest.TestCase):
    """BL-44: a mono-colour deck answers a mana-colour CHOOSE_MODE itself."""
    def _color_req(self, opts=("white", "blue", "black", "red", "green")):
        r = json.loads((FIX_ENGINE / "react.json").read_text())
        r["decisionType"] = "CHOOSE_MODE"; r["seq"] = 900
        r["state"] = dict(r.get("state") or {}, purpose="COLOR", min=1, max=1)
        r["options"] = [{"id": i, "label": o} for i, o in enumerate(opts)]
        return r

    def test_giada_picks_white_and_only_for_colour_windows(self):
        tmp = Path(tempfile.mkdtemp(prefix="mono-"))
        r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))
        self.assertEqual(r._mono_color, "white")
        ans = r._fastpath(self._color_req())
        self.assertEqual(ans, ({"chosen": [0]}, "color"))
        self.assertIsNone(r._fastpath(self._color_req(opts=("blue", "black"))), "the colour is not offered: the model decides")
        other = self._color_req(); other["state"]["purpose"] = "TRIGGER_ORDER"
        self.assertIsNone(r._fastpath(other), "not a colour window")
        r._mono_color = None
        self.assertIsNone(r._fastpath(self._color_req()), "multi-colour or unknown identity: the model decides")

    def test_identity_from_commander_entries(self):
        tmp = Path(tempfile.mkdtemp(prefix="mono2-"))
        r = SeatRunner(2, "selvala-heart-of-the-wilds", str(tmp), log_dir=str(tmp / "logs"))
        self.assertEqual(r._mono_color, "green")
        r.deck = "no-such-deck"
        self.assertIsNone(r._deck_mono_color(), "missing dossier: None, never an error")


class SpellReactorRuleTests(unittest.TestCase):
    def test_copy_spell_with_only_abilities_on_the_stack_is_dead(self):
        r = runner_g()
        ans, src = r._fastpath(react_rep(FLARE, stack=("Staff of Domination", "Selvala, Heart of the Wilds"),
                                     kinds=("ability", "ability"), owners=(0, 0)))
        self.assertEqual((ans, src), (PASS, "affordability"))
        self.assertIn("no spell on the stack", r._fast_why)

    def test_a_spell_on_the_stack_goes_to_the_model(self):
        r = runner_g()
        self.assertIsNone(r._fastpath(react_rep(FLARE, stack=("Genesis Wave",), kinds=("spell",), owners=(0,))))

    def test_missing_stack_kinds_fails_open(self):
        r = runner_g()
        self.assertIsNone(r._fastpath(react_rep(FLARE, kinds=None)))
        self.assertIsNone(r._fastpath(react_rep(FLARE, stack=("A", "B"), kinds=("ability",), owners=(0, 0))), "length mismatch")

    def test_a_non_reactor_option_keeps_the_window(self):
        r = runner_g()
        self.assertIsNone(r._fastpath(react_rep(FLARE, BOLT, untapped=1)))


class RepeatTapPassTests(unittest.TestCase):
    def test_tap_only_helper(self):
        t = SeatRunner._tap_only_utility
        self.assertTrue(t({"label": RING[0]}))
        self.assertFalse(t({"label": "Maze of Ith  {T} — Untap target attacking creature; prevent all combat damage."}))
        self.assertFalse(t({"label": "Viscera Seer  Sacrifice a creature — Scry 1."}))
        self.assertFalse(t({"label": "Staff of Domination  {5}, {T} — Draw a card."}), "mana cost is not tap-only")
        self.assertFalse(t({"label": "Pass (do nothing)"}))

    def test_first_window_goes_to_the_model_then_repeats_are_passed(self):
        r = runner_g()
        first = react_rep(RING)
        self.assertIsNone(r._fastpath(first), "the first offer is always the model's")
        r._note_tap_pass(first, PASS)                       # the model passed it
        again = react_rep(RING, stack=("Selvala, Heart of the Wilds",), opp_life=(36, 4, 40))
        ans, src = r._fastpath(again)
        self.assertEqual((ans, src), (PASS, "repeat"))
        self.assertIn("repeat", r._fast_why)

    def test_life_drop_threat_mana_or_new_option_reopen_the_window(self):
        r = runner_g()
        r._note_tap_pass(react_rep(RING), PASS)
        self.assertIsNone(r._fastpath(react_rep(RING, life=19)), "own life dropped: the desperation draw stays live")
        self.assertIsNone(r._fastpath(react_rep(RING, untapped=1)), "mana up: not resourceless")
        self.assertIsNone(r._fastpath(react_rep(RING, targets=[["seat 2"]])), "an item aimed at us")
        self.assertIsNone(r._fastpath(react_rep(RING, BOLT)), "a new option")
        self.assertIsNone(r._fastpath(react_rep(RING, stack=(), kinds=())), "empty stack is a tactical window")
        self.assertIsNone(r._fastpath(react_rep(RING, turn=24)), "next turn")

    def test_a_punt_never_arms_the_repeat_and_acting_clears_it(self):
        r = runner_g()
        # punts go through _record only; _note_tap_pass is called for MODEL passes alone
        r._note_tap_pass(react_rep(RING), {"chosenId": 1})
        self.assertIsNone(r._tap_pass)
        r._note_tap_pass(react_rep(RING), PASS)
        self.assertIsNotNone(r._tap_pass)


class AutoYieldTests(unittest.TestCase):
    # BOLT (affordable with 3 untapped) is a live option: the affordability and
    # spell-reactor rules stay quiet, so what follows is the yield rule alone.
    STAFF = dict(stack=("Staff of Domination",), kinds=("ability",), owners=(0,))
    STAFF_ON_SELVALA = dict(stack=("Staff of Domination", "Selvala, Heart of the Wilds"), kinds=("ability", "ability"), owners=(0, 0))

    def test_first_offer_reaches_the_model_then_the_same_top_item_is_yielded(self):
        r = runner_g()
        first = react_rep(BOLT, untapped=3, **self.STAFF)
        self.assertIsNone(r._fastpath(first))
        r._note_yield(first, PASS)
        again = react_rep(BOLT, untapped=3, opp_life=(36, 4, 40), **self.STAFF_ON_SELVALA)
        ans, src = r._fastpath(again)
        self.assertEqual((ans, src), (PASS, "yield"))
        self.assertIn("Staff of Domination", r._fast_why)

    def test_a_spell_anywhere_on_the_stack_blocks_the_yield(self):
        r = runner_g()
        r._note_yield(react_rep(BOLT, untapped=3, **self.STAFF), PASS)
        gw = react_rep(BOLT, untapped=3, stack=("Staff of Domination", "Genesis Wave"), kinds=("ability", "spell"), owners=(0, 0))
        self.assertIsNone(r._fastpath(gw), "Genesis Wave under the Staff: the copy decision stays live")
        trig = react_rep(BOLT, untapped=3, stack=("Managorger Hydra", "Genesis Wave"), kinds=("trigger", "spell"), owners=(0, 0))
        self.assertIsNone(r._fastpath(trig))

    def test_life_drop_new_mana_threat_or_new_top_item_reopen(self):
        r = runner_g()
        r._note_yield(react_rep(BOLT, untapped=3, **self.STAFF), PASS)
        self.assertIsNone(r._fastpath(react_rep(BOLT, untapped=3, life=19, **self.STAFF)), "life dropped")
        self.assertIsNone(r._fastpath(react_rep(BOLT, untapped=5, **self.STAFF)), "more mana than at the yield")
        self.assertIsNone(r._fastpath(react_rep(BOLT, untapped=3, targets=[["seat 2"]], **self.STAFF)), "aimed at us")
        self.assertIsNone(r._fastpath(react_rep(BOLT, untapped=3, stack=("Selvala, Heart of the Wilds",), kinds=("ability",), owners=(0,))), "a different top item")
        self.assertIsNone(r._fastpath(react_rep(BOLT, untapped=3, turn=24, **self.STAFF)), "next turn is not remembered here")
        self.assertIsNone(r._fastpath(react_rep(BOLT, RING, untapped=3, **self.STAFF)), "a new option")

    def test_missing_kinds_never_yield_and_acting_clears(self):
        r = runner_g()
        r._note_yield(react_rep(BOLT, untapped=3, kinds=None), PASS)
        self.assertEqual(r._yielded, {})
        r._note_yield(react_rep(BOLT, untapped=3, **self.STAFF), PASS)
        self.assertTrue(r._yielded)
        r._note_yield(react_rep(BOLT, untapped=3, **self.STAFF), {"chosenId": 1})  # a take is never a yield
        self.assertEqual(len(r._yielded), 1)

    def test_less_mana_than_at_the_yield_still_yields(self):
        r = runner_g()
        r._note_yield(react_rep(BOLT, untapped=3, **self.STAFF), PASS)
        ans, src = r._fastpath(react_rep(BOLT, untapped=1, **self.STAFF))
        self.assertEqual(src, "yield")


class ReactorAndThreatGuards(unittest.TestCase):
    def test_stifle_class_counters_are_not_dead_on_an_all_abilities_stack(self):   # finding R1 (P0)
        r = runner_g()
        stifle = ("Stifle  {U} — Counter target activated or triggered ability.", "{U}")
        self.assertIsNone(r._fastpath(react_rev(stifle, untapped=1)), "Stifle answers an ability: the model decides")
        negate = ("Negate  {1}{U} — Counter target noncreature spell.", "{1}{U}")
        ans, src = r._fastpath(react_rev(negate, untapped=2))
        self.assertEqual((ans, src), (PASS, "affordability"), "a pure spell counter is dead vs abilities")

    def test_mana_only_options_stay_live_when_our_source_is_targeted(self):   # finding R4 (P1)
        r = runner_g()
        lotus = ("Gilded Lotus  {T} — Add three mana of any one color.", "{T}")
        ans, src = r._fastpath(react_rev(lotus, untapped=1))
        self.assertEqual(src, "affordability", "no threat: mana-only is dead")
        self.assertIsNone(r._fastpath(react_rev(lotus, untapped=1, stack=("Beast Within",), kinds=("spell",), owners=(3,),
                                            targets=[["Gilded Lotus (77)"]])), "Beast Within on the Lotus: float it first")

    def test_repeat_rule_needs_an_all_abilities_stack(self):   # finding R5 (P1)
        r = runner_g()
        ring = ("The One Ring  {T} — draw a card for each burden counter.", "{T}")
        first = react_rev(ring)
        r._note_tap_pass(first, PASS)
        self.assertEqual(r._fastpath(react_rev(ring))[1], "repeat")
        self.assertIsNone(r._fastpath(react_rev(ring, stack=("Peer into the Abyss",), kinds=("spell",), owners=(3,))),
                          "a spell on the stack: dig with the Ring is a live question")

    def test_game_reset_clears_the_per_turn_memories(self):   # finding R7 (P2)
        r = runner_g()
        r._tap_pass = (1, ("x",), 40); r._yielded = {(1, "a", 0, "ability", ()): (40, 0, 0)}
        req = react_rev(stack=(), kinds=(), owners=()); req["seq"] = 1; req["turn"] = 1
        req["decisionType"] = "CAST_SPELL"   # an own-main window: nothing to yield on after the reset
        r.mb.game_reset = True
        r.brain.decide = lambda *a, **k: (PASS, {"latency_s": 0.1, "usage": None, "cache_read": None, "raw": "{}"})
        r.brain.session_id = "s"; r.brain.ensure_session = lambda *a, **k: True
        r.mb.respond = lambda req, ans: True
        r.handle(req)
        self.assertIsNone(r._tap_pass); self.assertEqual(r._yielded, {})


class AutopassThreatClause(unittest.TestCase):
    MOTHER = [{"id": 0, "label": "Pass (do nothing)", "type": "PASS"},
              {"id": 1, "label": "Mother of Runes  {T} — protect", "type": "ABILITY"}]

    def test_threatened_own_creature_escapes_the_allowlist(self):
        r = runner_p()
        req = react_w2(1, stack=["Swords to Plowshares"],
                    targets=[["Serra Ascendant (55)"]],
                    options=self.MOTHER,
                    battlefield=[{"id": 55, "name": "Serra Ascendant"}])
        self.assertIsNone(r._fastpath(req),
                          "removal aimed at OUR creature is the one window "
                          "Mother exists for — never autopass")

    def test_threatened_self_escapes_the_allowlist(self):
        r = runner_p()
        req = react_w2(1, stack=["Lava Spike"], targets=[["seat 0"]],
                    options=self.MOTHER, battlefield=[])
        self.assertIsNone(r._fastpath(req))

    def test_divided_damage_label_still_threatens(self):
        # Wave-3 F7: divided spells append " [n]" to the target label — the
        # clause must strip it, or Arc Trail at the protected creature is
        # auto-passed with Mother untapped.
        r = runner_p()
        req = react_w2(1, stack=["Arc Trail"],
                    targets=[["Serra Ascendant (55) [2]", "seat 0 [1]"]],
                    options=self.MOTHER,
                    battlefield=[{"id": 55, "name": "Serra Ascendant"}])
        self.assertIsNone(r._fastpath(req),
                          "divided-damage suffixes must not hide a threat")

    def test_own_spell_at_own_creature_is_not_a_threat(self):
        # Wave-3 F9: the seat's own pump on its own attacker must not burn
        # the allowlist (stackOwners already says whose item it is).
        r = runner_p()
        req = react_w2(1, stack=["Giant Growth"],
                    targets=[["Serra Ascendant (55)"]],
                    owners=[0],  # the seat's own item
                    options=self.MOTHER,
                    battlefield=[{"id": 55, "name": "Serra Ascendant"}])
        got = r._fastpath(req)
        self.assertIsNotNone(got, "own spell aiming own stuff is a plan, not a threat")
        self.assertEqual(got[1], "autopass")

    def test_unthreatening_window_still_autopasses(self):
        r = runner_p()
        req = react_w2(1, stack=["Divination"], targets=[[]],
                    options=self.MOTHER,
                    battlefield=[{"id": 55, "name": "Serra Ascendant"}])
        got = r._fastpath(req)
        self.assertIsNotNone(got, "no threat -> the allowlist still saves the call")
        self.assertEqual(got[1], "autopass")


class HoldGuardTests(unittest.TestCase):
    def _runner(self):
        tmp = Path(tempfile.mkdtemp(prefix="hold-"))
        return SeatRunner(0, "purphoros-god-of-the-forge", str(tmp),
                          log_dir=str(tmp / "logs"), react_hold=True)

    def _fp(self, r, req):
        return r._fastpath(req)  # returns (answer, source) or None

    def test_armed_holds_on_already_seen_stack(self):
        r = self._runner()
        r.hold = {"turn": 7, "seen": {"Opponent Draw Spell"}}
        got = self._fp(r, react_req(2, ["Opponent Draw Spell"]))
        self.assertEqual(got, ({"chosenId": 0}, "hold"))

    def test_new_object_escalates(self):  # the key misplay guard
        r = self._runner()
        r.hold = {"turn": 7, "seen": {"Opponent Draw Spell"}}
        # a NEW spell (a wincon, say) appears — must NOT auto-pass
        self.assertIsNone(self._fp(r, react_req(3, ["Opponent Draw Spell",
                                                    "Expropriate"])))

    def test_empty_stack_escalates(self):  # tactical window (fogs/tricks) protected
        r = self._runner()
        r.hold = {"turn": 7, "seen": {"Opponent Draw Spell"}}
        self.assertIsNone(self._fp(r, react_req(4, [])))

    def test_hold_scoped_to_its_turn(self):
        r = self._runner()
        r.hold = {"turn": 7, "seen": {"X"}}
        self.assertIsNone(self._fp(r, react_req(5, ["X"], turn=8)))

    def test_disabled_by_default(self):
        tmp = Path(tempfile.mkdtemp(prefix="hold-"))
        r = SeatRunner(0, "purphoros-god-of-the-forge", str(tmp),
                       log_dir=str(tmp / "logs"))  # react_hold defaults False
        r.hold = {"turn": 7, "seen": {"X"}}
        self.assertIsNone(self._fp(r, react_req(6, ["X"])))


class LowEffortRuleTests(unittest.TestCase):
    def test_other_players_abilities_only_and_unthreatened(self):
        tmp = Path(tempfile.mkdtemp(prefix="eff-"))
        r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))
        self.assertTrue(r._unthreatened_ability_react(react_eff()))
        self.assertTrue(r._unthreatened_ability_react(react_eff(stack=("A", "B"), kinds=("trigger", "ability"), owners=(0, 3))))
        self.assertFalse(r._unthreatened_ability_react(react_eff(kinds=("spell",))), "a spell is a full question")
        self.assertFalse(r._unthreatened_ability_react(react_eff(owners=(2,))), "our own item: the own-trigger rule owns that")
        self.assertFalse(r._unthreatened_ability_react(react_eff(targets=[["seat 2"]])), "aimed at us")
        self.assertFalse(r._unthreatened_ability_react(react_eff(stack=(), kinds=(), owners=())), "empty stack")
        self.assertFalse(r._unthreatened_ability_react(react_eff(kinds=None)), "missing metadata fails open")
        oracle = react_eff()
        oracle["state"]["stackOracle"] = ["When Thassa's Oracle enters, look at the top X cards … you win the game."]
        self.assertFalse(r._unthreatened_ability_react(oracle), "a game-deciding ability is a full-effort question")
        os.environ["ARENA_REACT_LOW_EFFORT"] = "off"
        try:
            self.assertFalse(r._unthreatened_ability_react(react_eff()))
        finally:
            os.environ.pop("ARENA_REACT_LOW_EFFORT", None)


class YieldPublishAndVisibilityTests(unittest.TestCase):
    def test_yields_are_published_for_the_engine_mirror(self):
        tmp = Path(tempfile.mkdtemp(prefix="pub-"))
        r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))
        req = react_eff()
        req["turn"] = 23
        req["state"]["life"] = 21; req["state"]["manaPool"] = 0; req["state"]["untappedManaSourceCount"] = 0
        req["options"] = [{"id": 0, "label": "Pass (do nothing)"}, {"id": 1, "label": "The One Ring  {T} — draw"}]
        r._note_yield(req, {"chosenId": 0})
        f = Path(tmp) / "seat-2" / "yield.json"
        self.assertTrue(f.exists(), "yield.json written next to the seat's inbox")
        body = json.loads(f.read_text())
        self.assertEqual(body["seat"], 2)
        item = body["items"][0]
        self.assertEqual((item["turn"], item["name"], item["owner"], item["kind"]), (23, "Staff of Domination", 0, "ability"))
        self.assertEqual(item["options"], ["The One Ring"])
        self.assertEqual((item["life"], item["pool"], item["untapped"]), (21, 0, 0))

    def test_usage_snapshot_carries_context_and_rotations(self):
        tmp = Path(tempfile.mkdtemp(prefix="vis-"))
        r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))
        r.brain.last_prompt_tokens = 123_456; r.brain.rotations = 2
        req = react_eff(); req["seq"] = 1; req["turn"] = 1
        r._record(req, {"chosenId": 0}, "memo", why="t")
        rec = json.loads((tmp / "logs" / "seat-2.jsonl").read_text().splitlines()[-1])
        self.assertEqual(rec["cum"]["last_prompt_tokens"], 123_456)
        self.assertEqual(rec["cum"]["rotations"], 2)

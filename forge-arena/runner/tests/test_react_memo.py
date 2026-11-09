"""The same-turn REACT memo (seatd/runner.py `_react_signature` / `_fastpath` "memo").

A window identical to one the MODEL already passed this turn is passed without a call. What
"identical" means has been earned one game at a time:
- wave 2 (2026-08-28): the signature keys on phase, combat and stack targets — one correct pass at
  "beginning of combat, nothing declared" must not fast-pass the post-blocks fog window;
- options A/B (2026-08-17): a SHRINKING cascade of the seat's own identical triggers collapses after
  the first pass; an opponent object or a non-trigger on the stack breaks the collapse;
- BL-52 (game 49): own life is bucketed by five above ten like an opponent's, exact at ten or below;
- plan item 3 (2026-09-03): only a REAL model pass feeds the memo — a punt or an invalid answer never;
- BL-62 (game 64): the memo forgets its passes when a stack object with a NEW name appears.
Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seatd.runner import SeatRunner  # noqa: E402


FIX = Path(__file__).parent / "fixtures"


META = {"latency_s": 1.0, "usage": None, "cache_read": None, "raw": "{}"}


PASS = {"chosenId": 0}


AGATE = ("Agate Instigator",)


BIRGI_IGNUS = ("Birgi, God of Storytelling", "Grinning Ignus")


IGNUS = ("Grinning Ignus",)


MANEUVER = ["Flawless Maneuver  {0} — Creatures you control gain indestructible"]


def react(seq, life=40, opp=(40, 35, 40), stack=IGNUS, options=None,
          turn=10, phase="MAIN1", pool=0, targets=None):
    """An opponent's loop window as seat 2 (the fixture seat) sees it."""
    r = json.loads((FIX / "react.json").read_text())
    r["seq"] = seq
    r["turn"] = turn
    r["phase"] = phase
    st = r["state"]
    st["life"] = life
    st["stack"] = list(stack)
    st["manaPool"] = pool
    st.pop("stackOwners", None)
    st.pop("stackKinds", None)
    if targets is not None:
        st["stackTargets"] = targets
    for o, l in zip(st["opponents"], opp):
        o["life"] = l
    if options is not None:
        r["options"] = [{"id": 0, "label": "Pass (do nothing)", "cost": None, "type": "PASS"}]
        r["options"] += [{"id": i + 1, "label": lab, "cost": "{0}", "type": "Instant"}
                         for i, lab in enumerate(options)]
    return r


def runner():
    tmp = Path(tempfile.mkdtemp(prefix="bl52-"))
    return SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))


def react_w2(seq, turn=9, phase="MAIN1", stack=(), combat=None, targets=None,
          options=None, battlefield=None, owners=None):
    r = json.loads((FIX / "react.json").read_text())
    r["seq"] = seq
    r["turn"] = turn
    r["phase"] = phase
    r["state"]["stack"] = list(stack)
    r["state"]["stackOwners"] = list(owners) if owners is not None else [1] * len(stack)
    r["state"]["stackKinds"] = ["spell"] * len(stack)
    if combat is not None:
        r["state"]["combat"] = combat
    if targets is not None:
        r["state"]["stackTargets"] = targets
    if battlefield is not None:
        r["state"]["battlefield"] = battlefield
    if options is not None:
        r["options"] = options
    return r


def runner_p():
    tmp = Path(tempfile.mkdtemp(prefix="wave2-"))
    return SeatRunner(0, "purphoros-god-of-the-forge", str(tmp),
                      log_dir=str(tmp / "logs"))


def react_trig(seq, stack, owners, kinds, turn=9, pool=0):
    r = json.loads((FIX / "react.json").read_text())
    r["seq"] = seq
    r["turn"] = turn
    r["state"]["stack"] = list(stack)
    r["state"]["stackOwners"] = list(owners)
    r["state"]["stackKinds"] = list(kinds)
    r["state"]["manaPool"] = pool
    return r


def react_cs(seq, turn=9):
    r = json.loads((FIX / "react.json").read_text())
    r["seq"] = seq
    r["turn"] = turn
    r["state"]["stack"] = ["Counterspell"]
    r["state"]["stackOwners"] = [1]
    r["state"]["stackKinds"] = ["spell"]
    return r


def window(seq, stack, turn=9):
    r = react_cs(seq, turn)
    r["state"]["stack"] = list(stack)
    r["state"]["stackOwners"] = [1] * len(stack)
    r["state"]["stackKinds"] = ["spell"] * len(stack)
    return r


class OwnLifeBucket(unittest.TestCase):
    def test_own_life_moving_within_a_bucket_shares_the_signature(self):
        r = runner()
        a, b = react(1, life=34), react(2, life=31)
        self.assertEqual(r._react_signature(a), r._react_signature(b),
                         "a ping that leaves us in the same bucket is the same decision")
        r.react_seen.add(r._react_signature(a))          # the model passed at 34
        got = r._fastpath(b)
        self.assertIsNotNone(got, "the window at 31 must fast-pass")
        self.assertEqual(got[1], "memo")

    def test_own_life_crossing_a_bucket_edge_reopens(self):
        # The buckets are [45,49], [40,44], ... like an opponent's: 30 -> 29
        # straddles an edge and re-asks, exactly as an opponent's 30 -> 29 does.
        r = runner()
        self.assertNotEqual(r._react_signature(react(1, life=30)),
                            r._react_signature(react(2, life=29)))
        self.assertNotEqual(r._react_signature(react(3, life=45)),
                            r._react_signature(react(4, life=44)))

    def test_entering_kill_range_is_never_memoised_against_above_ten(self):
        r = runner()
        eleven, ten = react(1, life=11), react(2, life=10)
        self.assertNotEqual(r._react_signature(eleven), r._react_signature(ten),
                            "11 -> 10: kill range is exact")
        r.react_seen.add(r._react_signature(eleven))
        self.assertIsNone(r._fastpath(ten), "at ten the model is asked again")
        # 14 -> 11 is still one bucket (both above ten)
        self.assertEqual(r._react_signature(react(3, life=14)),
                         r._react_signature(react(4, life=11)))

    def test_kill_range_own_life_stays_exact_every_point(self):
        r = runner()
        self.assertNotEqual(r._react_signature(react(1, life=9)),
                            r._react_signature(react(2, life=8)), "9 -> 8 is exact")
        seen = set()
        for i, life in enumerate(range(10, 0, -1)):
            req = react(10 + i, life=life)
            self.assertIsNone(r._fastpath(req), f"own life {life}: never a memo hit")
            sig = r._react_signature(req)
            self.assertNotIn(sig, seen)
            seen.add(sig)
            r.react_seen.add(sig)

    def test_stack_top_change_reopens(self):
        r = runner()
        r.react_seen.add(r._react_signature(react(1, life=43, stack=IGNUS)))
        self.assertIsNone(r._fastpath(react(2, life=42, stack=AGATE)))
        self.assertIsNone(r._fastpath(react(3, life=42, stack=BIRGI_IGNUS)))
        # same names, different target: still a new decision
        r.react_seen.add(r._react_signature(react(4, life=43, stack=("Shock",), targets=[["seat 0"]])))
        self.assertIsNone(r._fastpath(react(5, life=42, stack=("Shock",), targets=[["seat 2"]])))

    def test_options_change_reopens(self):
        r = runner()
        r.react_seen.add(r._react_signature(react(1, life=43, options=MANEUVER)))
        self.assertIsNotNone(r._fastpath(react(2, life=42, options=MANEUVER)))
        self.assertIsNone(r._fastpath(react(3, life=42, options=MANEUVER + ["Generous Gift  {2}{W} — destroy"])))
        self.assertIsNone(r._fastpath(react(4, life=42, options=[])))

    def test_phase_and_pool_still_reopen(self):
        r = runner()
        r.react_seen.add(r._react_signature(react(1, life=43)))
        self.assertIsNone(r._fastpath(react(2, life=42, phase="END_OF_TURN")))
        self.assertIsNone(r._fastpath(react(3, life=42, pool=2)))

    def test_opponent_bucketing_unchanged(self):
        r = runner()
        a = r._react_signature(react(1, opp=(34, 4, 40)))
        self.assertEqual(a, r._react_signature(react(2, opp=(32, 4, 40))),
                         "an opponent moving inside a bucket is the same decision")
        self.assertNotEqual(a, r._react_signature(react(3, opp=(34, 3, 40))),
                            "an opponent at 4 -> 3 is exact (kill range)")
        self.assertNotEqual(a, r._react_signature(react(4, opp=(29, 4, 40))),
                            "an opponent crossing a bucket edge re-opens")
        self.assertNotEqual(a, r._react_signature(react(5, opp=(34, 11, 40))),
                            "an opponent leaving kill range re-opens")

    def test_game25_shape_the_looper_in_kill_range_still_reasks(self):
        # Game 25: the LOOPING opponent's life moved on every activation. Above
        # ten his moves are bucketed (the fix that game earned); at ten or
        # below every point re-opens the window, before and after BL-52. Own
        # life is now treated the same way.
        r = runner()
        r.react_seen.add(r._react_signature(react(1, opp=(34, 40, 40))))
        self.assertIsNotNone(r._fastpath(react(2, opp=(33, 40, 40))))
        r.react_seen.add(r._react_signature(react(3, opp=(10, 40, 40))))
        self.assertIsNone(r._fastpath(react(4, opp=(9, 40, 40))))
        self.assertIsNone(r._fastpath(react(5, opp=(10, 40, 40), life=10)))  # we entered kill range too
        r.react_seen.add(r._react_signature(react(6, opp=(10, 40, 40), life=10)))
        self.assertIsNone(r._fastpath(react(7, opp=(10, 40, 40), life=9)))

    def test_life_bucket_helper(self):
        self.assertEqual(SeatRunner._life_bucket(10), 10)
        self.assertEqual(SeatRunner._life_bucket(11), "10+")
        self.assertEqual(SeatRunner._life_bucket(44), "40+")
        self.assertEqual(SeatRunner._life_bucket(45), "45+")
        self.assertIsNone(SeatRunner._life_bucket(None))
        self.assertIs(SeatRunner._life_bucket(True), True)


class MemoSafety(unittest.TestCase):
    def test_a_model_action_never_feeds_the_memo(self):
        r = runner()
        r.brain.decide = lambda prompt, **kw: ({"chosenId": 1, "why": "protect"}, dict(META))
        acted = react(1, life=44, options=MANEUVER)
        r.handle(acted)
        self.assertNotIn(r._react_signature(acted), r.react_seen)
        self.assertIsNone(r._fastpath(react(2, life=43, options=MANEUVER)),
                          "the seat acted at 44: the window at 43 is a fresh question")

    def test_a_model_pass_feeds_it_and_the_turn_boundary_clears_it(self):
        r = runner()
        calls = []
        r.brain.decide = lambda prompt, **kw: (calls.append(1) or dict(PASS), dict(META))
        r.handle(react(1, life=44, options=MANEUVER))
        self.assertEqual(len(calls), 1)
        r.handle(react(2, life=43, options=MANEUVER))
        self.assertEqual(len(calls), 1, "43 after a pass at 44 is a memo hit")
        r.handle(react(3, life=43, options=MANEUVER, turn=11))
        self.assertEqual(len(calls), 2, "a new turn forgets the memo")

    def test_cycle_signature_untouched(self):
        # Cycle replay uses its own signature, which never held life at all;
        # armed cycles still break on novelty through stack/options/phase.
        r = runner()
        self.assertEqual(r._cycle_signature(react(1, life=44)), r._cycle_signature(react(2, life=10)))
        self.assertNotEqual(r._cycle_signature(react(3, stack=IGNUS)), r._cycle_signature(react(4, stack=AGATE)))


class Game49Shape(unittest.TestCase):
    def test_bystander_pinged_once_per_recast(self):
        """The turn-10 tape, synthesised: three windows per recast (Agate's
        trigger, Birgi + Ignus, Ignus alone), one ping to every bystander per
        recast, lives 45 -> 1 with the opponents at 40/35/40 moving in
        lockstep. The memo fires for own life inside a bucket and stops for
        good at own life 20, where the 35-life opponent enters kill range
        (exact from there); own life at ten or below is never memoised. The
        live tape (137 windows, one duplicate 45-life window) replayed 58."""
        r = runner()
        hits = 0
        kill_range_hits = 0
        seq = 0
        for step in range(45):
            life = 45 - step
            opp = (40 - step, 35 - step, 40 - step)
            for stack in (AGATE, BIRGI_IGNUS, IGNUS):
                seq += 1
                req = react(seq, life=life, opp=opp, stack=stack, options=MANEUVER)
                if r._fastpath(req) is not None:
                    hits += 1
                    kill_range_hits += life <= 10
                else:
                    r.react_seen.add(r._react_signature(req))   # the model passed
        self.assertEqual(hits, 57, "12 per bucket for 44-41, 39-36, 34-31, 29-26; 9 for 24-21")
        self.assertEqual(kill_range_hits, 0)


class MemoSignatureWave2(unittest.TestCase):
    def test_combat_change_reopens_the_window(self):
        r = runner_p()
        quiet = react_w2(1, phase="COMBAT_DECLARE_ATTACKERS", combat=[])
        alpha = react_w2(2, phase="COMBAT_DECLARE_ATTACKERS",
                      combat=[{"attacker": "Serra Angel", "defender": "seat 0",
                               "blockedBy": []}])
        r.react_seen.add(r._react_signature(quiet))
        self.assertIsNone(r._fastpath(alpha),
                          "attackers on the table is a NEW decision")


class TriggerCascadeMemo(unittest.TestCase):
    def _runner(self):
        tmp = Path(tempfile.mkdtemp(prefix="trig-"))
        return SeatRunner(0, "purphoros-god-of-the-forge", str(tmp),
                          log_dir=str(tmp / "logs"))

    def test_shrinking_own_cascade_memoizes_after_first_pass(self):
        r = self._runner()
        # 4 identical own triggers on the stack -> brain decides once (pass)
        first = react_trig(1, ["Purphoros"] * 4, [0] * 4, ["trigger"] * 4)
        self.assertIsNone(r._fastpath(first))          # not memoized yet
        r.react_seen.add(r._react_signature(first))     # brain passed
        # 3, 2, 1 remaining: same set of names, all own triggers -> memo hits
        for n in (3, 2, 1):
            req = react_trig(1 + n, ["Purphoros"] * n, [0] * n, ["trigger"] * n)
            fp = r._fastpath(req)
            self.assertIsNotNone(fp, f"cascade of {n} should fastpath")
            self.assertEqual(fp[1], "memo")

    def test_opponent_object_breaks_the_memo(self):
        r = self._runner()
        first = react_trig(1, ["Purphoros"] * 3, [0] * 3, ["trigger"] * 3)
        r.react_seen.add(r._react_signature(first))
        # an opponent's spell joins the stack -> exact multiset again -> no memo
        req = react_trig(2, ["Purphoros", "Purphoros", "Counterspell"],
                    [0, 0, 2], ["trigger", "trigger", "spell"])
        self.assertIsNone(r._fastpath(req))

    def test_own_spell_not_trigger_breaks_the_memo(self):
        r = self._runner()
        first = react_trig(1, ["Purphoros"] * 3, [0] * 3, ["trigger"] * 3)
        r.react_seen.add(r._react_signature(first))
        req = react_trig(2, ["Purphoros", "Purphoros"], [0, 0], ["trigger", "spell"])
        self.assertIsNone(r._fastpath(req))

    def test_missing_owner_fields_fail_open(self):
        r = self._runner()
        a = json.loads((FIX / "react.json").read_text()); a["seq"] = 1; a["turn"] = 9
        a["state"]["stack"] = ["Purphoros"] * 3
        a["state"].pop("stackOwners", None); a["state"].pop("stackKinds", None)
        r.react_seen.add(r._react_signature(a))
        b = json.loads(json.dumps(a)); b["seq"] = 2
        b["state"]["stack"] = ["Purphoros"] * 2               # different multiset
        self.assertIsNone(r._fastpath(b))                     # no collapse w/o fields
        self.assertFalse(r._all_own_triggers(a))

    def test_life_change_still_reopens(self):
        r = self._runner()
        first = react_trig(1, ["Purphoros"] * 3, [0] * 3, ["trigger"] * 3)
        r.react_seen.add(r._react_signature(first))
        req = react_trig(2, ["Purphoros"] * 2, [0] * 2, ["trigger"] * 2)
        req["state"]["life"] = (first["state"].get("life") or 40) - 5
        self.assertIsNone(r._fastpath(req))


class OwnTriggerRouting(unittest.TestCase):
    def test_predicate(self):
        r = SeatRunner(2, "giada-font-of-hope", str(Path(tempfile.mkdtemp())),
                       log_dir=str(Path(tempfile.mkdtemp()) / "logs"))
        self.assertTrue(r._all_own_triggers(react_trig(1, ["A", "A"], [2, 2], ["trigger", "trigger"])))
        self.assertFalse(r._all_own_triggers(react_trig(1, ["A", "B"], [2, 1], ["trigger", "trigger"])))
        self.assertFalse(r._all_own_triggers(react_trig(1, ["A"], [2], ["ability"])))
        self.assertFalse(r._all_own_triggers(react_trig(1, [], [], [])))


class MemoOnlyFromModel(unittest.TestCase):
    def test_punt_does_not_memoize(self):
        r = runner_p()
        r.brain.decide = lambda prompt, **kw: (None, dict(META))   # timeout/wedge
        req = react_cs(1)
        r.handle(req)
        self.assertNotIn(r._react_signature(req), r.react_seen,
                         "a punt must not install a same-turn memo entry")
        self.assertIsNone(r._fastpath(react_cs(2)),
                          "the next identical window must reach the model")

    def test_invalid_answer_does_not_memoize(self):
        r = runner_p()
        r.brain.decide = lambda prompt, **kw: ({"chosenId": 999}, dict(META))  # illegal id
        req = react_cs(1)
        r.handle(req)
        self.assertNotIn(r._react_signature(req), r.react_seen)

    def test_deviation_is_cleared_between_decisions(self):
        r = runner_p()
        r.brain.decide = lambda prompt, **kw: (
            {"chosenId": 0, "deviation": {"wanted": "Counterspell", "blocked_by": "no mana"}},
            dict(META))
        r.handle(react_cs(1))
        self.assertIsNotNone(r._deviation, "the model call that reported it keeps it")
        # a memo hit: no model call, so no deviation may be attached to its record
        recorded = []
        r._record = lambda req, answer, source, meta=None, why=None, consumed=None: \
            recorded.append((source, getattr(r, "_deviation", None)))
        r.handle(react_cs(2))
        self.assertEqual(recorded[-1][0], "memo")
        self.assertIsNone(recorded[-1][1],
                          "a model-free decision must not carry a stale deviation")


class MemoSeesANewSpell(unittest.TestCase):
    def setUp(self):
        self.r = runner_p()
        self.calls = []
        self.r.brain.decide = lambda prompt, **kw: (self.calls.append(1) or {"chosenId": 0, "why": "wait"}, dict(META))

    def test_the_window_after_a_new_spell_resolved_goes_to_the_model(self):
        r = self.r
        r.handle(window(1, ["Kabira Takedown"]))
        r.handle(window(2, ["Collective Resistance", "Kabira Takedown"]))
        self.assertEqual(len(self.calls), 2, "a new spell above mine: the model is asked")
        r.handle(window(3, ["Kabira Takedown"]))
        self.assertEqual(len(self.calls), 3, "game 64 t21: the stack looks like window 1, but Resistance resolved in between")
        r.handle(window(4, ["Kabira Takedown"]))
        self.assertEqual(len(self.calls), 3, "the same window again, nothing new since: the memo replays the pass")

    def test_names_already_seen_keep_the_memo(self):
        r = self.r
        for seq, stack in ((1, ["Grinning Ignus"]), (2, ["Purphoros, God of the Forge", "Grinning Ignus"]), (3, ["Grinning Ignus"])):
            r.handle(window(seq, stack))
        self.assertEqual(len(self.calls), 3, "each stack shape once")
        for seq, stack in ((4, ["Purphoros, God of the Forge", "Grinning Ignus"]), (5, ["Grinning Ignus"]),
                           (6, ["Purphoros, God of the Forge", "Grinning Ignus"]), (7, ["Grinning Ignus"])):
            r.handle(window(seq, stack))
        self.assertEqual(len(self.calls), 3, "a loop repeats names the seat has seen: every later lap is memoised (BL-52 keeps its saving)")

    def test_a_yield_is_forgotten_with_the_memo(self):
        """Review 2026-10-02: my trigger on the stack (passed -> yielded), a new spell above it (passed), then the
        trigger alone again: it was auto-yielded with no model call."""
        r = self.r
        def trig(seq, stack, kinds):
            w = window(seq, stack)
            w["state"]["stackKinds"] = list(kinds)
            w["state"]["stackOwners"] = [r.seat] * len(stack)
            return w
        r.handle(trig(1, ["Ravenous Chupacabra"], ["trigger"]))
        r.handle(trig(2, ["Collective Resistance", "Ravenous Chupacabra"], ["spell", "trigger"]))
        r.handle(trig(3, ["Ravenous Chupacabra"], ["trigger"]))
        self.assertEqual(len(self.calls), 3, "the window after the new spell resolved reaches the model, not the yield")

    def test_the_turn_boundary_clears_the_names(self):
        r = self.r
        r.handle(window(1, ["Kabira Takedown"]))
        self.assertEqual(r._stack_names_seen, {"Kabira Takedown"})
        r.handle(window(2, ["Swords to Plowshares"], turn=10))
        self.assertEqual(r._stack_names_seen, {"Swords to Plowshares"})

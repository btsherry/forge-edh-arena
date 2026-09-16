"""BL-52 (game 49, 2026-09-16): a bystander's REACT memo never matched while
a loop pinged it. `_react_signature` kept the seat's OWN life exact (game
25's rule — the LOOPER's life moved then, not the bystanders'), so Agate
Instigator's one-ping-per-recast changed Giada's life on every window and
136 of her 137 turn-10 REACT windows went to the model to say "pass".

Own life now gets the rule everyone else's life already had: exact at ten
or below (kill range — the decision may change with every point), bucketed
by five above it. Everything else must still match a window the model
already passed this turn; a model ACTION never feeds the memo; the turn
boundary still clears it; the cycle signature (which ignores life) is
untouched. Run: python3 -m unittest discover -s tests -p 'test_react_memo.py'"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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
        self.assertIs(SeatRunner._life_bucket(True), True)   # bools are not lives


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


if __name__ == "__main__":
    unittest.main()

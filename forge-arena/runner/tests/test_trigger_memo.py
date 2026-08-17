"""Option A/B (2026-08-17): own-trigger cascades. The memo fastpath must
collapse a SHRINKING cascade of the seat's own identical triggers after the
first pass, and must NOT collapse once an opponent object (or a non-trigger)
is on the stack. Own-trigger REACT windows route to effort low (never skip).
Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd.runner import SeatRunner  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def react(seq, stack, owners, kinds, turn=9, pool=0):
    r = json.loads((FIX / "react.json").read_text())
    r["seq"] = seq
    r["turn"] = turn
    r["state"]["stack"] = list(stack)
    r["state"]["stackOwners"] = list(owners)
    r["state"]["stackKinds"] = list(kinds)
    r["state"]["manaPool"] = pool
    return r


class TriggerCascadeMemo(unittest.TestCase):
    def _runner(self):
        tmp = Path(tempfile.mkdtemp(prefix="trig-"))
        return SeatRunner(0, "purphoros-god-of-the-forge", str(tmp),
                          log_dir=str(tmp / "logs"))

    def test_shrinking_own_cascade_memoizes_after_first_pass(self):
        r = self._runner()
        # 4 identical own triggers on the stack -> brain decides once (pass)
        first = react(1, ["Purphoros"] * 4, [0] * 4, ["trigger"] * 4)
        self.assertIsNone(r._fastpath(first))          # not memoized yet
        r.react_seen.add(r._react_signature(first))     # brain passed
        # 3, 2, 1 remaining: same set of names, all own triggers -> memo hits
        for n in (3, 2, 1):
            req = react(1 + n, ["Purphoros"] * n, [0] * n, ["trigger"] * n)
            fp = r._fastpath(req)
            self.assertIsNotNone(fp, f"cascade of {n} should fastpath")
            self.assertEqual(fp[1], "memo")

    def test_opponent_object_breaks_the_memo(self):
        r = self._runner()
        first = react(1, ["Purphoros"] * 3, [0] * 3, ["trigger"] * 3)
        r.react_seen.add(r._react_signature(first))
        # an opponent's spell joins the stack -> exact multiset again -> no memo
        req = react(2, ["Purphoros", "Purphoros", "Counterspell"],
                    [0, 0, 2], ["trigger", "trigger", "spell"])
        self.assertIsNone(r._fastpath(req))

    def test_own_spell_not_trigger_breaks_the_memo(self):
        r = self._runner()
        first = react(1, ["Purphoros"] * 3, [0] * 3, ["trigger"] * 3)
        r.react_seen.add(r._react_signature(first))
        req = react(2, ["Purphoros", "Purphoros"], [0, 0], ["trigger", "spell"])
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
        first = react(1, ["Purphoros"] * 3, [0] * 3, ["trigger"] * 3)
        r.react_seen.add(r._react_signature(first))
        req = react(2, ["Purphoros"] * 2, [0] * 2, ["trigger"] * 2)
        req["state"]["life"] = (first["state"].get("life") or 40) - 5
        self.assertIsNone(r._fastpath(req))                   # a ping landed -> re-ask


class OwnTriggerRouting(unittest.TestCase):
    def test_predicate(self):
        r = SeatRunner(2, "giada-font-of-hope", str(Path(tempfile.mkdtemp())),
                       log_dir=str(Path(tempfile.mkdtemp()) / "logs"))
        self.assertTrue(r._all_own_triggers(react(1, ["A", "A"], [2, 2], ["trigger", "trigger"])))
        self.assertFalse(r._all_own_triggers(react(1, ["A", "B"], [2, 1], ["trigger", "trigger"])))
        self.assertFalse(r._all_own_triggers(react(1, ["A"], [2], ["ability"])))
        self.assertFalse(r._all_own_triggers(react(1, [], [], [])))


if __name__ == "__main__":
    unittest.main()

"""Reactive hold-posture (#2) tests — the misplay-guard cases. A hold may only
auto-pass a REACT when armed, stack non-empty, and every stack object was
already seen; a NEW object or an empty-stack window must escalate. Run:
python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd.runner import SeatRunner  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def react_req(seq, stack, turn=7):
    r = json.loads((FIX / "react.json").read_text())
    r["seq"] = seq
    r["turn"] = turn
    r["state"]["stack"] = list(stack)
    return r


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


if __name__ == "__main__":
    unittest.main()

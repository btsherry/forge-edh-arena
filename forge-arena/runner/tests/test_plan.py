"""Executable-turn-plan tests (SPEC-executable-turn-plans.md): the binder and
the four-part guard. Uses SeatRunner with a fake mailbox/brain so no engine or
model is needed. Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd import rules  # noqa: E402
from seatd.runner import SeatRunner  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def cast_req(seq, options, phase="MAIN1", stack=None, turn=6):
    """Build a CAST_SPELL req with the given options (list of (id,label))."""
    base = json.loads((FIX / "cast_spell.json").read_text())
    base["seq"] = seq
    base["turn"] = turn
    base["phase"] = phase
    base["decisionType"] = "CAST_SPELL"
    base["state"]["stack"] = stack or []
    base["options"] = [{"id": 0, "label": "Pass (do nothing)", "type": "PASS"}] + [
        {"id": i, "label": lbl, "type": "Creature"} for i, lbl in options]
    return base


class BinderTests(unittest.TestCase):
    def test_binds_card_name_to_live_option_id(self):
        req = cast_req(5, [(7, "Sol Ring  {T} — adds {C}{C}"),
                           (9, "Llanowar Elves  {G} — 1/1")])
        self.assertEqual(rules.bind_plan_step({"card": "Sol Ring"}, req), 7)
        self.assertEqual(rules.bind_plan_step({"card": "Llanowar Elves"}, req), 9)

    def test_absent_card_returns_none(self):
        req = cast_req(5, [(7, "Sol Ring  {T} — adds {C}{C}")])
        self.assertIsNone(rules.bind_plan_step({"card": "Craterhoof Behemoth"}, req))

    def test_pass_option_never_bound(self):
        req = cast_req(5, [(7, "Sol Ring")])
        self.assertIsNone(rules.bind_plan_step({"card": "Pass"}, req))


class GuardTests(unittest.TestCase):
    def _runner(self):
        tmp = Path(tempfile.mkdtemp(prefix="plan-"))
        (tmp / "seat-0" / "inbox").mkdir(parents=True)
        (tmp / "seat-0" / "outbox").mkdir(parents=True)
        # SeatRunner builds a SeatBrain (loads a dossier) — use a real deck dir.
        r = SeatRunner(0, "purphoros-god-of-the-forge", str(tmp),
                       log_dir=str(tmp / "logs"), speculative=True)
        return r

    def test_guard_binds_and_validates_on_match(self):
        r = self._runner()
        r.plan = {"turn": 6, "steps": [{"card": "Sol Ring", "why": "ramp"}], "idx": 0}
        req = cast_req(5, [(7, "Sol Ring  {T} — adds {C}{C}")])
        self.assertEqual(r._plan_guard(req, r.plan["steps"][0]), 7)

    def test_guard_fails_on_nonempty_stack(self):  # #2b
        r = self._runner()
        req = cast_req(5, [(7, "Sol Ring")], stack=["Opponent's Counterspell"])
        self.assertIsNone(r._plan_guard(req, {"card": "Sol Ring"}))

    def test_guard_fails_off_main_phase(self):  # #2a
        r = self._runner()
        req = cast_req(5, [(7, "Sol Ring")], phase="UPKEEP")
        self.assertIsNone(r._plan_guard(req, {"card": "Sol Ring"}))

    def test_guard_fails_when_card_absent(self):  # #3 (was countered/removed)
        r = self._runner()
        req = cast_req(5, [(7, "Goldhound  {R}")])
        self.assertIsNone(r._plan_guard(req, {"card": "Sol Ring"}))


if __name__ == "__main__":
    unittest.main()

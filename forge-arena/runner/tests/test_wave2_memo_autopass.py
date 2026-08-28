"""Wave-2 (2026-08-28 dual audit): the REACT memo must key on phase, combat
and stack targets — one correct pass at "beginning of combat, nothing
declared" must NOT fast-pass the post-blocks fog window (audit finding 1,
the game-2 death one layer up) — and the autopass allowlist must never eat
a window whose stack targets OUR stuff (finding 5, note 12's dropped
clause). Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd.runner import SeatRunner  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def react(seq, turn=9, phase="MAIN1", stack=(), combat=None, targets=None,
          options=None, battlefield=None):
    r = json.loads((FIX / "react.json").read_text())
    r["seq"] = seq
    r["turn"] = turn
    r["phase"] = phase
    r["state"]["stack"] = list(stack)
    r["state"]["stackOwners"] = [1] * len(stack)
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


def runner():
    tmp = Path(tempfile.mkdtemp(prefix="wave2-"))
    return SeatRunner(0, "purphoros-god-of-the-forge", str(tmp),
                      log_dir=str(tmp / "logs"))


class MemoSignatureWave2(unittest.TestCase):
    def test_phase_change_reopens_the_window(self):
        r = runner()
        early = react(1, phase="COMBAT_BEGIN")
        late = react(2, phase="COMBAT_DECLARE_BLOCKERS")
        r.react_seen.add(r._react_signature(early))
        self.assertIsNone(r._fastpath(late),
                          "a later combat phase is a NEW decision, not a memo hit")

    def test_combat_change_reopens_the_window(self):
        r = runner()
        quiet = react(1, phase="COMBAT_DECLARE_ATTACKERS", combat=[])
        alpha = react(2, phase="COMBAT_DECLARE_ATTACKERS",
                      combat=[{"attacker": "Serra Angel", "defender": "seat 0",
                               "blockedBy": []}])
        r.react_seen.add(r._react_signature(quiet))
        self.assertIsNone(r._fastpath(alpha),
                          "attackers on the table is a NEW decision")

    def test_target_change_reopens_the_window(self):
        r = runner()
        at_me = react(1, stack=["Shock"], targets=[["seat 0"]])
        at_them = react(2, stack=["Shock"], targets=[["seat 2"]])
        r.react_seen.add(r._react_signature(at_me))
        self.assertIsNone(r._fastpath(at_them),
                          "same spell at a different target is a NEW decision")

    def test_true_repeat_still_memoizes(self):
        r = runner()
        a = react(1, phase="MAIN1", stack=["Shock"], targets=[["seat 2"]])
        b = react(2, phase="MAIN1", stack=["Shock"], targets=[["seat 2"]])
        r.react_seen.add(r._react_signature(a))
        got = r._fastpath(b)
        self.assertIsNotNone(got, "identical windows must still fast-pass")
        self.assertEqual(got[1], "memo")


class AutopassThreatClause(unittest.TestCase):
    MOTHER = [{"id": 0, "label": "Pass (do nothing)", "type": "PASS"},
              {"id": 1, "label": "Mother of Runes  {T} — protect", "type": "ABILITY"}]

    def test_threatened_own_creature_escapes_the_allowlist(self):
        r = runner()
        req = react(1, stack=["Swords to Plowshares"],
                    targets=[["Serra Ascendant (55)"]],
                    options=self.MOTHER,
                    battlefield=[{"id": 55, "name": "Serra Ascendant"}])
        self.assertIsNone(r._fastpath(req),
                          "removal aimed at OUR creature is the one window "
                          "Mother exists for — never autopass")

    def test_threatened_self_escapes_the_allowlist(self):
        r = runner()
        req = react(1, stack=["Lava Spike"], targets=[["seat 0"]],
                    options=self.MOTHER, battlefield=[])
        self.assertIsNone(r._fastpath(req))

    def test_unthreatening_window_still_autopasses(self):
        r = runner()
        req = react(1, stack=["Divination"], targets=[[]],
                    options=self.MOTHER,
                    battlefield=[{"id": 55, "name": "Serra Ascendant"}])
        got = r._fastpath(req)
        self.assertIsNotNone(got, "no threat -> the allowlist still saves the call")
        self.assertEqual(got[1], "autopass")


if __name__ == "__main__":
    unittest.main()

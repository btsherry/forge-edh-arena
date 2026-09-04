"""Interactive plan item 3 (2026-09-03): only a REAL model pass feeds the
same-turn REACT memo. A punt (timeout / wedge / invalid answer) also yields
{"chosenId": 0} via safe_default, but the brain never saw the window; before
this fix it was memoized and every identical window that turn auto-passed
under a "why" claiming the brain had considered it — which also hid the
punts from the ratings void counter. Also: a deviation reported by one model
call must not be stamped onto the records of later model-free decisions.
Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd.runner import SeatRunner  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
META = {"latency_s": 1.0, "usage": None, "cache_read": None, "raw": "{}"}


def react(seq, turn=9):
    r = json.loads((FIX / "react.json").read_text())
    r["seq"] = seq
    r["turn"] = turn
    r["state"]["stack"] = ["Counterspell"]
    r["state"]["stackOwners"] = [1]
    r["state"]["stackKinds"] = ["spell"]
    return r


def runner():
    tmp = Path(tempfile.mkdtemp(prefix="memo-"))
    return SeatRunner(0, "purphoros-god-of-the-forge", str(tmp),
                      log_dir=str(tmp / "logs"))


class MemoOnlyFromModel(unittest.TestCase):
    def test_punt_does_not_memoize(self):
        r = runner()
        r.brain.decide = lambda prompt, **kw: (None, dict(META))   # timeout/wedge
        req = react(1)
        r.handle(req)
        self.assertNotIn(r._react_signature(req), r.react_seen,
                         "a punt must not install a same-turn memo entry")
        self.assertIsNone(r._fastpath(react(2)),
                          "the next identical window must reach the model")

    def test_invalid_answer_does_not_memoize(self):
        r = runner()
        r.brain.decide = lambda prompt, **kw: ({"chosenId": 999}, dict(META))  # illegal id
        req = react(1)
        r.handle(req)
        self.assertNotIn(r._react_signature(req), r.react_seen)

    def test_model_pass_still_memoizes(self):
        r = runner()
        r.brain.decide = lambda prompt, **kw: ({"chosenId": 0, "why": "nothing to do"},
                                               dict(META))
        req = react(1)
        r.handle(req)
        self.assertIn(r._react_signature(req), r.react_seen,
                      "a real model pass is exactly what the memo is for")
        self.assertIsNotNone(r._fastpath(react(2)))

    def test_deviation_is_cleared_between_decisions(self):
        r = runner()
        r.brain.decide = lambda prompt, **kw: (
            {"chosenId": 0, "deviation": {"wanted": "Counterspell", "blocked_by": "no mana"}},
            dict(META))
        r.handle(react(1))
        self.assertIsNotNone(r._deviation, "the model call that reported it keeps it")
        # a memo hit: no model call, so no deviation may be attached to its record
        recorded = []
        r._record = lambda req, answer, source, meta=None, why=None, consumed=None: \
            recorded.append((source, getattr(r, "_deviation", None)))
        r.handle(react(2))
        self.assertEqual(recorded[-1][0], "memo")
        self.assertIsNone(recorded[-1][1],
                          "a model-free decision must not carry a stale deviation")


class EngineTimeoutAdoption(unittest.TestCase):
    """Plan item 12: the engine's timeoutSec on a request is the budget source."""

    def test_runner_adopts_the_engine_timeout(self):
        r = runner()
        r.brain.decide = lambda prompt, **kw: ({"chosenId": 0}, dict(META))
        self.assertEqual(r.timeout_s, 90.0)
        req = react(1)
        req["timeoutSec"] = 300
        r.handle(req)
        self.assertEqual(r.timeout_s, 300.0)
        self.assertEqual(r.mb.timeout_s, 300.0)

    def test_unstamped_request_keeps_the_launch_timeout(self):
        r = runner()
        r.brain.decide = lambda prompt, **kw: ({"chosenId": 0}, dict(META))
        req = react(1)
        req.pop("timeoutSec", None)
        r.handle(req)
        self.assertEqual(r.timeout_s, 90.0)


class RunnerHygiene(unittest.TestCase):
    """Plan item 13: (a) an exception inside a decision never kills the runner
    — it logs, answers the safe default, and records a punt; (h) the shared
    log is one file per game with game.jsonl a symlink to the current one."""

    def test_exception_in_decision_becomes_a_recorded_punt(self):
        r = runner()

        def boom(prompt, **kw):
            raise RuntimeError("model client exploded")
        r.brain.decide = boom
        r.handle(react(1))   # must not raise
        rows = [json.loads(l) for l in r._jsonl_path.read_text().splitlines()]
        self.assertEqual(rows[-1]["source"], "punt")
        self.assertIn("runner exception", rows[-1]["why"])
        self.assertIn("INTERNAL ERROR", r._log_path.read_text())

    def test_game_log_rotates_per_game_with_a_current_symlink(self):
        r = runner()
        r.brain.decide = lambda prompt, **kw: ({"chosenId": 0}, dict(META))
        req = react(1)
        req["gameId"] = "1756950000123-4242"
        r.handle(req)
        per_game = r._game_log.with_name("game-1756950000123-4242.jsonl")
        self.assertTrue(per_game.exists(), "records go to the per-game file")
        self.assertTrue(r._game_log.is_symlink(), "game.jsonl is a symlink")
        self.assertEqual(r._game_log.resolve(), per_game.resolve())
        self.assertEqual(len(per_game.read_text().splitlines()), 1)
        # a second game: the symlink moves, the first file stays
        req2 = react(1, turn=1)
        req2["gameId"] = "1756950009999-4242"
        r.handle(req2)
        self.assertEqual(r._game_log.resolve(),
                         r._game_log.with_name("game-1756950009999-4242.jsonl").resolve())
        self.assertTrue(per_game.exists())


if __name__ == "__main__":
    unittest.main()

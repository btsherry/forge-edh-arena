"""Wedged-session recovery (game 7, 2026-08-17): after consecutive failed
model calls spanning long enough, the brain drops --resume, re-inits a fresh
session at the next decision, and prefixes that decision with a rejoin note.
Fast failure bursts alone must NOT cost the game memory. Offline: subprocess
is monkeypatched; time is monkeypatched to make spans deterministic."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seatd import brain as brain_mod  # noqa: E402
from seatd.brain import SeatBrain  # noqa: E402

DECK = "selvala-heart-of-the-wilds"


class Proc:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def envelope(session, result='{"chosenId": 0}'):
    return json.dumps({"session_id": session, "result": result,
                       "usage": {"input_tokens": 1, "output_tokens": 1,
                                 "cache_read_input_tokens": 100,
                                 "cache_creation_input_tokens": 0},
                       "total_cost_usd": 0.0, "is_error": False})


class WedgeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.calls = []          # (argv, prompt)
        self.script = []         # per-call behaviour: "ok" | "exit1" | "timeout"
        self.now = [1000.0]
        self.sessions = iter(["sess-A", "sess-B", "sess-C"])
        self.cur = ["sess-A"]
        orig_run, orig_time = brain_mod._run, brain_mod.time.time

        def fake_run(cmd, **kw):
            self.calls.append((list(cmd), kw.get("input", "")))
            beh = self.script.pop(0) if self.script else "ok"
            if beh == "exit1":
                return Proc('{"is_error":true,"result":"API Error: 500"}', returncode=1)
            if beh == "timeout":
                raise brain_mod.subprocess.TimeoutExpired(cmd, 72)
            if "--resume" not in cmd:          # fresh init: new session id
                self.cur[0] = next(self.sessions)
            return Proc(envelope(self.cur[0]))

        brain_mod._run = fake_run
        brain_mod.time.time = lambda: self.now[0]
        self.addCleanup(lambda: setattr(brain_mod, "_run", orig_run))
        self.addCleanup(lambda: setattr(brain_mod.time, "time", orig_time))

    def _brain(self):
        return SeatBrain(1, DECK, model="opus", effort="low", log=lambda *a: None)

    def test_fast_burst_keeps_session(self):
        b = self._brain()
        self.assertTrue(b.ensure_session())
        self.assertEqual(b.session_id, "sess-A")
        # three exit-1s within 10 seconds: a blip, not a wedge
        self.script = ["exit1", "exit1", "exit1"]
        for _ in range(3):
            self.now[0] += 3
            ans, _ = b.decide("q", timeout_s=60)
            self.assertIsNone(ans)
        self.assertEqual(b.session_id, "sess-A", "a 9s burst must not drop the session")
        ans, _ = b.decide("q", timeout_s=60)
        self.assertEqual(ans, {"chosenId": 0})
        self.assertEqual(b._fail_streak, 0)

    def test_long_streak_reinits_and_rejoins(self):
        b = self._brain()
        self.assertTrue(b.ensure_session())
        # three failures spanning >= 60s (two 72s timeouts then a 500) => wedged
        self.script = ["timeout", "timeout", "exit1"]
        for _ in range(3):
            self.now[0] += 72
            ans, _ = b.decide("q", timeout_s=90)
            self.assertIsNone(ans)
        self.assertIsNone(b.session_id, "wedge must drop the resumed session")
        self.assertTrue(b._rejoin_pending)
        # next decision: fresh init (no --resume), then the decision with the note
        n = len(self.calls)
        ans, _ = b.decide("DECISION seq=9", timeout_s=90)
        self.assertEqual(ans, {"chosenId": 0})
        init_argv, init_prompt = self.calls[n]
        dec_argv, dec_prompt = self.calls[n + 1]
        self.assertNotIn("--resume", init_argv)
        self.assertIn("--resume", dec_argv)
        self.assertEqual(dec_argv[dec_argv.index("--resume") + 1], "sess-B")
        self.assertTrue(dec_prompt.startswith(brain_mod.REJOIN_NOTE))
        self.assertIn("DECISION seq=9", dec_prompt)
        self.assertFalse(b._rejoin_pending)
        # the note is one-shot
        ans, _ = b.decide("DECISION seq=10", timeout_s=90)
        self.assertFalse(self.calls[-1][1].startswith(brain_mod.REJOIN_NOTE))

    def test_hard_fail_count_wedges_regardless_of_time(self):
        b = self._brain()
        self.assertTrue(b.ensure_session())
        self.script = ["exit1"] * brain_mod.WEDGE_HARD_FAILS
        for _ in range(brain_mod.WEDGE_HARD_FAILS):
            self.now[0] += 1
            b.decide("q", timeout_s=60)
        self.assertIsNone(b.session_id)

    def test_nonzero_exit_logs_stdout(self):
        lines = []
        b = SeatBrain(1, DECK, model="opus", effort="low", log=lines.append)
        self.assertTrue(b.ensure_session())
        self.script = ["exit1"]
        b.decide("q", timeout_s=60)
        self.assertTrue(any("API Error: 500" in l for l in lines),
                        "the stdout envelope text must reach the seat log")


if __name__ == "__main__":
    unittest.main()

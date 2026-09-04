"""Interactive plan item 2 (2026-09-03): the decision budget is ONE clock.
`decide()` takes the engine's deadline; init and the decision call each get
what REMAINS of it. Before: `ensure_session` got the budget and `_call` got
the ORIGINAL budget again, so a lazy re-init could block the single-threaded
seat loop for 2x the window while the engine timed out around it.
Run: python3 -m unittest discover -s tests"""
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


class BudgetDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.calls = []            # (timeout passed to subprocess, was_init)
        self.init_takes = [0.0]    # simulated wall time the init call burns
        self.now = [1000.0]
        orig_run, orig_time = brain_mod.subprocess.run, brain_mod.time.time

        def fake_run(cmd, **kw):
            is_init = "--resume" not in cmd
            self.calls.append((kw.get("timeout"), is_init))
            if is_init:
                self.now[0] += self.init_takes[0]
            else:
                self.now[0] += 1.0
            return Proc(envelope("sess-A"))

        brain_mod.subprocess.run = fake_run
        brain_mod.time.time = lambda: self.now[0]
        self.addCleanup(lambda: setattr(brain_mod.subprocess, "run", orig_run))
        self.addCleanup(lambda: setattr(brain_mod.time, "time", orig_time))

    def _brain(self):
        return SeatBrain(1, DECK, model="opus", effort="low", log=lambda *a: None)

    def test_init_and_call_share_one_deadline(self):
        b = self._brain()
        self.init_takes[0] = 50.0
        deadline = self.now[0] + 72.0
        ans, _ = b.decide("q", deadline=deadline)
        self.assertEqual(ans, {"chosenId": 0})
        self.assertEqual(len(self.calls), 2, "init then decision")
        init_to, dec_to = self.calls[0][0], self.calls[1][0]
        self.assertLessEqual(init_to, 72.0 - 5.0 + 1e-6,
                             "init may use the window minus the call floor")
        self.assertLessEqual(dec_to, 72.0 - 50.0 + 1e-6,
                             "the decision call gets only what is LEFT after init")
        self.assertLessEqual(self.now[0], deadline + 1e-6,
                             "the answer landed before the engine's deadline")

    def test_init_that_eats_the_window_punts_on_time(self):
        b = self._brain()
        self.init_takes[0] = 70.0
        deadline = self.now[0] + 72.0
        ans, _ = b.decide("q", deadline=deadline)
        self.assertIsNone(ans, "under the call floor -> safe default, no model call")
        self.assertEqual(len(self.calls), 1, "no decision call was attempted")
        self.assertTrue(b.session_id, "the session stays warm for the next decision")

    def test_warm_session_gets_the_whole_remaining_window(self):
        b = self._brain()
        b.session_id = "sess-A"          # already initialised
        deadline = self.now[0] + 72.0
        ans, _ = b.decide("q", deadline=deadline)
        self.assertEqual(ans, {"chosenId": 0})
        self.assertEqual(len(self.calls), 1)
        self.assertAlmostEqual(self.calls[0][0], 72.0, places=6)

    def test_legacy_duration_form_still_works(self):
        b = self._brain()
        b.session_id = "sess-A"
        ans, _ = b.decide("q", timeout_s=30.0)
        self.assertEqual(ans, {"chosenId": 0})
        self.assertAlmostEqual(self.calls[0][0], 30.0, places=6)

    def test_no_fixed_cap_on_long_timeout_games(self):
        b = self._brain()
        b.session_id = "sess-A"
        deadline = self.now[0] + 300.0
        b.decide("q", deadline=deadline)
        self.assertAlmostEqual(self.calls[0][0], 300.0, places=6,
                               msg="the old 240s literal is gone; the engine's timeout rules")


if __name__ == "__main__":
    unittest.main()

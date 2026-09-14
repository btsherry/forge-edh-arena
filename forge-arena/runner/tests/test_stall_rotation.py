"""B3 / W-18 (hardening plan 2026-09-14): two consecutive persistent-call timeouts
with no answered call between them rotate the session at once — a fresh session
carrying the game record — instead of re-resuming a process that is not coming
back until WEDGE_FAILS drops the memory. Driven through the runner with a fake
transport whose every call is a deadline kill and a spawn retry that also times
out. Run: python3 -m unittest discover -s tests"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import seatd.brain as brain_mod  # noqa: E402
from seatd.runner import SeatRunner  # noqa: E402

ENVELOPE = {"type": "result", "result": '{"chosenId": 0, "why": "hold"}', "session_id": "s-old",
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 5}}


class FakePersistent:
    """The long-lived transport: every call is a deadline kill until `ok` is set."""
    ok = False
    made = []

    def __init__(self, cmd_base, session_id, cwd, log, stderr_path=None):
        self.cmd = list(cmd_base); self.session_id = session_id; self.log = log
        self.proc = None; self.turns = 0; self.last_timeout = False; self._alive = False
        FakePersistent.made.append(self)

    def alive(self):
        return self._alive

    def start(self):
        self._alive = True
        return True

    def kill(self):
        self._alive = False

    def call(self, prompt, timeout_s):
        self.last_timeout = False
        if FakePersistent.ok:
            self.turns += 1
            return dict(ENVELOPE)
        self.last_timeout = True     # what the real call() does before killing the process
        self.kill()
        return None


def _spawn_times_out(cmd, *, input, timeout, cwd, on_child=None):
    raise subprocess.TimeoutExpired(cmd, timeout)


def _req(seq):
    return {"seq": seq, "turn": 3, "phase": "MAIN1", "decisionType": "CAST_SPELL", "gameId": "g1",
            "options": [{"id": 0, "label": "Pass (do nothing)"}, {"id": 1, "label": "Sol Ring {1}"}],
            "state": {"stack": [], "manaPool": 0, "untappedManaSourceCount": 3, "life": 40}}


class StallRotation(unittest.TestCase):
    def setUp(self):
        self._orig = (brain_mod.PersistentClaude, brain_mod._run)
        brain_mod.PersistentClaude, brain_mod._run = FakePersistent, _spawn_times_out
        FakePersistent.ok = False; FakePersistent.made = []
        tmp = Path(tempfile.mkdtemp(prefix="stall-"))
        self.r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"), timeout_s=30.0)
        self.r.brain.session_id = "s-old"
        self.r.brain.persistent_enabled = True      # the suite pins ARENA_BRAIN_TRANSPORT=spawn at import
        self.r.mb.respond = lambda req, ans: True
        self.r._fastpath = lambda req: None         # this is about the transport, not the fastpaths
        self.rotations = []
        self.r.brain.rotate = lambda text, timeout_s=120.0: self.rotations.append(text) or True
        self.events = tmp / "logs" / "transport-events.jsonl"

    def tearDown(self):
        brain_mod.PersistentClaude, brain_mod._run = self._orig

    def _rotate_events(self):
        rows = [json.loads(l) for l in self.events.read_text().splitlines()] if self.events.exists() else []
        return [e for e in rows if e.get("kind") == "rotate"]

    def test_second_consecutive_stall_rotates_with_the_reason_recorded(self):
        r = self.r
        r.handle(_req(1))
        self.assertEqual(r.brain.stalls, 1)
        self.assertEqual(self.rotations, [], "one stall: the process restarts on --resume, no rotation")
        self.assertEqual(self._rotate_events(), [])
        r.handle(_req(2))
        self.assertEqual(r.brain.stalls, 2)
        self.assertEqual(len(self.rotations), 1, "the second back-to-back stall rotates")
        ev = self._rotate_events()
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["reason"], ev[0]["seat"], ev[0]["gameId"]), ("stall-x2", 2, "g1"))
        self.assertTrue(any("stall-x2" in l for l in r._game_log.parent.joinpath("seat-2.log").read_text().splitlines()))
        # both windows were answered on time with the safe default, as punts
        rows = [json.loads(l) for l in r._game_log.read_text().splitlines()]
        self.assertEqual([x["source"] for x in rows], ["punt", "punt"])
        self.assertEqual(r.brain.wedges, 0, "rotation, not the wedge path: the game record is kept")

    def test_an_answered_call_between_two_stalls_resets_the_count(self):
        r = self.r
        r.handle(_req(1))
        self.assertEqual(r.brain.stalls, 1)
        FakePersistent.ok = True
        r.handle(_req(2))
        self.assertEqual(r.brain.stalls, 0, "an answer in between: the streak restarts")
        FakePersistent.ok = False
        r.handle(_req(3))
        self.assertEqual((r.brain.stalls, self.rotations), (1, []), "one stall again, no rotation")

    def test_a_forced_rotation_ignores_the_token_caps_and_a_capped_one_names_its_reason(self):
        r = self.r
        r.rotate_at, r.rotate_hard = 250_000, 600_000
        r.brain.last_prompt_tokens = 1_000
        self.assertFalse(r._maybe_rotate(), "under the cap")
        self.assertTrue(r._maybe_rotate(hard=True, reason="stall-x2"), "a reason forces it")
        r.brain.last_prompt_tokens = 300_000
        self.assertTrue(r._maybe_rotate())
        self.assertEqual([e["reason"] for e in self._rotate_events()], ["stall-x2", "turn-boundary"])
        r.brain.session_id = None
        self.assertFalse(r._maybe_rotate(hard=True, reason="stall-x2"), "no session: nothing to rotate")


class BrainRotateResetsTheStreaks(unittest.TestCase):
    def test_rotate_clears_stalls_and_the_failure_streak(self):
        tmp = Path(tempfile.mkdtemp(prefix="stall2-"))
        r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))
        b = r.brain
        b.session_id = "s-old"; b.stalls = 2; b._fail_streak = 2; b._fail_streak_t0 = 1.0
        b._call = lambda prompt, timeout_s, resume, **k: {"session_id": "s-new", "usage": {"input_tokens": 7}}
        self.assertTrue(b.rotate("RECORD"))
        self.assertEqual((b.session_id, b.stalls, b._fail_streak, b._fail_streak_t0), ("s-new", 0, 0, None))


if __name__ == "__main__":
    unittest.main()

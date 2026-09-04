"""Round-two cleanup (2026-09-04), brain side: BL-27 extract_json survives
mana symbols in prose; BL-28 the CLI child is tracked and killable, and the
seat's signal handler kills it and exits; BL-24 argv is pinned by the golden
test. Run: python3 -m unittest discover -s tests"""
import signal
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seatd import brain as brain_mod  # noqa: E402
import seat_runner  # noqa: E402


class ExtractJson(unittest.TestCase):
    def test_mana_symbols_before_the_answer(self):
        t = ('I can pay {G}{2}{W} for this and keep {U} floating, so '
             '{"chosenId": 3, "why": "tempo"}')
        self.assertEqual(brain_mod.extract_json(t), {"chosenId": 3, "why": "tempo"})

    def test_brace_noise_after_the_answer(self):
        t = '{"chosen": [1, 2]} — leaving {R} up for Lightning Bolt {R}'
        self.assertEqual(brain_mod.extract_json(t), {"chosen": [1, 2]})

    def test_arrays_and_garbage_are_not_answers(self):
        self.assertIsNone(brain_mod.extract_json("[1, 2, 3]"))
        self.assertIsNone(brain_mod.extract_json("{G} {W} nothing here"))
        self.assertIsNone(brain_mod.extract_json(""))

    def test_plain_and_fenced_still_work(self):
        self.assertEqual(brain_mod.extract_json('{"keep": true}'), {"keep": True})
        self.assertEqual(brain_mod.extract_json('```json\n{"keep": false}\n```'), {"keep": False})


class TrackedChild(unittest.TestCase):
    def test_timeout_kills_the_child_and_raises(self):
        seen = []
        cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
        with self.assertRaises(subprocess.TimeoutExpired):
            brain_mod._run(cmd, input="", timeout=0.3, cwd=None, on_child=seen.append)
        self.assertIsNotNone(seen[0], "child reported on start")
        self.assertIsNone(seen[-1], "child cleared on exit")
        self.assertIsNotNone(seen[0].returncode, "child is dead, not orphaned")

    def test_completed_process_contract(self):
        cmd = [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"]
        proc = brain_mod._run(cmd, input="ok", timeout=10, cwd=None)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "OK")

    def test_kill_child_is_safe_with_and_without_a_child(self):
        class FakeBrain:
            pass
        b = brain_mod.SeatBrain.__new__(brain_mod.SeatBrain)
        b._child = None
        b.kill_child()                      # no child: no-op

        class Child:
            killed = False

            def kill(self):
                self.killed = True
        c = Child()
        b._track_child(c)
        b.kill_child()
        self.assertTrue(c.killed)


class SignalHandler(unittest.TestCase):
    def test_sigterm_kills_child_and_exits(self):
        class B:
            killed = 0

            def kill_child(self):
                self.killed += 1

        class R:
            brain = B()
        r = R()
        old_term, old_int = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
        try:
            seat_runner.install_signal_handlers(r)
            handler = signal.getsignal(signal.SIGTERM)
            with self.assertRaises(SystemExit) as cm:
                handler(signal.SIGTERM, None)
            self.assertEqual(cm.exception.code, 128 + signal.SIGTERM)
            self.assertEqual(r.brain.killed, 1)
        finally:
            signal.signal(signal.SIGTERM, old_term)
            signal.signal(signal.SIGINT, old_int)


if __name__ == "__main__":
    unittest.main()

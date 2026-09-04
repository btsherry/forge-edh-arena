"""arena-autostop.sh (Ben, 2026-09-04): a table that has clearly concluded is
torn down without a hand stop. The watcher waits for the engine's gameOver
flag in the observer snapshot (or the GUI JVM's PID to vanish), lingers, and
runs the stop command; a table already stopped by hand is left alone.
Exercised through the script's env hooks against a temp tree, with a stub
stop command that leaves a marker file.
Run: python3 -m unittest discover -s tests"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "arena-autostop.sh"


class AutostopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.state = d / "observer-state.json"
        self.gui_pid = d / "gui.pid"
        self.own_pid = d / "autostop.pid"
        self.mark = d / "stopped.marker"
        self.stop = d / "stop.sh"
        self.stop.write_text("#!/bin/sh\necho stopped > \"$ARENA_AUTOSTOP_TEST_MARK\"\nexit 0\n")
        self.stop.chmod(0o755)
        self.own_pid.write_text("12345")
        self.env = dict(os.environ,
                        ARENA_AUTOSTOP_STATE=str(self.state),
                        ARENA_AUTOSTOP_GUI_PID_FILE=str(self.gui_pid),
                        ARENA_AUTOSTOP_PID_FILE=str(self.own_pid),
                        ARENA_AUTOSTOP_STOP=str(self.stop),
                        ARENA_AUTOSTOP_POLL="0.2",
                        ARENA_AUTOSTOP_GUI_GONE_LINGER="0",
                        ARENA_AUTOSTOP_TEST_MARK=str(self.mark))

    def tearDown(self):
        self.tmp.cleanup()

    def _snapshot(self, over):
        tmp = self.state.with_suffix(".tmp")
        tmp.write_text(json.dumps({"kind": "observer-snapshot", "turn": 9, "gameOver": over}))
        os.replace(tmp, self.state)

    def _run(self, linger="0"):
        return subprocess.Popen(["sh", str(SCRIPT), linger], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def test_game_over_lingers_then_runs_the_stop_command(self):
        self._snapshot(False)
        self.gui_pid.write_text(str(os.getpid()))          # a live "JVM"
        p = self._run(linger="1")
        time.sleep(0.6)
        self.assertIsNone(p.poll(), "still waiting while the game is on")
        self.assertFalse(self.mark.exists())
        self._snapshot(True)
        out, _ = p.communicate(timeout=12)
        self.assertEqual(p.returncode, 0, out)
        self.assertTrue(self.mark.exists(), out)
        self.assertIn("match over", out)
        self.assertIn("stopping in 1s", out)
        self.assertFalse(self.own_pid.exists(), "its own PID file goes before it becomes arena-stop")

    def test_gui_jvm_gone_before_game_over_stops_the_table(self):
        self._snapshot(False)
        self.gui_pid.write_text("2147483000")              # no such process
        p = self._run()
        out, _ = p.communicate(timeout=12)
        self.assertEqual(p.returncode, 0, out)
        self.assertTrue(self.mark.exists(), out)
        self.assertIn("GUI JVM gone", out)

    def test_table_already_stopped_is_left_alone(self):
        # arena-stop cleared the snapshot and every PID file: nothing to do
        p = self._run()
        out, _ = p.communicate(timeout=12)
        self.assertEqual(p.returncode, 0, out)
        self.assertFalse(self.mark.exists(), "a hand stop always wins — no second stop")
        self.assertIn("already stopped", out)
        self.assertFalse(self.own_pid.exists())

    def test_hand_stop_during_the_linger_means_no_second_stop(self):
        self._snapshot(True)
        self.gui_pid.write_text(str(os.getpid()))
        p = self._run(linger="2")
        time.sleep(0.8)
        self.state.unlink()                                 # what arena-stop does
        self.gui_pid.unlink()
        out, _ = p.communicate(timeout=12)
        self.assertEqual(p.returncode, 0, out)
        self.assertFalse(self.mark.exists(), out)
        self.assertIn("stopped by someone else", out)

    def test_linger_must_be_a_whole_number(self):
        p = subprocess.run(["sh", str(SCRIPT), "soon"], env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=10)
        self.assertEqual(p.returncode, 2, p.stdout)
        self.assertIn("whole number", p.stdout)

    def test_before_the_match_is_live_the_watcher_keeps_waiting(self):
        # snapshot not yet written but the GUI PID is alive: launch in progress
        self.gui_pid.write_text(str(os.getpid()))
        p = self._run()
        time.sleep(0.7)
        try:
            self.assertIsNone(p.poll(), "no snapshot + live JVM is 'not started yet', not 'stopped'")
        finally:
            p.kill()
            p.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()

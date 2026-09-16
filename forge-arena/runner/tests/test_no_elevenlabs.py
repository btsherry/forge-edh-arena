"""Step 10 of the release plan (Ben, 2026-09-16): the table without ElevenLabs. Two conditions —
no key at all (the distributed case: every seat line, atom, heckle and deal line is a baked take and
must play; Joshua's live lines fall to stock or a record, never a hang) and a key present with the API
down (the render must fail fast, be recorded once per failure, and never stall the queue).
Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import time
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import voice_runner as vr  # noqa: E402
from test_table_lines import _TableCase  # noqa: E402


def _play_a_game(case, r):
    """A short synthetic game through the real scan/step paths with the fake clock: the deal, a cast,
    a big attack, a death, an advice line, game over. Returns the longest step in fake seconds."""
    longest = 0.0
    def step():
        nonlocal longest
        t0 = time.monotonic()
        r.step()                                        # the daemon's own step: scans, patter, one line, the final marker
        longest = max(longest, time.monotonic() - t0)
    case._snap(1, 2); step(); case.clock.t += 6
    case._snap(2, 1, events=[{"seq": 1, "kind": "cast", "turn": 2, "seat": 1, "spell": "Sol Ring", "cmc": 1}]); step(); case.clock.t += 6
    with (case.logs / "advisor-0.jsonl").open("a") as f:
        f.write(json.dumps({"ts": time.time(), "kind": "advice", "seq": 9, "turn": 2, "text": "Hold the counterspell for the Rhystic Study."}) + "\n")
    step(); case.clock.t += 6; step(); case.clock.t += 6
    case._snap(3, 3, events=[{"seq": 2, "kind": "attack", "turn": 3, "seat": 3, "defenders": [0], "power": 9}]); step(); case.clock.t += 6
    seats = [case._seat(0), case._seat(1), case._seat(3)]                                    # seat 2 vanished
    (case.mailbox / "observer-state.json").write_text(json.dumps({"turn": 4, "phase": "MAIN1", "activeSeat": 1, "gameOver": False,
                                                                     "seats": seats, "events": [], "stackDetail": []}))
    step(); case.clock.t += 6; step(); case.clock.t += 6
    (case.mailbox / "observer-state.json").write_text(json.dumps({"turn": 4, "phase": "MAIN1", "activeSeat": 1, "gameOver": True, "winner": "s1",
                                                                     "seats": seats, "events": [{"seq": 3, "kind": "gameover", "turn": 4, "winner": 1}], "stackDetail": []}))
    for _ in range(6):
        step(); case.clock.t += 6
    return longest


class NoKey(_TableCase):
    def setUp(self):
        self._saved = os.environ.pop("ELEVENLABS_API_KEY", None)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        if self._saved is not None:
            os.environ["ELEVENLABS_API_KEY"] = self._saved

    def test_everything_runs_and_barks_on_stock_takes_alone(self):
        r = self.r
        self.assertFalse(r.renderer.live, "no key: live rendering is off")
        longest = _play_a_game(self, r)
        self.assertLess(longest, 2.0, f"no step waited on a render: {longest:.2f}s")
        spoke = self._records("spoke")
        self.assertTrue(any(x["kind"] == "bark" for x in spoke), "the seats spoke from stock takes")
        self.assertTrue(any(x["stock"] in ("eliminated", "player-eliminated") for x in spoke), "the death was voiced")
        self.assertTrue(any(x["kind"] == "game_over" for x in spoke), "the game-over trio played")
        advice = [x for x in self._records("skipped", "advice")]
        self.assertTrue(advice and all("no audio" in x["why"] for x in advice), "Joshua's live line is skipped with a record, not a hang")
        self.assertEqual([x for x in self._records("render-failed")], [], "nothing was even attempted live")
        self.assertTrue((self.mailbox / "seat-0-voice" / "final.json").exists(), "the watcher may tear down")


class KeyButApiDown(_TableCase):
    def setUp(self):
        super().setUp()                                  # the fixture scrubs the key from the environment; give the renderer one directly
        self.r.renderer.api_key = "sk-test-not-a-real-key"
        self._orig = vr.urllib.request.urlopen
        def down(req, timeout=30):
            raise urllib.error.URLError("connection refused (test: the API is down)")
        vr.urllib.request.urlopen = down

    def tearDown(self):
        vr.urllib.request.urlopen = self._orig
        super().tearDown()

    def test_a_dead_api_fails_fast_is_recorded_and_the_table_keeps_talking(self):
        r = self.r
        self.assertTrue(r.renderer.live, "a key is set: the runner will try to render Joshua's line")
        longest = _play_a_game(self, r)
        self.assertLess(longest, 5.0, f"a failed render never stalls the queue: {longest:.2f}s")
        failed = self._records("render-failed")
        self.assertGreaterEqual(len(failed), 1, "the failure is recorded")
        self.assertTrue(any(x["kind"] == "bark" for x in self._records("spoke")), "the seats kept talking on stock takes")
        self.assertTrue(any(x["kind"] == "game_over" for x in self._records("spoke")), "the ending played")
        self.assertTrue((self.mailbox / "seat-0-voice" / "final.json").exists())


if __name__ == "__main__":
    unittest.main()

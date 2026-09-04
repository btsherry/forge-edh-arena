"""Interactive plan item 5 (2026-09-03): the advisor's lifecycle logic.

- Feed file numbers were never monotonic (chosen-<n> reuses its request's
  number; digests/notes take fresh ones), so "oldest number < last seen"
  fired on ordinary interleaving and dropped the Claude session mid-game.
  A stamped feed resets on a gameId CHANGE only.
- Resume after a pause consumes the backlog quietly: no stale notes streamed,
  no advice on stale requests, context kept; one announcement.
- A new game re-arms the frequency governor (gov_turn/gov_budget), so a
  second game in one process gets advice past the mulligan.
Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import advisor_runner as ar  # noqa: E402


class FakeBrain:
    def __init__(self, *a, **kw):
        self.deck, self.model, self.effort = "giada-font-of-hope", "opus", "low"
        self.session_id = "sess-1"
        self.totals = {"calls": 0}
        self.resets = 0
        self.decisions = []

    def reset(self):
        self.resets += 1

    def ensure_session(self, *a, **kw):
        return True

    def decide(self, prompt, timeout=None, **kw):
        self.decisions.append(prompt)
        return {}, {"raw": "advice text", "latency_s": 0.1}


class AdvisorLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain = FakeBrain
        ar.opponent_deck_sections = lambda *a, **kw: []
        self.r = ar.AdvisorRunner("giada-font-of-hope", base, "opus", "low", 30.0,
                                  log_dir=base / "logs")
        self.r.inbox.mkdir(parents=True)
        self.r.RANDOM_ADMIT_P = 1.0   # deterministic admission for these tests

    def tearDown(self):
        ar.SeatBrain, ar.opponent_deck_sections = self._orig
        self.tmp.cleanup()

    def _write(self, kind, n, body):
        body = dict(body)
        body.setdefault("seq", n)
        (self.r.inbox / f"{kind}-{n}.json").write_text(json.dumps(body))

    def _req(self, n, turn, gid="g1"):
        self._write("req", n, {"gameId": gid, "turn": turn, "phase": "MAIN1",
                               "decisionType": "PRIORITY", "prompt": "act or pass",
                               "state": {}, "options": []})

    def test_interleaved_numbers_in_one_game_do_not_reset(self):
        self._req(7, 3)
        self._write("digest", 9, {"gameId": "g1", "turn": 2, "digest": ["a", "b"]})
        self.r._process(self.r._scan())
        self._write("chosen", 7, {"gameId": "g1", "decisionType": "PRIORITY", "chosen": "pass"})
        self.r._process(self.r._scan())
        self.assertEqual(self.r.brain.resets, 0, "7 after 9 is ordinary interleaving, not a new game")
        self.assertEqual(self.r.game_id, "g1")

    def test_game_id_change_resets_and_rearms_the_governor(self):
        self._req(40, 25)
        self.r._process(self.r._scan())
        self.assertEqual(self.r.gov_turn, 25)
        self._req(1, 1, gid="g2")
        self.r._process(self.r._scan())
        self.assertEqual(self.r.brain.resets, 1)
        self.assertEqual(self.r.game_id, "g2")
        self.assertEqual(self.r.gov_turn, 1, "the governor re-armed for the new game's turn 1")
        self.assertEqual(len(self.r.brain.decisions), 2, "turn 1 of game 2 was advised")

    def test_resume_consumes_backlog_quietly(self):
        self._write("note", 3, {"gameId": "g1", "turn": 4, "phase": "MAIN1", "note": "(auto-passed)"})
        self._write("chosen", 2, {"gameId": "g1", "decisionType": "PRIORITY", "chosen": "pass"})
        self._write("digest", 4, {"gameId": "g1", "turn": 4, "digest": ["x"]})
        self._req(5, 5)
        n = self.r._process(self.r._scan(), quiet=True)
        self.assertEqual(n, 4)
        self.assertEqual(self.r.brain.decisions, [], "no advice on a stale backlog")
        stream = self.r._stream.read_text() if self.r._stream.exists() else ""
        self.assertNotIn("(auto-passed)", stream, "stale notes are not streamed on resume")
        self.assertTrue(any("the human chose" in c for c in self.r.pending_context))
        self.assertTrue(any("turn 4 public log" in c for c in self.r.pending_context))
        kinds = [json.loads(l)["kind"] for l in self.r._jsonl.read_text().splitlines()]
        self.assertIn("skipped_backlog", kinds)
        self.assertEqual(list(self.r.inbox.iterdir()), [], "backlog consumed")

    def test_unstamped_feed_keeps_seq_heuristic_on_monotonic_kinds_only(self):
        self._write("req", 9, {"turn": 3, "phase": "MAIN1", "decisionType": "PRIORITY",
                               "prompt": "x", "state": {}, "options": []})
        self.r._process(self.r._scan())
        self._write("chosen", 7, {"decisionType": "PRIORITY", "chosen": "pass"})
        self.r._process(self.r._scan())
        self.assertEqual(self.r.brain.resets, 0, "a chosen file never signals a new game")
        self._write("req", 1, {"turn": 1, "phase": "MAIN1", "decisionType": "PRIORITY",
                               "prompt": "x", "state": {}, "options": []})
        self.r._process(self.r._scan())
        self.assertEqual(self.r.brain.resets, 1, "an unstamped req regression still does")


if __name__ == "__main__":
    unittest.main()

"""Ask the advisor (Ben, 2026-09-04): the Advisor tab's field writes
logs/control/ask/ask-<millis>-<serial>.json; the runner answers each with one
direct call, streams [you]/[advisor] lines, records `ask`, and deletes the
file on pickup (the panel's "sent" signal). Questions are handled before the
pause gate — a paused advisor still answers a typed question.
Run: python3 -m unittest discover -s tests"""
import inspect
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import advisor_runner as ar  # noqa: E402


class FakeBrain:
    def __init__(self, *a, **kw):
        self.deck, self.model, self.effort = "giada-font-of-hope", "opus", "low"
        self.totals = {"calls": 0}
        self.decisions = []
        self.reply = "Hold it — the flyers are the real threat."

    def reset(self):
        pass

    def ensure_session(self, *a, **kw):
        return True

    def decide(self, prompt, timeout=None, **kw):
        self.decisions.append(prompt)
        return {}, {"raw": self.reply, "latency_s": 0.2}


class AdvisorAskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain = FakeBrain
        ar.opponent_deck_sections = lambda *a, **kw: []
        self.r = ar.AdvisorRunner("giada-font-of-hope", base, "opus", "low", 30.0,
                                  log_dir=base / "logs")
        self.r.inbox.mkdir(parents=True)
        self.asks = base / "logs" / "control" / "ask"
        self.asks.mkdir(parents=True)

    def tearDown(self):
        ar.SeatBrain, ar.opponent_deck_sections = self._orig
        self.tmp.cleanup()

    def _ask(self, name, body):
        p = self.asks / name
        p.write_text(body if isinstance(body, str) else json.dumps(body))
        return p

    def _stream(self):
        return self.r._stream.read_text() if self.r._stream.exists() else ""

    def _records(self, kind):
        if not self.r._jsonl.exists():
            return []
        out = []
        for line in self.r._jsonl.read_text().splitlines():
            rec = json.loads(line)
            if rec.get("kind") == kind:
                out.append(rec)
        return out

    def _asked(self, prompt):
        return prompt.split("ASKS: ")[1].split("\n")[0]

    def test_question_is_answered_streamed_recorded_and_consumed(self):
        (self.r.inbox / "req-3.json").write_text(json.dumps(
            {"gameId": "g1", "seq": 3, "turn": 12, "phase": "MAIN1", "decisionType": "PRIORITY",
             "prompt": "act", "state": {}, "options": []}))
        self.r._process(self.r._scan(), quiet=True)   # sets the turn label without advising
        p = self._ask("ask-1700000000000-001.json", {"ask": "Should I attack with everything?", "ts": 1})
        self.assertEqual(self.r._handle_asks(), 1)
        self.assertFalse(p.exists(), "the file is deleted on pickup — that is the panel's 'sent' signal")
        self.assertEqual(len(self.r.brain.decisions), 1)
        self.assertIn("THE HUMAN AT YOUR SEAT ASKS: Should I attack with everything?",
                      self.r.brain.decisions[0])
        s = self._stream()
        self.assertIn("[t12 · you] Should I attack with everything?", s)
        self.assertIn("[t12 · advisor] Hold it — the flyers are the real threat.", s)
        rec = self._records("ask")
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0]["text"], "Should I attack with everything?")
        self.assertEqual(rec[0]["answer"], self.r.brain.reply)
        self.assertEqual(rec[0]["turn"], 12)

    def test_pending_context_folds_into_the_question_once(self):
        self.r._push_context("- the human chose \"pass\" for PRIORITY (seq 3)")
        self._ask("ask-1700000000000-001.json", {"ask": "why did that matter?"})
        self.r._handle_asks()
        self.assertIn("SINCE LAST TIME:", self.r.brain.decisions[0])
        self.assertEqual(self.r.pending_context, [], "context is consumed by the call that used it")

    def test_questions_answer_in_numeric_send_order(self):
        # sorted by (millis, serial) as integers, never lexically
        self._ask("ask-1700000000001-002.json", {"ask": "second"})
        self._ask("ask-1700000000000-010.json", {"ask": "first"})
        self._ask("ask-1700000000001-003.json", {"ask": "third"})
        self.assertEqual(self.r._handle_asks(), 3)
        self.assertEqual([self._asked(d) for d in self.r.brain.decisions],
                         ["first", "second", "third"])

    def test_malformed_or_empty_questions_are_dropped_not_re_read(self):
        self._ask("ask-1700000000000-001.json", "{not json")       # torn/partial write
        self._ask("ask-1700000000000-002.json", {"ask": "   "})     # blank
        self._ask("ask-1700000000000-003.json", {"nope": 1})        # wrong key
        self._ask("ask-1700000000000-004.json", {"ask": 42})        # wrong type
        self.assertEqual(self.r._handle_asks(), 0)
        self.assertEqual(self.r.brain.decisions, [])
        # the unparseable one is left for the next poll (it may still be being
        # written); the parseable-but-useless ones are consumed and recorded
        self.assertEqual(sorted(p.name for p in self.asks.iterdir()),
                         ["ask-1700000000000-001.json"])
        self.assertEqual(len(self._records("ask_rejected")), 3)

    def test_long_question_is_capped_and_whitespace_collapsed(self):
        self._ask("ask-1700000000000-001.json", {"ask": "a  b\n\nc " + "x" * 900})
        self.r._handle_asks()
        asked = self._asked(self.r.brain.decisions[0])
        self.assertTrue(asked.startswith("a b c xxx"))
        self.assertEqual(len(asked), ar.ASK_MAX_CHARS)

    def test_empty_reply_is_said_not_swallowed(self):
        self.r.brain.reply = ""
        self._ask("ask-1700000000000-001.json", {"ask": "hello?"})
        self.r._handle_asks()
        self.assertIn("[t? · advisor] (no answer", self._stream())

    def test_missing_ask_dir_is_quiet(self):
        shutil.rmtree(self.asks)
        self.assertEqual(self.r._handle_asks(), 0)

    def test_asks_run_before_the_pause_gate_in_the_main_loop(self):
        # Structural pin: run() consults the asks before it reads the pause
        # toggle, so a paused advisor still answers a typed question.
        src = inspect.getsource(ar.AdvisorRunner.run)
        self.assertLess(src.index("self._handle_asks()"), src.index("self._toggle_enabled()"))


if __name__ == "__main__":
    unittest.main()

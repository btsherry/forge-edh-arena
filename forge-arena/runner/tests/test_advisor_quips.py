"""Voice quips (2026-09-07): the advisor may end a line with one [quip:<id>]
tag from a closed vocabulary; the tag leaves the panel text and becomes its
own `quip` record for the voice runner. The human's choices are recorded too
(so stale advice is never spoken).
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
        self.reply = "Hold the Boots until Urza taps out. [quip:calculating]"

    def reset(self):
        pass

    def ensure_session(self, *a, **kw):
        return True

    def decide(self, prompt, timeout=None, **kw):
        self.last_prompt = prompt
        return {}, {"raw": self.reply, "latency_s": 0.1}


class QuipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain = FakeBrain
        ar.opponent_deck_sections = lambda *a, **kw: []
        self.r = ar.AdvisorRunner("giada-font-of-hope", base, "opus", "low", 30.0, log_dir=base / "logs")
        self.r.inbox.mkdir(parents=True)
        self.r.RANDOM_ADMIT_P = 1.0

    def tearDown(self):
        ar.SeatBrain, ar.opponent_deck_sections = self._orig
        self.tmp.cleanup()

    def _records(self, kind):
        return [json.loads(l) for l in self.r._jsonl.read_text().splitlines() if json.loads(l).get("kind") == kind]

    def test_split_quip_strips_known_tags_and_drops_unknown_ones(self):
        self.assertEqual(ar.split_quip("Good line. [quip:ouch]"), ("Good line.", "ouch"))
        self.assertEqual(ar.split_quip("Good line. [quip:not-a-thing]"), ("Good line.", None))
        self.assertEqual(ar.split_quip("No tag here."), ("No tag here.", None))
        self.assertEqual(ar.split_quip("Mid [quip:hello] sentence."), ("Mid sentence.", "hello"))

    def test_advice_prompt_offers_the_vocabulary_and_the_tag_becomes_a_quip_record(self):
        (self.r.inbox / "req-3.json").write_text(json.dumps(
            {"gameId": "g1", "seq": 3, "turn": 5, "phase": "MAIN1", "decisionType": "PRIORITY",
             "prompt": "act", "state": {}, "options": []}))
        self.r._process(self.r._scan())
        self.assertIn("[quip:calculating]", self.r.brain.last_prompt)
        self.assertIn("at most once per game", self.r.brain.last_prompt)
        adv = self._records("advice")
        self.assertEqual(adv[0]["text"], "Hold the Boots until Urza taps out.", "the tag never reaches the panel")
        self.assertNotIn("[quip", self.r._stream.read_text())
        q = self._records("quip")
        self.assertEqual((q[0]["id"], q[0]["turn"], q[0]["with"], q[0]["seq"]), ("calculating", 5, "advice", 3))

    def test_commentary_carries_quips_too(self):
        self.r.brain.reply = "Purphoros just dealt twelve. [quip:ouch]"
        (self.r.inbox / "digest-9.json").write_text(json.dumps({"gameId": "g1", "seq": 9, "turn": 6, "digest": ["a", "b"]}))
        self.r._process(self.r._scan())
        self.assertEqual(self._records("color")[0]["text"], "Purphoros just dealt twelve.")
        self.assertEqual(self._records("quip")[0]["with"], "color")

    def test_the_humans_choice_is_recorded_for_the_voice_runner(self):
        (self.r.inbox / "chosen-3.json").write_text(json.dumps({"gameId": "g1", "seq": 3, "decisionType": "PRIORITY", "chosen": "pass"}))
        self.r._process(self.r._scan())
        self.assertEqual(self._records("chosen")[0]["seq"], 3)


if __name__ == "__main__":
    unittest.main()

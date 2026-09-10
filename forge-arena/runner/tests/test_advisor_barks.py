"""Seat barks, advisor side (experimental/voicework2, 2026-09-10): the advisor's
advice and colour prompts offer a closed [bark:<seat>:<id>] vocabulary with each
seat's voice and temperament; a tag in the reply leaves the panel text and
becomes a `bark` record for the voice runner. Unknown ids and seats outside 1-3
are dropped; ARENA_BARKS=off removes the offer from the prompt entirely.
Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import advisor_runner as ar  # noqa: E402
import voice_runner as vr  # noqa: E402

VOICES = {1: {"library": "harry", "voice": "Harry", "temperament": "fiery young warrior"},
          2: {"library": "bill", "voice": "Bill", "temperament": "elder professor"},
          3: {"library": "lily", "voice": "Lily", "temperament": "warm and wise"}}


class FakeBrain:
    def __init__(self, *a, **kw):
        self.deck, self.model, self.effort = "giada-font-of-hope", "opus", "low"
        self.session_id = "sess-1"
        self.totals = {"calls": 0}
        self.reply = "Purphoros swung fourteen into Urza. [bark:1:that-hurt]"

    def reset(self):
        pass

    def ensure_session(self, *a, **kw):
        return True

    def decide(self, prompt, timeout=None, **kw):
        self.last_prompt = prompt
        return {}, {"raw": self.reply, "latency_s": 0.1}


class BarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._env = dict(os.environ)
        os.environ.pop("ARENA_BARKS", None)
        self._orig = (ar.SeatBrain, ar.opponent_deck_sections, vr.load_seat_libraries)
        ar.SeatBrain = FakeBrain
        ar.opponent_deck_sections = lambda *a, **kw: []
        vr.load_seat_libraries = lambda *a, **kw: dict(VOICES)
        self.r = self._runner()

    def _runner(self):
        base = Path(self.tmp.name) / f"r{len(os.listdir(self.tmp.name))}"
        r = ar.AdvisorRunner("giada-font-of-hope", base, "opus", "low", 30.0, log_dir=base / "logs")
        r.inbox.mkdir(parents=True)
        r.RANDOM_ADMIT_P = 1.0
        return r

    def tearDown(self):
        ar.SeatBrain, ar.opponent_deck_sections, vr.load_seat_libraries = self._orig
        os.environ.clear(); os.environ.update(self._env)
        self.tmp.cleanup()

    def _records(self, kind):
        return [json.loads(l) for l in self.r._jsonl.read_text().splitlines() if json.loads(l).get("kind") == kind]

    # ---- pure helpers
    def test_vocabulary_matches_the_seat_libraries(self):
        """The ids the advisor may emit are exactly the ids every voice library renders."""
        root = Path(__file__).resolve().parents[1] / "voice" / "stock" / "voices"
        for lib in ("harry", "bill", "lily"):
            m = json.loads((root / lib / "manifest.json").read_text())
            self.assertEqual(tuple(m["phrases"]), ar.BARKS, lib)
        self.assertEqual(len(ar.BARKS), 21)

    def test_split_bark_strips_known_tags_and_drops_bad_ones(self):
        self.assertEqual(ar.split_bark("Big turn. [bark:2:big-swing]"), ("Big turn.", (2, "big-swing")))
        self.assertEqual(ar.split_bark("Big turn. [bark: 3 : my-turn ]"), ("Big turn.", (3, "my-turn")))
        self.assertEqual(ar.split_bark("Mid [bark:1:taunt] sentence."), ("Mid sentence.", (1, "taunt")))
        self.assertEqual(ar.split_bark("No tag."), ("No tag.", None))
        dropped = []
        self.assertEqual(ar.split_bark("x [bark:1:not-a-thing]", log=dropped.append), ("x", None))
        self.assertEqual(ar.split_bark("x [bark:0:taunt]", log=dropped.append), ("x", None), "never the human seat")
        self.assertEqual(ar.split_bark("x [bark:4:taunt]", log=dropped.append), ("x", None))
        self.assertEqual(len(dropped), 3)
        self.assertIn("unknown id", dropped[0]); self.assertIn("seat must be 1-3", dropped[1])

    def test_guide_names_the_voices_and_the_moments_or_is_empty(self):
        g = ar.bark_guide(VOICES, "some")
        for frag in ("seat 1: Harry — fiery young warrior", "seat 3: Lily — warm and wise", "[bark:<seat>:that-hurt] when it takes a big hit",
                     "[bark:<seat>:my-turn]", "Never seat 0", "a quip OR a bark"):
            self.assertIn(frag, g)
        self.assertEqual(ar.bark_guide(VOICES, "off"), "")
        self.assertEqual(ar.bark_guide({}, "some"), "", "no voice libraries, no offer")

    # ---- through the runner
    def test_colour_reply_bark_becomes_a_record_and_leaves_the_panel_text(self):
        (self.r.inbox / "digest-9.json").write_text(json.dumps({"gameId": "g1", "seq": 9, "turn": 6, "digest": ["a", "b"]}))
        self.r._process(self.r._scan())
        self.assertIn("SEAT BARK", self.r.brain.last_prompt)
        self.assertIn("seat 2: Bill — elder professor", self.r.brain.last_prompt)
        self.assertEqual(self._records("color")[0]["text"], "Purphoros swung fourteen into Urza.")
        self.assertNotIn("[bark", self.r._stream.read_text())
        b = self._records("bark")
        self.assertEqual((b[0]["seat"], b[0]["id"], b[0]["turn"], b[0]["with"], b[0]["seq"]), (1, "that-hurt", 6, "color", 9))

    def test_advice_reply_may_carry_a_bark_and_quip_and_bark_are_both_kept(self):
        self.r.brain.reply = "Block with the angel. [quip:calculating] [bark:3:big-swing]"
        (self.r.inbox / "req-3.json").write_text(json.dumps(
            {"gameId": "g1", "seq": 3, "turn": 5, "phase": "COMBAT_DECLARE_BLOCKERS", "decisionType": "DECLARE_BLOCKERS",
             "prompt": "act", "state": {}, "options": []}))
        self.r._process(self.r._scan())
        self.assertIn("SEAT BARK", self.r.brain.last_prompt)
        self.assertEqual(self._records("advice")[0]["text"], "Block with the angel.")
        self.assertEqual(self._records("quip")[0]["id"], "calculating")
        b = self._records("bark")[0]
        self.assertEqual((b["seat"], b["id"], b["with"]), (3, "big-swing", "advice"))

    def test_barks_off_removes_the_offer_and_ignores_tags(self):
        os.environ["ARENA_BARKS"] = "off"
        self.r = self._runner()
        (self.r.inbox / "digest-9.json").write_text(json.dumps({"gameId": "g1", "seq": 9, "turn": 6, "digest": ["a"]}))
        self.r._process(self.r._scan())
        self.assertNotIn("SEAT BARK", self.r.brain.last_prompt)
        # a tag the model emits anyway is still stripped from the panel; the record is harmless (the voice runner ignores it when off)
        self.assertEqual(self._records("color")[0]["text"], "Purphoros swung fourteen into Urza.")


if __name__ == "__main__":
    unittest.main()

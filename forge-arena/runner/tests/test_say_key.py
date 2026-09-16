"""§4.4 (hardening plan 2026-09-14), seat side: a non-procedural decision window offers
an optional "say" key from a short menu of table-line ids; the runner validates it,
keeps it out of the engine answer and records it in game.jsonl beside "why" for the
voice runner to tail. Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from seatd import rules  # noqa: E402
from seatd.runner import SeatRunner  # noqa: E402

VOICES = Path(__file__).resolve().parents[1] / "voice" / "stock" / "voices"


def _cast(seq=1, options=None, **over):
    req = {"seq": seq, "turn": 4, "phase": "MAIN1", "decisionType": "CAST_SPELL", "gameId": "g",
           "options": options if options is not None else [{"id": 0, "label": "Pass (do nothing)"}, {"id": 1, "label": "Sol Ring {1}"}],
           "state": {"stack": [], "manaPool": 0, "untappedManaSourceCount": 3, "life": 40}}
    req.update(over)
    return req


class SayOffer(unittest.TestCase):
    def test_offered_on_moments_not_on_ceremony(self):
        self.assertIn('OPTIONAL "say"', rules.build_user_prompt(_cast()))
        self.assertIn('OPTIONAL "say"', rules.build_user_prompt(_cast(), seat=2))
        self.assertNotIn('"say"', rules.build_user_prompt(_cast(), seat=0), "seat 0 is the advisor playing the human's seat: no table line (Ben)")
        self.assertFalse(rules.say_offer(_cast(), 0)); self.assertTrue(rules.say_offer(_cast(), 3))
        self.assertNotIn('"say"', rules.build_user_prompt(_cast(options=[{"id": 0, "label": "Pass (do nothing)"}])), "a plain pass")
        for dt in ("MULLIGAN", "CHOOSE_NUMBER", "CHOOSE_MODE", "CONFIRM", "PAY_UNLESS", "CHOOSE_CARD"):
            self.assertNotIn('"say"', rules.build_user_prompt(_cast(decisionType=dt)), dt)
        for dt in ("REACT", "CHOOSE_ENTITY", "CHOOSE_ENTITIES"):
            self.assertIn('OPTIONAL "say"', rules.build_user_prompt(_cast(decisionType=dt)), dt)
            self.assertNotIn('"say"', rules.build_user_prompt(_cast(decisionType=dt, options=[{"id": 3, "label": "only"}])), dt + " forced")
        for dt in ("DECLARE_ATTACKERS", "DECLARE_BLOCKERS"):
            self.assertIn('OPTIONAL "say"', rules.build_user_prompt(_cast(decisionType=dt, options=[])), dt)

    def test_the_offer_is_one_short_line_of_real_ids(self):
        self.assertNotIn("\n", rules.SAY_OFFER)
        self.assertLess(len(rules.SAY_OFFER.split()), 80, "well under the 150-token budget")
        self.assertEqual(len(set(rules.SAY_MENU)), len(rules.SAY_MENU))
        main, table = VOICES / "harry" / "manifest.json", VOICES / "harry" / "table" / "manifest.json"
        if not (main.exists() and table.exists()):
            self.skipTest("harry's libraries are not checked out")
        have = set()
        for m in (main, table):
            have |= set((json.loads(m.read_text()).get("phrases") or {}).keys())
        pending_render = {"counter-offer"}   # table deals plan §7: rendered in the voice lane
        self.assertEqual([i for i in rules.SAY_MENU if i not in have and i not in pending_render], [],
                         "every menu id is a phrase harry can speak")

    def test_validate_strips_the_key(self):
        self.assertEqual(rules.validate(_cast(), {"chosenId": 1, "why": "w", "say": "taunt"}), {"chosenId": 1})


class SayRecorded(unittest.TestCase):
    def _runner(self):
        tmp = Path(tempfile.mkdtemp(prefix="say-"))
        r = SeatRunner(2, "giada-font-of-hope", str(tmp), log_dir=str(tmp / "logs"))
        r.brain.session_id = "s"; r.brain.ensure_session = lambda *a, **k: True
        r._fastpath = lambda req: None
        sent = []
        r.mb.respond = lambda req, ans: sent.append(ans) or True
        return r, sent

    def _decide(self, r, out):
        r.brain.decide = lambda *a, **k: (dict(out), {"latency_s": 0.1, "usage": None, "raw": json.dumps(out)})

    def _rows(self, r):
        return [json.loads(l) for l in r._game_log.read_text().splitlines()]

    def _log(self, r):
        return (r._game_log.parent / "seat-2.log").read_text()

    def test_a_valid_say_is_recorded_beside_why_and_never_sent(self):
        r, sent = self._runner()
        self._decide(r, {"chosenId": 1, "why": "ramp", "say": "Taunt "})
        r.handle(_cast(1))
        self.assertEqual(sent, [{"chosenId": 1}], "the engine sees the contract fields only")
        row = self._rows(r)[-1]
        self.assertEqual((row["say"], row["why"], row["source"]), ("taunt", "ramp", "model"))
        self.assertNotIn("dropped", self._log(r))

    def test_an_unknown_id_is_dropped_with_a_note(self):
        r, sent = self._runner()
        self._decide(r, {"chosenId": 1, "why": "ramp", "say": "trash-talk"})
        r.handle(_cast(2))
        self.assertEqual(sent, [{"chosenId": 1}])
        self.assertNotIn("say", self._rows(r)[-1])
        self.assertIn("say 'trash-talk' dropped: not on the menu", self._log(r))

    def test_a_say_on_a_procedural_window_is_dropped(self):
        r, sent = self._runner()
        self._decide(r, {"chosenId": 0, "why": "nothing to do", "say": "gg"})
        r.handle(_cast(3, options=[{"id": 0, "label": "Pass (do nothing)"}]))
        self.assertEqual(sent, [{"chosenId": 0}])
        self.assertNotIn("say", self._rows(r)[-1])
        self.assertIn("say 'gg' dropped: procedural window (CAST_SPELL)", self._log(r))

    def test_no_say_key_means_no_say_field_and_a_punt_speaks_nothing(self):
        r, sent = self._runner()
        self._decide(r, {"chosenId": 1, "why": "ramp"})
        r.handle(_cast(4))
        self.assertNotIn("say", self._rows(r)[-1])
        self._decide(r, {"chosenId": 99, "why": "bad id", "say": "gg"})    # invalid answer -> safe default
        r.handle(_cast(5))
        row = self._rows(r)[-1]
        self.assertEqual(row["source"], "punt"); self.assertNotIn("say", row)


if __name__ == "__main__":
    unittest.main()

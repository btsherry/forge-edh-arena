"""Round-two cleanup (2026-09-04), operations side: BL-26 the ratings sweep
survives malformed and vanished spools; BL-09 transport events attribute by
game id; BL-13 the advisor's carried context is bounded and the drop is
stated; item R the table roster rule; BL-14 the importer's quantity rule.
Run: python3 -m unittest discover -s tests"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ratings  # noqa: E402
import advisor_runner as ar  # noqa: E402
from tests.test_ratings import Env, spool  # noqa: E402


class SweepHardening(unittest.TestCase):
    def test_malformed_spool_is_skipped_not_a_traceback(self):
        env = Env()
        env.add_spool({"schema": 1, "seats": "nope"}, name="game-1000000000000-9.json")
        env.add_spool(spool([[3], [2], [1], [0]]))
        n, out = env.run()
        self.assertEqual(n, 1, "the good spool still rates")
        self.assertTrue(list((env.tmp / "results").glob("game-1000000000000-9.json.skipped")))
        self.assertTrue(any("malformed spool" in ln for ln in out), out)

    def test_vanished_spool_is_another_sweepers_win(self):
        out = []
        ok = ratings._rename_quiet(Path(tempfile.mkdtemp()) / "game-x.json", ".rated", out.append)
        self.assertFalse(ok)
        self.assertTrue(any("another sweeper" in ln for ln in out))

    def test_spool_problem_names_the_gap(self):
        self.assertEqual(ratings.spool_problem([]), "not an object")
        self.assertEqual(ratings.spool_problem({"startMillis": 1}), "missing endMillis")
        good = spool([[3], [2], [1], [0]])
        self.assertIsNone(ratings.spool_problem(good))


class EventsByGameId(unittest.TestCase):
    def _events(self, env, events):
        (env.tmp / "logs" / "transport-events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n")

    def test_other_games_punts_do_not_void_a_stamped_spool(self):
        env = Env()
        sp = spool([[3], [2], [1], [0]])
        sp["gameId"] = "g-this"
        env.add_spool(sp)
        # nine punts inside the time window but stamped for ANOTHER game
        self._events(env, [{"ts": 1000_000_000.0 + 100 + i, "seat": 1,
                            "kind": "punt", "gameId": "g-other"} for i in range(9)])
        n, _ = env.run()
        self.assertEqual(n, 1, "events of another game never void this one")

    def test_own_and_unstamped_events_still_void(self):
        for gid in ("g-this", None):
            env = Env()
            sp = spool([[3], [2], [1], [0]])
            sp["gameId"] = "g-this"
            env.add_spool(sp)
            self._events(env, [{"ts": 1000_000_000.0 + 100 + i, "seat": 1,
                                "kind": "punt", "gameId": gid} for i in range(9)])
            n, _ = env.run()
            self.assertEqual(n, 0, f"gameId={gid!r} must void")


class FakeBrain:
    def __init__(self, *a, **kw):
        self.deck, self.model, self.effort = "giada-font-of-hope", "opus", "low"
        self.session_id = "sess-1"
        self.totals = {"calls": 0}
        self.decisions = []

    def reset(self):
        pass

    def ensure_session(self, *a, **kw):
        return True

    def decide(self, prompt, timeout=None, **kw):
        self.decisions.append(prompt)
        return {}, {"raw": "advice", "latency_s": 0.1}


class AdvisorContextBound(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._orig = (ar.SeatBrain, ar.opponent_deck_sections)
        ar.SeatBrain = FakeBrain
        ar.opponent_deck_sections = lambda *a, **kw: []
        self.r = ar.AdvisorRunner("giada-font-of-hope", base, "opus", "low", 30.0,
                                  log_dir=base / "logs")

    def tearDown(self):
        ar.SeatBrain, ar.opponent_deck_sections = self._orig
        self.tmp.cleanup()

    def test_bound_drops_oldest_and_says_so(self):
        for i in range(ar.CONTEXT_MAX_LINES + 10):
            self.r._push_context(f"- line {i}")
        self.assertEqual(len(self.r.pending_context), ar.CONTEXT_MAX_LINES)
        self.assertEqual(self.r.pending_context[0], "- line 10")
        self.assertEqual(self.r._context_dropped, 10)
        self.r._advise({"seq": 1, "turn": 3, "phase": "MAIN1", "decisionType": "CAST_SPELL",
                        "prompt": "p", "state": {}, "options": []})
        prompt = self.r.brain.decisions[-1]
        self.assertIn("10 earlier line(s) dropped", prompt)
        self.assertIn("- line 49", prompt)
        self.assertNotIn("- line 9\n", prompt)
        self.assertEqual(self.r.pending_context, [])
        self.assertEqual(self.r._context_dropped, 0)

    def test_guarded_writes_survive_a_missing_log_dir(self):
        self.r._stream = Path(self.tmp.name) / "gone" / "advisor-0.log"
        self.r._jsonl = Path(self.tmp.name) / "gone" / "advisor-0.jsonl"
        self.r._stream_write("x")          # must not raise
        self.r._record("note", {"a": 1})   # must not raise


class TableRosterRule(unittest.TestCase):
    ROSTER = ar.DEFAULT_TABLE.split()

    def test_default_order_is_urza_giada_purphoros_selvala(self):
        self.assertEqual(self.ROSTER, ["urza-lord-high-artificer", "giada-font-of-hope",
                                       "purphoros-god-of-the-forge", "selvala-heart-of-the-wilds"])

    def test_human_on_selvala_faces_the_first_three(self):
        self.assertEqual(ar.table_opponents("selvala-heart-of-the-wilds", self.ROSTER),
                         ["urza-lord-high-artificer", "giada-font-of-hope",
                          "purphoros-god-of-the-forge"])

    def test_human_on_a_non_roster_deck_faces_the_first_three(self):
        self.assertEqual(ar.table_opponents("sheoldreds-sacrifice", self.ROSTER),
                         self.ROSTER[:3])

    def test_human_on_a_roster_deck_removes_only_that_deck(self):
        self.assertEqual(ar.table_opponents("giada-font-of-hope", self.ROSTER),
                         ["urza-lord-high-artificer", "purphoros-god-of-the-forge",
                          "selvala-heart-of-the-wilds"])


def _load_add_deck():
    p = Path(__file__).resolve().parents[2] / "scripts" / "arena-add-deck.py"
    spec = importlib.util.spec_from_file_location("arena_add_deck", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ImporterQuantityRule(unittest.TestCase):
    def test_leading_numbers_that_cannot_be_counts_are_names(self):
        mod = _load_add_deck()
        d = Path(tempfile.mkdtemp()) / "t.dck"
        d.write_text("[metadata]\nName=T\n[Commander]\n1 Sheoldred, the Apocalypse\n"
                     "[Main]\n3x Forest\n2 Swamp\nForest\n1996 World Champion\n"
                     "1 Sol Ring|C21|1\n")
        parsed = mod.parse_dck(str(d))
        cmdrs, main = parsed["commanders"], parsed["main"]
        self.assertEqual(cmdrs, [("Sheoldred, the Apocalypse", 1)])
        self.assertIn(("Forest", 3), main)
        self.assertIn(("Swamp", 2), main)
        self.assertIn(("Forest", 1), main)
        self.assertIn(("1996 World Champion", 1), main)
        self.assertIn(("Sol Ring", 1), main)


if __name__ == "__main__":
    unittest.main()

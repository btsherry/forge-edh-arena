"""ELO applier tests (plan §13, F-20/F-21/F-22/F-23/F-28): tie groups,
self-pairs, snapshot semantics, attribution, cross-check skips, idempotency.
Run: python3 -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ratings  # noqa: E402


def spool(groups, seats=None, start=1000_000_000_000, end=1000_000_600_000):
    seats = seats or [
        {"seat": 0, "name": "s0", "slug": "deck-a", "control": "ai"},
        {"seat": 1, "name": "s1", "slug": "deck-b", "control": "ai"},
        {"seat": 2, "name": "s2", "slug": "deck-c", "control": "ai"},
        {"seat": 3, "name": "s3", "slug": "deck-d", "control": "ai"},
    ]
    return {"schema": 1, "startMillis": start, "endMillis": end,
            "turnsPlayed": 12, "advisor": False, "seats": seats,
            "placementGroups": groups, "lostGroupTurns": []}


class Env:
    def __init__(self, models=("mA", "mB", "mC", "mD"), decisions=6):
        self.tmp = Path(tempfile.mkdtemp(prefix="elo-"))
        (self.tmp / "results").mkdir()
        (self.tmp / "logs").mkdir()
        self.game_log = self.tmp / "logs" / "game.jsonl"
        t = 1000_000_000.0 + 60
        lines = []
        for seat, m in enumerate(models):
            for i in range(decisions):
                lines.append(json.dumps({
                    "ts": t + seat * 7 + i, "seat": seat,
                    "deck": f"deck-{'abcd'[seat]}", "source": "model",
                    "model": m, "type": "CAST_SPELL"}))
        self.game_log.write_text("\n".join(lines) + "\n")

    def add_spool(self, sp, name="game-1000000000000-1.json"):
        (self.tmp / "results" / name).write_text(json.dumps(sp))

    def run(self):
        out = []
        n = ratings.sweep(self.tmp / "results", self.tmp / "ratings.json",
                          self.tmp / "ratings-history.jsonl", self.game_log,
                          self.tmp / "logs" / "elo", log=out.append)
        return n, out

    def tables(self):
        return json.loads((self.tmp / "ratings.json").read_text())


class EloMath(unittest.TestCase):
    def test_strict_placement_zero_sum(self):
        env = Env()
        env.add_spool(spool([[3], [2], [1], [0]]))
        n, _ = env.run()
        self.assertEqual(n, 1)
        m = env.tables()["models"]
        self.assertEqual(m["mD"]["elo"], 1060.0)   # 3 wins x K40 x 0.5
        self.assertEqual(m["mC"]["elo"], 1020.0)
        self.assertEqual(m["mB"]["elo"], 980.0)
        self.assertEqual(m["mA"]["elo"], 940.0)
        self.assertAlmostEqual(sum(v["elo"] for v in m.values()), 4000.0)
        self.assertTrue(all(v["games"] == 1 for v in m.values()))

    def test_tie_group_win_batch(self):
        env = Env()
        env.add_spool(spool([[3], [0, 1, 2]]))   # win: everyone else ties
        env.run()
        m = env.tables()["models"]
        self.assertEqual(m["mD"]["elo"], 1060.0)
        for k in ("mA", "mB", "mC"):
            self.assertEqual(m[k]["elo"], 980.0)  # one loss, two 0.5s vs equals

    def test_mass_draw_no_movement(self):
        env = Env()
        env.add_spool(spool([[0, 1, 2, 3]]))
        env.run()
        m = env.tables()["models"]
        for v in m.values():
            self.assertEqual(v["elo"], 1000.0)
            self.assertEqual(v["games"], 1)

    def test_self_pairs_skipped_single_game_count(self):
        env = Env(models=("mY", "mX", "mX", "mX"))
        env.add_spool(spool([[0], [1], [2], [3]]))
        env.run()
        m = env.tables()["models"]
        self.assertEqual(m["mY"]["elo"], 1060.0)   # 3 wins vs mX only
        self.assertEqual(m["mX"]["elo"], 940.0)    # 3 losses, self-pairs skipped
        self.assertEqual(m["mX"]["games"], 1)      # ONE game, not three
        d = env.tables()["decks"]
        self.assertEqual(d["deck-a"]["games"], 1)  # decks all distinct: rated

    def test_k_decay_uses_snapshot_games(self):
        env = Env()
        env.tmp.joinpath("ratings.json").write_text(json.dumps(
            {"version": 1, "decks": {}, "combos": {},
             "models": {"mD": {"elo": 1000.0, "games": 10}}}))
        env.add_spool(spool([[3], [2], [1], [0]]))
        env.run()
        m = env.tables()["models"]
        self.assertEqual(m["mD"]["elo"], 1030.0)   # K=20 for the veteran
        self.assertEqual(m["mA"]["elo"], 940.0)    # K=40 newcomers unaffected

    def test_placement_gap_skips(self):
        env = Env()
        env.add_spool(spool([[3], [2]]))           # seats 0/1 unplaced
        n, out = env.run()
        self.assertEqual(n, 0)
        self.assertTrue(any("SKIP" in l for l in out))
        self.assertFalse((env.tmp / "ratings.json").exists())


class Attribution(unittest.TestCase):
    def test_redial_majority_wins(self):
        env = Env()
        t = 1000_000_000.0 + 90
        with env.game_log.open("a") as f:
            for i in range(2):  # 2 late haiku decisions vs 6 mD: majority mD
                f.write(json.dumps({"ts": t + i, "seat": 3, "deck": "deck-d",
                                    "source": "model", "model": "haiku"}) + "\n")
        env.add_spool(spool([[3], [2], [1], [0]]))
        env.run()
        self.assertIn("mD", env.tables()["models"])
        self.assertNotIn("haiku", env.tables()["models"])

    def test_zero_model_decisions_rates_deck_only(self):
        env = Env()
        # wipe seat 3's records: fastpath-only seat
        recs = [json.loads(l) for l in env.game_log.read_text().splitlines()]
        env.game_log.write_text("\n".join(
            json.dumps(r) for r in recs if r["seat"] != 3) + "\n")
        env.add_spool(spool([[3], [2], [1], [0]]))
        env.run()
        t = env.tables()
        self.assertNotIn("mD", t["models"])
        self.assertEqual(t["decks"]["deck-d"]["elo"], 1060.0)  # deck still rates
        # seat 3's pairs vanish from the model ladder: others only played 2 pairs
        self.assertEqual(t["models"]["mC"]["elo"], 1040.0)

    def test_roster_mismatch_skips_game(self):
        env = Env()
        sp = spool([[3], [2], [1], [0]])
        sp["seats"][1]["slug"] = "some-other-deck"
        env.add_spool(sp)
        n, out = env.run()
        self.assertEqual(n, 0)
        self.assertTrue(any("roster drift" in l for l in out))
        self.assertTrue(list((env.tmp / "results").glob("*.skipped")))

    def test_human_advisor_pilot(self):
        seats = [
            {"seat": 0, "name": "Ben", "slug": "deck-a",
             "control": "human+advisor"},
            {"seat": 1, "name": "s1", "slug": "deck-b", "control": "ai"},
            {"seat": 2, "name": "s2", "slug": "deck-c", "control": "ai"},
            {"seat": 3, "name": "s3", "slug": "deck-d", "control": "ai"},
        ]
        env = Env()
        env.add_spool(spool([[0], [3], [2], [1]], seats=seats))
        env.run()
        m = env.tables()["models"]
        self.assertEqual(m["human+advisor"]["elo"], 1060.0)
        self.assertIn("human+advisor|deck-a", env.tables()["combos"])


class Lifecycle(unittest.TestCase):
    def test_idempotent_rerun(self):
        env = Env()
        env.add_spool(spool([[3], [2], [1], [0]]))
        n1, _ = env.run()
        n2, _ = env.run()
        self.assertEqual((n1, n2), (1, 0))
        self.assertEqual(env.tables()["models"]["mD"]["games"], 1)

    def test_digests_written_flat(self):
        env = Env()
        env.add_spool(spool([[3], [2], [1], [0]]))
        env.run()
        d = json.loads((env.tmp / "logs" / "elo" / "seat-3.json").read_text())
        self.assertEqual(d["m"], 1060.0)
        self.assertEqual(d["pilot"], "mD")
        self.assertEqual(d["n"], 1)

    def test_history_appended(self):
        env = Env()
        env.add_spool(spool([[3], [2], [1], [0]]))
        env.run()
        lines = (env.tmp / "ratings-history.jsonl").read_text().splitlines()
        rec = json.loads(lines[-1])
        self.assertEqual(rec["placementGroups"], [[3], [2], [1], [0]])
        self.assertIn("changes", rec)

    def test_seat_order_in_groups_is_irrelevant(self):
        e1, e2 = Env(), Env()
        e1.add_spool(spool([[3], [1, 2], [0]]))
        e2.add_spool(spool([[3], [2, 1], [0]]))
        e1.run(); e2.run()
        self.assertEqual(e1.tables(), e2.tables())


class VoidGames(unittest.TestCase):
    """Transport-contaminated games are recorded but never rated."""

    def _events(self, env, events):
        p = env.tmp / "logs" / "transport-events.jsonl"
        p.write_text("\n".join(json.dumps(e) for e in events) + "\n")

    def test_wedge_in_window_voids(self):
        env = Env()
        env.add_spool(spool([[3], [2], [1], [0]]))
        self._events(env, [{"ts": 1000_000_000.0 + 120, "seat": 2, "kind": "wedge"}])
        n, out = env.run()
        self.assertEqual(n, 0, "a voided game must not count as rated")
        self.assertFalse((env.tmp / "ratings.json").exists(),
                         "ladders must not move on a voided game")
        hist = (env.tmp / "ratings-history.jsonl").read_text().strip().splitlines()
        rec = json.loads(hist[-1])
        self.assertTrue(rec.get("voided"))
        self.assertIn("wedged", rec.get("voidReason", ""))
        self.assertTrue(list((env.tmp / "results").glob("*.voided")),
                        "spool should be renamed .voided")

    def test_punt_pileup_on_one_seat_voids(self):
        env = Env()
        env.add_spool(spool([[3], [2], [1], [0]]))
        self._events(env, [{"ts": 1000_000_000.0 + 100 + i, "seat": 1,
                            "kind": "punt"} for i in range(9)])
        n, _ = env.run()
        self.assertEqual(n, 0)
        rec = json.loads((env.tmp / "ratings-history.jsonl")
                         .read_text().strip().splitlines()[-1])
        self.assertTrue(rec.get("voided"))

    def test_events_outside_window_do_not_void(self):
        env = Env()
        env.add_spool(spool([[3], [2], [1], [0]]))
        self._events(env, [{"ts": 1000_000_000.0 - 9999, "seat": 2, "kind": "wedge"},
                           {"ts": 1000_001_000.0 + 9999, "seat": 1, "kind": "punt"}])
        n, _ = env.run()
        self.assertEqual(n, 1, "out-of-window events must not void the game")

    def test_scattered_punts_below_threshold_rate_normally(self):
        env = Env()
        env.add_spool(spool([[3], [2], [1], [0]]))
        self._events(env, [{"ts": 1000_000_000.0 + 100 + i, "seat": i % 4,
                            "kind": "punt"} for i in range(7)])
        n, _ = env.run()
        self.assertEqual(n, 1, "a few scattered punts are normal, not contamination")

    def test_env_override_rates_anyway(self):
        import os
        env = Env()
        env.add_spool(spool([[3], [2], [1], [0]]))
        self._events(env, [{"ts": 1000_000_000.0 + 120, "seat": 2, "kind": "wedge"}])
        os.environ["ARENA_RATE_VOIDED"] = "1"
        try:
            n, _ = env.run()
        finally:
            del os.environ["ARENA_RATE_VOIDED"]
        self.assertEqual(n, 1, "ARENA_RATE_VOIDED=1 must force rating")


if __name__ == "__main__":
    unittest.main()

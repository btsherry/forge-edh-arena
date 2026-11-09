"""ELO applier tests (plan §13, F-20/F-21/F-22/F-23/F-28): tie groups, self-pairs, snapshot semantics,
attribution, cross-check skips, idempotency, voided games (transport-contaminated games are recorded but never
rated); BL-26 the sweep survives malformed and vanished spools; BL-09 transport events attribute by game id;
BL-21 a record in game.jsonl AND game-<id>.jsonl is one decision; BL-59 (2026-10-16) the ladder keys on the
concrete model id — aliases resolve by the record's own time and `ratings.py --rebuild` re-rates the archive
corpus. Run: python3 -m unittest discover -s tests"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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


def epoch(iso: str) -> float:
    return datetime.datetime.fromisoformat(iso).timestamp()


ALIASES = ratings.compile_aliases({
    "_comment": "ignored",
    "opus": [{"until": "2026-09-25T00:00:00-07:00", "id": "claude-opus-5"},
             {"id": "claude-opus-5-5"}],
    "fable": [{"id": "claude-fable-5-1"}],
})


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
        env = Env()
        env.add_spool(spool([[3], [2], [1], [0]]))
        self._events(env, [{"ts": 1000_000_000.0 + 120, "seat": 2, "kind": "wedge"}])
        os.environ["ARENA_RATE_VOIDED"] = "1"
        try:
            n, _ = env.run()
        finally:
            del os.environ["ARENA_RATE_VOIDED"]
        self.assertEqual(n, 1, "ARENA_RATE_VOIDED=1 must force rating")


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


class DualLogNotDoubleCounted(unittest.TestCase):
    """BL-21 follow-up: a record present in game.jsonl AND game-<id>.jsonl is one decision."""

    def test_records_in_both_files_count_once(self):
        env = Env()
        flat = env.game_log.read_text()
        (env.tmp / "logs" / "game-1000000000000-1.jsonl").write_text(flat)  # the per-game copy
        recs = ratings.slice_game_log(env.game_log, 1000_000_000.0, 1000_000_000.0 + 3600)
        self.assertEqual(len(recs), len(flat.splitlines()), "each decision once, not twice")
        env.add_spool(spool([[3], [2], [1], [0]]))
        n, _ = env.run()
        self.assertEqual(n, 1)
        rec = json.loads((env.tmp / "ratings-history.jsonl").read_text().strip().splitlines()[-1])
        self.assertEqual(rec["seats"][0]["modelDecisions"], {"mA": 6}, "6 decisions, not 12")


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


class AliasResolution(unittest.TestCase):

    def test_an_alias_resolves_by_the_records_own_time(self):
        self.assertEqual(ratings.resolve_model("opus", epoch("2026-09-01T12:00:00-07:00"), ALIASES), "claude-opus-5")
        self.assertEqual(ratings.resolve_model("opus", epoch("2026-09-25T00:00:00-07:00"), ALIASES), "claude-opus-5-5",
                         "`until` is exclusive")
        self.assertEqual(ratings.resolve_model("opus", epoch("2026-10-01T12:00:00-07:00"), ALIASES), "claude-opus-5-5")

    def test_no_timestamp_means_the_current_resolution(self):
        self.assertEqual(ratings.resolve_model("opus", None, ALIASES), "claude-opus-5-5")

    def test_concrete_ids_and_unknown_names_pass_through(self):
        self.assertEqual(ratings.resolve_model("claude-opus-5-5", 0, ALIASES), "claude-opus-5-5")
        self.assertEqual(ratings.resolve_model("human+advisor", 0, ALIASES), "human+advisor")
        self.assertEqual(ratings.resolve_model("", 0, ALIASES), "")

    def test_the_shipped_alias_file_parses(self):
        table = ratings.load_aliases()
        self.assertIn("opus", table)
        self.assertEqual(table["opus"][-1][0], None, "the last entry is the open-ended current resolution")
        self.assertEqual(table["opus"][-1][1], "claude-opus-5-5")

    def test_the_ladder_keys_on_the_resolved_id(self):
        # the Env's records sit at ts ~1e9 (2001): an `opus` alias there is claude-opus-5
        env = Env(models=("opus", "mB", "mC", "mD"))
        env.add_spool(spool([[0], [1], [2], [3]]))
        n = ratings.sweep(env.tmp / "results", env.tmp / "ratings.json",
                          env.tmp / "ratings-history.jsonl", env.game_log,
                          env.tmp / "logs" / "elo", log=lambda *a: None, aliases=ALIASES)
        self.assertEqual(n, 1)
        models = env.tables()["models"]
        self.assertIn("claude-opus-5", models)
        self.assertNotIn("opus", models)
        self.assertIn("claude-opus-5|deck-a", env.tables()["combos"])


class Rebuild(unittest.TestCase):

    def _archive_from(self, env: Env) -> Path:
        """Move a swept Env's logs and consumed spools into archive/<stamp>-stop/
        the way arena-stop.sh does."""
        arch = env.tmp / "logs" / "archive" / "20260101-000000-stop"
        arch.mkdir(parents=True)
        shutil.copy(env.game_log, arch / "game.jsonl")
        for p in (env.tmp / "results").glob("game-*.json.*"):
            shutil.copy(p, arch / p.name)
        return arch.parent

    def test_rebuild_with_no_aliases_reproduces_the_live_sweep(self):
        env = Env()
        env.add_spool(spool([[0], [1], [2], [3]]), name="game-1000000000000-1.json")
        env.add_spool(spool([[3], [2], [1], [0]], start=1000_000_300_000, end=1000_000_500_000),
                      name="game-1000000300000-2.json")
        n, _ = env.run()
        self.assertEqual(n, 2)
        live = env.tables()
        archive = self._archive_from(env)
        out = env.tmp / "rebuilt"
        out.mkdir()
        got = ratings.rebuild(archive, out / "ratings.json", out / "ratings-history.jsonl",
                              out / "elo", log=lambda *a: None, aliases={}, keep_backups=False)
        self.assertEqual(got, 2)
        rebuilt = json.loads((out / "ratings.json").read_text())
        self.assertEqual(rebuilt["models"], live["models"])
        self.assertEqual(rebuilt["decks"], live["decks"])
        self.assertEqual(rebuilt["combos"], live["combos"])
        history = [json.loads(l) for l in (out / "ratings-history.jsonl").read_text().splitlines()]
        self.assertEqual([h["spool"] for h in history],
                         ["game-1000000000000-1.json", "game-1000000300000-2.json"])
        self.assertTrue(all(h["archive"] == "20260101-000000-stop" for h in history))
        self.assertTrue(list((out / "elo").glob("seat-*.json")), "digests are written for the last rated game")

    def test_rebuild_with_aliases_splits_one_alias_into_its_ids(self):
        env = Env(models=("opus", "opus", "mC", "mD"))
        env.add_spool(spool([[0], [1], [2], [3]]))
        env.run()
        archive = self._archive_from(env)
        out = env.tmp / "rebuilt"
        out.mkdir()
        ratings.rebuild(archive, out / "ratings.json", out / "ratings-history.jsonl",
                        out / "elo", log=lambda *a: None, aliases=ALIASES, keep_backups=False)
        models = json.loads((out / "ratings.json").read_text())["models"]
        self.assertIn("claude-opus-5", models)
        self.assertNotIn("opus", models)
        # seats 0 and 1 are the same rated player: a self-pair, skipped; games_played still 1
        self.assertEqual(models["claude-opus-5"]["games"], 1)

    def test_rebuild_backs_up_the_live_files(self):
        env = Env()
        env.add_spool(spool([[0], [1], [2], [3]]))
        env.run()
        archive = self._archive_from(env)
        ratings.rebuild(archive, env.tmp / "ratings.json", env.tmp / "ratings-history.jsonl",
                        env.tmp / "logs" / "elo", log=lambda *a: None, aliases={})
        baks = list(env.tmp.glob("ratings.json.bak-*")) + list(env.tmp.glob("ratings-history.jsonl.bak-*"))
        self.assertEqual(len(baks), 2)

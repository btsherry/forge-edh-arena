"""BL-59 re-key (2026-10-16): the Elo ladder keys on the concrete model id.
Records that carry an alias resolve by their own timestamp through
ratings-aliases.json; `ratings.py --rebuild` re-rates the archive corpus from
scratch and, with an empty alias table, reproduces the live sweep exactly.
Run: python3 -m unittest discover -s tests"""
import datetime
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ratings  # noqa: E402
from test_ratings import Env, spool  # noqa: E402


def epoch(iso: str) -> float:
    return datetime.datetime.fromisoformat(iso).timestamp()


ALIASES = ratings.compile_aliases({
    "_comment": "ignored",
    "opus": [{"until": "2026-09-25T00:00:00-07:00", "id": "claude-opus-5"},
             {"id": "claude-opus-5-5"}],
    "fable": [{"id": "claude-fable-5-1"}],
})


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


if __name__ == "__main__":
    unittest.main()

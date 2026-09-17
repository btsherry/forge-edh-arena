"""The voice tuning (2026-09-16, hardening plan §2 — "36 environment knobs on the voice path"):
the numbers the talk runs on live in runner/voice/stock/voices/tuning.json, the operator keeps
five knobs, and this suite holds the file to the code — every key read by exactly one attribute,
no attribute still reading a retired environment variable, the operator set exactly as agreed,
and the launch banner and the README pointing at the file rather than listing the knobs."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE.parent
ROOT = RUNNER.parent
sys.path.insert(0, str(RUNNER))
import voice_runner as vr  # noqa: E402
from chains import ChainTable  # noqa: E402
from voice import table as vr_table  # noqa: E402

TUNING = RUNNER / "voice" / "stock" / "voices" / "tuning.json"
VOICE_PATH = [RUNNER / "voice_runner.py", RUNNER / "chains.py"] + sorted((RUNNER / "voice").glob("*.py"))

# key -> the attribute that holds it (the runner's, or the chain table's)
HELD_BY = {
    "min_gap_s": lambda r: r.min_gap, "your_move_p": lambda r: r.your_move_p,
    "color_mode": lambda r: r.color_mode, "color_p": lambda r: r.color_p,
    "color_joshua_share": lambda r: r.color_joshua_share, "advice_grace_s": lambda r: r.advice_grace,
    "duty_target": lambda r: None if r.duty_target == min(0.45, vr.DUTY_BASE * r.chatter) else r.duty_target,
    "duty_human": lambda r: r.duty_human, "table_p": lambda r: r.table_mult,
    "barks_p": lambda r: r.barks_p, "barks_cooldown_s": lambda r: r.barks_cooldown,
    "barks_opener_p": lambda r: r.barks_opener_p, "barks_swing": lambda r: r.barks_swing,
    "barks_hit": lambda r: r.barks_hit, "barks_human_p": lambda r: r.barks_human_p,
    "barks_slow_s": lambda r: r.barks_slow, "barks_mana": lambda r: r.barks_mana,
    "patter": lambda r: r.patter_on, "patter_gap_s": lambda r: list(r.patter_gap),
    "patter_human": lambda r: r.patter_human, "patter_after_advice_s": lambda r: r.patter_after_advice,
    "chain_p": lambda r: r.chains.first_hop_p, "chain_decay": lambda r: r.chains.decay,
    "chain_max_hops": lambda r: r.chains.max_hops, "chain_gap_s": lambda r: r.chains.gap_s,
    "chain_human_p": lambda r: r.chains.human_mult,
}
# what the operator keeps on the voice path: the dial, the two switches, the bleeps; Joshua's render
# settings (not tuning); the launch plumbing. ARENA_VOICE_FOCUS is the GUI's and is not read in Python.
OPERATOR = {"ARENA_CHATTER", "ARENA_BARKS", "ARENA_VOICE_YOUR_MOVE", "ARENA_VOICE_SFX"}
RENDER = {"ARENA_VOICE_ID", "ARENA_VOICE_MODEL", "ARENA_VOICE_FORMAT", "ARENA_VOICE_MAX_CHARS", "ARENA_VOICE_FX", "ARENA_VOICE_GLITCH"}
PLUMBING = {"ARENA_HUMAN_DECK", "ARENA_SEAT_DECKS"}
RETIRED = {"ARENA_VOICE_MIN_GAP", "ARENA_VOICE_COLOR", "ARENA_VOICE_COLOR_P", "ARENA_VOICE_YOUR_MOVE_P", "ARENA_VOICE_DUTY",
           "ARENA_VOICE_DUTY_HUMAN", "ARENA_VOICE_PATTER", "ARENA_VOICE_PATTER_GAP", "ARENA_VOICE_PATTER_HUMAN",
           "ARENA_VOICE_PATTER_AFTER_ADVICE", "ARENA_TABLE_P", "ARENA_BARKS_P", "ARENA_BARKS_COOLDOWN", "ARENA_BARKS_OPENER_P",
           "ARENA_BARKS_SWING", "ARENA_BARKS_HIT", "ARENA_BARKS_HUMAN_P", "ARENA_BARKS_SLOW", "ARENA_BARKS_MANA",
           "ARENA_BARKS_CHAIN_P", "ARENA_BARKS_CHAIN_DECAY", "ARENA_BARKS_CHAIN_MAX", "ARENA_BARKS_CHAIN_HUMAN_P", "ARENA_BARKS_CHAIN_GAP"}


def _config():
    spec = importlib.util.spec_from_file_location("arena_config", ROOT / "scripts" / "arena-config.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TheFile(unittest.TestCase):
    def test_loads_with_the_schema_and_the_agreed_keys(self):
        raw = json.loads(TUNING.read_text())
        self.assertEqual(raw["schema"], vr_table.TUNING_SCHEMA)
        self.assertTrue(raw.get("note"), "the file documents itself once")
        tune = vr.load_tuning()
        self.assertEqual(set(tune), set(HELD_BY), "the 24 retired knobs, no more, no fewer")
        self.assertNotIn("schema", tune); self.assertNotIn("note", tune)
        self.assertEqual(len(RETIRED), 24)

    def test_the_values_are_the_defaults_the_code_shipped_with(self):
        tune = vr.load_tuning()
        self.assertEqual((tune["min_gap_s"], tune["duty_human"], tune["barks_mana"], tune["duty_target"]), (8, 0.6, 6, None),
                         "the human-turn budget is 0.6 and big mana 6 as committed; the gap 8; the budget derived")
        self.assertEqual((tune["chain_p"], tune["chain_decay"], tune["chain_max_hops"], tune["chain_gap_s"], tune["chain_human_p"]), (0.6, 0.5, 3, 0.25, 0.5))
        self.assertEqual(tune["patter_gap_s"], [5, 7])

    def test_a_missing_or_foreign_file_is_a_loud_fault(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                vr.load_tuning(Path(d) / "nowhere.json")
            bad = Path(d) / "bad.json"
            bad.write_text(json.dumps({"schema": "arena.voice-chains/1", "min_gap_s": 8}))
            with self.assertRaises(RuntimeError):
                vr.load_tuning(bad)

    def test_chains_json_carries_no_numbers_any_more(self):
        chains = json.loads((RUNNER / "voice" / "stock" / "voices" / "chains.json").read_text())
        for k in ("first_hop_p", "decay", "max_hops", "gap_s", "human_trigger_mult"):
            self.assertNotIn(k, chains, "one source: tuning.json")


class EveryKeyHeldOnce(unittest.TestCase):
    def test_each_key_is_read_by_exactly_one_attribute_in_the_code(self):
        reads = Counter()
        for f in VOICE_PATH:
            reads.update(re.findall(r'tune\["([a-z_]+)"\]', f.read_text()))
        tune = vr.load_tuning()
        self.assertEqual(set(reads), set(tune), f"orphan keys {set(tune) - set(reads)} / reads of keys the file lacks {set(reads) - set(tune)}")
        self.assertEqual({k: n for k, n in reads.items() if n != 1}, {}, "a key read twice is two attributes disagreeing")

    def test_the_runner_and_the_chain_table_hold_the_file(self):
        env = dict(os.environ)
        for k in OPERATOR | RETIRED:
            os.environ.pop(k, None)
        try:
            with tempfile.TemporaryDirectory() as d:
                tmp = Path(d); (tmp / "logs").mkdir(); (tmp / "mailbox").mkdir()
                r = vr.VoiceRunner(tmp / "logs", tmp / "mailbox", dry_run=True)
                tune = vr.load_tuning()
                self.assertIsNotNone(r.chains, "the shipped chains.json loads")
                for key, held in HELD_BY.items():
                    self.assertEqual(held(r), tune[key], f"{key}: the attribute does not hold the file's value")
                r2 = vr.VoiceRunner(tmp / "logs", tmp / "mailbox", dry_run=True,
                                    tuning={"min_gap_s": 3, "chain_max_hops": 1, "duty_target": 0.3, "patter_gap_s": [4]})
                self.assertEqual((r2.min_gap, r2.chains.max_hops, r2.duty_target, r2.patter_gap), (3.0, 1, 0.3, (4.0, 4.0)), "an override replaces a value")
                self.assertEqual(r2.barks_p, tune["barks_p"], "and leaves the rest")
        finally:
            os.environ.clear(); os.environ.update(env)

    def test_an_old_chains_json_still_supplies_its_numbers_beneath_the_tuning(self):
        old = ChainTable({"invites": {}, "first_hop_p": 0.9, "gap_s": 1.5})
        self.assertEqual((old.first_hop_p, old.gap_s, old.max_hops), (0.9, 1.5, 3), "no tuning given: the file's own keys, then the shipped defaults")
        tuned = ChainTable({"invites": {}, "first_hop_p": 0.9}, tuning={"chain_p": 0.1})
        self.assertEqual(tuned.first_hop_p, 0.1, "the tuning wins")


class TheOperatorKnobs(unittest.TestCase):
    def _env_reads(self):
        seen = set()
        rx = re.compile(r'environ\.get\("(ARENA_[A-Z_]+)"')
        for f in VOICE_PATH:
            seen.update(rx.findall(f.read_text()))
        return seen

    def test_the_voice_path_reads_exactly_the_agreed_set(self):
        self.assertEqual(self._env_reads(), OPERATOR | RENDER | PLUMBING)

    def test_no_retired_name_survives_anywhere_it_would_act(self):
        for f in VOICE_PATH:
            text = f.read_text()
            for name in RETIRED:
                self.assertNotRegex(text, rf'environ\.get\("{name}"', f"{f.name} still reads {name}")
        cfg = _config()
        rows = {name for rows in cfg.KNOBS.values() for name, _, _ in rows}
        self.assertEqual(rows & RETIRED, set(), "retired knobs still in the launch banner")
        self.assertIn(cfg.TUNING_FILE, rows, "the banner points at the file instead")
        readme = (ROOT / "packaging" / "README.md").read_text()
        table = readme[readme.index("| `ARENA_MAILBOX_TIMEOUT`"):]
        for name in RETIRED:
            self.assertNotIn(f"| `{name}` |", table, f"README settings table still has a row for {name}")
        self.assertIn(f"`{cfg.TUNING_FILE}`", table)

    def test_the_banner_prints_the_file_as_a_file(self):
        cfg = _config()

        class A:
            mode = ""; deck = ""; model = ""; effort = ""; timeout = ""; advisor = ""; voice = ""; stops = ""; linger = ""; autostop = ""
        text = cfg.render(A(), env={})
        self.assertIn(f"     {cfg.TUNING_FILE}   the numbers", text)
        self.assertNotIn(f"{cfg.TUNING_FILE}=", text, "a file is not a variable with a value")


if __name__ == "__main__":
    unittest.main()


class TuningContract(unittest.TestCase):
    def test_an_unknown_key_or_a_string_patter_switch_is_refused(self):
        import tempfile, pathlib, sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        import voice_runner as vr
        d = pathlib.Path(tempfile.mkdtemp())
        with self.assertRaises(ValueError):
            vr.VoiceRunner(d, d / "mb", dry_run=True, tuning={"bogus_key": 1})
        with self.assertRaises(ValueError):
            vr.VoiceRunner(d, d / "mb", dry_run=True, tuning={"patter": "off"})

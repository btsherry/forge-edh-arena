"""Seat-bark stock libraries (experimental/voicework2, 2026-09-10).

Three static voices — harry (seat 1), bill (seat 2), lily (seat 3) — share ONE
21-id vocabulary; each id has four wordings in that voice's register, every
wording led by an eleven_v3 delivery tag. The builder renders/bakes any library
by name; wording N>1 lands in <id>-N.wav. These tests pin the contract the voice
runner and the advisor will rely on; the audio itself is checked by
StockLibrary-style tests once the takes exist.
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNNER))
sys.path.insert(0, str(RUNNER / "voice"))
import build_stock as bs  # noqa: E402

VOICES = RUNNER / "voice" / "stock" / "voices"
LIBS = ("harry", "bill", "lily")
TAG_RE = re.compile(r"^\[[a-z ]+\] \S")


def load(lib: str) -> dict:
    return json.loads((VOICES / lib / "manifest.json").read_text())


class SharedVocabulary(unittest.TestCase):
    def test_three_libraries_one_vocabulary_four_wordings_each(self):
        ids = None
        for lib in LIBS:
            m = load(lib)
            self.assertEqual(m["schema"], "arena.voice-stock/1")
            self.assertEqual(m["library"], lib)
            these = list(m["phrases"])
            self.assertEqual(len(these), 21, lib)
            if ids is None:
                ids = these
            self.assertEqual(these, ids, f"{lib} must share the vocabulary, in the same order")
            for pid, ph in m["phrases"].items():
                self.assertIsInstance(ph["text"], list, f"{lib}/{pid}: wordings are a list")
                self.assertEqual(len(ph["text"]), 4, f"{lib}/{pid}: exactly four wordings")
                self.assertEqual(len(set(ph["text"])), 4, f"{lib}/{pid}: wordings must differ")
                self.assertTrue(ph.get("when"), f"{lib}/{pid}: 'when' guides the advisor")
                for t in ph["text"]:
                    self.assertRegex(t, TAG_RE, f"{lib}/{pid}: every wording opens with a v3 delivery tag: {t!r}")
                    self.assertLessEqual(len(t.split("]", 1)[1].split()), 10, f"{lib}/{pid}: keep it under ~2.5 s: {t!r}")
        self.assertIn("my-turn", ids)
        self.assertIn("eliminated", ids)

    def test_seats_voices_and_render_settings(self):
        seats = set()
        for lib in LIBS:
            m = load(lib)
            seats.add(m["seat"])
            self.assertTrue(m["voice_id"], f"{lib}: voice_id comes from the account's library, never from memory")
            self.assertIn(m["voice_name"].split(" - ")[0].lower(), lib)
            model, settings, formats = bs.render_settings(m)
            self.assertEqual(model, "eleven_v3", "tags need v3")
            self.assertIn(settings["stability"], (0.0, 0.5), f"{lib}: v3 tags only take at Creative/Natural stability")
            self.assertEqual(formats[0], "pcm_44100")
            b = bs.bake_settings(m)
            self.assertEqual((b["fx"], b["glitch"], b["rate"]), ("none", "off", 22050), f"{lib}: a seat voice stays clean and small")
            self.assertTrue(m.get("temperament"), f"{lib}: the advisor's guide quotes the temperament")
        self.assertEqual(seats, {1, 2, 3})


class Builder(unittest.TestCase):
    def test_variants_enumerate_str_and_list_texts(self):
        m = {"phrases": {"your-move": {"text": ["Your move.", "Your turn to play."]},
                         "calculating": {"text": "Calculating."}}}
        self.assertEqual(bs.variants(m), [
            ("your-move", 1, "Your move.", "your-move"),
            ("your-move", 2, "Your turn to play.", "your-move-2"),
            ("calculating", 1, "Calculating.", "calculating"),
        ])

    def test_joshua_defaults_are_the_original_settings(self):
        """The shipped manifest carries no render/bake block; the defaults must
        reproduce the 2026-09-07 takes exactly or a re-bake would change them."""
        m = {}
        self.assertEqual(bs.render_settings(m), ("eleven_v3", {"stability": 1.0, "speed": 0.92}, ("pcm_44100", "pcm_24000")))
        self.assertEqual(bs.bake_settings(m), {"rate": 44100, "fx": "chain", "glitch": "light", "target_lufs": -18})
        self.assertEqual(bs.bake_settings(m, "off")["glitch"], "off")

    def test_bake_argv_chain_vs_none(self):
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td)
            (lib / "fx-chain.txt").write_text("volume=1.0\n")
            raw, tmp = lib / "raw" / "x.wav", lib / "x.tmp.wav"
            chain = bs.bake_argv(raw, tmp, lib, {}, bs.bake_settings({}))
            self.assertIn("volume=1.0", chain)
            self.assertEqual(chain[chain.index("-ar") + 1], "44100")
            clean = bs.bake_argv(raw, tmp, lib, {}, bs.bake_settings({"bake": {"fx": "none", "rate": 22050, "target_lufs": -18}}))
            self.assertIn("loudnorm=I=-18:TP=-1.5:LRA=11", clean)
            self.assertEqual(clean[clean.index("-ar") + 1], "22050")
            self.assertNotIn("volume=1.0", clean)

    def test_resolve_library_by_name_and_default(self):
        self.assertEqual(bs.resolve_library(""), bs.STOCK)
        self.assertEqual(bs.resolve_library(None), bs.STOCK)
        for lib in LIBS:
            self.assertEqual(bs.resolve_library(lib), VOICES / lib)
        with self.assertRaises(SystemExit):
            bs.resolve_library("no-such-voice")


if __name__ == "__main__":
    unittest.main()

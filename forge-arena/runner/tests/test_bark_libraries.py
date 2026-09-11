"""Seat-bark stock libraries (experimental/voicework2, 2026-09-10).

Three static voices — harry (seat 1), bill (seat 2), lily (seat 3) — share ONE
21-id vocabulary; each id has four wordings in that voice's register, every
wording led by an eleven_v3 delivery tag. The builder renders/bakes any library
by name; wording N>1 lands in <id>-N.wav. These tests pin the contract the voice
runner and the advisor will rely on; the audio itself is checked by
StockLibrary-style tests once the takes exist.
"""
import collections
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
            cats = collections.Counter(ph.get("category") for ph in m["phrases"].values())
            self.assertEqual(len(these), 63, f"{lib}: 21 barks + 8 reactions + 19 replies + 15 patter lines")
            self.assertEqual((cats["bark"], cats["reaction"], cats["reply"], cats["patter"]), (21, 8, 19, 15), f"{lib}: {dict(cats)}")
            if ids is None:
                ids = these
            self.assertEqual(these, ids, f"{lib} must share the vocabulary, in the same order")
            for pid, ph in m["phrases"].items():
                self.assertIsInstance(ph["text"], list, f"{lib}/{pid}: wordings are a list")
                if ph.get("category") == "bark" or ph.get("source") == "elevenlabs-v3-2026-09-10-replies":
                    self.assertEqual(len(ph["text"]), 4, f"{lib}/{pid}: the barks and the first ten replies carry four wordings")
                self.assertEqual(len(set(ph["text"])), len(ph["text"]), f"{lib}/{pid}: wordings must differ")
                self.assertTrue(ph.get("when"), f"{lib}/{pid}: 'when' guides the advisor")
                for t in ph["text"]:
                    self.assertRegex(t, TAG_RE, f"{lib}/{pid}: every wording opens with a v3 delivery tag: {t!r}")
                    self.assertLessEqual(len(t.split("]", 1)[1].split()), 10, f"{lib}/{pid}: keep it under ~2.5 s: {t!r}")
        self.assertIn("my-turn", ids)
        self.assertIn("eliminated", ids)
        self.assertIn("clapback", ids)

    def test_chain_table_is_consistent_with_the_vocabulary(self):
        table = json.loads((VOICES / "chains.json").read_text())
        ids = set(load("harry")["phrases"])
        roles = {"target", "aggressor", "bystander", "leader", "origin"}
        for opener, opts in table["invites"].items():
            self.assertIn(opener, ids, f"chains.json invites from an unknown line {opener!r}")
            for o in opts:
                self.assertIn(o["role"], roles, o); self.assertIn(o["reply"], ids, o)
        joshua = json.loads((RUNNER / "voice" / "stock" / "manifest.json").read_text())["phrases"]
        for k, v in table["joshua_replies"].items():
            if k != "note":
                self.assertIn(v, joshua, f"Joshua's reply {v!r} is not a stock quip")
        self.assertTrue(0 < table["first_hop_p"] <= 1 and 0 < table["decay"] <= 1 and table["max_hops"] >= 1)

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
            self.assertEqual(formats, ("pcm_24000",), f"{lib}: 24 kHz raws like the Joshua takes")
            b = bs.bake_settings(m)
            self.assertEqual((b["fx"], b["glitch"], b["rate"]), ("none", "off", 22050), f"{lib}: a seat voice stays clean and small")
            self.assertEqual((b["gain"], b["target_lufs"], b["true_peak_max"]), ("library", -24.0, -1.0), f"{lib}: library-relative gain to the Joshua level")
            self.assertTrue(m.get("temperament"), f"{lib}: the advisor's guide quotes the temperament")
        self.assertEqual(seats, {1, 2, 3})


class RenderedAudio(unittest.TestCase):
    """Stage 2b (2026-09-10): every wording of every library is a baked WAV in the
    runner's format — 22.05 kHz mono 16-bit for the seat voices, 44.1 kHz for the
    Joshua variants — and no take is silent or longer than a bark should be."""
    def test_every_seat_wording_is_a_baked_wav(self):
        import wave
        for lib in LIBS:
            m = load(lib)
            for pid, n, text, stem in bs.variants(m):
                f = VOICES / lib / f"{stem}.wav"
                self.assertTrue(f.exists(), f"{lib}/{stem}.wav missing for {text!r}")
                with wave.open(str(f)) as w:
                    self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 22050), f"{lib}/{stem}")
                    secs = w.getnframes() / w.getframerate()
                    self.assertTrue(0.5 <= secs <= 6.0, f"{lib}/{stem}: {secs:.1f}s")
                self.assertTrue((VOICES / lib / "raw" / f"{stem}.wav").exists(), f"{lib}/raw/{stem}.wav: the dry take is the source for re-bakes")

    def test_joshua_variants_are_baked_beside_the_originals(self):
        import wave
        J = json.loads((RUNNER / "voice" / "stock" / "manifest.json").read_text())
        for pid, n, text, stem in bs.variants(J):
            f = RUNNER / "voice" / "stock" / f"{stem}.wav"
            self.assertTrue(f.exists(), f"{stem}.wav missing for {text!r}")
            if n > 1:
                with wave.open(str(f)) as w:
                    self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 44100), stem)


class Builder(unittest.TestCase):
    def test_variants_enumerate_str_and_list_texts(self):
        m = {"phrases": {"your-move": {"text": ["Your move.", "Your turn to play."]},
                         "calculating": {"text": "Calculating."}}}
        self.assertEqual(bs.variants(m), [
            ("your-move", 1, "Your move.", "your-move"),
            ("your-move", 2, "Your turn to play.", "your-move-2"),
            ("calculating", 1, "Calculating.", "calculating"),
        ])

    def test_ids_selectors_pick_a_phrase_or_one_wording(self):
        self.assertTrue(bs.selected(None, "win", 3))
        self.assertTrue(bs.selected({"win"}, "win", 3))
        self.assertTrue(bs.selected({"win:3"}, "win", 3))
        self.assertFalse(bs.selected({"win:3"}, "win", 1))
        self.assertFalse(bs.selected({"taunt"}, "win", 1))

    def test_joshua_manifest_lists_four_wordings_for_the_nine_repeaters(self):
        J = json.loads((RUNNER / "voice" / "stock" / "manifest.json").read_text())
        nine = ("your-move", "calculating", "interesting", "ouch", "startup", "game-over-gg", "strange-game", "you-win", "player-eliminated")
        for pid in nine:
            self.assertIsInstance(J["phrases"][pid]["text"], list, pid)
            self.assertEqual(len(J["phrases"][pid]["text"]), 4, pid)
        self.assertEqual(J["phrases"]["your-move"]["text"][0], "Your move.", "wording 1 is the shipped file")
        self.assertEqual(J["phrases"]["startup"]["text"][0], "Would you like to play a game?", "Ben's own take stays wording 1")
        others = [pid for pid, ph in J["phrases"].items() if pid not in nine]
        self.assertTrue(all(isinstance(J["phrases"][p]["text"], str) for p in others), "the other 54 lines are unchanged")

    def test_joshua_defaults_are_the_original_settings(self):
        """The shipped manifest carries no render/bake block; the defaults must
        reproduce the 2026-09-07 takes exactly or a re-bake would change them."""
        m = {}
        self.assertEqual(bs.render_settings(m), ("eleven_v3", {"stability": 1.0, "speed": 0.92}, ("pcm_44100", "pcm_24000")))
        self.assertEqual(bs.bake_settings(m), {"rate": 44100, "fx": "chain", "glitch": "light", "target_lufs": -24.0, "true_peak_max": -1.0})
        self.assertEqual(bs.bake_settings(m, "off")["glitch"], "off")

    def test_bake_argv_chain_vs_none(self):
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td)
            (lib / "fx-chain.txt").write_text("volume=1.0\n")
            raw, tmp = lib / "raw" / "x.wav", lib / "x.tmp.wav"
            chain = bs.bake_argv(raw, tmp, lib, {}, bs.bake_settings({}))
            self.assertIn("volume=1.0", chain)
            self.assertEqual(chain[chain.index("-ar") + 1], "44100")
            clean = bs.bake_argv(raw, tmp, lib, {}, bs.bake_settings({"bake": {"fx": "none", "rate": 22050}}), gain_db=-7.25)
            self.assertIn("volume=-7.25dB", clean, "a plain gain, never loudnorm/compression (Ben: don't squash the delivery)")
            self.assertEqual(clean[clean.index("-ar") + 1], "22050")
            self.assertNotIn("volume=1.0", clean)

    def test_library_gain_is_one_number_and_the_peak_guard_is_per_take(self):
        # dry ElevenLabs takes measure about -17 LUFS; the Joshua library sits at -24.3
        measures = [(-16.9, -0.7), (-18.7, -1.9), (-17.6, -3.0), (-99.0, -99.0)]   # the last is silence: ignored
        g = bs.library_gain(measures, -24.0)
        self.assertAlmostEqual(g, -24.0 - (-16.9 - 18.7 - 17.6) / 3, places=2)
        self.assertLess(g, 0)
        # a shout keeps the same gain as a sigh (relative dynamics preserved)...
        self.assertEqual(bs.file_gain(g, -0.7, -1.0), g)
        self.assertEqual(bs.file_gain(g, -12.0, -1.0), g)
        # ...unless that one take would clip the ceiling after a POSITIVE library gain
        self.assertEqual(bs.file_gain(+4.0, -2.0, -1.0), 1.0)
        self.assertEqual(bs.library_gain([], -24.0), 0.0)

    def test_parse_loudnorm_reads_the_last_json_block(self):
        err = 'size=N/A time=00:00:02.1\n[Parsed_loudnorm_0 @ 0x1] \n{\n\t"input_i" : "-17.61",\n\t"input_tp" : "-3.02",\n\t"input_lra" : "5.1"\n}\ntrailing line\n'
        self.assertEqual(bs.parse_loudnorm(err), (-17.61, -3.02))

    def test_resolve_library_by_name_and_default(self):
        self.assertEqual(bs.resolve_library(""), bs.STOCK)
        self.assertEqual(bs.resolve_library(None), bs.STOCK)
        for lib in LIBS:
            self.assertEqual(bs.resolve_library(lib), VOICES / lib)
        with self.assertRaises(SystemExit):
            bs.resolve_library("no-such-voice")


if __name__ == "__main__":
    unittest.main()

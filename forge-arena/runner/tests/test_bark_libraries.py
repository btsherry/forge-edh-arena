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
LIBS = ("harry", "bill", "lily", "joshua")      # joshua: the fourth seat's voice for all-AI tables (Ben, 2026-09-16)
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
            self.assertEqual(len(these), 66, f"{lib}: 21 barks + 11 reactions + 19 replies + 15 patter lines")
            self.assertEqual((cats["bark"], cats["reaction"], cats["reply"], cats["patter"]), (21, 11, 19, 15), f"{lib}: {dict(cats)}")
            if ids is None:
                ids = these
            self.assertEqual(these, ids, f"{lib} must share the vocabulary, in the same order")
            for pid, ph in m["phrases"].items():
                self.assertIsInstance(ph["text"], list, f"{lib}/{pid}: wordings are a list")
                if ph.get("category") == "bark" or ph.get("source") == "elevenlabs-v3-2026-09-10-replies":
                    self.assertGreaterEqual(len(ph["text"]), 4, f"{lib}/{pid}: the barks and the first ten replies carry at least four wordings")
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
        ids = set(load("harry")["phrases"]) | set(json.loads((VOICES / "harry" / "table" / "manifest.json").read_text())["phrases"])
        roles = {"target", "aggressor", "bystander", "leader", "origin", "open"}
        for opener, opts in table["invites"].items():
            self.assertIn(opener, ids, f"chains.json invites from an unknown line {opener!r}")
            for o in opts:
                self.assertIn(o["role"], roles, o); self.assertIn(o["reply"], ids, o)
        for prefix, generic in table["families"].items():
            if prefix != "note":
                self.assertIn(generic, table["invites"], f"family {prefix!r} points at an opener without invites")
                self.assertTrue(any(k.startswith(prefix) for k in ids), f"family {prefix!r} matches no table line")
        self.assertNotIn("joshua_replies", table, "A14 (Ben, 2026-09-14): Joshua never answers a seat — the reply map is gone")
        tune = json.loads((VOICES / "tuning.json").read_text())             # the numbers moved to tuning.json (2026-09-16)
        self.assertTrue(0 < tune["chain_p"] <= 1 and 0 < tune["chain_decay"] <= 1 and tune["chain_max_hops"] >= 1)
        for k in ("first_hop_p", "decay", "max_hops", "gap_s", "human_trigger_mult"):
            self.assertNotIn(k, table, f"chains.json {k!r}: one source for the numbers — voices/tuning.json")

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
            if lib == "joshua":
                self.assertEqual((b["fx"], b["glitch"], b["rate"]), ("chain", "light", 22050), "Joshua keeps his mainframe chain and glitches at the table (Ben, 2026-09-16)")
                self.assertTrue((VOICES / lib / "fx-chain.txt").exists(), "the chain file sits beside his manifest")
            else:
                self.assertEqual((b["fx"], b["glitch"], b["rate"]), ("none", "off", 22050), f"{lib}: a seat voice stays clean and small")
            self.assertEqual((b["gain"], b["target_lufs"], b["true_peak_max"]), ("library", -24.0, -1.0), f"{lib}: library-relative gain to the Joshua level")
            self.assertTrue(m.get("temperament"), f"{lib}: the advisor's guide quotes the temperament")
        self.assertEqual(seats, {0, 1, 2, 3}, "joshua sits at seat 0 — voiced only when no human does")


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
                if (VOICES / lib / "raw").is_dir():                       # the dry takes left the tree 2026-09-17 (Ben): a re-bake re-renders
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
        deals = {p for p in others if J["phrases"][p].get("source") == "deals-2026-09-16"}
        self.assertEqual(deals, {"joshua-deal-yes", "joshua-deal-no", "joshua-deal-counter"}, "Executive's three deal answers (2026-09-16)")
        self.assertTrue(all(len(J["phrases"][p]["text"]) == 3 for p in deals), "three wordings each")
        self.assertTrue(all(isinstance(J["phrases"][p]["text"], str) for p in others if p not in deals), "the other 54 lines are unchanged")

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

    def test_tts_request_retries_transport_failures_and_gives_up_cleanly(self):
        """2026-09-11: a single 60 s socket timeout killed two Lily batches — now a take
        gets four attempts with a growing pause, and a lost take is skipped, not fatal."""
        import io
        import urllib.error

        class Resp(io.BytesIO):
            headers = {"character-cost": "23"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        calls, naps = [], []
        def opener(req, timeout):
            calls.append(timeout)
            if len(calls) < 3:
                raise TimeoutError("The read operation timed out")
            return Resp(b"pcm")
        self.assertEqual(bs.tts_request("req", opener=opener, sleep=naps.append), (b"pcm", 23))
        self.assertEqual((len(calls), naps), (3, [5.0, 10.0]), "two failures, two growing pauses, then the take")
        calls.clear(); naps.clear()
        def always(req, timeout):
            calls.append(1); raise urllib.error.URLError("dropped")
        self.assertIsNone(bs.tts_request("req", opener=always, sleep=naps.append))
        self.assertEqual((len(calls), len(naps)), (4, 3), "four attempts, then None — the caller skips the take")
        def http(req, timeout):
            raise urllib.error.HTTPError("u", 403, "forbidden", {}, io.BytesIO(b"tier"))
        with self.assertRaises(urllib.error.HTTPError):
            bs.tts_request("req", opener=http, sleep=naps.append)

    def test_resolve_library_by_name_and_default(self):
        self.assertEqual(bs.resolve_library(""), bs.STOCK)
        self.assertEqual(bs.resolve_library(None), bs.STOCK)
        for lib in LIBS:
            self.assertEqual(bs.resolve_library(lib), VOICES / lib)
        with self.assertRaises(SystemExit):
            bs.resolve_library("no-such-voice")


if __name__ == "__main__":
    unittest.main()


class TheFourthVoice(unittest.TestCase):
    """Ben, 2026-09-16: the fourth seat gets Joshua. His library sits at seat 0 and is assigned only when no human
    sits there; on a human table seat 0 is never voiced and the three seat voices keep their defaults."""

    def test_the_humans_seat_is_never_voiced_and_all_ai_seats_zero_speaks_as_joshua(self):
        sys.path.insert(0, str(RUNNER / "voice"))
        import table as T
        libs = T.load_libraries(VOICES)
        self.assertIn("joshua", libs); self.assertEqual(libs["joshua"]["seat"], 0)
        human = T.assign_voices(libs, None, {}, exclude_seat=0)
        self.assertEqual(sorted(human), [1, 2, 3], "a human table: three voices, seat 0 silent")
        self.assertNotIn("joshua", {v["library"] for v in human.values()})
        allai = T.assign_voices(libs, None, {}, exclude_seat=None)
        self.assertEqual({s: v["library"] for s, v in allai.items()}, {0: "joshua", 1: "harry", 2: "bill", 3: "lily"},
                         "game 55: four seats, three libraries doubled Harry; now the fourth is Joshua")
        by_deck = {"purphoros-god-of-the-forge": "harry"}
        assigned = T.assign_voices(libs, {1: "urza-lord-high-artificer", 2: "giada-font-of-hope", 3: "purphoros-god-of-the-forge"}, by_deck, exclude_seat=0)
        self.assertEqual(assigned[3]["library"], "harry", "Ben's deck association still wins")
        self.assertNotIn(0, assigned)

    def test_joshuas_table_and_card_libraries_cover_the_same_ids(self):
        for sub in ("table", "cards"):
            ref = json.loads((VOICES / "harry" / sub / "manifest.json").read_text())["phrases"]
            j = json.loads((VOICES / "joshua" / sub / "manifest.json").read_text())["phrases"]
            self.assertEqual(list(j), list(ref), f"{sub}: the same ids in the same order")
            for pid, ph in j.items():
                self.assertTrue(ph["text"] and all(TAG_RE.match(t) for t in ph["text"]), f"joshua/{sub}/{pid}")


class TheTableAtStartup(unittest.TestCase):
    """Game 56: the all-AI voice runner seats roster[i] at seat i from the first line, and Ben's associations
    (Purphoros eager, Urza cool, Giada warm, Selvala Joshua) decide who speaks as whom."""

    def test_the_launcher_roster_seats_four_decks_and_the_associations_place_the_voices(self):
        sys.path.insert(0, str(RUNNER / "voice"))
        import table as T
        roster = "urza-lord-high-artificer giada-font-of-hope purphoros-god-of-the-forge selvala-heart-of-the-wilds"
        decks = T.table_from_launcher("", roster, all_ai=True)
        self.assertEqual(decks, {0: "urza-lord-high-artificer", 1: "giada-font-of-hope", 2: "purphoros-god-of-the-forge", 3: "selvala-heart-of-the-wilds"})
        self.assertEqual(T.table_from_launcher("selvala-heart-of-the-wilds", roster, all_ai=False),
                         {1: "urza-lord-high-artificer", 2: "giada-font-of-hope", 3: "purphoros-god-of-the-forge"}, "a human table: the roster minus the human's deck")
        by_deck = T.load_assignments(VOICES)
        self.assertEqual(by_deck["selvala-heart-of-the-wilds"], "joshua", "Ben, 2026-09-16: Selvala gets Joshua as an association")
        voices = T.assign_voices(T.load_libraries(VOICES), decks, by_deck, exclude_seat=None)
        self.assertEqual({s: v["library"] for s, v in sorted(voices.items())}, {0: "bill", 1: "lily", 2: "harry", 3: "joshua"},
                         "all-AI: Urza cool, Giada warm, Purphoros eager, Selvala Joshua — from the first line, no mid-game switch")
        human = T.assign_voices(T.load_libraries(VOICES), T.table_from_launcher("giada-font-of-hope", roster, all_ai=False), by_deck, exclude_seat=0)
        self.assertNotIn("joshua", {v["library"] for v in human.values()}, "a human table: Selvala at an AI seat takes a free seat voice, never Joshua")

"""Round 31 card lines (experimental/voicework2, 2026-09-10) — the "cards" sub-library
(runner/voice/card_lines.py): every game changer, commander and combo shape on disk
has lines in the three registers, grounded in the oracle text on record. The runner
keeps its generic hooks and swaps in the named wording when the ctx names the card:
the caster's line, the reply it invites, the relief when it leaves, the commander's
arrival and death, the combo's last piece (owner crows, table alarms), the human's
game changers and commander included.
Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "voice"))
import voice_runner as vr  # noqa: E402
import card_lines as cl  # noqa: E402
from test_barks_runtime import silent_wav  # noqa: E402
from test_table_lines import _TableCase, REAL_VOICES, LIBS  # noqa: E402


def real_cards(lib="harry") -> dict:
    return json.loads((REAL_VOICES / lib / "cards" / "manifest.json").read_text())


class CardLibraries(unittest.TestCase):
    def test_coverage_of_the_record_and_one_vocabulary(self):
        self.assertEqual(cl.coverage(), [], "every game changer, commander and combo shape on disk has lines")
        ids = None
        for lib in LIBS:
            m = real_cards(lib)
            parent = json.loads((REAL_VOICES / lib / "manifest.json").read_text())
            self.assertEqual((m["library"], m["parent"], m["voice_id"], m["render"], m["bake"]), (f"{lib}/cards", lib, parent["voice_id"], parent["render"], parent["bake"]))
            these = list(m["phrases"]); ids = ids or these
            self.assertEqual(these, ids, lib)
            for pid, ph in m["phrases"].items():
                self.assertIn(ph["category"], ("card", "commander", "combo"), pid)
                self.assertTrue(ph.get("card") and ph.get("when"), pid)
                for t in ph["text"]:
                    self.assertRegex(t, r"^\[[a-z ]+\] \S", f"{lib}/{pid}: {t!r}")
                    self.assertLessEqual(len(t.split("]", 1)[1].split()), 10, f"{lib}/{pid}: {t!r}")
                self.assertEqual(len(set(ph["text"])), len(ph["text"]), pid)
        for name in cl.game_changers_on_disk():
            slug = cl.card_slug(name)
            self.assertEqual(slug, vr.card_slug(name), "the runner and the generator agree on the slug")
            for part, n in (("cast", 2), ("react", 2), ("gone", 1)):
                self.assertIn(f"gc-{slug}-{part}", ids); self.assertEqual(len(real_cards()["phrases"][f"gc-{slug}-{part}"]["text"]), n, f"{slug}-{part}")
        for who in set(cl.commanders_on_disk().values()):
            for part in ("cast", "react", "dead"):
                self.assertIn(f"cmd-{who}-{part}", ids)
        combos = json.loads((REAL_VOICES / "combos.json").read_text())["combos"]
        for key, sets in combos.items():
            self.assertIn(f"combo-{key}-online", ids); self.assertIn(f"combo-{key}-react", ids)
            self.assertTrue(all(1 < len(s) <= 3 for s in sets), key)
        self.assertEqual(sum(len(s) for s in combos.values()), 60, "the sixty <=3-piece combos in the dossiers")
        self.assertEqual(vr.card_slug("Tergrid, God of Fright // Tergrid's Lantern"), "tergrid-god-of-fright")
        self.assertEqual(vr.card_slug("The One Ring"), "the-one-ring"); self.assertEqual(vr.card_slug("Gaea's Cradle"), "gaea-s-cradle")

    def test_combo_index_and_deck_combos(self):
        idx = vr.load_combo_index()
        self.assertEqual(idx[frozenset({"Hullbreaker Horror", "Sol Ring"})], "hullbreaker")
        self.assertEqual(idx[frozenset({"Ondu Spiritdancer", "Secret Arcade"})], "spiritdancer-arcade", "front-face names")
        urza = vr.deck_combos_of("urza-lord-high-artificer", idx)
        self.assertTrue(urza and all(key for _, key in urza), f"every Urza combo has a line key: {urza}")
        self.assertIn((frozenset({"Dramatic Reversal", "Isochron Scepter"}), "dramatic-scepter"), urza)
        self.assertIn((frozenset({"Sol Ring", "Tidespout Tyrant"}), "tidespout"), urza, "a piece the record puts in hand still counts once it is on the board")
        self.assertEqual(vr.deck_combos_of("no-such-deck", idx), [])
        self.assertEqual(vr.load_combo_index(Path("/nowhere")), {})


class RenderedCards(unittest.TestCase):
    """Every card wording of every voice is a baked take in the runner's format, with its dry take kept."""

    def test_every_card_wording_is_a_baked_wav(self):
        import wave
        for lib in LIBS:
            n = 0
            for pid, ph in real_cards(lib)["phrases"].items():
                for i, text in enumerate(ph["text"], 1):
                    stem = pid if i == 1 else f"{pid}-{i}"
                    f = REAL_VOICES / lib / "cards" / f"{stem}.wav"
                    self.assertTrue(f.exists(), f"{lib}/cards/{stem}.wav missing for {text!r}")
                    with wave.open(str(f)) as w:
                        self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 22050), f"{lib}/cards/{stem}")
                        secs = w.getnframes() / w.getframerate()
                        self.assertTrue(0.4 <= secs <= 8.0, f"{lib}/cards/{stem}: {secs:.1f}s")   # Bill's slowest ten-word line runs 7.3 s
                    self.assertTrue((REAL_VOICES / lib / "cards" / "raw" / f"{stem}.wav").exists(), f"{lib}/cards/raw/{stem}.wav")
                    n += 1
            self.assertEqual(n, 264, lib)


class CardRuntime(_TableCase):
    def setUp(self):
        super().setUp()
        ids = list(real_cards()["phrases"])
        for lib in ("harry", "bill"):
            d = vr.VOICES_DIR / lib / "cards"; d.mkdir()
            (d / "manifest.json").write_text(json.dumps({"schema": "arena.voice-stock/1", "library": f"{lib}/cards", "phrases": {pid: {"text": ["x"]} for pid in ids}}))
            for pid in ids:
                (d / f"{pid}.wav").write_bytes(silent_wav())
        (vr.VOICES_DIR / "combos.json").write_text((REAL_VOICES / "combos.json").read_text())
        self.r = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock)
        self.r.rng.random = lambda: 0.0
        self.r.rng.shuffle = lambda x: None
        self.r.game_changers[1] = {"Rhystic Study", "Mana Vault"}
        self.r.game_changers[0] = {"Smothering Tithe"}

    def _prime(self):
        self._snap(3, 1, events=[{"seq": 1, "kind": "cast", "turn": 2, "seat": 1, "spell": "x", "cmc": 1}]); self.r.queue.clear()
        return [{"seq": 1, "kind": "cast", "turn": 2, "seat": 1, "spell": "x", "cmc": 1}]

    def test_game_changer_and_commander_lines_replace_the_generic_ones_and_their_replies(self):
        ev = self._prime()
        ev.append({"seq": 2, "kind": "cast", "turn": 3, "seat": 1, "spell": "Rhystic Study", "commander": False, "cmc": 3})
        self._snap(3, 1, events=ev)
        q = [x for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual([(x["stock"], x["library"], x["ctx"]["generic"], x["ctx"]["card"]) for x in q], [("gc-rhystic-study-cast", "harry/cards", "game-changer", "rhystic-study")])
        self.assertIn((1, "game-changer"), self.r._said_this_turn)
        item = q[0]; self.r.queue.clear()
        self.r.rng.random = lambda: 0.01
        self.r.after_spoken(item)
        self.assertEqual(self._barks(), [("gc-rhystic-study-react", "bill/cards", 2)], "the reply the generic line invites, in the card's words")
        ev.append({"seq": 3, "kind": "cast", "turn": 4, "seat": 1, "spell": "Urza, Lord High Artificer", "commander": True, "cmc": 4})
        self._snap(4, 1, events=ev)
        q = [x for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual([(x["stock"], x["library"]) for x in q], [("cmd-urza-cast", "harry/cards")])
        item = q[0]; self.r.queue.clear()
        self.r.after_spoken(item)
        self.assertEqual(self._barks(), [("cmd-urza-react", "bill/cards", 2)])
        ev.append({"seq": 4, "kind": "left", "turn": 5, "by": 2, "cards": ["Mana Vault"], "seats": [1], "commanders": [], "n": 1, "tokens": 0})
        self._snap(5, 2, events=ev)
        got = self._barks()
        self.assertIn(("gc-mana-vault-gone", "bill/cards", 2), got, f"the relief is Bill's, in the card's words: {got}")
        ev.append({"seq": 5, "kind": "left", "turn": 6, "by": 0, "cards": ["Urza, Lord High Artificer"], "seats": [1], "commanders": ["Urza, Lord High Artificer"], "n": 1, "tokens": 0})
        self._snap(6, 0, events=ev)
        self.assertEqual(self._barks(), [("cmd-urza-dead", "harry/cards", 1)])

    def test_the_humans_game_changer_and_commander_draw_the_cards_reaction(self):
        ev = self._prime()
        ev.append({"seq": 2, "kind": "cast", "turn": 3, "seat": 0, "spell": "Smothering Tithe", "commander": False, "cmc": 4})
        self._snap(3, 0, events=ev)
        got = self._barks()
        self.assertEqual(len(got), 1); self.assertEqual(got[0][0], "gc-smothering-tithe-react"); self.assertTrue(got[0][1].endswith("/cards"))
        ev.append({"seq": 3, "kind": "cast", "turn": 4, "seat": 0, "spell": "Giada, Font of Hope", "commander": True, "cmc": 2})
        self._snap(4, 0, events=ev)
        got = self._barks()
        self.assertEqual([g[0] for g in got], ["cmd-giada-react"])

    def test_the_last_combo_piece_is_announced_once_and_the_table_alarms(self):
        seats = [self._seat(0), self._seat(1, extra=("Hullbreaker Horror", "Sol Ring")), self._seat(2), self._seat(3)]
        self._snap(3, 1, seats=seats)
        q = [x for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual([(x["stock"], x["library"], x["ctx"]["generic"]) for x in q], [("combo-hullbreaker-online", "harry/cards", "engine-online")])
        item = q[0]; self.r.queue.clear()
        self.r.rng.random = lambda: 0.01
        self.r.after_spoken(item)
        self.assertEqual(self._barks(), [("combo-hullbreaker-react", "bill/cards", 2)], "engine-online invites the leader's scoff: it becomes the combo's alarm")
        self._snap(3, 1, seats=seats)
        self.assertEqual(self._barks(), [], "announced once")
        self.r.rng.random = lambda: 0.0
        seats[1]["battlefield"].append({"name": "Mana Vault", "types": "Artifact", "tapped": False})
        self._snap(3, 1, seats=seats)
        self.assertEqual(self._barks(), [], "Hullbreaker + Vault is the same shape: not announced again")
        seats[1]["battlefield"].append({"name": "Isochron Scepter", "types": "Artifact", "tapped": False, "imprinted": ["Dramatic Reversal"]})
        self._snap(3, 1, seats=seats)
        self.assertEqual(self._barks(), [("combo-dramatic-scepter-online", "harry/cards", 1)], "a different shape is a new announcement; the imprinted card counts")
        # the human's board: a bystander raises it
        seats[0]["battlefield"] += [{"name": "Heliod, Sun-Crowned", "types": "Legendary Creature", "tapped": False, "power": 5}, {"name": "Walking Ballista", "types": "Artifact Creature", "tapped": False, "power": 2}]
        self._snap(4, 0, seats=seats)
        got = self._barks()
        self.assertEqual([g[0] for g in got], ["combo-heliod-ballista-react"]); self.assertTrue(got[0][1].endswith("/cards"))

    def test_the_advisors_commander_tag_takes_the_seats_own_commander_line(self):
        """Game 46: the advisor tagged commander-cast for Purphoros and the generic line played beside Giada's named one."""
        with (self.logs / "advisor-0.jsonl").open("a") as f:
            f.write(json.dumps({"ts": 1.0, "kind": "bark", "seat": 1, "id": "commander-cast", "turn": 4, "with": "color"}) + "\n")
            f.write(json.dumps({"ts": 1.0, "kind": "bark", "seat": 2, "id": "big-swing", "turn": 4, "with": "color"}) + "\n")
        self.r.scan_advisor()
        self.assertEqual([(q["stock"], q["library"]) for q in self.r.queue if q["kind"] == "bark"], [("big-swing", "bill")], "newest tag wins the one pending slot")
        self.r.queue.clear(); self.r._roll_turn(5)
        with (self.logs / "advisor-0.jsonl").open("a") as f:
            f.write(json.dumps({"ts": 2.0, "kind": "bark", "seat": 1, "id": "commander-cast", "turn": 5, "with": "color"}) + "\n")
        self.r.scan_advisor()
        self.assertEqual([(q["stock"], q["library"]) for q in self.r.queue if q["kind"] == "bark"], [("cmd-urza-cast", "harry/cards")])

    def test_a_recast_is_no_crow_a_self_bounce_is_no_relief_and_the_second_round_is_a_loop(self):
        """Game 47, turn 20: Urza bounced his own Mana Vault with Hullbreaker Horror and recast it six
        times; Harry and Lily gave relief lines ("Vault's gone!") and Bill crowed "Mana Vault. Three
        mana, now." each turn. A self-caused departure is never relief, a recast is never a crow, and
        the second round of the same card in a turn is a loop with its own line."""
        ev = self._prime()
        ev.append({"seq": 2, "kind": "cast", "turn": 3, "seat": 1, "spell": "Mana Vault", "commander": False, "cmc": 1})
        self._snap(3, 1, events=ev)
        self.assertEqual(self._barks(), [("gc-mana-vault-cast", "harry/cards", 1)], "the first cast of the game: the crow")
        ev.append({"seq": 3, "kind": "left", "turn": 3, "by": 1, "cards": ["Mana Vault"], "seats": [1], "commanders": [], "n": 1, "tokens": 0})
        self._snap(3, 1, events=ev)
        got = self._barks()
        self.assertEqual([g[0] for g in got], ["loop", "looping"], f"the owner bounced it: no relief; cast + self-bounce = the second round = a loop: {got}")
        self.assertEqual((got[0][1], got[0][2], got[1][1], got[1][2]), ("bill/table", 2, "harry/table", 1))
        ev.append({"seq": 4, "kind": "cast", "turn": 3, "seat": 1, "spell": "Mana Vault", "commander": False, "cmc": 1})
        ev.append({"seq": 5, "kind": "left", "turn": 3, "by": 1, "cards": ["Mana Vault"], "seats": [1], "commanders": [], "n": 1, "tokens": 0})
        self._snap(3, 1, events=ev)
        self.assertEqual(self._barks(), [], "rounds three and four: quiet — the loop was called once")
        self.assertEqual(self.r._card_events_turn[(1, "Mana Vault")], 4)
        # next turn: a recast is still no crow (the table has met the card), and the loop line is rare
        self.r._casts[1] = []                                                # (no flurry in this instant)
        ev.append({"seq": 6, "kind": "cast", "turn": 7, "seat": 1, "spell": "Mana Vault", "commander": False, "cmc": 1})
        self._snap(7, 1, events=ev)
        self.assertEqual(self._barks(), [], "a recast the next turn: no crow")
        self.assertEqual(self.r._card_events_turn.get((1, "Mana Vault")), 1, "the per-turn count rolled")
        # an OPPONENT removing it is still relief
        ev.append({"seq": 7, "kind": "left", "turn": 7, "by": 2, "cards": ["Mana Vault"], "seats": [1], "commanders": [], "n": 1, "tokens": 0})
        self._snap(7, 1, events=ev)
        self.assertEqual(self._barks(), [("gc-mana-vault-gone", "bill/cards", 2)])
        # the human's recast of a game changer: the alarm sounds once
        self.r._roll_turn(8)
        ev.append({"seq": 8, "kind": "cast", "turn": 8, "seat": 0, "spell": "Smothering Tithe", "commander": False, "cmc": 4})
        self._snap(8, 0, events=ev)
        self.assertEqual([g[0] for g in self._barks()], ["gc-smothering-tithe-react"])
        self.r._roll_turn(12)
        ev.append({"seq": 9, "kind": "cast", "turn": 12, "seat": 0, "spell": "Smothering Tithe", "commander": False, "cmc": 4})
        self._snap(12, 0, events=ev)
        self.assertEqual(self._barks(), [], "recast: the table has met it")

    def test_without_the_take_or_the_library_the_generic_line_stays(self):
        (vr.VOICES_DIR / "harry" / "cards" / "gc-rhystic-study-cast.wav").unlink()
        ev = self._prime()
        ev.append({"seq": 2, "kind": "cast", "turn": 3, "seat": 1, "spell": "Rhystic Study", "commander": False, "cmc": 3})
        self._snap(3, 1, events=ev)
        self.assertEqual(self._barks(), [("game-changer", "harry", 1)])
        for lib in ("harry", "bill"):
            for f in (vr.VOICES_DIR / lib / "cards").iterdir():
                f.unlink()
            (vr.VOICES_DIR / lib / "cards").rmdir()
        r = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock)
        self.assertEqual(r.card_ids, set())
        self.assertEqual(r.card_swap(1, "game-changer", {"card": "rhystic-study", "card_kind": "gc"}), "")
        self.assertEqual(r.lib_for(1, "gc-rhystic-study-cast"), "harry")


if __name__ == "__main__":
    unittest.main()

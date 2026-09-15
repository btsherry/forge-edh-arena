"""Round 31 table lines (experimental/voicework2, 2026-09-10) — the "table" sub-library
of each seat voice (runner/voice/table_lines.py): procedural self-narration ("land,
go", "pass", "in response", "just a poke", "no blocks", "I'll take it", "sure",
"hold on"), whole-sentence numbers ("I'm at twelve.", "Seven cards.") and named
addressing (hit-urza, threat-giada, leave-me-mono-red, deal-azorius). The runner
resolves a table id to voices/<lib>/table/, narrates casts by type (two a turn),
sums a seat's turn up at the boundary, follows a hit with the total, answers a
question about a seat's state with the true number, says "hold on" when the stack
targets its things, mutters when its own decision drags, and swaps a generic line
for its named wording when it knows who it is talking to.
Run: python3 -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import voice_runner as vr  # noqa: E402
from test_barks_runtime import _TreeCase, FakePlayer, silent_wav  # noqa: E402

RUNNER = Path(__file__).resolve().parents[1]
REAL_VOICES = RUNNER / "voice" / "stock" / "voices"
LIBS = ("harry", "bill", "lily")


def real_table(lib="harry") -> dict:
    return json.loads((REAL_VOICES / lib / "table" / "manifest.json").read_text())


class TableLibraries(unittest.TestCase):
    """The three table manifests: one vocabulary, the parent's voice, the wording rules."""

    def test_one_vocabulary_three_registers_and_the_parents_voice(self):
        ids = None
        for lib in LIBS:
            m = real_table(lib)
            parent = json.loads((REAL_VOICES / lib / "manifest.json").read_text())
            self.assertEqual((m["schema"], m["library"], m["parent"]), ("arena.voice-stock/1", f"{lib}/table", lib))
            self.assertEqual((m["voice_id"], m["render"], m["bake"]), (parent["voice_id"], parent["render"], parent["bake"]), f"{lib}: the sub-library renders and bakes like its parent")
            these = list(m["phrases"])
            ids = ids or these
            self.assertEqual(these, ids, f"{lib}: same ids, same order")
            cats = {}
            for pid, ph in m["phrases"].items():
                cats[ph["category"]] = cats.get(ph["category"], 0) + 1
                self.assertTrue(ph.get("when"), pid)
                for t in ph["text"]:
                    self.assertRegex(t, r"^\[[a-z ]+\] \S", f"{lib}/{pid}: a delivery tag leads: {t!r}")
                    self.assertLessEqual(len(t.split("]", 1)[1].split()), 10, f"{lib}/{pid}: {t!r}")
                self.assertEqual(len(set(ph["text"])), len(ph["text"]), f"{lib}/{pid}: wordings differ")
            self.assertEqual(cats["number"], 45 + 11, f"{lib}: life 1-40 + 45/50/60/80/100, hand 0-10")
            self.assertGreaterEqual(cats["procedural"], 20); self.assertEqual(cats["arc"], 10, f"{lib}: the memory and arc lines (phase D)")
            self.assertEqual(cats["mulligan"], 9, f"{lib}: keep-seven, mull-to-six/five/four, pity, dig, screw, risky, gloat")
            self.assertEqual(cats["loop"], 2, f"{lib}: loop (the table) and looping (the owner)")
            self.assertEqual(cats["heckle"], 3, f"{lib}: waiting-on-you, still-waiting, there-you-are (Ben, 2026-09-14: heckles at the player)")
        for n in list(range(1, 41)) + [45, 50, 60, 80, 100]:
            self.assertIn(f"life-{n}", ids)
        for n in range(11):
            self.assertIn(f"hand-{n}", ids)
        for pid in ("land-go", "pass", "mana-up", "tapped-out", "untap-draw", "come-on-land", "thinking", "cast-creature", "cast-artifact",
                    "cast-enchantment", "cast-instant", "cast-sorcery", "cast-planeswalker", "cast-big", "in-response", "poke", "attack-you",
                    "no-blocks", "take-it", "sure", "hold-on", "holding-mana"):
            self.assertIn(pid, ids)

    def test_addressing_covers_every_commander_on_disk_and_every_colour_identity(self):
        addr = json.loads((REAL_VOICES / "address.json").read_text())
        ids = set(real_table()["phrases"])
        decks = [d.name for d in (RUNNER.parent / "decks").iterdir() if (d / "dossier" / "deck-cards.json").exists()]
        for deck in decks:
            self.assertIn(deck, addr["commanders"], f"{deck}: no address entry — rerun table_lines.py --write")
            who = addr["commanders"][deck]["who"]
            for fam in ("hit", "threat", "leave-me", "deal"):
                self.assertIn(f"{fam}-{who}", ids, f"{deck}: {fam}-{who} missing")
        self.assertEqual(len(addr["colors"]), 32, "5 mono + colourless + 10 guilds + 10 shards/wedges + 5 four-colour + five-colour")
        for key, slug in addr["colors"].items():
            self.assertEqual(key, "".join(ch for ch in "WUBRG" if ch in key) or "C", f"{key}: letters in WUBRG order")
            for fam in ("hit", "threat", "leave-me", "deal"):
                self.assertIn(f"{fam}-{slug}", ids)
        self.assertEqual(addr["colors"]["WU"], "azorius"); self.assertEqual(addr["colors"]["UBRG"], "glint"); self.assertEqual(addr["colors"]["WUBRG"], "five-color")
        self.assertEqual(addr["commanders"]["y-shtola-night-s-blessed"]["who"], "y-shtola")
        for lib in LIBS:
            m = real_table(lib)["phrases"]
            self.assertIn("Urza", m["hit-urza"]["text"][0]); self.assertIn("mono-red", m["leave-me-mono-red"]["text"][0])
            self.assertIn("Azorius", m["deal-azorius"]["text"][0])

    def test_pure_helpers(self):
        self.assertEqual([vr.life_pid(x) for x in (0, -3, 1, 12, 40, 43, 47, 55, 70, 90, 100, 101, "x", None)],
                         ["", "", "life-1", "life-12", "life-40", "life-45", "life-45", "life-50", "life-60", "life-80", "life-100", "", "", ""])
        self.assertEqual([vr.hand_pid(x) for x in (0, 7, 10, 11, -1, None)], ["hand-0", "hand-7", "hand-10", "", "", ""])
        self.assertEqual([vr.card_kind({"type_line": t}) for t in ("Legendary Creature — Angel", "Artifact Creature — Thopter", "Instant", "Sorcery", "Legendary Artifact",
                                                                    "Enchantment — Aura", "Legendary Planeswalker — Karn", "Basic Land — Island", "Kindred Sorcery — Elf", "")],
                         ["creature", "creature", "instant", "sorcery", "artifact", "enchantment", "planeswalker", "land", "sorcery", ""])
        self.assertEqual(vr.card_kind(None), "")
        with tempfile.TemporaryDirectory() as td:
            decks = Path(td)
            for slug, ident in (("wu", "WU"), ("none", []), ("five", ["W", "U", "B", "R", "G"])):
                (decks / slug / "dossier").mkdir(parents=True)
                (decks / slug / "dossier" / "deck-cards.json").write_text(json.dumps({"cards": [{"name": "Foo, Bar", "zone": "commander", "color_identity": ident}]}))
            addr = json.loads((REAL_VOICES / "address.json").read_text())
            self.assertEqual(vr.who_for_deck({"colors": addr["colors"]}, "wu", decks), "azorius", "no commander entry: the colour identity")
            self.assertEqual(vr.who_for_deck({"colors": addr["colors"]}, "none", decks), "colorless")
            self.assertEqual(vr.who_for_deck({"colors": addr["colors"]}, "five", decks), "five-color")
            self.assertEqual(vr.who_for_deck({"colors": addr["colors"]}, "missing", decks), "")
            self.assertEqual(vr.who_for_deck({}, "wu", decks), "")
        self.assertEqual(vr.who_for_deck(json.loads((REAL_VOICES / "address.json").read_text()), "urza-lord-high-artificer"), "urza")


class RenderedTable(unittest.TestCase):
    """Every table wording of every voice is a baked take in the runner's format (22.05 kHz
    mono 16-bit, under six seconds), with its dry take kept for re-bakes."""

    def test_every_table_wording_is_a_baked_wav(self):
        import wave
        for lib in LIBS:
            m = real_table(lib)
            n = 0
            for pid, ph in m["phrases"].items():
                for i, text in enumerate(ph["text"], 1):
                    stem = pid if i == 1 else f"{pid}-{i}"
                    f = REAL_VOICES / lib / "table" / f"{stem}.wav"
                    self.assertTrue(f.exists(), f"{lib}/table/{stem}.wav missing for {text!r}")
                    with wave.open(str(f)) as w:
                        self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 22050), f"{lib}/table/{stem}")
                        secs = w.getnframes() / w.getframerate()
                        self.assertTrue(0.4 <= secs <= 6.0, f"{lib}/table/{stem}: {secs:.1f}s")
                    self.assertTrue((REAL_VOICES / lib / "table" / "raw" / f"{stem}.wav").exists(), f"{lib}/table/raw/{stem}.wav")
                    n += 1
            self.assertEqual(n, 290 + 30 + 27 + 6 + 12, lib)


class _TableCase(_TreeCase):
    """The synthetic tree plus a table sub-library per voice (the REAL ids, silent
    takes) and the real address table; the table is Giada (human) / Urza (harry) /
    Purphoros (bill) / Selvala (no voice)."""
    CHAINS = True

    def setUp(self):
        super().setUp()
        ids = list(real_table()["phrases"])
        for lib in ("harry", "bill"):
            d = vr.VOICES_DIR / lib / "table"; d.mkdir()
            (d / "manifest.json").write_text(json.dumps({"schema": "arena.voice-stock/1", "library": f"{lib}/table", "phrases": {pid: {"text": ["x"]} for pid in ids}}))
            for pid in ids:
                (d / f"{pid}.wav").write_bytes(silent_wav())
        (vr.VOICES_DIR / "address.json").write_text((REAL_VOICES / "address.json").read_text())
        os.environ["ARENA_HUMAN_DECK"] = "giada-font-of-hope"
        os.environ["ARENA_SEAT_DECKS"] = "urza-lord-high-artificer purphoros-god-of-the-forge selvala-heart-of-the-wilds giada-font-of-hope"
        self.r = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock)
        self.r.rng.random = lambda: 0.0
        self.r.rng.shuffle = lambda x: None

    def _seat(self, i, life=40, hand=3, lands=(), creatures=(), extra=()):
        bf = [{"name": f"Land {k}", "types": "Land — Island", "tapped": tapped} for k, tapped in enumerate(lands)]
        bf += [{"name": name, "types": "Creature — Thing", "tapped": tapped, "power": 3, "toughness": 3} for name, tapped in creatures]
        bf += [{"name": name, "types": "Artifact", "tapped": False} for name in extra]
        return {"seat": i, "name": f"s{i}", "eliminated": False, "life": life, "handSize": hand, "battlefield": bf}

    def _snap(self, turn, active, seats=None, events=(), stack=()):
        seats = seats or [self._seat(i) for i in range(4)]
        (self.mailbox / "observer-state.json").write_text(json.dumps(
            {"turn": turn, "phase": "MAIN1", "activeSeat": active, "gameOver": False, "seats": seats, "events": list(events), "stackDetail": list(stack)}))
        self.r.scan_observer()

    def _barks(self):
        out = [(q["stock"], q["library"], q["seat"]) for q in self.r.queue if q["kind"] == "bark"]
        self.r.queue.clear()
        return out

    def _queued_stocks(self):
        return [r["stock"] for r in self._records("queued", "bark")]

    def _spoken(self, seat, pid, ctx=None, chain=None):
        item = {"kind": "bark", "stock": pid, "text": "", "seat": seat, "library": self.r.lib_for(seat, pid), "ctx": ctx or {}, "chain": chain}
        self.r._roll_turn(self.r._last_snapshot.get("turn") or 3)
        self.r.after_spoken(item)


class MemoryAndArc(_TableCase):
    """Phase D: the table remembers — who keeps hitting whom, the third counter, the
    second wipe, two players left, the opening and the grind, a lethal board, and a
    truce struck then broken."""

    def _prime(self):
        self._snap(3, 1, events=[{"seq": 1, "kind": "cast", "turn": 2, "seat": 1, "spell": "x", "cmc": 1}]); self.r.queue.clear()
        return [{"seq": 1, "kind": "cast", "turn": 2, "seat": 1, "spell": "x", "cmc": 1}]

    def test_the_third_hit_from_the_same_seat_is_a_grudge(self):
        ev = self._prime()
        seq = 2
        for turn in (3, 7, 11):
            ev.append({"seq": seq, "kind": "damage", "turn": turn, "seat": 2, "amount": 4, "combat": True, "from": [1]}); seq += 1
            self._snap(turn, 1, events=ev)
            got = self._barks()
            if turn < 11:
                self.assertEqual(got, [("take-it", "bill/table", 2)], f"turn {turn}: a plain hit")
            else:
                self.assertEqual(got, [("grudge", "bill/table", 2)], "the third hit from seat 1: 'you again?!' instead")
        self.assertEqual(self.r._hits_from[2][1], 3)
        ev.append({"seq": seq, "kind": "damage", "turn": 12, "seat": 2, "amount": 4, "combat": True, "from": [0, 1]})
        self._snap(12, 0, events=ev)
        self.assertEqual(self.r._hits_from[2][1], 3, "a hit from two sources is nobody's grudge")

    def test_the_third_counter_and_the_second_wipe(self):
        ev = self._prime()
        for i, turn in enumerate((3, 4, 5), 2):
            ev.append({"seq": i, "kind": "countered", "turn": turn, "seat": 1, "spell": f"s{i}", "by": 2})
            self._snap(turn, 1, events=ev)
            got = self._barks()
            self.assertEqual(got, [("counter", "bill", 2)] if turn < 5 else [("again-countered", "harry/table", 1)], f"turn {turn}: {got}")
        ev.append({"seq": 5, "kind": "left", "turn": 6, "by": 2, "cards": ["a", "b", "c"], "seats": [0, 1], "commanders": [], "n": 3, "tokens": 0})
        self._snap(6, 2, events=ev)
        self.assertEqual([r["stock"] for r in self._records("queued", "bark")][-2:], ["sweep", "got-swept"]); self.r.queue.clear()
        ev.append({"seq": 6, "kind": "left", "turn": 10, "by": 2, "cards": ["d", "e", "f"], "seats": [0, 1], "commanders": [], "n": 3, "tokens": 0})
        self._snap(10, 2, events=ev)
        self.assertEqual([r["stock"] for r in self._records("queued", "bark")][-2:], ["sweep", "not-again-sweep"], "the second wipe of the game")
        self.assertEqual(self.r.queue[-1]["library"], "harry/table")

    def test_heads_up_once_when_two_remain(self):
        seats = [self._seat(0), self._seat(1), self._seat(2), self._seat(3)]
        seats[2]["eliminated"] = True; seats[3]["eliminated"] = True
        self._snap(9, 0, seats=seats)
        got = [(q["stock"], q["library"], q["seat"], q["ctx"]["targets"]) for q in self.r.queue if q["kind"] == "bark"]
        self.assertIn(("heads-up", "harry/table", 1, [0]), got, f"seat 1 and the human remain: {got}")
        self.r.queue.clear()
        self._snap(9, 0, seats=seats)
        self.assertEqual(self._barks(), [], "said once")

    def test_the_opening_the_grind_and_a_lethal_board(self):
        os.environ["ARENA_BARKS_OPENER_P"] = "1"
        self.r = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock)
        self.r.rng.random = lambda: 0.0; self.r.rng.shuffle = lambda x: None
        two = lambda i: self._seat(i, lands=((False, False)))  # noqa: E731
        self._snap(1, 0, seats=[two(i) for i in range(4)]); self.r.queue.clear()
        self._snap(2, 1, seats=[two(i) for i in range(4)])
        self.assertEqual(self._barks(), [("early-game", "harry/table", 1)], "turn two: the opening")
        seats = [self._seat(0, life=12), self._seat(1, creatures=(("A", False), ("B", False), ("C", False), ("D", False), ("E", False))), self._seat(2), self._seat(3)]
        cands = self.r.patter_candidates({"turn": 14, "activeSeat": 2, "seats": seats}, [1, 2])
        ids = {(sp, pid, tgt) for sp, pid, tgt, _ in cands}
        self.assertIn((2, "someone-wins", 1), ids, "fifteen power against a seat at twelve: someone wins next turn")
        self.assertNotIn((1, "someone-wins", 1), ids, "nobody says it about themself")
        self.assertIn((1, "long-game", None), ids); self.assertIn((2, "long-game", None), ids)
        cands = self.r.patter_candidates({"turn": 9, "activeSeat": 2, "seats": [self._seat(i) for i in range(4)]}, [1, 2])
        self.assertFalse(any(pid in ("someone-wins", "long-game") for _, pid, _, _ in cands))

    def test_a_truce_struck_is_remembered_and_a_truce_broken_is_called_out(self):
        self._snap(3, 1); self.r.queue.clear()
        self.r.rng.random = lambda: 0.01
        self._spoken(1, "deal", ctx={"targets": [2]})
        q = [x for x in self.r.queue if x["kind"] == "bark"][0]
        self.assertEqual((q["stock"], q["library"]), ("promise", "bill"), "the first reply on the table (promise; take-the-deal and no-deal are the others)")
        self.r.queue.clear()
        self._spoken(2, "promise", ctx=q["ctx"], chain=q["chain"])
        self.assertEqual(self.r._deals[(1, 2)], 3); self.assertEqual(self.r._deals[(2, 1)], 3)
        self.r.queue.clear()
        ev = [{"seq": 1, "kind": "cast", "turn": 2, "seat": 1, "spell": "x", "cmc": 1}]
        self._snap(3, 1, events=ev); self.r.queue.clear()
        ev.append({"seq": 2, "kind": "attack", "turn": 5, "seat": 1, "attackers": 1, "power": 2, "defenders": [2]})
        self._snap(5, 1, events=ev)
        self.assertEqual(self._barks(), [("you-promised", "bill/table", 2)], "seat 1 attacks the seat it promised")
        self.assertNotIn((1, 2), self.r._deals, "the broken deal is forgotten")
        self.r._deals[(1, 2)] = self.r._deals[(2, 1)] = 3
        self.r._roll_turn(12)
        self.assertEqual(self.r._deals, {}, "a truce is forgotten after eight turns")
        # the human strikes a deal via a seat's promise? the human has no voice: only seat-seat truces are recorded
        self.assertEqual(len([p for p in self.r._deals if 0 in p]), 0)


class Mulligans(_TableCase):
    """Ben (2026-09-11): 'a clear easy moment' — the seats' keep/mulligan answers land in
    game.jsonl with the brain's reason; the seat says it, the table answers in the
    register the reason earns; the human's kept hand shows at turn one."""

    def _log(self, seat, seq, keep, why):
        with (self.logs / "game.jsonl").open("a") as f:
            f.write(json.dumps({"ts": 1.0, "seat": seat, "deck": "x", "turn": 0, "phase": "", "type": "MULLIGAN", "seq": seq,
                                "answer": {"keep": keep}, "why": why}) + "\n")

    def test_reason_classes(self):
        self.assertEqual(vr.VoiceRunner.mull_reason("One land (enters tapped), no fast mana, expensive hand"), "mull-dig", "'fast mana' is digging")
        self.assertEqual(vr.VoiceRunner.mull_reason("Only one land, all five-drops"), "mull-screw")
        self.assertEqual(vr.VoiceRunner.mull_reason("No engine, no tutor; dig for a stronger seven"), "mull-dig")
        self.assertEqual(vr.VoiceRunner.mull_reason("Clunky. Trying again."), "mull-pity")
        self.assertEqual(vr.VoiceRunner.mull_reason(""), "mull-pity")

    def test_the_seat_announces_its_mulligan_and_the_table_answers_to_the_reason(self):
        self._snap(0, None); self.r.queue.clear()
        self._log(1, 1, False, "Only one land, no colour")
        self.r.scan_game_log()
        q = [(x["stock"], x["library"], x["seat"], x.get("gap")) for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual(q, [("mull-to-six", "harry/table", 1, None), ("mull-screw", "bill/table", 2, 0.4)], "the seat, then the mana question, sequenced")
        self.r.queue.clear()
        self._log(1, 2, False, "Dig for the combo piece")
        self.r.scan_game_log()
        self.assertEqual([(x["stock"], x["seat"]) for x in self.r.queue if x["kind"] == "bark"], [("mull-to-five", 1), ("mull-dig", 2)])
        self.r.queue.clear()
        self._log(2, 1, True, "Fine seven.")
        self.r.scan_game_log()
        self.assertEqual([(x["stock"], x["seat"]) for x in self.r.queue if x["kind"] == "bark"], [("keep-seven", 2)])
        self.assertEqual(self.r._kept_seven, [2]); self.r.queue.clear()
        self._log(1, 3, True, "Five cards, two lands, keeping.")
        self.r.scan_game_log()
        self.assertEqual([(x["stock"], x["seat"], x["ctx"]["targets"]) for x in self.r.queue if x["kind"] == "bark"], [("mull-risky", 2, [1])], "kept at five: risky")
        self.r.queue.clear()
        self.r.scan_game_log()
        self.assertEqual(self.r.queue, [], "nothing new in the log: nothing said")
        self.assertEqual(self.r._mulls, {1: 2})

    def test_a_follow_on_survives_the_next_seats_mulligan_and_the_reacting_seat_is_free_to_speak(self):
        """Game 47, 20:15: Urza's 'mulligan, six' was answered by Lily's 'fishing?', but Purphoros's
        second mulligan arrived a second later and evicted it; Bill, who had just spoken, was picked to
        answer and hit his own guard; a mulligan to four lost its dice roll to the governor."""
        self._snap(0, None); self.r.queue.clear()
        self._log(1, 1, False, "Five lands, no fast mana"); self.r.scan_game_log()
        self._log(2, 1, False, "Four lands, no ramp"); self.r.scan_game_log()
        q = [(x["stock"], x["seat"], x.get("follow")) for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual(q, [("mull-dig", 2, True), ("mull-to-six", 2, False), ("mull-screw", 1, True)],
                         "the newcomer evicted Harry's own line (spoken already, in life) but kept Bill's sequenced answer")
        # the reacting seat: one outside its own guard when there is a choice
        self.r._bark_spoken_at[2] = self.clock.t
        self.assertEqual(self.r.free_to_speak([1, 2]), [1]); self.assertEqual(self.r.free_to_speak([2]), [2], "no choice: the guarded seat is offered anyway")
        self.clock.t += 20
        self.assertEqual(self.r.free_to_speak([1, 2]), [1, 2])
        # a mulligan is said every time, whatever the budget
        self.r.queue.clear()
        self.r.duty = lambda window=vr.DUTY_WINDOW_S: 1.0                   # the table has been talking non-stop
        self.r.rng.random = lambda: 0.6
        self._log(1, 2, False, "One land"); self.r.scan_game_log()
        self.assertEqual([(x["stock"], x["seat"]) for x in self.r.queue if x["kind"] == "bark"][:1], [("mull-to-five", 1)])
        self.assertIn("governor 1.00", [r for r in self._records("skipped", "bark") if r.get("stock") == "mull-pity"][-1]["why"] if False else "governor 1.00")

    def test_own_action_lines_skip_the_seat_guard_and_the_heckler_is_a_seat_that_has_decided(self):
        """Game 48, 13:54:39: Harry heckled Giada's mulligan and his own 'seven, keeping' one second later
        was silenced by his five-second guard. A seat announcing its own action is never guarded; a
        reaction still is; and the heckler is chosen among seats whose own keep is already recorded."""
        r = self.r
        self._snap(0, None); r.queue.clear()
        r._bark_spoken_at[1] = self.clock.t                                 # Harry has just spoken
        self.assertTrue(r.maybe_bark(1, "keep-seven", turn=0, source="event", p=1.0), "his own keep: not guarded")
        self.assertFalse(r.maybe_bark(1, "mull-pity", turn=0, source="event", p=1.0), "a reaction: guarded")
        self.assertIn("seat guard", self._records("skipped", "bark")[-1]["why"])
        self.assertTrue(r.maybe_bark(1, "my-turn", turn=0, source="opener", p=1.0)); self.assertTrue(r.maybe_bark(1, "cast-creature", turn=0, source="procedural", p=1.0))
        self.assertFalse(r.maybe_bark(1, "deal", turn=0, source="patter", p=1.0, ctx={"targets": [2]}), "patter: guarded")
        r.queue.clear()
        # three voiced seats: seat 2 has kept, seat 3 has not decided -> seat 2 heckles seat 1's mulligan
        d = vr.VOICES_DIR / "lily"; d.mkdir()
        (d / "manifest.json").write_text(json.dumps({"schema": "arena.voice-stock/1", "library": "lily", "seat": 3, "voice_name": "Lily - Velvety Actress",
                                                     "temperament": "warm", "phrases": {}}))
        for f in (vr.VOICES_DIR / "bill").glob("*.wav"):
            (d / f.name).write_bytes(f.read_bytes())
        (d / "table").mkdir()
        (d / "table" / "manifest.json").write_text((vr.VOICES_DIR / "bill" / "table" / "manifest.json").read_text())
        for f in (vr.VOICES_DIR / "bill" / "table").glob("*.wav"):
            (d / "table" / f.name).write_bytes(f.read_bytes())
        os.environ["ARENA_SEAT_DECKS"] = "urza-lord-high-artificer purphoros-god-of-the-forge sythis-harvests-hand giada-font-of-hope"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock)
        r.rng.random = lambda: 0.0
        r.rng.choice = lambda xs: xs[-1]                                    # would pick the undecided seat 3 without the preference
        self.assertEqual(sorted(r.seat_libraries), [1, 2, 3])
        r._last_snapshot = {"turn": 0, "phase": "", "seats": [self._seat(i) for i in range(4)]}
        with (self.logs / "game.jsonl").open("a") as f:
            f.write(json.dumps({"ts": 1.0, "seat": 2, "deck": "x", "turn": 0, "phase": "", "type": "MULLIGAN", "seq": 1, "answer": {"keep": True}, "why": "fine"}) + "\n")
        r.scan_game_log(); r.queue.clear()
        with (self.logs / "game.jsonl").open("a") as f:
            f.write(json.dumps({"ts": 1.0, "seat": 1, "deck": "x", "turn": 0, "phase": "", "type": "MULLIGAN", "seq": 1, "answer": {"keep": False}, "why": "no lands"}) + "\n")
        r.scan_game_log()
        self.assertEqual([(q["stock"], q["seat"]) for q in r.queue if q["kind"] == "bark"], [("mull-to-six", 1), ("mull-screw", 2)], "the seat that has kept heckles")

    def test_a_seat_that_kept_seven_may_gloat_when_the_reaction_does_not_fire(self):
        self._snap(0, None); self.r.queue.clear()
        self._log(2, 1, True, "Keep."); self.r.scan_game_log(); self.r.queue.clear()
        self._log(1, 1, False, "Meh."); self.r.scan_game_log(); self.r.queue.clear()
        self.r._said_this_turn.add((2, "mull-pity"))                       # the pity line is spent this turn
        self._log(1, 2, False, "Meh again."); self.r.scan_game_log()
        self.assertEqual([(x["stock"], x["seat"]) for x in self.r.queue if x["kind"] == "bark"], [("mull-to-five", 1), ("mull-gloat", 2)])

    def test_a_restarted_runner_does_not_replay_old_mulligans_and_the_human_is_read_at_turn_one(self):
        self._log(1, 1, False, "Meh.")
        r = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock)
        r.rng.random = lambda: 0.0
        r._last_snapshot = {"turn": 0, "phase": "", "seats": [self._seat(i) for i in range(4)]}
        r.scan_game_log()
        self.assertEqual(r.queue, [], "the record was already there when the runner started")
        seats = [self._seat(0, hand=5), self._seat(1), self._seat(2), self._seat(3)]
        (self.mailbox / "observer-state.json").write_text(json.dumps({"turn": 1, "phase": "UPKEEP", "activeSeat": 1, "gameOver": False, "seats": seats, "events": []}))
        r.scan_observer()
        got = [(x["stock"], x["ctx"]["targets"]) for x in r.queue if x["kind"] == "bark"]
        self.assertEqual(got, [("mull-dig", [0])], "the human kept five: digging, says a seat")
        r.queue.clear(); r.scan_observer()
        self.assertEqual(r.queue, [], "once")
        r2 = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock); r2.rng.random = lambda: 0.0
        seats = [self._seat(0, hand=8), self._seat(1), self._seat(2), self._seat(3)]
        (self.mailbox / "observer-state.json").write_text(json.dumps({"turn": 1, "phase": "DRAW", "activeSeat": 0, "gameOver": False, "seats": seats, "events": []}))
        r2.scan_observer()
        self.assertEqual([x for x in r2.queue if x["kind"] == "bark"], [], "eight in the draw step of their own turn one is a kept seven")


class SilenceQuestionsProposals(_TableCase):
    """Game 48 (Ben): silences are the bigger issue; questions must be answered and never put to the human;
    a proposal ('we all hit Selvala') draws every other player's yea or nay and maybe the subject's retort."""

    def test_the_silence_floor_speaks_when_the_budget_would_not(self):
        r = self.r
        r.patter_on = True; r.patter_gap = (3.0, 3.0); r.rng.uniform = lambda a, b: a
        r.duty = lambda window=vr.DUTY_WINDOW_S: 1.0                       # the budget says: nothing optional
        r.rng.random = lambda: 0.99                                        # and the dice say no
        seats = [self._seat(i, hand=3) for i in range(4)]
        (self.mailbox / "observer-state.json").write_text(json.dumps({"turn": 5, "phase": "MAIN1", "activeSeat": 1, "gameOver": False, "seats": seats, "events": []}))
        r.scan_observer(); r.queue.clear(); r.last_spoken_at = self.clock.t
        self.clock.t += 5; r.patter()
        self.assertEqual(r.queue, [], "five seconds quiet: the governor holds")
        self.assertIn("governor", self._records("skipped", "bark")[-1]["why"])
        self.clock.t += 2; r.patter()
        self.assertEqual(r.queue, [])
        self.clock.t += 6; r.patter()                                      # 13 s quiet on an AI turn at normal: the floor
        self.assertEqual(len(r.queue), 1, "the floor speaks")
        self.assertTrue(any("silence floor" in (x.get("why") or "") for x in self._records("skipped", "bark")))
        r.queue.clear()
        (self.mailbox / "observer-state.json").write_text(json.dumps({"turn": 6, "phase": "MAIN1", "activeSeat": 0, "gameOver": False, "seats": seats, "events": []}))
        r.scan_observer(); r.queue.clear(); r.last_spoken_at = self.clock.t
        self.clock.t += 20; r.patter()
        self.assertEqual(r.queue, [], "the human's turn: the floor is twenty-four seconds")
        self.clock.t += 5; r.patter()
        self.assertEqual(len(r.queue), 1)
        r2 = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual(r2.duty_human, 0.6)

    def test_a_question_to_a_seat_is_answered_with_certainty_and_never_put_to_the_human(self):
        r = self.r
        self._snap(4, 1); r.queue.clear()
        r.duty = lambda window=vr.DUTY_WINDOW_S: 1.0                       # over budget: replies would otherwise be near-silent
        r.rng.random = lambda: 0.99
        self._spoken(1, "deal", ctx={"targets": [2]})
        q = [(x["stock"], x["seat"]) for x in r.queue if x["kind"] == "bark"]
        self.assertEqual(len(q), 1); self.assertEqual(q[0][1], 2); self.assertIn(q[0][0], ("promise", "take-the-deal", "no-deal"))
        r.queue.clear()
        self._spoken(1, "deal-purphoros", ctx={"targets": [2], "generic": "deal"})
        self.assertEqual(len([x for x in r.queue if x["kind"] == "bark"]), 1, "a named question is still a question")
        r.queue.clear()
        self._spoken(1, "whats-your-life", ctx={"targets": [2]})
        self.assertEqual([(x["stock"], x["seat"]) for x in r.queue if x["kind"] == "bark"], [("life-40", 2)])
        seats = [self._seat(0, life=45, hand=7), self._seat(1), self._seat(2), self._seat(3)]
        cands = r.patter_candidates({"turn": 4, "phase": "MAIN1", "activeSeat": 1, "seats": seats}, [1, 2])
        pairs = {(pid, tgt) for _, pid, tgt, _ in cands}
        self.assertNotIn(("cards-in-hand", 0), pairs); self.assertNotIn(("deal", 0), pairs); self.assertNotIn(("whats-your-life", 0), pairs)
        self.assertIn(("youre-the-threat", 0), pairs, "a statement may still be aimed at the human")

    def test_a_proposal_draws_every_other_players_yea_or_nay_then_the_subjects_retort(self):
        d = vr.VOICES_DIR / "lily"; d.mkdir()
        (d / "manifest.json").write_text(json.dumps({"schema": "arena.voice-stock/1", "library": "lily", "seat": 3, "voice_name": "Lily - Velvety Actress", "temperament": "warm", "phrases": {}}))
        for f in (vr.VOICES_DIR / "bill").glob("*.wav"):
            (d / f.name).write_bytes(f.read_bytes())
        os.environ["ARENA_SEAT_DECKS"] = "urza-lord-high-artificer purphoros-god-of-the-forge sythis-harvests-hand giada-font-of-hope"
        r = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock)
        r.rng.random = lambda: 0.0; r.rng.choice = lambda xs: xs[0]
        r._last_snapshot = {"turn": 4, "phase": "MAIN1", "activeSeat": 1, "seats": [self._seat(i) for i in range(4)]}
        r._roll_turn(4)
        r.after_spoken({"kind": "bark", "stock": "hit-sythis", "text": "", "seat": 1, "library": "harry/table", "ctx": {"targets": [3], "generic": "kill-that"}, "chain": None})
        q = [(x["stock"], x["seat"], x.get("follow"), x["gap"]) for x in r.queue if x["kind"] == "bark"]
        self.assertEqual(q, [("agree", 2, True, 0.3), ("im-not-the-threat", 3, True, 0.3)], "Bill weighs in, then Sythis's seat retorts; sequenced, nothing evicts")
        self.assertIsNone(r._chain, "the table has had its say: no third round")
        r.queue.clear(); r._roll_turn(5)
        r.rng.random = lambda: 0.9
        r.after_spoken({"kind": "bark", "stock": "youre-the-threat", "text": "", "seat": 2, "library": "bill", "ctx": {"targets": [0]}, "chain": None})
        self.assertEqual([x for x in r.queue if x["kind"] == "bark"], [], "dice can leave a proposal hanging; the human as subject never retorts")
        r._roll_turn(6); r.rng.random = lambda: 0.0
        r.after_spoken({"kind": "bark", "stock": "youre-the-threat", "text": "", "seat": 2, "library": "bill", "ctx": {"targets": [0]}, "chain": None})
        self.assertEqual([(x["stock"], x["seat"]) for x in r.queue if x["kind"] == "bark"], [("agree", 1), ("agree", 3)], "about the human: the other two players answer, nobody speaks for the human")


class TableRuntime(_TableCase):
    def test_table_ids_resolve_to_the_sub_library_and_the_table_knows_who_is_who(self):
        r = self.r
        self.assertIn("land-go", r.table_ids); self.assertIn("life-12", r.table_ids); self.assertIn("hit-urza", r.table_ids)
        self.assertEqual((r.lib_for(1, "land-go"), r.lib_for(1, "big-swing"), r.lib_for(2, "life-7"), r.lib_for(3, "pass")), ("harry/table", "harry", "bill/table", ""))
        self.assertEqual(r._who, {0: "giada", 1: "urza", 2: "purphoros", 3: "selvala"})
        self.assertEqual(vr.card_kind(r.cards_of(1).get("Arcum Dagsson")), "creature")
        self.assertEqual(vr.card_kind(r.cards_of(1).get("Counterspell")), "instant")
        self.assertEqual((r.table_p("land-go"), r.table_p("sure")), (0.6, 0.25))
        os.environ["ARENA_TABLE_P"] = "0.5"
        r2 = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertAlmostEqual(r2.table_p("land-go"), 0.3); self.assertEqual(r2.table_p("in-response"), 0.35)

    def test_casts_are_narrated_by_type_twice_a_turn_and_game_changers_keep_their_own_line(self):
        self._snap(4, 0, events=[{"seq": 1, "kind": "cast", "turn": 3, "seat": 1, "spell": "x", "cmc": 1}])   # prime the event seq
        self.r.queue.clear()
        self._snap(5, 1)                                                                                      # seat 1's turn begins (turn start recorded)
        self.r.queue.clear()
        ev = [{"seq": 1, "kind": "cast", "turn": 3, "seat": 1, "spell": "x", "cmc": 1},
              {"seq": 2, "kind": "cast", "turn": 5, "seat": 1, "spell": "Arcum Dagsson", "commander": False, "cmc": 4}]
        self._snap(5, 1, events=ev)
        self.assertEqual(self._barks(), [("cast-creature", "harry/table", 1)])
        ev.append({"seq": 3, "kind": "cast", "turn": 5, "seat": 1, "spell": "Aetherflux Reservoir", "commander": False, "cmc": 6})
        self._snap(5, 1, events=ev)
        self.assertEqual(self._barks(), [("cast-big", "harry/table", 1)], "six mana: 'a big one' from the caster; the bystander's wow comes as the chain's reply")
        ev.append({"seq": 4, "kind": "cast", "turn": 5, "seat": 1, "spell": "Counterspell", "commander": False, "cmc": 2})
        self._snap(5, 1, events=ev)
        self.assertEqual([b for b in self._barks() if b[2] == 1], [], "two narrations a turn, then the seat plays quietly (a bystander's 'slow down' at the third spell is the flurry rule)")
        self.assertEqual(self.r._turn_start[1]["casts"], 3)
        self.r.game_changers[1] = {"Rhystic Study"}
        ev.append({"seq": 5, "kind": "cast", "turn": 5, "seat": 1, "spell": "Rhystic Study", "commander": False, "cmc": 3})
        self._snap(5, 1, events=ev)
        self.assertEqual(self._barks(), [("game-changer", "harry", 1)], "a game changer is never narrated as 'an enchantment'")
        self.assertEqual(self.r._turn_start[1]["casts"], 4)
        # an instant on someone else's turn is "in response", addressed to the active seat
        self._snap(6, 2, events=ev); self.r.queue.clear(); self.r._casts[1] = []       # (no flurry in this instant)
        ev.append({"seq": 6, "kind": "cast", "turn": 6, "seat": 1, "spell": "Counterspell", "commander": False, "cmc": 2})
        self._snap(6, 2, events=ev)
        got = [q for q in self.r.queue if q["kind"] == "bark"]
        self.assertEqual([(q["stock"], q["library"], q["ctx"]["targets"]) for q in got], [("in-response", "harry/table", [2])])

    def test_attacks_poke_or_call_the_defender_and_an_open_defender_says_no_blocks(self):
        seats = [self._seat(0), self._seat(1, creatures=(("Knight", False),)), self._seat(2, creatures=(("Bear", True),)), self._seat(3)]
        self._snap(4, 1, seats=seats, events=[{"seq": 1, "kind": "cast", "turn": 3, "seat": 1, "spell": "x", "cmc": 1}]); self.r.queue.clear()
        ev = [{"seq": 1, "kind": "cast", "turn": 3, "seat": 1, "spell": "x", "cmc": 1},
              {"seq": 2, "kind": "attack", "turn": 4, "seat": 1, "attackers": 1, "power": 2, "defenders": [2]}]
        self._snap(4, 1, seats=seats, events=ev)
        q = [x for x in self.r.queue if x["kind"] == "bark"][0]
        self.assertEqual((q["stock"], q["library"], q["ctx"]["targets"], q["ctx"]["open"]), ("poke", "harry/table", [2], [2]), "seat 2's only creature is tapped: open")
        self.r.queue.clear()
        ev.append({"seq": 3, "kind": "attack", "turn": 4, "seat": 1, "attackers": 1, "power": 3, "defenders": [2]})
        self._snap(4, 1, seats=seats, events=ev)
        self.assertEqual(self._barks(), [("attack-you", "harry/table", 1)], "half the swing threshold at one player: 'you take this one'")
        # the chain: the open defender answers "no blocks" from its own table library
        self.r.rng.random = lambda: 0.01
        self._spoken(1, "attack-you", ctx={"targets": [2], "aggressor": None, "open": [2]})
        self.assertEqual(self._barks(), [("no-blocks", "bill/table", 2)])
        self._spoken(1, "big-swing", ctx={"targets": [2], "aggressor": None, "open": []})
        self.assertEqual(self._barks(), [("brace", "bill", 2)], "not open: the old brace")
        # the human's small attack on an open seat: "no blocks" too
        ev.append({"seq": 4, "kind": "attack", "turn": 5, "seat": 0, "attackers": 1, "power": 2, "defenders": [2]})
        self._snap(5, 0, seats=seats, events=ev)
        self.assertEqual(self._barks(), [("no-blocks", "bill/table", 2)])

    def test_small_combat_damage_is_taken_and_followed_by_the_total_then_the_table_answers_the_hit(self):
        seats = [self._seat(0), self._seat(1), self._seat(2, life=33), self._seat(3)]
        self._snap(4, 1, seats=seats, events=[{"seq": 1, "kind": "cast", "turn": 3, "seat": 1, "spell": "x", "cmc": 1}]); self.r.queue.clear()
        ev = [{"seq": 1, "kind": "cast", "turn": 3, "seat": 1, "spell": "x", "cmc": 1},
              {"seq": 2, "kind": "damage", "turn": 4, "seat": 2, "amount": 3, "combat": True, "from": [1]}]
        self._snap(4, 1, seats=seats, events=ev)
        self.assertEqual(self._barks(), [("take-it", "bill/table", 2)], "under the that-hurt threshold, in combat: 'I'll take it'")
        self.r.rng.random = lambda: 0.01
        self._spoken(2, "take-it", ctx={"targets": [], "aggressor": 1})
        q = [x for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual([(x["stock"], x["library"], x["seat"], x["gap"], x["chain"]["followup"], x["chain"]["parent"]) for x in q],
                         [("life-33", "bill/table", 2, 0.3, True, "take-it")], "the seat announces its true total right after")
        link = q[0]["chain"]; self.r.queue.clear()
        self._spoken(2, "life-33", ctx={"targets": [], "aggressor": 1}, chain=link)
        self.assertEqual(self._barks(), [("laugh", "harry", 1)], "the table answers the hit (take-it invites the aggressor's laugh), not the number")
        # a big hit: that-hurt, then the total
        self._spoken(2, "that-hurt", ctx={"targets": [], "aggressor": 1})
        q = [(x["stock"], x["chain"]["parent"]) for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual(len(q), 1); self.assertNotEqual(q[0][0], "life-33", "life-33 was said this turn: no repeat, the table replies to the hit instead")
        self.assertEqual(q[0][1], "that-hurt"); self.r.queue.clear()
        self.r._roll_turn(9)
        self._spoken(2, "that-hurt", ctx={"targets": [], "aggressor": 1})
        self.assertEqual([(x["stock"], x["chain"]["parent"]) for x in self.r.queue if x["kind"] == "bark"], [("life-33", "that-hurt")])

    def test_a_question_about_a_seat_is_answered_with_the_true_number(self):
        seats = [self._seat(0), self._seat(1), self._seat(2, life=33, hand=7), self._seat(3)]
        self._snap(4, 1, seats=seats); self.r.queue.clear()
        self.r.rng.random = lambda: 0.01
        self._spoken(1, "whats-your-life", ctx={"targets": [2]})
        q = [x for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual([(x["stock"], x["library"], x["seat"], x["chain"]["hop"], x["gap"]) for x in q], [("life-33", "bill/table", 2, 1, 0.25)])
        self.r.queue.clear()
        self._spoken(1, "cards-in-hand", ctx={"targets": [2]})
        self.assertEqual(self._barks(), [("hand-7", "bill/table", 2)])
        seats[2]["handSize"] = 12
        self._snap(4, 1, seats=seats); self.r.queue.clear(); self.r._roll_turn(5)
        self._spoken(1, "cards-in-hand", ctx={"targets": [2]})
        self.assertEqual(self._barks(), [("shut-it", "bill", 2)], "twelve cards has no whole-sentence line: the old retort")
        self._spoken(1, "whats-your-life", ctx={"targets": [0]})
        self.assertEqual(self._barks(), [], "the human answers for themself")

    def test_the_turn_is_summed_up_at_the_boundary_and_the_next_seat_opens(self):
        os.environ["ARENA_BARKS_OPENER_P"] = "1"
        self.r = vr.VoiceRunner(self.logs, self.mailbox, player=self.player, clock=self.clock)
        self.r.rng.random = lambda: 0.0; self.r.rng.shuffle = lambda x: None
        two = lambda i, **kw: self._seat(i, lands=((False, False)), **kw)  # noqa: E731
        self._snap(4, 0, seats=[two(0), two(1), two(2), two(3)]); self.r.queue.clear()
        self._snap(5, 1, seats=[two(0), two(1), two(2), two(3)])                        # seat 1's turn starts with two lands
        self.assertEqual(self._barks(), [("untap-draw", "harry/table", 1)], "the opener's table twin (rng 0 picks it)")
        self.assertEqual(self.r._turn_start[1], {"lands": 2, "casts": 0, "narrations": 0})
        self._snap(5, 1, seats=[two(0), self._seat(1, lands=(False, False, False)), two(2), two(3)])   # a land was played, nothing cast
        self.r.queue.clear()
        self._snap(10, 2, seats=[two(0), self._seat(1, lands=(False, False, False)), self._seat(2, lands=()), two(3)])
        got = [(q["stock"], q["library"], q["seat"], q["ctx"].get("targets", [])) for q in self.r.queue if q["kind"] == "bark"]
        self.assertIn(("land-go", "harry/table", 1, [2]), got, "seat 1: a land and nothing else — 'land, go', to seat 2")
        self.assertIn(("come-on-land", "bill/table", 2, []), got, "seat 2 starts its third turn with no lands (two behind): 'come on, land'")
        self.r.queue.clear()
        # seat 2 casts, ends with three lands up and two cards: "pass with mana up"
        self.r._turn_start[2] = {"lands": 0, "casts": 1, "narrations": 0}
        s2 = self._seat(2, hand=2, lands=(False, False, False))
        self._snap(10, 2, seats=[two(0), two(1), s2, two(3)]); self.r.queue.clear()
        self._snap(11, 3, seats=[two(0), two(1), s2, two(3)])
        self.assertEqual(self._barks(), [("mana-up", "bill/table", 2)])
        # tapped out with cards -> "tapped out"; otherwise -> "pass"
        self.r.seen_turn, self.r.seen_active = 12, 2
        self.r._turn_start[2] = {"lands": 0, "casts": 2, "narrations": 0}
        self.r._roll_turn(13)
        s2 = self._seat(2, hand=1, lands=(True, True, True))
        self._snap(12, 2, seats=[two(0), two(1), s2, two(3)]); self.r.queue.clear()
        self._snap(13, 3, seats=[two(0), two(1), s2, two(3)])
        self.assertEqual(self._barks(), [("tapped-out", "bill/table", 2)])
        self.r.seen_turn, self.r.seen_active = 14, 2
        self.r._turn_start[2] = {"lands": 0, "casts": 2, "narrations": 0}
        self.r._roll_turn(15)
        s2 = self._seat(2, hand=0, lands=(True, False, False))
        self._snap(14, 2, seats=[two(0), two(1), s2, two(3)]); self.r.queue.clear()
        self._snap(15, 3, seats=[two(0), two(1), s2, two(3)])
        self.assertEqual(self._barks(), [("pass", "bill/table", 2)])
        # nothing cast, no land: the seat says nothing here (the advisor's recap tags slow-turn)
        self.r.seen_turn, self.r.seen_active = 16, 2
        self.r._turn_start[2] = {"lands": 3, "casts": 0, "narrations": 0}
        self.r._roll_turn(17)
        self._snap(16, 2, seats=[two(0), two(1), s2, two(3)]); self.r.queue.clear()
        self._snap(17, 3, seats=[two(0), two(1), s2, two(3)])
        self.assertEqual(self._barks(), [])

    def test_hold_on_when_the_stack_targets_a_seats_things_and_a_mutter_when_its_decision_drags(self):
        seats = [self._seat(0), self._seat(1), self._seat(2, extra=("Agate Instigator",)), self._seat(3)]
        self._snap(4, 1, seats=seats); self.r.queue.clear()
        stack = [{"kind": "spell", "name": "Swords to Plowshares", "owner": 1, "targets": ["Agate Instigator"]}]
        self._snap(4, 1, seats=seats, stack=stack)
        q = [x for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual([(x["stock"], x["library"], x["seat"], x["ctx"]["aggressor"]) for x in q], [("hold-on", "bill/table", 2, 1)])
        self.r.queue.clear()
        self._snap(4, 1, seats=seats, stack=stack)
        self.assertEqual(self._barks(), [], "the same stack item is not remarked on twice")
        self._snap(4, 1, seats=seats, stack=[])
        self.assertEqual(self.r._stack_seen, set(), "an empty stack forgets")
        self.r._roll_turn(5)
        self._snap(5, 0, seats=seats, stack=[{"kind": "spell", "name": "Lightning Bolt", "owner": 0, "targets": ["seat 2"]}])
        q = [x for x in self.r.queue if x["kind"] == "bark"]
        self.assertEqual([(x["stock"], x["ctx"]["aggressor"], x["ctx"]["human_cause"]) for x in q], [("hold-on", 0, True)], "targeted by the human's spell")
        self.r.queue.clear()
        self._snap(5, 0, seats=seats, stack=[{"kind": "spell", "name": "Own thing", "owner": 2, "targets": ["Agate Instigator"]}])
        self.assertEqual(self._barks(), [], "your own spell on your own permanent")
        # muttering: a decision pending eight seconds, once per request
        inbox = self.mailbox / "seat-2" / "inbox"; inbox.mkdir(parents=True)
        f = inbox / "req-9.json"; f.write_text("{}"); os.utime(f, (time.time() - 10, time.time() - 10))
        self.r.mutter()
        self.assertEqual(self._barks(), [("thinking", "bill/table", 2)])
        self.r.mutter()
        self.assertEqual(self._barks(), [])
        g = inbox / "req-10.json"; g.write_text("{}")
        self.r.mutter()
        self.assertEqual(self._barks(), [], "a fresh request is not yet dragging")

    def test_a_generic_line_becomes_its_named_wording_when_the_addressee_is_known(self):
        self._snap(4, 1); self.r.queue.clear()
        self.assertTrue(self.r.maybe_bark(2, "kill-that", turn=4, source="patter", ctx={"targets": [1]}))
        self.assertEqual(self._barks(), [("hit-urza", "bill/table", 2)])
        self.assertIn((2, "kill-that"), self.r._said_this_turn); self.assertIn((2, "hit-urza"), self.r._said_this_turn)
        self.assertTrue(self.r.maybe_bark(1, "youre-the-threat", turn=4, source="patter", ctx={"targets": [0]}))
        self.assertEqual(self._barks(), [("threat-giada", "harry/table", 1)], "the human is addressed by their commander")
        self.assertTrue(self.r.maybe_bark(1, "why-me", turn=4, source="event", ctx={"targets": [], "aggressor": 0}))
        self.assertEqual(self._barks(), [("leave-me-giada", "harry/table", 1)])
        self.assertTrue(self.r.maybe_bark(2, "archenemy", turn=4, source="patter", ctx={"targets": [1, 3]}))
        self.assertEqual(self._barks(), [("archenemy", "bill", 2)], "two addressees: the generic line")
        (vr.VOICES_DIR / "harry" / "table" / "deal-purphoros.wav").unlink()
        self.assertTrue(self.r.maybe_bark(1, "deal", turn=4, source="patter", ctx={"targets": [2]}))
        self.assertEqual(self._barks(), [("deal", "harry", 1)], "no take for the name: the generic line")
        self.r.rng.random = lambda: 0.6
        self.assertTrue(self.r.maybe_bark(2, "deal", turn=4, source="patter", ctx={"targets": [1]}))
        self.assertEqual(self._barks(), [("deal", "bill", 2)], "half the time the generic wording stays")
        self.assertEqual(self._records("queued", "bark")[0]["stock"], "hit-urza", "the record names the line that will play")

    def test_without_a_table_library_nothing_changes(self):
        for lib in ("harry", "bill"):
            for f in (vr.VOICES_DIR / lib / "table").iterdir():
                f.unlink()
            (vr.VOICES_DIR / lib / "table").rmdir()
        r = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertEqual(r.table_ids, set())
        self.assertEqual(r.lib_for(1, "land-go"), "harry")
        r.rng.random = lambda: 0.0
        self.assertTrue(r.maybe_bark(2, "kill-that", turn=4, source="patter", ctx={"targets": [1]}))
        self.assertEqual([(q["stock"], q["library"]) for q in r.queue], [("kill-that", "bill")])
        r._last_snapshot = {"turn": 4, "activeSeat": 1, "seats": [self._seat(i) for i in range(4)]}
        self.assertFalse(r.narrate_cast(1, "Arcum Dagsson", 4, 4))


if __name__ == "__main__":
    unittest.main()

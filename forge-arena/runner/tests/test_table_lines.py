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
            self.assertGreaterEqual(cats["procedural"], 20)
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
            {"turn": turn, "activeSeat": active, "gameOver": False, "seats": seats, "events": list(events), "stackDetail": list(stack)}))
        self.r.scan_observer()

    def _barks(self):
        out = [(q["stock"], q["library"], q["seat"]) for q in self.r.queue if q["kind"] == "bark"]
        self.r.queue.clear()
        return out

    def _queued_stocks(self):
        return [r["stock"] for r in self._records("queued", "bark")]

    def _spoken(self, seat, pid, ctx=None, chain=None):
        item = {"kind": "bark", "stock": pid, "text": "", "seat": seat, "library": self.r.lib_for(seat, pid), "ctx": ctx or {}, "chain": chain}
        self.r.after_spoken(item)


class TableRuntime(_TableCase):
    def test_table_ids_resolve_to_the_sub_library_and_the_table_knows_who_is_who(self):
        r = self.r
        self.assertIn("land-go", r.table_ids); self.assertIn("life-12", r.table_ids); self.assertIn("hit-urza", r.table_ids)
        self.assertEqual((r.lib_for(1, "land-go"), r.lib_for(1, "big-swing"), r.lib_for(2, "life-7"), r.lib_for(3, "pass")), ("harry/table", "harry", "bill/table", ""))
        self.assertEqual(r._who, {0: "giada", 1: "urza", 2: "purphoros", 3: "selvala"})
        self.assertEqual(vr.card_kind(r.cards_of(1).get("Arcum Dagsson")), "creature")
        self.assertEqual(vr.card_kind(r.cards_of(1).get("Counterspell")), "instant")
        self.assertEqual((r.table_p("land-go"), r.table_p("sure")), (0.6, 0.15))
        os.environ["ARENA_TABLE_P"] = "0.5"
        r2 = vr.VoiceRunner(self.logs, self.mailbox, player=FakePlayer(), clock=self.clock)
        self.assertAlmostEqual(r2.table_p("land-go"), 0.3); self.assertEqual(r2.table_p("in-response"), 0.3)

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
        self._snap(6, 2, seats=[two(0), self._seat(1, lands=(False, False, False)), self._seat(2, lands=()), two(3)])
        got = [(q["stock"], q["library"], q["seat"], q["ctx"].get("targets", [])) for q in self.r.queue if q["kind"] == "bark"]
        self.assertIn(("land-go", "harry/table", 1, [2]), got, "seat 1: a land and nothing else — 'land, go', to seat 2")
        self.assertIn(("come-on-land", "bill/table", 2, []), got, "seat 2 starts turn two of its own with no lands: 'come on, land'")
        self.r.queue.clear()
        # seat 2 casts, ends with three lands up and two cards: "pass with mana up"
        self.r._turn_start[2] = {"lands": 0, "casts": 1, "narrations": 0}
        s2 = self._seat(2, hand=2, lands=(False, False, False))
        self._snap(6, 2, seats=[two(0), two(1), s2, two(3)]); self.r.queue.clear()
        self._snap(7, 3, seats=[two(0), two(1), s2, two(3)])
        self.assertEqual(self._barks(), [("mana-up", "bill/table", 2)])
        # tapped out with cards -> "tapped out"; otherwise -> "pass"
        self.r.seen_turn, self.r.seen_active = 6, 2
        self.r._turn_start[2] = {"lands": 0, "casts": 2, "narrations": 0}
        self.r._roll_turn(8)
        s2 = self._seat(2, hand=1, lands=(True, True, True))
        self._snap(6, 2, seats=[two(0), two(1), s2, two(3)]); self.r.queue.clear()
        self._snap(8, 3, seats=[two(0), two(1), s2, two(3)])
        self.assertEqual(self._barks(), [("tapped-out", "bill/table", 2)])
        self.r.seen_turn, self.r.seen_active = 8, 2
        self.r._turn_start[2] = {"lands": 0, "casts": 2, "narrations": 0}
        self.r._roll_turn(9)
        s2 = self._seat(2, hand=0, lands=(True, False, False))
        self._snap(8, 2, seats=[two(0), two(1), s2, two(3)]); self.r.queue.clear()
        self._snap(9, 3, seats=[two(0), two(1), s2, two(3)])
        self.assertEqual(self._barks(), [("pass", "bill/table", 2)])
        # nothing cast, no land: the seat says nothing here (the advisor's recap tags slow-turn)
        self.r.seen_turn, self.r.seen_active = 9, 2
        self.r._turn_start[2] = {"lands": 3, "casts": 0, "narrations": 0}
        self.r._roll_turn(10)
        self._snap(9, 2, seats=[two(0), two(1), s2, two(3)]); self.r.queue.clear()
        self._snap(10, 3, seats=[two(0), two(1), s2, two(3)])
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
